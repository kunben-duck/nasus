from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, update, delete
from sqlalchemy.exc import DBAPIError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image.context_invalidations import ContextInvalidateInput, context_invalidation_query_keys
from apps.api.app.domain.system_image.context_invalidation import INVALIDATE_CONTEXT_TOOL, ContextInvalidationIntegrityError
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.context_invalidation_models import ContextInvalidationRecord as Record, ContextInvalidationNodeRecord, ContextInvalidationEdgeRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, AuditEventRecord, SSEEventOutboxRecord, LLMCallRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_context_change_impact_api import impact, read, query
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_test_design_scope_api import design_scope
from apps.api.tests.test_test_design_results_api import generation_result, read_result
from apps.api.tests.test_test_design_mapping_api import mapping, submit as mapping_submit
from apps.api.tests.test_semantic_evaluations_api import invoke, completed, count
from apps.api.tests.test_source_access_api import grant_member


def selection(v):
    result = completed(query(v))
    return {**v["impact_request"], "expected_impact_hash": result["result"]["image_query"]["result_hash"],
        "reason": "Independent fixture source change confirmation; not execution authorization"}


def submit(v, request=None, headers=None):
    pending = invoke(v, INVALIDATE_CONTEXT_TOOL, request or selection(v), headers=headers, key=uuid4().hex)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers or v["headers"])


def history(v, invalidation_id, headers=None):
    return v["client"].get(f"{v['image_url']}/context-invalidations/{invalidation_id}", headers=headers or v["headers"])


def test_confirmed_invalidation_blocks_current_consumers_but_preserves_all_history(impact, monkeypatch):
    v = impact
    context_url = f"{v['image_url']}/context-packs/{v['impact_request']['context_id']}"
    before = v["client"].get(context_url, headers=v["headers"]).json()
    old_result = read_result(v, v["generation_metadata"]).json()
    calls_before = count(v, LLMCallRecord)
    request = selection(v)
    pending = invoke(v, INVALIDATE_CONTEXT_TOOL, {**request, "confirmed_by_user": True}, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert count(v, Record) == 0
    command = completed(v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=v["headers"]))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    response = history(v, ident)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    archived = response.json()
    assert archived["metadata"]["invalidation_applied"] and not archived["metadata"]["impact_complete"]
    assert archived["metadata"]["impact_hash"] == request["expected_impact_hash"]
    assert {node["kind"] for node in archived["dependencies"]} == {"context", "scope", "generation", "case", "coverage", "mapping"}
    after = v["client"].get(context_url, headers=v["headers"]).json()
    for key in ("metadata", "context", "derivation"):
        assert after[key] == before[key]
    assert after["current_use"] == {"stale": True, "generation_authorized": False,
        "reason": "source_change_invalidated", "invalidation_id": ident}
    current_result = read_result(v, v["generation_metadata"]).json()
    assert current_result["metadata"] == old_result["metadata"] and current_result["result"] == old_result["result"]
    assert not current_result["current_use"]["scope_current"]
    view = v["client"].get(v["mapping_url"], headers=v["headers"],
        params={"artifact_hash": v["generation_metadata"]["artifact_hash"]}).json()
    assert not view["head"]["current_use"]["mapping_current"] and not view["scope_current"]
    assert view["head"]["revision"]["status"] == "reviewed"
    refused = mapping_submit(v, {**v["mapping_request"], "expected_previous_revision_id": view["head"]["revision"]["revision_id"]})
    assert refused.json()["status"] == "failed", refused.text
    generation = invoke(v, "query.quality.test_design_generation", {"project_id": v["project_id"],
        "scope_revision_id": v["execution"]["request"].scope_revision_id,
        "scope_artifact_hash": v["execution"]["request"].scope_artifact_hash}, key=uuid4().hex)
    assert generation.json()["status"] == "failed" and count(v, LLMCallRecord) == calls_before
    with actor_scope(UserProfile.model_validate(v["owner"])):
        restored = app.state.container.context_invalidations.invalidate(ContextInvalidateInput.model_validate(request),
            invocation_id=command["id"], recorded_at=datetime.now(timezone.utc).isoformat())
    assert restored == archived["metadata"] and count(v, Record) == 1
    # Archiving the same old source image under a fresh ID must not bypass stale.
    from apps.api.tests.test_context_packs_api import archive as archive_context, read as read_context
    from apps.api.tests.test_published_context_packs import preview_response, request_for
    preview = preview_response(v, request_for(v, v["context_head"])).json()
    clone, _ = read_context(v, completed(archive_context(v, preview)[0]))
    assert clone["metadata"]["context_id"] != request["context_id"]
    assert clone["current_use"]["stale"] and clone["current_use"]["invalidation_id"] == ident
    with session_scope() as session:
        node_rows = session.scalars(select(ContextInvalidationNodeRecord).where(ContextInvalidationNodeRecord.invalidation_id == ident)).all()
        edge_rows = session.scalars(select(ContextInvalidationEdgeRecord).where(ContextInvalidationEdgeRecord.invalidation_id == ident)).all()
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == command["id"])).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident)).all()
        assert len(node_rows) == archived["metadata"]["dependency_count"] and edge_rows and audits and events
        conversation_id = v["conversation"].json()["id"]
        assert len(events) == 1 and events[0].conversation_id == conversation_id
        assert events[0].event_payload["snapshot_hint"] is True
        assert events[0].event_payload["query_keys"] == context_invalidation_query_keys(v["project_id"])
        terminal = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == command["id"],
            SSEEventOutboxRecord.event_type == "tool.invocation.updated").order_by(SSEEventOutboxRecord.sequence)).all()
        assert terminal[-1].event_payload["query_keys"] == context_invalidation_query_keys(v["project_id"])
        durable = json.dumps([row.event_payload for row in events]) + json.dumps(command["result"])
    replay = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=conversation_id, after_event_id=None)
    assert [event.entity_id for event in replay if event.event_type == "system_image.context.invalidated"] == [ident]
    assert not EventOutboxRepository().list_after(stream_kind="conversation", stream_id=uuid4().hex, after_event_id=None)
    for private in ("changed dependency fixture", "Orders", "HTTP 400", "artifact_ref", "s3://", "source_fields", request["reason"]):
        assert private not in durable
    for model, operation in ((Record, update(Record).where(Record.invalidation_id == ident).values(content_hash="corrupt")),
        (ContextInvalidationNodeRecord, delete(ContextInvalidationNodeRecord).where(ContextInvalidationNodeRecord.invalidation_id == ident)),
        (ContextInvalidationEdgeRecord, delete(ContextInvalidationEdgeRecord).where(ContextInvalidationEdgeRecord.invalidation_id == ident))):
        with pytest.raises(DBAPIError), session_scope() as session:
            session.execute(operation)
    assert history(v, ident).status_code == 200
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    migration = importlib.import_module("apps.api.migrations.versions.0067_context_invalidations")
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="cannot downgrade"):
            migration.downgrade()
    repository = app.state.container.context_invalidations.repository
    def corrupt(*args):
        raise ValueError("private malformed invalidation fixture")
    with monkeypatch.context() as scoped:
        scoped.setattr(type(repository), "_verified_value", corrupt)
        bad = history(v, ident)
        assert bad.status_code == 502 and "private malformed" not in bad.text
    grant_member(v)
    assert history(v, ident, v["member_headers"]).status_code == 200
    access_repo = SourceAccessRepository()
    access = access_repo.load_snapshot(v["project_id"])
    access_repo.set_policy(v["project_id"], v["impact_binding"], SourceAccessRule("restricted"),
        expected_epoch=access.acl_epoch, changed_by=v["owner"]["id"], invocation_id="invalidation-revoke-" + uuid4().hex)
    denied = history(v, ident, v["member_headers"])
    assert denied.status_code == 403 and "dependencies" not in denied.text and "graph_hash" not in denied.text


def test_invalidation_does_not_transfer_to_another_rebuilt_image_revision(impact):
    from apps.api.tests.test_published_image_reads import publish
    from apps.api.tests.test_context_packs_api import archive as archive_context, read as read_context
    from apps.api.tests.test_published_context_packs import preview_response, request_for
    v = impact
    completed(submit(v))
    v["invoke"]("system_image.context.materialize")
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    images = v["client"].get(v["image_url"] + "/revisions", headers=v["headers"]).json()["items"]
    image = next(item for item in images if item["manifest_id"] == manifest.manifest_id)
    assert image["image_revision_id"] != v["context_head"]["image_revision_id"]
    v["target"] = {**v["target"], "image_revision_id": image["image_revision_id"],
        "image_artifact_hash": image["artifact_hash"], "expected_head_id": v["context_head"]["publication_id"]}
    head = publish(v)
    preview = preview_response(v, request_for(v, head)).json()
    rebuilt, _ = read_context(v, completed(archive_context(v, preview)[0]))
    assert not rebuilt["current_use"]["stale"] and "invalidation_id" not in rebuilt["current_use"]
    assert rebuilt["current_use"]["generation_authorized"] is False
    old = v["client"].get(f"{v['image_url']}/context-packs/{v['impact_request']['context_id']}", headers=v["headers"])
    assert old.status_code == 200 and old.json()["current_use"]["reason"] == "source_change_invalidated"


def test_new_dependency_after_preview_requires_a_new_explicit_confirmation(impact):
    v = impact
    request = selection(v)
    view = v["client"].get(v["mapping_url"], headers=v["headers"],
        params={"artifact_hash": v["generation_metadata"]["artifact_hash"]}).json()
    completed(mapping_submit(v, {**v["mapping_request"], "expected_previous_revision_id": view["head"]["revision"]["revision_id"],
        "reason": "Another independently reviewed immutable fixture mapping"}))
    failed = submit(v, request)
    assert failed.json()["status"] == "failed" and count(v, Record) == 0, failed.text
    assert failed.json()["result"]["followup_reason"] == "context_invalidation_changed"
    completed(submit(v))
    assert count(v, Record) == 1


def test_outbox_failure_rolls_back_nodes_edges_and_stale_state(impact, monkeypatch):
    v = impact
    request = selection(v)
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "system_image.context.invalidated":
            raise RuntimeError("private outbox fixture")
        return original(self, event, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(EventOutboxRepository, "append", fail)
        failed = submit(v, request)
    assert failed.json()["status"] == "failed" and "private outbox fixture" not in failed.text
    assert count(v, Record) == 0
    with session_scope() as session:
        for model in (ContextInvalidationNodeRecord, ContextInvalidationEdgeRecord):
            assert not session.scalar(select(model).join(Record, Record.invalidation_id == model.invalidation_id)
                .where(Record.project_id == v["project_id"]).limit(1))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert not app.state.container.context_packs.read(v["project_id"], request["context_id"])["current_use"]["stale"]
    completed(submit(v, request))


@pytest.mark.parametrize("age", [-60, 901])
def test_direct_commit_cannot_bypass_confirmation_ttl_or_future_time(impact, age):
    v = impact
    request = ContextInvalidateInput.model_validate(selection(v))
    ident = uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id=INVALIDATE_CONTEXT_TOOL, status="running", summary="Explicit invalid confirmation fixture",
            conversation_id=v["conversation"].json()["id"], input_payload={**request.model_dump(mode="json"),
                "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
                "confirmed_at": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()}))
    with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(ContextInvalidationIntegrityError):
        app.state.container.context_invalidations.invalidate(request, invocation_id=ident, recorded_at=datetime.now(timezone.utc).isoformat())
    assert count(v, Record) == 0


def test_unchanged_sources_and_non_reviewer_do_not_create_stale_facts(impact):
    v = impact
    no_change = {**v["impact_request"], "after_revision_id": v["impact_request"]["before_revision_id"]}
    value = read(v, after_revision_id=no_change["after_revision_id"]).json()
    failed = submit(v, {**no_change, "expected_impact_hash": snapshot_digest(value), "reason": "No changes fixture"})
    assert failed.json()["status"] == "failed" and count(v, Record) == 0
    grant_member(v)
    denied = submit(v, selection(v), headers=v["member_headers"])
    assert denied.status_code in (200, 403) and (denied.status_code == 403 or denied.json()["status"] != "completed")
    assert count(v, Record) == 0
