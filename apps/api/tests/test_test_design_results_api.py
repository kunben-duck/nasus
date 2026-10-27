from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.application.quality_loop.test_design_results import response_digest
from apps.api.app.domain.quality_loop.test_design_generation import TestDesignGenerationInvalid
from apps.api.app.domain.quality_loop.test_design_scope import TestDesignScopeChanged
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignResultRecord as Result, TestDesignCaseRecord as Case, TestDesignCoverageRecord as Coverage
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord, LLMCallRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_test_design_scope_api import design_scope, submit
from apps.api.tests.test_test_design_generation_api import generation_request
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import completed, count
from apps.api.tests.test_published_context_packs import advance
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_design_result_fixture import seed_generation_execution


@pytest.fixture
def generation_result(design_scope):
    v = design_scope
    completed(submit(v))
    selection, _ = generation_request(v)
    service = app.state.container.test_design_results
    with actor_scope(UserProfile.model_validate(v["owner"])):
        execution = seed_generation_execution(service, selection, v["owner"]["id"], conversation_id=v["conversation"].json()["id"])
    v.update(result_service=service, execution=execution)
    return v


def commit(v, **overrides):
    args = {k: v["execution"][k] for k in ("request", "invocation_id", "call_id", "content")}
    args.update(overrides)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        return v["result_service"].commit(**args)


def read_result(v, metadata, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-results/{metadata['generation_id']}",
        headers=headers or v["headers"])


def assert_empty(v):
    assert count(v, Result) == count(v, Case) == count(v, Coverage) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == v["execution"]["invocation_id"])).all()
        assert not session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"],
            SSEEventOutboxRecord.event_type == "quality.test_design.generated")).all()


def test_generated_cases_coverage_and_events_commit_as_immutable_drafts(generation_result):
    v = generation_result
    metadata = commit(v)
    response = read_result(v, metadata)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    value = response.json()
    assert metadata["case_count"] > 0 and metadata["gap_count"] == 0
    assert value["metadata"] == metadata and value["current_use"]["scope_current"]
    proposal = value["result"]["proposal"]
    assert proposal["coverage"]["planned_constraint_count"] == proposal["coverage"]["constraint_denominator"]
    assert proposal["coverage"]["passed_count"] == proposal["coverage"]["assertion_mapped_count"] == 0
    assert not value["current_use"]["execution_authorized"] and value["result"]["status"] == "draft"
    assert "synthetic-result-fixture-key" not in response.text and "artifact_ref" not in response.text
    assert count(v, Result) == count(v, Coverage) == 1 and count(v, Case) == len(proposal["cases"])
    with session_scope() as session:
        audits = session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == metadata["generation_id"])).all()
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == metadata["generation_id"])).all()
        assert len(audits) == len(events) == 1 and audits[0].actor == v["owner"]["id"]
        assert events[0].conversation_id == v["conversation"].json()["id"]
        assert "HTTP 400" not in json.dumps(events[0].event_payload)
    for model in (Result, Case, Coverage):
        for statement in (delete(model), update(model).values(project_id="changed")):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement.where(model.project_id == v["project_id"]))
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from apps.api.app.infrastructure.persistence.database import engine
    migration = importlib.import_module("apps.api.migrations.versions.0058_test_design_results")
    with engine.begin() as connection:
        original = migration.op
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="cannot downgrade"):
                migration.downgrade()
        finally:
            migration.op = original


def test_recovery_is_idempotent_after_withdrawal_and_never_rewrites(generation_result, monkeypatch):
    v = generation_result
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: commit(v), range(2)))
    assert values[0] == values[1] and count(v, Result) == 1
    def no_put(*args):
        raise AssertionError("recovery cannot rewrite a generation artifact")
    monkeypatch.setattr(v["result_service"].artifacts, "put", no_put)
    assert commit(v) == values[0]
    request = v["execution"]["request"]
    completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": request.scope_revision_id, "decision": "withdraw", "contract": None}))
    assert commit(v) == values[0]
    history = read_result(v, values[0])
    assert history.status_code == 200 and not history.json()["current_use"]["scope_current"]
    with pytest.raises(TestDesignResultIntegrityError):
        commit(v, content=v["execution"]["content"] + " ")
    with pytest.raises(TestDesignResultIntegrityError):
        commit(v, call_id="rebound")


def test_commit_requires_exact_canonical_successful_native_receipt(generation_result):
    v = generation_result
    with pytest.raises(TestDesignResultIntegrityError):
        commit(v, call_id="missing")
    fields = {"runtime_mode": "fallback", "outcome": "error", "usage_source": "estimated", "input_token_count": 0,
              "output_token_count": 0, "request_hash": "sha256:" + "0" * 64, "response_hash": "sha256:" + "0" * 64,
              "tool_invocation_id": "foreign", "model_name": "other", "purpose": "other", "model_calls": 2}
    for key, replacement in fields.items():
        with session_scope() as session:
            row = session.get(LLMCallRecord, v["execution"]["call_id"])
            previous = getattr(row, key)
            setattr(row, key, replacement)
        with pytest.raises(TestDesignResultIntegrityError):
            commit(v)
        with session_scope() as session:
            setattr(session.get(LLMCallRecord, v["execution"]["call_id"]), key, previous)
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, v["execution"]["invocation_id"])
        row.input_payload = {**row.input_payload, "confirmed_actor_id": "forged"}
    with pytest.raises(TestDesignResultIntegrityError):
        commit(v)
    assert_empty(v)


@pytest.mark.parametrize("failure", ["outbox", "head", "scope", "model", "actor"])
def test_no_partial_cases_or_coverage_on_commit_races(generation_result, monkeypatch, failure):
    v = generation_result
    if failure == "outbox":
        original = EventOutboxRepository.append
        def fail(self, event, **kwargs):
            if event.event_type == "quality.test_design.generated":
                raise RuntimeError("injected generation outbox failure")
            return original(self, event, **kwargs)
        monkeypatch.setattr(EventOutboxRepository, "append", fail)
    else:
        original = v["result_service"].artifacts.put
        def change(*args):
            result = original(*args)
            if failure == "head":
                advance(v, v["context_head"])
            elif failure == "scope":
                completed(submit(v, {**v["scope_request"], "expected_previous_revision_id": v["execution"]["request"].scope_revision_id,
                    "decision": "withdraw", "contract": None}))
            elif failure == "model":
                v["result_service"].profiles.repository.save_model_config(v["execution"]["config"].model_copy(update={"model_name": "changed"}), v["execution"]["encrypted"])
            else:
                with session_scope() as session:
                    session.get(UserIdentityRecord, v["owner"]["id"]).status = "disabled"
            return result
        monkeypatch.setattr(v["result_service"].artifacts, "put", change)
    with pytest.raises((RuntimeError, ValueError, PermissionError)):
        commit(v)
    assert_empty(v)


def test_bad_outputs_cannot_be_archived_and_historical_reads_recheck_acl(generation_result, monkeypatch):
    v = generation_result
    original = v["result_service"].artifacts.put
    def no_put(*args):
        raise AssertionError("invalid response should fail before artifact write")
    monkeypatch.setattr(v["result_service"].artifacts, "put", no_put)
    output = json.loads(v["execution"]["content"])
    output["cases"][0]["assertions"][0]["oracle"]["expected_result"] = "rewritten"
    for content in (json.dumps(output), "bad-json", '{"cases":[],"gaps":[]}'):
        with pytest.raises(TestDesignGenerationInvalid):
            commit(v, content=content)
    assert_empty(v)
    monkeypatch.setattr(v["result_service"].artifacts, "put", original)
    metadata = commit(v)
    grant_member(v)
    assert read_result(v, metadata, v["member_headers"]).status_code == 200
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], snapshot.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="result-source-revocation")
    response = read_result(v, metadata, v["member_headers"])
    assert response.status_code == 403 and "HTTP 400" not in response.text
    url = f"/v1/projects/{v['project_id']}/quality/test-design-results/{metadata['generation_id']}"
    assert v["client"].get(url).status_code == 401
    assert v["client"].get(url.replace(v["project_id"], "foreign"), headers=v["headers"]).status_code in {403, 404}


def test_read_rederives_coverage_and_rejects_tampered_artifacts(generation_result, monkeypatch):
    v = generation_result
    metadata = commit(v)
    artifacts = v["result_service"].artifacts
    original = artifacts.read
    def corrupt(*args):
        payload = deepcopy(original(*args))
        payload["proposal"]["coverage"]["passed_count"] = 99
        return payload
    monkeypatch.setattr(artifacts, "read", corrupt)
    response = read_result(v, metadata)
    assert response.status_code == 502, response.text
    assert "HTTP 400" not in response.text


def test_explicit_generation_gaps_survive_archive_without_fake_planned_coverage(generation_result):
    v = generation_result
    output = {"input_digest": v["execution"]["request"].input_digest, "cases": [], "gaps": [{
        "gap_id": "fixture-unresolved", "row_ids": [row["row_id"] for row in v["execution"]["prepared"]["obligations"]],
        "description": "Synthetic response reports missing fixtures; no cases fabricated"}]}
    content = json.dumps(output)
    with session_scope() as session:
        session.get(LLMCallRecord, v["execution"]["call_id"]).response_hash = response_digest(content)
    metadata = commit(v, content=content)
    assert metadata["case_count"] == 0 and metadata["gap_count"] == 1
    response = read_result(v, metadata)
    assert response.status_code == 200, response.text
    proposal = response.json()["result"]["proposal"]
    assert proposal["gaps"] == output["gaps"]
    assert proposal["coverage"]["planned_constraint_count"] == proposal["coverage"]["planned_obligation_count"] == 0
    assert proposal["coverage"]["gap_obligation_count"] == proposal["coverage"]["obligation_denominator"]
    assert count(v, Case) == 0 and count(v, Result) == count(v, Coverage) == 1
