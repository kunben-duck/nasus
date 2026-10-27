"""Real PG aggregate transactions with explicit native HTTP/reply fixtures."""
import asyncio
from copy import deepcopy
import importlib
import json

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.generation_batch_executor import GenerationBatchExecutorApplicationService
from apps.api.app.application.quality_loop.generation_batch_results import GenerationBatchResultApplicationService
from apps.api.app.application.quality_loop.generation_work_lease import GenerationLeaseLost
from apps.api.app.application.quality_loop.test_design_results import BATCH_RESULT_SCHEMA, TestDesignResultIntegrityError
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.llm.test_design_model import HTTPTestDesignModel
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, LLMCallRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.generation_batch_result_repository import GenerationBatchResultRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignCaseRecord as Case, TestDesignCoverageRecord as Coverage, TestDesignResultBatchCallRecord as Provenance
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_generation_batch_ledger_api import (
    ledger, execution, design_scope, publication, documents, evidence_api, reserve, archive, count, Plan, Claim, BatchReply, Result,
)
from apps.api.tests.test_generation_batches import responses_for
from apps.api.tests.test_semantic_link_model import native_reply
from apps.api.tests.test_source_access_api import grant_member


@pytest.fixture
def aggregate(ledger):
    v = ledger
    results = GenerationBatchResultApplicationService(v["batch_receipts"], GenerationBatchResultRepository(),
        app.state.container.test_design_results.artifacts)
    sent = []
    outputs = dict(responses_for(v["batch_planned"].input, v["batch_planned"].plan))
    def handle(request):
        wire = json.loads(request.content)
        batch = json.loads(wire["messages"][-1]["content"])
        sent.append(batch["batch_digest"])
        return httpx.Response(200, json=native_reply("openai_compatible", outputs[batch["batch_digest"]]))
    v.update(batch_results=results, batch_native_sent=sent, batch_executor=GenerationBatchExecutorApplicationService(
        v["batch_receipts"], HTTPTestDesignModel(transport=httpx.MockTransport(handle)), results=results))
    return v


def commit(v):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        return v["batch_results"].commit(v["batch_request"], lease=v["batch_lease"])


def populate(v):
    with actor_scope(UserProfile.model_validate(v["owner"])):
        reserve(v)
        for sequence, (_, content) in enumerate(responses_for(v["batch_planned"].input, v["batch_planned"].plan)):
            v["batch_receipts"].claim(v["batch_request"], sequence, lease=v["batch_lease"])
            archive(v, sequence, content)


def read(v, metadata, *, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-results/{metadata['generation_id']}",
        headers=headers or v["headers"])


def assert_empty(v):
    assert count(v, Result) == count(v, Case) == count(v, Coverage) == count(v, Provenance) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == v["batch_invocation_id"],
            AuditEventRecord.action == "quality.test_design.generated")).all()
        assert not session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"],
            SSEEventOutboxRecord.event_type == "quality.test_design.generated")).all()


@pytest.mark.parametrize("documents", [3], indirect=True)
def test_native_three_batch_aggregate_outbox_rollback_replays_without_extra_egress(aggregate, monkeypatch):
    v = aggregate
    original = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "quality.test_design.generated":
            raise RuntimeError("injected aggregate outbox failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(RuntimeError, match="aggregate outbox failure"):
            asyncio.run(v["batch_executor"].execute(v["batch_request"], lease=v["batch_lease"]))
    assert_empty(v)
    assert len(v["batch_native_sent"]) == count(v, BatchReply) == 3
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        metadata = asyncio.run(v["batch_executor"].execute(v["batch_request"], lease=v["batch_lease"]))
    assert metadata["schema"] == BATCH_RESULT_SCHEMA and metadata["call_id"] is None and len(metadata["call_ids"]) == 3
    response = read(v, metadata)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["view_schema"] == "nasus.test-design-result-view.v3"
    assert value["view_hash"] == acceptance_digest({key: item for key, item in value.items() if key != "view_hash"})
    assert "artifact_ref" not in response.text and "native-test-design-fixture-key" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    coverage = value["result"]["proposal"]["coverage"]
    assert coverage["obligation_denominator"] == len(v["batch_planned"].input["obligations"])
    assert coverage["passed_count"] == coverage["assertion_mapped_count"] == 0 and not value["current_use"]["execution_authorized"]
    assert count(v, Result) == count(v, Coverage) == 1 and count(v, Provenance) == 3 and count(v, Case) == metadata["case_count"]
    def no_put(*args):
        raise AssertionError("aggregate replay must not rewrite an archive")
    monkeypatch.setattr(v["batch_results"].artifacts, "put", no_put)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert asyncio.run(v["batch_executor"].execute(v["batch_request"], lease=v["batch_lease"])) == metadata
    assert len(v["batch_native_sent"]) == 3 and not v["native_calls"]
    with session_scope() as session:
        row = session.get(Result, metadata["generation_id"])
        assert row.provenance_kind == "batch" and row.call_id is None
        calls = session.scalars(select(LLMCallRecord).where(LLMCallRecord.tool_invocation_id == v["batch_invocation_id"])).all()
        assert len(calls) == 3 and all(call.model_calls == 1 for call in calls)
    for statement in (delete(Provenance), update(Provenance).values(call_id="foreign")):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(Provenance.project_id == v["project_id"]))
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    migration = importlib.import_module("apps.api.migrations.versions.0064_generation_batch_results")
    with engine.begin() as connection:
        original_op = migration.op
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="cannot downgrade"):
                migration.downgrade()
        finally:
            migration.op = original_op
    assert v["jobs"].repository.command(v["batch_invocation_id"])[1] == "running"


def test_incomplete_native_call_set_cannot_commit_an_aggregate(aggregate):
    v = aggregate
    with actor_scope(UserProfile.model_validate(v["owner"])):
        reserve(v)
        v["batch_receipts"].claim(v["batch_request"], 0, lease=v["batch_lease"])
    with pytest.raises(TestDesignResultIntegrityError, match="every successful"):
        commit(v)
    assert_empty(v)
    assert count(v, Claim) == 1 and count(v, BatchReply) == 0 and not v["batch_native_sent"]


@pytest.mark.parametrize("failure", ["lease", "acl"])
def test_aggregate_commit_rechecks_lease_and_source_scope_after_private_write(aggregate, monkeypatch, failure):
    v = aggregate
    populate(v)
    original = v["batch_results"].artifacts.put
    def change(*args):
        result = original(*args)
        if failure == "lease":
            v["stop_batch_heartbeat"]()
            v["jobs"].repository.release_lease(v["batch_lease"])
        else:
            repository = SourceAccessRepository()
            snapshot = repository.load_snapshot(v["project_id"])
            repository.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
                expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="batch-result-acl-change")
        return result
    monkeypatch.setattr(v["batch_results"].artifacts, "put", change)
    with pytest.raises(GenerationLeaseLost if failure == "lease" else (ValueError, PermissionError)):
        commit(v)
    assert_empty(v)
    assert count(v, BatchReply) == 1 and not v["batch_native_sent"]


def test_historical_aggregate_checks_every_native_archive_audit_and_current_reader_acl(aggregate, monkeypatch):
    v = aggregate
    populate(v)
    metadata = commit(v)
    service = app.state.container.test_design_results
    monkeypatch.setattr(service.profiles, "resolve", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("historical draft read must not require current model egress permission")))
    assert read(v, metadata).status_code == 200
    original = service.batch_replies.read
    def corrupt(*args):
        value = deepcopy(original(*args))
        value["content"] += " "
        return value
    monkeypatch.setattr(service.batch_replies, "read", corrupt)
    assert read(v, metadata).status_code == 502
    monkeypatch.setattr(service.batch_replies, "read", original)
    grant_member(v)
    assert read(v, metadata, headers=v["member_headers"]).status_code == 200
    repository = SourceAccessRepository()
    snapshot = repository.load_snapshot(v["project_id"])
    repository.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="aggregate-historical-revocation")
    denied = read(v, metadata, headers=v["member_headers"])
    assert denied.status_code == 403 and "Explicit synthetic test input" not in denied.text


def test_versioned_aggregate_enters_independent_canonical_mapping_without_egress_or_draft_changes(aggregate):
    from apps.api.tests.test_test_design_mapping_api import reviews, submit, inspect, completed
    v = aggregate
    populate(v)
    metadata = commit(v)
    original = read(v, metadata).json()
    v.update(generation_metadata=metadata,
        mapping_url=f"/v1/projects/{v['project_id']}/quality/test-design-results/{metadata['generation_id']}/mapping-review",
        mapping_request=dict(project_id=v["project_id"], generation_id=metadata["generation_id"],
            generation_artifact_hash=metadata["artifact_hash"], expected_previous_revision_id=None, decision="review",
            mappings=reviews(original["result"]["proposal"]), reason="Independent v3 protocol review, never target pass"))
    grant_member(v)
    url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(url, headers=v["headers"], json={"role": "qa_lead"}).status_code == 200
    conversation = v["client"].post("/v1/conversations", headers=v["member_headers"],
        json={"space_type": "project", "space_id": v["project_id"]})
    assert conversation.status_code == 200
    previous = v["conversation"]
    v["conversation"] = conversation
    try:
        listing = v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-review-drafts", headers=v["member_headers"])
        assert listing.status_code == 200 and listing.json()["items"][0]["metadata"] == metadata
        completed(submit(v, headers=v["member_headers"]))
    finally:
        v["conversation"] = previous
    response = inspect(v, v["member_headers"])
    assert response.status_code == 200, response.text
    head = response.json()["head"]
    assert head["revision"]["authority_actor"] == v["member"]["id"] and head["current_use"]["mapping_complete"]
    coverage = head["assessment"]["coverage"]
    assert coverage["assertion_mapped_count"] == original["result"]["proposal"]["coverage"]["obligation_denominator"]
    assert coverage["automated_count"] == coverage["executed_on_target_count"] == coverage["passed_count"] == 0
    assert head["current_use"]["execution_authorized"] is False and read(v, metadata).json() == original
    assert count(v, Provenance) == len(metadata["call_ids"]) and not v["native_calls"] and not v["batch_native_sent"]
