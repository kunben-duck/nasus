import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.quality_loop.acceptance_specifications import AcceptanceReviewInput
from apps.api.app.domain.quality_loop.acceptance_specification import AC_TOOL, AC_POLICY, AcceptanceIntegrityError, StaleAcceptanceSpecification
from apps.api.app.domain.system_image.source_access import SourceAccessRule, StaleSourceAccessScope
from apps.api.app.infrastructure.persistence.acceptance_specification_models import AcceptanceRevisionRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_document_projection_api import documents, REQUIREMENT
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, completed, count
from apps.api.tests.test_source_access_api import grant_member


ORACLE = dict(preconditions="Authenticated user", action="POST /search with empty input", observation="HTTP response status", expected_result="HTTP 400")


@pytest.fixture
def acceptance(documents):
    v = documents
    image = candidate(v)
    obj = next(o for o in v["document_objects"] if o["type"] == "SourceAcceptanceCriterion")
    query = dict(image_revision_id=image["image_revision_id"], image_artifact_hash=image["artifact_hash"], object_id=obj["id"])
    url = f"/v1/projects/{v['project_id']}/quality/acceptance-specifications"
    response = v["client"].get(url, params=query, headers=v["headers"])
    assert response.status_code == 200, response.text
    preview = response.json()
    payload = dict(project_id=v["project_id"], **query, basis_digest=preview["basis_digest"], expected_previous_revision_id=None,
        decision="approve", oracle=ORACLE, authority_basis="user_confirmed_requirement", reason="Fixture reviewer confirms requirement independently of code", policy_revision=AC_POLICY)
    v.update(ac_url=url, ac_query=query, ac_preview=preview, ac_request=payload, ac_service=app.state.container.acceptance_specifications)
    return v


def submit(v, payload=None, *, headers=None, key=None):
    pending = invoke(v, AC_TOOL, payload or v["ac_request"], headers=headers, key=key or uuid4().hex)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers or v["headers"])


def inspect(v):
    result = v["client"].get(v["ac_url"], params=v["ac_query"], headers=v["headers"])
    assert result.status_code == 200, result.text
    return result.json()


def test_authority_needs_separate_confirmation_is_immutable_and_can_be_withdrawn(acceptance):
    v = acceptance
    assert v["ac_preview"]["head"] is None and v["ac_preview"]["current"] is None
    key = uuid4().hex
    pending = invoke(v, AC_TOOL, {**v["ac_request"], "confirmed_by_user": True}, key=key).json()
    assert pending["status"] == "waiting_confirmation" and count(v, AcceptanceRevisionRecord) == 0
    done = completed(confirm(v, pending))
    assert completed(invoke(v, AC_TOOL, v["ac_request"], key=key))["id"] == done["id"]
    assert completed(confirm(v, pending))["id"] == done["id"]
    approved = inspect(v)
    assert approved["head"]["status"] == "approved" and approved["head"]["authority_actor"] == v["owner"]["id"]
    assert approved["current"]["oracle"] == ORACLE and approved["basis"] == v["ac_preview"]["basis"]
    assert approved["basis"]["source_authority"] == "unapproved_source_projection"
    assert approved["image_publication"] == "unchanged" and approved["revision_count"] == 1
    read_url = f"{v['ac_url']}/{approved['head']['revision_id']}"
    old = v["client"].get(read_url, headers=v["headers"])
    assert old.status_code == 200 and old.headers["cache-control"] == "private, no-store"
    assert old.json()["historical_not_live"] is True
    with actor_scope(UserProfile.model_validate(v["owner"])):
        resolved = v["ac_service"].resolve_oracle(v["project_id"], v["ac_query"]["image_revision_id"], v["ac_query"]["object_id"],
            approved["head"]["revision_id"], approved["head"]["artifact_hash"])
        assert resolved["oracle"] == ORACLE
        for image_id, artifact_hash in (("other-image", approved["head"]["artifact_hash"]),
                                         (v["ac_query"]["image_revision_id"], "sha256:" + "a" * 64)):
            with pytest.raises(AcceptanceIntegrityError):
                v["ac_service"].resolve_oracle(v["project_id"], image_id, v["ac_query"]["object_id"], approved["head"]["revision_id"], artifact_hash)
    for statement in (update(AcceptanceRevisionRecord).values(status="withdrawn").where(AcceptanceRevisionRecord.project_id == v["project_id"]),
                      delete(AcceptanceRevisionRecord).where(AcceptanceRevisionRecord.project_id == v["project_id"])):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement)
    query_result = completed(invoke(v, "query.quality.acceptance_specification", {"project_id": v["project_id"], **v["ac_query"]}))
    receipt = query_result["result"]["acceptance_authority"]
    assert receipt["head_revision_id"] == approved["head"]["revision_id"] and receipt["status"] == "approved"
    assert "Empty input" not in json.dumps(receipt) and "HTTP 400" not in json.dumps(receipt)
    assert submit(v).json()["result"]["followup_reason"] == "stale_acceptance_authority"
    withdrawn = {**v["ac_request"], "decision": "withdraw", "oracle": None, "authority_basis": None,
        "reason": "Requirements owner withdrew this oracle", "expected_previous_revision_id": approved["head"]["revision_id"]}
    completed(submit(v, withdrawn))
    current = inspect(v)
    assert current["head"]["status"] == "withdrawn" and current["current"]["oracle"] is None
    assert current["head"]["previous_revision_id"] == approved["head"]["revision_id"] and current["revision_count"] == 2
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(StaleAcceptanceSpecification):
            v["ac_service"].resolve_oracle(v["project_id"], v["ac_query"]["image_revision_id"], v["ac_query"]["object_id"],
                approved["head"]["revision_id"], approved["head"]["artifact_hash"])
        # A Planner may replay metadata, but it is explicitly not a live oracle grant.
        observation = app.state.container.tool_evidence.describe(query_result["id"], v["project_id"])
        assert observation == receipt and observation["observation"] == "query_time_not_live"
    assert v["client"].get(read_url, headers=v["headers"]).json() == old.json()
    assert count(v, AcceptanceRevisionRecord) == 2
    with session_scope() as session:
        rows = session.scalars(select(AcceptanceRevisionRecord).where(AcceptanceRevisionRecord.project_id == v["project_id"])).all()
        ids = [r.revision_id for r in rows]
        metadata = json.dumps([r.payload for r in rows])
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id.in_(ids))).all()
        assert len(events) == 2
        for raw in ("HTTP 400", "Empty input", "local-object://"):
            assert raw not in metadata + json.dumps([e.event_payload for e in events])


def test_invalid_authority_source_or_role_never_creates_specification(acceptance):
    v = acceptance
    for change in ({"oracle": None}, {"authority_basis": None}, {"authority_basis": "model_inferred"},
                   {"oracle": {**ORACLE, "observation": " "}}, {"reason": " "}, {"authority_actor": "forged"},
                   {"decision": "withdraw", "oracle": None, "authority_basis": None},
                   {"basis_digest": "sha256:" + "a" * 64}, {"image_artifact_hash": "sha256:" + "b" * 64},
                   {"object_id": next(o["id"] for o in v["document_objects"] if o["type"] == "TestCase")},
                   {"image_revision_id": "foreign"}, {"project_id": "foreign"}):
        response = submit(v, {**v["ac_request"], **change})
        assert response.status_code in {403, 404} or response.json()["status"] in {"failed", "denied"}, response.text
    grant_member(v)
    assert v["client"].get(v["ac_url"], params=v["ac_query"], headers=v["member_headers"]).json()["can_review"] is False
    denied = submit(v, headers=v["member_headers"])
    assert denied.status_code == 403 or denied.json()["status"] in {"failed", "denied"}
    assert v["client"].get(v["ac_url"], params=v["ac_query"]).status_code == 401
    assert count(v, AcceptanceRevisionRecord) == 0


def test_concurrent_approvals_require_cas_and_new_source_does_not_inherit(acceptance):
    v = acceptance
    pending = [invoke(v, AC_TOOL, {**v["ac_request"], "reason": f"Reviewer choice {i}"}, key=uuid4().hex).json() for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda p: confirm(v, p), pending))
    assert sorted(o.json()["status"] for o in outcomes) == ["completed", "failed"]
    assert count(v, AcceptanceRevisionRecord) == 1
    old = inspect(v)
    v["requirement_path"].write_text(REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    image = candidate(v)
    updated = v["client"].get(v["ac_url"], headers=v["headers"], params={**v["ac_query"],
        "image_revision_id": image["image_revision_id"], "image_artifact_hash": image["artifact_hash"]})
    assert updated.status_code == 200, updated.text
    assert updated.json()["head"] is None and updated.json()["basis_digest"] != old["basis_digest"]
    assert updated.json()["ac_id"] != old["ac_id"]
    v["requirement_path"].unlink()
    assert inspect(v) == old


def test_lost_completion_replays_original_decision_without_reactivating_withdrawn_oracle(acceptance, monkeypatch):
    v = acceptance
    done = completed(submit(v))
    approved = inspect(v)
    completed(submit(v, {**v["ac_request"], "decision": "withdraw", "oracle": None, "authority_basis": None,
        "reason": "Withdraw fixture authority", "expected_previous_revision_id": approved["head"]["revision_id"]}))
    withdrawn = inspect(v)
    with session_scope() as session:
        session.get(ToolInvocationRecord, done["id"]).status = "running"

    def unexpected_write(*args):
        raise AssertionError("recovery must reuse the original archived decision")

    monkeypatch.setattr(v["ac_service"].artifacts, "put", unexpected_write)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        replay = v["ac_service"].review(AcceptanceReviewInput.model_validate(v["ac_request"]),
            invocation_id=done["id"], recorded_at="recovery-must-not-replace-original-time")
        assert replay.revision_id == approved["head"]["revision_id"]
        assert replay.artifact_hash == approved["head"]["artifact_hash"]
        assert replay.recorded_at == approved["head"]["recorded_at"]
        with pytest.raises(StaleAcceptanceSpecification):
            v["ac_service"].resolve_oracle(v["project_id"], replay.image_revision_id, replay.object_id, replay.revision_id, replay.artifact_hash)
    assert inspect(v) == withdrawn and count(v, AcceptanceRevisionRecord) == 2
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id.in_([approved["head"]["revision_id"], withdrawn["head"]["revision_id"]]))).all()
        assert len(events) == 2


@pytest.mark.parametrize("change", [
    {"reason": "Rewritten after commit"},
    {"oracle": {**ORACLE, "expected_result": "HTTP 200"}},
])
def test_recovery_rejects_rewritten_canonical_input_against_original_artifact(acceptance, change):
    v = acceptance
    done = completed(submit(v))
    original = inspect(v)
    altered = {**v["ac_request"], **change}
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, done["id"])
        row.status = "running"
        row.input_payload = {**row.input_payload, **change}
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(AcceptanceIntegrityError, match="committed acceptance request changed"):
            v["ac_service"].review(AcceptanceReviewInput.model_validate(altered), invocation_id=done["id"], recorded_at="retry")
    assert inspect(v) == original and count(v, AcceptanceRevisionRecord) == 1


def test_concurrent_worker_retries_return_one_revision_and_one_event(acceptance, monkeypatch):
    v = acceptance
    pending = invoke(v, AC_TOOL, v["ac_request"], key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation"
    # Model the worker boundary after Runtime's confirmation gate, before either
    # attempt commits; public confirmation/idempotency is covered separately.
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, pending["id"])
        row.status = "running"
        row.input_payload = {**row.input_payload, "confirmed_by_user": True}
    barrier = Barrier(2)
    put = v["ac_service"].artifacts.put
    def put_together(*args):
        result = put(*args)
        barrier.wait(timeout=20)
        return result
    monkeypatch.setattr(v["ac_service"].artifacts, "put", put_together)
    def attempt(index):
        with actor_scope(UserProfile.model_validate(v["owner"])):
            return v["ac_service"].review(AcceptanceReviewInput.model_validate(v["ac_request"]),
                invocation_id=pending["id"], recorded_at=f"2026-09-19T00:00:0{index}+00:00")
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(attempt, range(2)))
    assert first == second and count(v, AcceptanceRevisionRecord) == 1
    with session_scope() as session:
        assert len(session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == first.revision_id)).all()) == 1


def test_outbox_canonical_and_commit_access_failures_roll_back(acceptance, monkeypatch):
    v = acceptance
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "quality.acceptance_specification.reviewed":
            raise RuntimeError("injected outbox failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    assert submit(v).json()["status"] == "failed" and count(v, AcceptanceRevisionRecord) == 0
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    record = v["ac_service"].repository.record
    def tamper(request, basis, **kwargs):
        with session_scope() as session:
            row = session.get(ToolInvocationRecord, kwargs["invocation_id"])
            row.input_payload = {**row.input_payload, "reason": "forged"}
        return record(request, basis, **kwargs)
    monkeypatch.setattr(v["ac_service"].repository, "record", tamper)
    assert submit(v).json()["status"] == "failed" and count(v, AcceptanceRevisionRecord) == 0
    def revoke(request, basis, **kwargs):
        def deny():
            raise StaleSourceAccessScope("injected commit scope change")
        return record(request, basis, **{**kwargs, "require_current": deny})
    monkeypatch.setattr(v["ac_service"].repository, "record", revoke)
    assert submit(v).json()["status"] == "failed" and count(v, AcceptanceRevisionRecord) == 0


def test_authority_artifact_and_read_acl_fail_closed(acceptance, monkeypatch):
    v = acceptance
    completed(submit(v))
    head = inspect(v)["head"]
    url = f"{v['ac_url']}/{head['revision_id']}"
    artifacts = v["ac_service"].artifacts
    original = artifacts.read
    def corrupt(*args):
        value = original(*args)
        value["request"]["oracle"]["expected_result"] = "forged result"
        return value
    monkeypatch.setattr(artifacts, "read", corrupt)
    result = v["client"].get(url, headers=v["headers"])
    assert result.status_code == 502 and "forged result" not in result.text
    grant_member(v)
    def revoke(*args):
        value = original(*args)
        access = SourceAccessRepository()
        snapshot = access.load_snapshot(v["project_id"])
        access.set_policy(v["project_id"], v["ac_preview"]["basis"]["binding_id"], SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="acceptance-read-revoke")
        return value
    monkeypatch.setattr(artifacts, "read", revoke)
    result = v["client"].get(url, headers=v["member_headers"])
    assert result.status_code in {403, 409} and "HTTP 400" not in result.text
