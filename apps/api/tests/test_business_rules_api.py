import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.quality_loop.business_rules import BusinessRuleReviewInput
from apps.api.app.domain.quality_loop.acceptance_specification import AcceptanceIntegrityError, StaleAcceptanceSpecification
from apps.api.app.domain.quality_loop.business_rule import RULE_POLICY, RULE_TOOL, RULE_QUERY_TOOL
from apps.api.app.domain.system_image.context_partition import PARTITION_POLICY, RULE_AUTHORITY_POLICY
from apps.api.app.domain.system_image.source_access import SourceAccessRule, StaleSourceAccessScope
from apps.api.app.infrastructure.persistence.business_rule_models import BusinessRuleRevisionRecord
from apps.api.app.infrastructure.persistence.acceptance_specification_models import AcceptanceRevisionRecord
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_document_projection_api import documents, REQUIREMENT
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, completed, count
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_context_packs_api import preview, archive, read


ORACLE = dict(preconditions="Unauthenticated caller", action="POST /search", observation="HTTP response status", expected_result="HTTP 401")


@pytest.fixture
def rule(documents):
    v = documents
    v["requirement_path"].write_text(REQUIREMENT + "## Business rules\nBR-1: Unauthenticated calls must return HTTP 401.\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    image = candidate(v)
    projection = v["client"].get(v["image_url"], headers=v["headers"]).json()
    target = next(o for o in projection["objects"] if o["type"] == "SourceBusinessRule")
    query = dict(image_revision_id=image["image_revision_id"], image_artifact_hash=image["artifact_hash"], object_id=target["id"])
    url = f"/v1/projects/{v['project_id']}/quality/business-rules"
    response = v["client"].get(url, params=query, headers=v["headers"])
    assert response.status_code == 200, response.text
    payload = dict(project_id=v["project_id"], **query, basis_digest=response.json()["basis_digest"],
        expected_previous_revision_id=None, decision="approve", oracle=ORACLE, authority_basis="user_confirmed_business_rule",
        reason="Independent fixture rule review, not inferred from code", policy_revision=RULE_POLICY)
    v.update(rule_url=url, rule_query=query, rule_request=payload, rule_service=app.state.container.business_rules,
             ac_query=query, rule_objects=projection["objects"])
    return v


def inspect_rule(v):
    response = v["client"].get(v["rule_url"], params=v["rule_query"], headers=v["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def submit_rule(v, payload=None, *, headers=None):
    pending = invoke(v, RULE_TOOL, payload or v["rule_request"], headers=headers, key=uuid4().hex)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers or v["headers"])


def withdraw(v):
    head = inspect_rule(v)["head"]
    return submit_rule(v, {**v["rule_request"], "decision": "withdraw", "oracle": None, "authority_basis": None,
        "expected_previous_revision_id": head["revision_id"], "reason": "Withdraw fixture rule"})


def test_rule_authority_is_independent_append_only_withdrawable_and_has_safe_receipts(rule):
    v = rule
    before = inspect_rule(v)
    pending = invoke(v, RULE_TOOL, {**v["rule_request"], "confirmed_by_user": True}).json()
    assert pending["status"] == "waiting_confirmation" and count(v, BusinessRuleRevisionRecord) == 0
    done = completed(confirm(v, pending))
    assert completed(confirm(v, pending))["id"] == done["id"]
    approved = inspect_rule(v)
    assert approved["rule_id"].startswith("rule_") and "ac_id" not in approved
    assert approved["basis"] == before["basis"] and approved["basis"]["source_authority"] == "unapproved_source_projection"
    assert approved["current"]["oracle"] == ORACLE and approved["head"]["status"] == "approved"
    assert approved["current"]["authority_basis"] == "user_confirmed_business_rule"
    old_url = v["rule_url"] + "/" + approved["head"]["revision_id"]
    old = v["client"].get(old_url, headers=v["headers"])
    assert old.status_code == 200 and old.headers["cache-control"] == "private, no-store"
    result = completed(invoke(v, RULE_QUERY_TOOL, {"project_id": v["project_id"], **v["rule_query"]}))
    receipt = result["result"]["business_rule_authority"]
    assert receipt["status"] == "approved" and "HTTP 401" not in json.dumps(receipt)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(result["id"], v["project_id"]) == receipt
        assert v["rule_service"].resolve_oracle(v["project_id"], v["rule_query"]["image_revision_id"], v["rule_query"]["object_id"],
            approved["head"]["revision_id"], approved["head"]["artifact_hash"])["oracle"] == ORACLE
    completed(withdraw(v))
    assert inspect_rule(v)["head"]["status"] == "withdrawn"
    assert v["client"].get(old_url, headers=v["headers"]).json() == old.json()
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(StaleAcceptanceSpecification):
            v["rule_service"].resolve_oracle(v["project_id"], v["rule_query"]["image_revision_id"], v["rule_query"]["object_id"],
                approved["head"]["revision_id"], approved["head"]["artifact_hash"])
    for statement in (update(BusinessRuleRevisionRecord).values(status="withdrawn"), delete(BusinessRuleRevisionRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(BusinessRuleRevisionRecord.project_id == v["project_id"]))
    assert count(v, BusinessRuleRevisionRecord) == 2 and count(v, AcceptanceRevisionRecord) == 0
    with session_scope() as session:
        ids = session.scalars(select(BusinessRuleRevisionRecord.revision_id).where(BusinessRuleRevisionRecord.project_id == v["project_id"])).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id.in_(ids))).all()
        assert len(events) == 2 and "HTTP 401" not in json.dumps([e.event_payload for e in events])


def test_rule_kind_authority_actor_and_membership_cannot_be_substituted(rule):
    v = rule
    ac = next(o for o in v["rule_objects"] if o["type"] == "SourceAcceptanceCriterion")
    for change in ({"object_id": ac["id"]}, {"authority_basis": "user_confirmed_requirement"}, {"authority_basis": "model_inferred"},
                   {"oracle": None}, {"oracle": {**ORACLE, "expected_result": " "}}, {"authority_actor": "forged"},
                   {"basis_digest": "sha256:" + "a" * 64}, {"project_id": "foreign"}):
        response = submit_rule(v, {**v["rule_request"], **change})
        assert response.status_code in {403, 404} or response.json()["status"] in {"failed", "denied"}, response.text
    grant_member(v)
    response = v["client"].get(v["rule_url"], params=v["rule_query"], headers=v["member_headers"])
    assert response.status_code == 200 and response.json()["can_review"] is False
    denied = submit_rule(v, headers=v["member_headers"])
    assert denied.status_code == 403 or denied.json()["status"] in {"failed", "denied"}
    assert v["client"].get(v["rule_url"], params=v["rule_query"]).status_code == 401
    assert count(v, BusinessRuleRevisionRecord) == 0


def test_rule_competing_approvals_and_worker_recovery(rule, monkeypatch):
    v = rule
    pending = [invoke(v, RULE_TOOL, {**v["rule_request"], "reason": f"choice {i}"}, key=uuid4().hex).json() for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [r.json() for r in pool.map(lambda p: confirm(v, p), pending)]
    assert sorted(r["status"] for r in results) == ["completed", "failed"]
    done = next(r for r in results if r["status"] == "completed")
    head = inspect_rule(v)["head"]
    completed(withdraw(v))
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, done["id"])
        row.status = "running"
        payload = {k: value for k, value in row.input_payload.items() if k in BusinessRuleReviewInput.model_fields}
    def no_put(*args):
        raise AssertionError("recovery must not rewrite the archived rule")
    monkeypatch.setattr(v["rule_service"].artifacts, "put", no_put)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        value = v["rule_service"].review(BusinessRuleReviewInput.model_validate(payload), invocation_id=done["id"], recorded_at="retry")
        assert value.revision_id == head["revision_id"] and value.artifact_hash == head["artifact_hash"]
        changed = {**payload, "reason": "replacement after commit"}
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, done["id"])
            row.input_payload = {**row.input_payload, "reason": changed["reason"]}
        with pytest.raises(AcceptanceIntegrityError):
            v["rule_service"].review(BusinessRuleReviewInput.model_validate(changed), invocation_id=done["id"], recorded_at="retry")
    assert inspect_rule(v)["head"]["status"] == "withdrawn" and count(v, BusinessRuleRevisionRecord) == 2


def test_rule_outbox_and_commit_authorization_failures_are_atomic(rule, monkeypatch):
    v = rule
    append = EventOutboxRepository.append
    def reject_event(self, event, **kwargs):
        if event.event_type == "quality.business_rule.reviewed":
            raise RuntimeError("injected outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", reject_event)
    assert submit_rule(v).json()["status"] == "failed" and count(v, BusinessRuleRevisionRecord) == 0
    monkeypatch.setattr(EventOutboxRepository, "append", append)
    record = v["rule_service"].repository.record
    def reject_access(request, basis, **kwargs):
        def denied():
            raise StaleSourceAccessScope("injected commit membership revocation")
        return record(request, basis, **{**kwargs, "require_current": denied})
    monkeypatch.setattr(v["rule_service"].repository, "record", reject_access)
    assert submit_rule(v).json()["status"] == "failed" and count(v, BusinessRuleRevisionRecord) == 0


def test_v3_pins_rules_and_withdrawal_invalidates_new_use_not_history(rule, monkeypatch):
    v = rule
    unapproved = preview(v, policy_revision=RULE_AUTHORITY_POLICY)
    legacy = preview(v, policy_revision=PARTITION_POLICY)
    legacy_before, legacy_url = read(v, completed(archive(v, legacy)[0]))
    completed(submit_rule(v))
    approved = preview(v, policy_revision=RULE_AUTHORITY_POLICY)
    assert approved["input_digest"] != unapproved["input_digest"]
    rule_constraint = next(c for c in approved["context"]["required_constraints"] if c["kind"] == "business_rule")
    assert rule_constraint["oracle"] == ORACLE and rule_constraint["authority"]["status"] == "approved"
    for part in approved["context"]["parts"]:
        assert rule_constraint in part["context"]["required_constraints"]
    before, url = read(v, completed(archive(v, approved)[0]))
    assert before["current_use"]["stale"] is False and before["current_use"]["generation_authorized"] is False
    completed(withdraw(v))
    after = v["client"].get(url, headers=v["headers"])
    assert after.status_code == 200
    assert after.json()["context"] == before["context"] and after.json()["current_use"]["stale"] is True
    legacy_after = v["client"].get(legacy_url, headers=v["headers"]).json()
    assert legacy_after["context"] == legacy_before["context"] and legacy_after["current_use"]["stale"] is False
    head = inspect_rule(v)["head"]
    completed(submit_rule(v, {**v["rule_request"], "expected_previous_revision_id": head["revision_id"]}))
    fresh = preview(v, policy_revision=RULE_AUTHORITY_POLICY)
    artifacts = app.state.container.context_packs.artifacts
    put = artifacts.put
    def revoke_during_write(*args):
        result = put(*args)
        completed(withdraw(v))
        return result
    monkeypatch.setattr(artifacts, "put", revoke_during_write)
    response, _ = archive(v, fresh)
    assert response.json()["status"] == "failed" and count(v, ContextPackRecord) == 2


def test_rule_history_remains_source_authorized_and_does_not_transfer_to_new_image(rule):
    v = rule
    completed(submit_rule(v))
    approved = inspect_rule(v)
    v["requirement_path"].write_text(v["requirement_path"].read_text().replace("401", "403"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    image = candidate(v)
    response = v["client"].get(v["rule_url"], headers=v["headers"], params={**v["rule_query"],
        "image_revision_id": image["image_revision_id"], "image_artifact_hash": image["artifact_hash"]})
    assert response.status_code == 200 and response.json()["head"] is None
    assert response.json()["rule_id"] != approved["rule_id"]
    grant_member(v)
    basis = approved["basis"]
    repository = SourceAccessRepository()
    epoch = repository.load_snapshot(v["project_id"]).acl_epoch
    repository.set_policy(v["project_id"], basis["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=epoch, changed_by=v["owner"]["id"], invocation_id="rule-denied")
    old = v["client"].get(v["rule_url"] + "/" + approved["head"]["revision_id"], headers=v["member_headers"])
    assert old.status_code == 403 and "HTTP 401" not in old.text
