from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.quality_loop.test_design_scope_inputs import ScopeReviewInput
from apps.api.app.domain.quality_loop.test_design_scope import SCOPE_TOOL, SCOPE_QUERY_TOOL, TestDesignScopeChanged, TestDesignScopeIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.test_design_scope_models import TestDesignScopeRecord as Record
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.db_models import UserIdentityRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, completed, count
from apps.api.tests.test_published_image_reads import publish
from apps.api.tests.test_published_context_packs import request_for, preview_response, advance
from apps.api.tests.test_context_packs_api import archive, read
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_test_design_scope import scope_contract, ORACLE


@pytest.fixture
def design_scope(publication):
    v = publication
    head = publish(v)
    view = preview_response(v, request_for(v, head)).json()
    approvals = []
    for item in view["context"]["required_constraints"]:
        assert item["kind"] == "acceptance_criterion"
        query = {k: head[k] for k in ("image_revision_id", "image_artifact_hash")} | {"object_id": item["object_id"]}
        url = f"/v1/projects/{v['project_id']}/quality/acceptance-specifications"
        basis = v["client"].get(url, headers=v["headers"], params=query).json()
        request = dict(project_id=v["project_id"], **query, basis_digest=basis["basis_digest"], expected_previous_revision_id=None,
            decision="approve", oracle=ORACLE, authority_basis="user_confirmed_requirement", reason="Independent fixture authority",
            policy_revision="nasus.acceptance-authority.v1")
        done = completed(confirm(v, invoke(v, "quality.acceptance_specification.review", request, key=uuid4().hex).json()))
        approvals.append((request, done["result"]["object_refs"][0].split(":", 1)[1]))
    view = preview_response(v, request_for(v, head)).json()
    archived, _ = read(v, completed(archive(v, view)[0]))
    metadata = archived["metadata"]
    request = dict(project_id=v["project_id"], context_id=metadata["context_id"], context_artifact_hash=metadata["artifact_hash"],
        expected_previous_revision_id=None, decision="approve", contract=scope_contract(archived["context"]["required_constraints"]),
        reason="Fixture reviewed test-design scope, not exweb author approval", policy_revision="nasus.test-design-scope.v1")
    v.update(scope_request=request, context=archived, context_head=head, scope_url=f"/v1/projects/{v['project_id']}/quality/test-design-scopes",
        scope_service=app.state.container.test_design_scopes, source_approvals=approvals)
    return v


def submit(v, request=None, headers=None):
    pending = invoke(v, SCOPE_TOOL, request or v["scope_request"], key=uuid4().hex, headers=headers)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers or v["headers"])


def inspect(v):
    response = v["client"].get(v["scope_url"], params={"context_id": v["scope_request"]["context_id"]}, headers=v["headers"])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


@pytest.mark.parametrize("state", ["unreviewed", "approved", "withdrawn", "stale"])
def test_scope_inspection_verifies_the_context_once_per_request(design_scope, monkeypatch, state):
    v = design_scope
    if state != "unreviewed":
        completed(submit(v))
    if state == "withdrawn":
        revision = inspect(v)["head"]["revision"]
        completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": revision["revision_id"],
            "decision": "withdraw", "contract": None}))
    elif state == "stale":
        advance(v, v["context_head"])
    original, calls = v["scope_service"].contexts.read, []

    def tracked(project_id, context_id):
        calls.append((project_id, context_id))
        return original(project_id, context_id)

    monkeypatch.setattr(v["scope_service"].contexts, "read", tracked)
    view = inspect(v)
    assert calls == [(v["project_id"], v["scope_request"]["context_id"])]
    assert view["context_current_use"]["stale"] is (state == "stale")
    if state == "unreviewed":
        assert view["head"] is None
    else:
        assert view["head"]["revision"]["status"] == ("withdrawn" if state == "withdrawn" else "approved")
        assert view["head"]["current_use"]["scope_current"] is (state == "approved")


def test_scope_inspection_rechecks_access_after_reusing_verified_context(design_scope, monkeypatch):
    v = design_scope
    completed(submit(v))
    original, calls = v["scope_service"].contexts.read, []

    def revoke(project_id, context_id):
        context = original(project_id, context_id)
        calls.append(context_id)
        repository = SourceAccessRepository()
        snapshot = repository.load_snapshot(project_id)
        repository.set_policy(project_id, snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="scope-inspection-revoke")
        return context

    monkeypatch.setattr(v["scope_service"].contexts, "read", revoke)
    response = v["client"].get(v["scope_url"], params={"context_id": v["scope_request"]["context_id"]}, headers=v["headers"])
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"]["code"] == "source_access_changed"
    assert calls == [v["scope_request"]["context_id"]]
    assert "head" not in response.json()


def test_approved_and_withdrawn_scope_audits_remain_readable_by_platform(design_scope):
    v = design_scope
    approved = completed(submit(v))
    revision = inspect(v)["head"]["revision"]
    withdrawn = completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": revision["revision_id"],
        "decision": "withdraw", "contract": None}))
    for command, status in ((approved, "approved"), (withdrawn, "withdrawn")):
        response = v["client"].get("/v1/audit-events", headers=v["headers"], params={"tool_invocation_id": command["id"]})
        assert response.status_code == 200, response.text
        events = response.json()
        assert any(event["action"] == "quality.test_design_scope.reviewed" and event["status"] == status for event in events)
        assert any(event["action"] == "tool.invocation.completed" and event["status"] == "completed" for event in events)
    # A later read must not fail while deserializing unrelated authority history.
    response = v["client"].get("/v1/audit-events", headers=v["headers"])
    assert response.status_code == 200, response.text


def test_scope_review_is_confirmed_immutable_atomic_and_withdrawable(design_scope):
    v = design_scope
    assert inspect(v)["head"] is None
    pending = invoke(v, SCOPE_TOOL, {**v["scope_request"], "confirmed_by_user": True}).json()
    assert pending["status"] == "waiting_confirmation" and count(v, Record) == 0
    done = completed(confirm(v, pending))
    head = inspect(v)["head"]
    revision = head["revision"]
    assert head["current_use"] == {"scope_current": True, "scope_complete": True, "generation_authorized": False}
    assert head["request"] == v["scope_request"]
    assert completed(confirm(v, pending))["id"] == done["id"]
    for statement in (delete(Record), update(Record).values(status="withdrawn")):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(Record.project_id == v["project_id"]))
    with session_scope() as session:
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == revision["revision_id"])).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == revision["revision_id"])).all()
        assert len(audits) == len(events) == 1 and audits[0].actor == v["owner"]["id"]
    query = completed(invoke(v, SCOPE_QUERY_TOOL, {k: v["scope_request"][k] for k in ("project_id", "context_id")}))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert v["scope_service"].resolve(v["project_id"], revision["revision_id"], revision["artifact_hash"])["request"] == head["request"]
        assert app.state.container.tool_evidence.describe(query["id"], v["project_id"]) == query["result"]["test_design_scope"]
    completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": revision["revision_id"], "decision": "withdraw", "contract": None}))
    old = v["client"].get(v["scope_url"] + "/" + revision["revision_id"], headers=v["headers"]).json()
    assert old["request"] == head["request"] and not old["current_use"]["scope_current"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(TestDesignScopeChanged):
            v["scope_service"].resolve(v["project_id"], revision["revision_id"], revision["artifact_hash"])
        with pytest.raises(TestDesignScopeChanged):
            app.state.container.tool_evidence.describe(query["id"], v["project_id"])
        assert v["scope_service"].review(ScopeReviewInput.model_validate(v["scope_request"]), invocation_id=done["id"], recorded_at="retry") == revision
    assert count(v, Record) == 2


def test_scope_missing_obligations_foreign_pins_and_member_review_are_rejected(design_scope):
    v = design_scope
    for change in ({"context_artifact_hash": "sha256:" + "0" * 64}, {"contract": None}, {"context_id": "foreign"},
                   {"contract": {**v["scope_request"]["contract"], "examples": []}}, {"authority_actor": "forged"}):
        result = submit(v, {**v["scope_request"], **change})
        assert result.status_code in {403, 404} or result.json()["status"] in {"failed", "denied"}, result.text
    grant_member(v)
    assert submit(v, headers=v["member_headers"]).json()["status"] in {"failed", "denied"}
    assert v["client"].get(v["scope_url"], params={"context_id": v["scope_request"]["context_id"]}).status_code == 401
    assert count(v, Record) == 0


def test_scope_cas_competition_and_recovery_do_not_move_head(design_scope, monkeypatch):
    v = design_scope
    pending = [invoke(v, SCOPE_TOOL, {**v["scope_request"], "reason": f"Concurrent fixture {i}"}, key=uuid4().hex).json() for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [r.json() for r in pool.map(lambda p: confirm(v, p), pending)]
    assert sorted(r["status"] for r in results) == ["completed", "failed"]
    done = next(r for r in results if r["status"] == "completed")
    revision = inspect(v)["head"]["revision"]
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, done["id"])
        payload = {k: value for k, value in row.input_payload.items() if k in ScopeReviewInput.model_fields}
    def no_put(*args):
        raise AssertionError("committed recovery must not rewrite artifacts")
    monkeypatch.setattr(v["scope_service"].artifacts, "put", no_put)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert v["scope_service"].review(ScopeReviewInput.model_validate(payload), invocation_id=done["id"], recorded_at="retry") == revision
        with pytest.raises(TestDesignScopeIntegrityError):
            v["scope_service"].review(ScopeReviewInput.model_validate({**payload, "reason": "rebound"}), invocation_id=done["id"], recorded_at="retry")
    assert count(v, Record) == 1


@pytest.mark.parametrize("failure", ["outbox", "head_changed_after_put", "source_oracle_withdrawn"])
def test_scope_commit_rechecks_inputs_and_rolls_back(design_scope, monkeypatch, failure):
    v = design_scope
    if failure == "outbox":
        original = EventOutboxRepository.append
        def fail(self, event, **kwargs):
            if event.event_type == "quality.test_design_scope.reviewed":
                raise RuntimeError("injected scope event failure")
            return original(self, event, **kwargs)
        monkeypatch.setattr(EventOutboxRepository, "append", fail)
    else:
        original = v["scope_service"].artifacts.put
        def change(*args):
            result = original(*args)
            if failure == "head_changed_after_put":
                advance(v, v["context_head"])
            else:
                request, revision = v["source_approvals"][0]
                request = {**request, "expected_previous_revision_id": revision, "decision": "withdraw", "oracle": None, "authority_basis": None}
                completed(confirm(v, invoke(v, "quality.acceptance_specification.review", request, key=uuid4().hex).json()))
            return result
        monkeypatch.setattr(v["scope_service"].artifacts, "put", change)
    assert submit(v).json()["status"] == "failed" and count(v, Record) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.action == "quality.test_design_scope.reviewed",
            AuditEventRecord.event_metadata["context_id"].as_string() == v["scope_request"]["context_id"])).all()


def test_scope_gaps_are_persisted_not_silently_ready_and_acl_is_rechecked(design_scope):
    v = design_scope
    request = deepcopy(v["scope_request"])
    request["contract"]["gaps"] = [{"id": "missing-boundary", "constraint_ids": [request["contract"]["examples"][0]["constraint_id"]],
                                     "description": "Fixture reviewer requests business clarification"}]
    completed(submit(v, request))
    view = inspect(v)["head"]
    assert view["current_use"]["scope_current"] and not view["current_use"]["scope_complete"]
    assert view["assessment"]["blockers"] == ["explicit_gap:missing-boundary"]
    grant_member(v)
    url = v["scope_url"] + "/" + view["revision"]["revision_id"]
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="scope-revoke")
    response = v["client"].get(url, headers=v["member_headers"])
    assert response.status_code == 403 and "HTTP 400" not in response.text


def test_scope_migration_refuses_destructive_downgrade(design_scope, monkeypatch):
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    completed(submit(design_scope))
    module = importlib.import_module("apps.api.migrations.versions.0057_test_design_scope")
    with engine.begin() as connection:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="cannot downgrade"):
            module.downgrade()
    assert count(design_scope, Record) == 1


def test_scope_history_does_not_expose_tampered_private_artifacts(design_scope, monkeypatch):
    v = design_scope
    completed(submit(v))
    view = inspect(v)["head"]
    artifacts = v["scope_service"].artifacts
    original = artifacts.read
    def corrupt(*args):
        payload = original(*args)
        payload["request"]["reason"] = "injected private source"
        return payload
    monkeypatch.setattr(artifacts, "read", corrupt)
    response = v["client"].get(v["scope_url"] + "/" + view["revision"]["revision_id"], headers=v["headers"])
    assert response.status_code == 502 and "injected private source" not in response.text


def test_scope_rechecks_registered_reviewer_after_private_artifact_write(design_scope, monkeypatch):
    v = design_scope
    artifacts = v["scope_service"].artifacts
    original = artifacts.put
    def disable(*args):
        result = original(*args)
        with session_scope() as session:
            session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
        return result
    monkeypatch.setattr(artifacts, "put", disable)
    response = submit(v)
    assert response.status_code in {401, 403} or response.json()["status"] == "failed"
    assert count(v, Record) == 0


def test_scope_receipt_becomes_stale_when_oracle_changes_without_scope_head_change(design_scope):
    v = design_scope
    completed(submit(v))
    query = completed(invoke(v, SCOPE_QUERY_TOOL, {k: v["scope_request"][k] for k in ("project_id", "context_id")}))
    before = query["result"]["test_design_scope"]
    assert before["scope_current"] and before["scope_complete"] and not before["context_stale"]
    request, revision = v["source_approvals"][0]
    withdrawn = {**request, "expected_previous_revision_id": revision, "decision": "withdraw", "oracle": None, "authority_basis": None}
    completed(confirm(v, invoke(v, "quality.acceptance_specification.review", withdrawn, key=uuid4().hex).json()))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(TestDesignScopeChanged):
            app.state.container.tool_evidence.describe(query["id"], v["project_id"])
    current = inspect(v)["head"]
    assert current["revision"]["revision_id"] == before["head_revision_id"] and not current["current_use"]["scope_current"]
