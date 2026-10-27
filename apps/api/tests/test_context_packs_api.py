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
from apps.api.app.application.system_image.context_pack_inputs import ContextCompileInput, ContextPreviewInput
from apps.api.app.domain.system_image.context_pack import COMPILE_CONTEXT_TOOL, ContextPackIntegrityError
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, SourceAccessRule
from apps.api.tests.test_acceptance_specifications_api import acceptance, documents, evidence_api, submit as approve, inspect, ORACLE
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, completed, count
from apps.api.tests.test_source_access_api import grant_member, policy as restrict_source


def preview(v, **overrides):
    params = {k: value for k, value in v["ac_query"].items() if k != "object_id"} | overrides
    response = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/context-packs/preview", headers=v["headers"], params=params)
    assert response.status_code == 200, response.text
    return response.json()


def archive(v, view=None):
    view = view or preview(v)
    payload = {**view["request"], "expected_input_digest": view["input_digest"]}
    pending = invoke(v, COMPILE_CONTEXT_TOOL, payload, key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation", pending
    return confirm(v, pending), payload


def read(v, done):
    ident = done["result"]["object_refs"][0].split(":", 1)[1]
    url = f"/v1/projects/{v['project_id']}/system-image/context-packs/{ident}"
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json(), url


def test_enclosing_image_scope_does_not_cache_live_acceptance_authority(acceptance, monkeypatch):
    v = acceptance
    completed(approve(v))
    approved = inspect(v)["head"]
    request = ContextPreviewInput(project_id=v["project_id"],
        **{key: value for key, value in v["ac_query"].items() if key != "object_id"})
    images = app.state.container.image_revisions
    service = app.state.container.context_packs
    reads = []
    original = images.artifacts.read

    def counted(*args):
        reads.append((args[-1], images._current_verified_reads()))
        return original(*args)

    monkeypatch.setattr(images.artifacts, "read", counted)
    with actor_scope(UserProfile.model_validate(v["owner"])), images.verified_read_session():
        outer = images._verified_reads.get()
        before = service.preview(request)
        assert before["context"]["required_constraints"][0]["oracle"] == ORACLE
        completed(approve(v, {**v["ac_request"], "decision": "withdraw", "oracle": None,
            "authority_basis": None, "reason": "Withdraw authority during one compiler operation",
            "expected_previous_revision_id": approved["revision_id"]}))
        after = service.preview(request)
        assert after["input_digest"] != before["input_digest"]
        assert after["context"]["required_constraints"][0]["oracle"] is None
        assert after["context"]["readiness"]["status"] == "blocked"
        assert images._verified_reads.get() is outer
    assert images._verified_reads.get() is None
    # The withdrawing HTTP command runs in a different task/thread; it must
    # verify its own bytes, not borrow this compiler's snapshot via ContextVar.
    assert sum(digest == request.image_artifact_hash and scope is outer for digest, scope in reads) == 1
    assert sum(digest == request.image_artifact_hash and scope is not outer for digest, scope in reads) == 1
    # The next independent operation verifies the artifact again, not just its head.
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.preview(request) == after
    assert sum(digest == request.image_artifact_hash for digest, _ in reads) == 3
    assert count(v, ContextPackRecord) == 0


def test_enclosing_image_scope_reauthorizes_a_cached_image_after_source_revocation(acceptance, monkeypatch):
    v = acceptance
    grant_member(v)
    request = ContextPreviewInput(project_id=v["project_id"],
        **{key: value for key, value in v["ac_query"].items() if key != "object_id"})
    images = app.state.container.image_revisions
    service = app.state.container.context_packs
    reads = []
    original = images.artifacts.read

    def counted(*args):
        reads.append(args[-1])
        return original(*args)

    monkeypatch.setattr(images.artifacts, "read", counted)
    with images.verified_read_session():
        outer = images._verified_reads.get()
        with actor_scope(UserProfile.model_validate(v["member"])):
            before = service.preview(request)
            assert before["context"]["required_constraints"]
        assert reads.count(request.image_artifact_hash) == 1
        restrict_source(v)
        with actor_scope(UserProfile.model_validate(v["member"])), pytest.raises(SourceAccessDenied):
            service.preview(request)
        assert images._verified_reads.get() is outer
        assert reads.count(request.image_artifact_hash) == 1
        with actor_scope(UserProfile.model_validate(v["owner"])):
            assert service.preview(request)["context"] == before["context"]
        # A different actor must independently verify immutable bytes in the scope.
        assert reads.count(request.image_artifact_hash) == 2
    assert images._verified_reads.get() is None
    assert count(v, ContextPackRecord) == 0


def test_fixed_context_preserves_oracles_source_recall_and_history_not_live_authority(acceptance):
    v = acceptance
    unapproved = preview(v)
    assert unapproved["context"]["readiness"]["status"] == "blocked"
    assert unapproved["context"]["required_constraints"][0]["oracle"] is None
    completed(approve(v))
    authority = inspect(v)
    ready = preview(v)
    assert ready["input_digest"] != unapproved["input_digest"]
    assert ready["context"]["readiness"]["status"] == "partial"
    assert ready["context"]["required_constraints"][0]["oracle"] == ORACLE
    assert ready["context"]["budget"]["used_upper_bound"] <= 12000
    assert ready["context"]["facts"] and all(f["semantic_class"] == "retrieval_candidate_not_coverage" for f in ready["context"]["facts"])
    response, payload = archive(v, ready)
    done = completed(response)
    before, url = read(v, done)
    assert before["context"] == ready["context"] and before["current_use"] == {
        "stale": False, "generation_authorized": False, "reason": "draft_investigation_only"}
    queried = completed(invoke(v, "query.system_image.context.read", {"project_id": v["project_id"], "context_id": before["metadata"]["context_id"]}))
    assert "HTTP 400" not in json.dumps(queried["result"]["context_pack"])
    completed(approve(v, {**v["ac_request"], "decision": "withdraw", "oracle": None, "authority_basis": None,
        "reason": "Withdraw context oracle", "expected_previous_revision_id": authority["head"]["revision_id"]}))
    after = v["client"].get(url, headers=v["headers"]).json()
    assert after["context"] == before["context"] and after["current_use"]["stale"] is True
    assert after["current_use"]["generation_authorized"] is False
    with session_scope() as session:
        session.get(ToolInvocationRecord, done["id"]).status = "running"
    with actor_scope(UserProfile.model_validate(v["owner"])):
        restored = app.state.container.context_packs.compile(ContextCompileInput.model_validate(payload), invocation_id=done["id"], recorded_at="retry")
        assert restored == before["metadata"]
        assert app.state.container.tool_evidence.describe(queried["id"], v["project_id"])["observation"] == "historical_not_live"
    assert count(v, ContextPackRecord) == 1
    with session_scope() as session:
        row = session.scalar(select(ContextPackRecord).where(ContextPackRecord.project_id == v["project_id"]))
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == row.context_id)).all()
        assert len(events) == 1 and "HTTP 400" not in json.dumps(row.payload) + json.dumps(events[0].event_payload)
    for statement in (update(ContextPackRecord).where(ContextPackRecord.project_id == v["project_id"]).values(project_id="other"),
                      delete(ContextPackRecord).where(ContextPackRecord.project_id == v["project_id"])):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement)


def test_context_rechecks_authority_after_object_write_before_commit(acceptance, monkeypatch):
    v = acceptance
    completed(approve(v))
    head = inspect(v)["head"]
    view = preview(v)
    artifacts = app.state.container.context_packs.artifacts
    put = artifacts.put
    def withdraw(*args):
        result = put(*args)
        completed(approve(v, {**v["ac_request"], "decision": "withdraw", "oracle": None, "authority_basis": None,
            "reason": "Race fixture", "expected_previous_revision_id": head["revision_id"]}))
        return result
    monkeypatch.setattr(artifacts, "put", withdraw)
    response, _ = archive(v, view)
    assert response.json()["status"] == "failed" and response.json()["result"]["followup_reason"] == "context_inputs_changed"
    assert count(v, ContextPackRecord) == 0


def test_stale_preview_budget_permissions_and_unsupported_purpose_fail_closed(acceptance):
    v = acceptance
    view = preview(v)
    completed(approve(v))
    response, _ = archive(v, view)
    assert response.json()["status"] == "failed" and count(v, ContextPackRecord) == 0
    preview_url = f"/v1/projects/{v['project_id']}/system-image/context-packs/preview"
    params = {k: value for k, value in v["ac_query"].items() if k != "object_id"}
    denied = v["client"].get(preview_url, params={**params, "max_tokens": 512}, headers=v["headers"])
    assert denied.status_code == 422 and denied.json()["detail"]["error"]["code"] == "mandatory_context_over_budget"
    assert v["client"].get(preview_url, params=params, headers=v["member_headers"]).status_code == 403
    assert v["client"].get(preview_url, params=params).status_code == 401
    for field, value in (("purpose", "release"), ("purpose", "execution"), ("policy_revision", "unknown")):
        assert v["client"].get(preview_url, params={**params, field: value}, headers=v["headers"]).status_code == 422
    invalid = invoke(v, "query.system_image.context.preview", {**view["request"], "purpose": "execution"})
    assert invalid.json()["status"] == "failed"


def test_context_outbox_failure_does_not_persist_pack(acceptance, monkeypatch):
    v = acceptance
    append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.context.compiled":
            raise RuntimeError("injected outbox failure")
        return append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    response, _ = archive(v)
    assert response.json()["status"] == "failed" and count(v, ContextPackRecord) == 0


def test_context_migration_does_not_downgrade_away_existing_derivations(acceptance, monkeypatch):
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine

    completed(archive(acceptance)[0])
    migration = importlib.import_module("apps.api.migrations.versions.0051_context_packs")
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="cannot downgrade"):
            migration.downgrade()
    assert count(acceptance, ContextPackRecord) == 1


def test_context_read_revalidates_private_source_and_hides_corrupt_artifacts(acceptance, monkeypatch):
    v = acceptance
    done = completed(archive(v)[0])
    before, url = read(v, done)
    artifacts = app.state.container.context_packs.artifacts
    original = artifacts.read
    def corrupt(*args):
        result = original(*args)
        result["context"]["required_constraints"][0]["source_fields"][0]["value"] = "injected secret"
        return result
    monkeypatch.setattr(artifacts, "read", corrupt)
    denied = v["client"].get(url, headers=v["headers"])
    assert denied.status_code == 502 and "injected secret" not in denied.text
    monkeypatch.setattr(artifacts, "read", original)
    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    def revoke(*args):
        result = original(*args)
        repo = SourceAccessRepository()
        snapshot = repo.load_snapshot(v["project_id"])
        repo.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="context-revoke")
        return result
    monkeypatch.setattr(artifacts, "read", revoke)
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code in {403, 409} and "Empty input" not in denied.text


def test_context_history_is_scoped_paginated_private_and_available_as_agent_tool(acceptance):
    v = acceptance
    first = completed(archive(v)[0])
    second = completed(archive(v)[0])
    ids = sorted(item["result"]["object_refs"][0].split(":", 1)[1] for item in (first, second))
    url = f"/v1/projects/{v['project_id']}/system-image/context-packs"
    params = {k: value for k, value in v["ac_query"].items() if k != "object_id"}
    response = v["client"].get(url, headers=v["headers"], params={**params, "limit": 1})
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    page = response.json()
    assert [i["context_id"] for i in page["items"]] == ids[:1] and page["next_after_id"] == ids[0]
    assert "Empty input" not in response.text
    next_page = v["client"].get(url, headers=v["headers"], params={**params, "limit": 1, "after_id": ids[0]}).json()
    assert [i["context_id"] for i in next_page["items"]] == ids[1:] and next_page["next_after_id"] is None
    assert v["client"].get(url, headers=v["headers"], params={**params, "after_id": "unknown"}).status_code == 404
    assert v["client"].get(url, headers=v["member_headers"], params=params).status_code == 403
    assert v["client"].get(url, headers=v["headers"], params={**params, "image_artifact_hash": "sha256:" + "0" * 64}).status_code == 502
    observed = completed(invoke(v, "query.system_image.context.list", {"project_id": v["project_id"], **params}))
    receipt = observed["result"]["context_pack"]
    assert receipt["context_ids"] == ids and receipt["observation"] == "history_index_requires_revalidation"
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(observed["id"], v["project_id"])["context_ids"] == ids


def test_large_new_oracle_marks_old_context_stale_without_erasing_history(acceptance):
    v = acceptance
    original = preview(v)
    ceiling = original["context"]["budget"]["used_upper_bound"] + 150
    original = preview(v, max_tokens=ceiling)
    before, url = read(v, completed(archive(v, original)[0]))
    large = {key: "Required business behavior " * 60 for key in ORACLE}
    completed(approve(v, {**v["ac_request"], "oracle": large}))
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["context"] == before["context"]
    assert after["current_use"] == {"stale": True, "generation_authorized": False, "reason": "current_mandatory_context_over_budget"}


def test_worker_retries_commit_one_context_and_reject_rebinding(acceptance, monkeypatch):
    v = acceptance
    view = preview(v)
    payload = {**view["request"], "expected_input_digest": view["input_digest"]}
    pending = invoke(v, COMPILE_CONTEXT_TOOL, payload, key=uuid4().hex).json()
    assert pending["status"] == "waiting_confirmation"
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, pending["id"])
        row.status = "running"
        row.input_payload = {**row.input_payload, "confirmed_by_user": True}
    service = app.state.container.context_packs
    put, barrier = service.artifacts.put, Barrier(2)
    def put_together(*args):
        result = put(*args)
        barrier.wait(timeout=30)
        return result
    monkeypatch.setattr(service.artifacts, "put", put_together)
    def attempt(index):
        with actor_scope(UserProfile.model_validate(v["owner"])):
            return service.compile(ContextCompileInput.model_validate(payload), invocation_id=pending["id"],
                recorded_at=f"2026-09-19T00:00:0{index}+00:00")
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(attempt, range(2)))
    assert first == second and count(v, ContextPackRecord) == 1
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == first["context_id"])).all()
        assert len(events) == 1
        row = session.get(ToolInvocationRecord, pending["id"])
        original_input = dict(row.input_payload)
        row.input_payload = {**row.input_payload, "max_tokens": 12001}
    try:
        with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(ContextPackIntegrityError):
            service.compile(ContextCompileInput.model_validate({**payload, "max_tokens": 12001}), invocation_id=pending["id"], recorded_at="recovery")
    finally:
        # Later populated migrations inspect every historical command in this DB.
        with session_scope() as session:
            session.get(ToolInvocationRecord, pending["id"]).input_payload = original_input
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.compile(ContextCompileInput.model_validate(payload), invocation_id=pending["id"], recorded_at="restored") == first
    assert count(v, ContextPackRecord) == 1
