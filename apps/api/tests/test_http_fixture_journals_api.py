"""Real PG/MinIO saved parent and durability; Runner responses are specimens."""
from dataclasses import replace
import hashlib
import importlib
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.http_fixture_journal_access import SavedRunPlanHttpFixtureAccess
from apps.api.app.application.quality_loop.http_fixtures import (
    HttpFixtureScope, HttpFixtureDispatchAlreadyClaimed, HttpFixtureLifecycleApplicationService, HttpFixtureOutcomeUnknown,
)
from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveParent
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord as Dispatch, HttpFixtureResultRecord as Result
from apps.api.app.infrastructure.persistence.http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.app.infrastructure.storage.http_fixture_artifacts import HttpFixtureExecutionArtifacts
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.tests.test_http_fixtures import Runner, manifest
from apps.api.tests.test_http_bindings import specimen
from apps.api.tests.test_run_plans_api import (
    native_scripts, select_binding_scripts, reviewed_plan_inputs, preview, submit, read,
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping,
)
from apps.api.tests.test_semantic_evaluations_api import completed
from apps.api.tests.http_fixture_work_pg_checks import verify_private_pg_fixture_work


def test_pg_fixture_restart_unknown_outcome_original_failure_and_atomic_events(native_scripts, monkeypatch):
    v = native_scripts
    select_binding_scripts(v)
    _draft, _review, _reviewer, selection = reviewed_plan_inputs(v)
    value = selection.model_dump(mode="json")
    value["environment"]["base_url"] = "http://127.0.0.1:8080"
    declaration = value["fixtures"][0]
    recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
    recipe["setup_steps"][-1]["value_json"] = '"EXPLICIT_NEGATIVE_CONTROL"'
    declaration["data_manifest_hash"] = acceptance_digest(recipe)
    value["policy_revision"] = "nasus.run-plan.v2"
    selection = type(selection).model_validate(value)
    response = preview(v, selection)
    assert response.status_code == 200, response.text
    command = completed(submit(v, response.json()["request"]))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    view = read(v, ident).json()
    parent = RunPlanObservationArchiveParent(project_id=v["project_id"], run_plan_id=ident,
        run_plan_artifact_hash=view["metadata"]["artifact_hash"], plan_digest=view["artifact"]["plan"]["plan_digest"])
    scope = HttpFixtureScope(v["project_id"], "private-fixture-" + uuid4().hex, recipe["case_id"], parent.plan_digest,
        acceptance_digest(recipe), value["environment"]["environment_id"], value["target_build"]["artifact_hash"],
        value["environment"]["inventory_hash"], 10000)
    artifacts = HttpFixtureExecutionArtifacts(ObjectStorage())
    access = SavedRunPlanHttpFixtureAccess(app.state.container.run_plans, parent, recipe)
    actor = UserProfile.model_validate(v["owner"])
    runner = Runner()
    runner.payload = lambda command: (specimen(command, states=["passed", "passed", "passed", "failed"], status="failed")
        if command.metadata["fixture_phase"] == "setup" else specimen(command))

    def journal():
        return PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=actor.id)

    def lifecycle(current_journal):
        return HttpFixtureLifecycleApplicationService(runner, current_journal, OwnedHttpFixtureObservationVerifier())

    def events(ident):
        with session_scope() as session:
            audit = session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == ident)).all()
            outbox = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == ident)).all()
            return [(row.action, row.tool_invocation_id) for row in audit], [row.event_type for row in outbox]

    with actor_scope(actor):
        original = lifecycle(journal()).prepare(scope, recipe, require_work=lambda: None)
        assert len(runner.commands) == 1 and original.execution.result.status == "failed"
        assert original.command.steps[-1]["value_json"] == '"EXPLICIT_NEGATIVE_CONTROL"'
        restarted = journal()
        replay = lifecycle(restarted).prepare(scope, recipe, require_work=lambda: None)
        assert replay == original and len(runner.commands) == 1
        cleanup = lifecycle(journal()).cleanup(scope, recipe, require_work=lambda: None)
        assert cleanup.cleanup_verified and len(runner.commands) == 2
        assert not cleanup.execution_authorized and not cleanup.business_coverage_verified and not cleanup.baseline_restored
        assert lifecycle(journal()).cleanup(scope, recipe, require_work=lambda: None) == cleanup and len(runner.commands) == 2
        with pytest.raises(HttpFixtureDispatchAlreadyClaimed):
            journal().claim(scope, "setup", original.command, require_current=lambda: None)
        with pytest.raises(HttpFixtureInvalid): journal().inspect(replace(scope, timeout_ms=11000), "setup")
        ident = restarted._identity(scope, "setup")
        audit, outbox = events(ident)
        assert len(audit) == len(outbox) == 2 and all(invocation is None for _, invocation in audit)
        assert "quality.http_fixture.dispatch_reserved" in outbox and "quality.http_fixture.result_recorded" in outbox
        with session_scope() as session:
            record = session.get(Result, ident)
            assert record.payload["canonical_execution_committed"] is False
            ref, digest = record.artifact_ref, record.artifact_hash
            assert session.get(Dispatch, ident).request_hash == "sha256:" + hashlib.sha256(original.execution.request_body).hexdigest()
        before = events(ident)
        restarted.complete(scope, "setup", original.command, original.execution, require_current=lambda: None)
        assert events(ident) == before
        artifacts.storage.put_bytes(artifacts._key(scope.project_id, digest), b"corrupted-original", content_type="application/json")
        with pytest.raises(HttpFixtureInvalid): journal().inspect(scope, "setup")
        assert len(runner.commands) == 2
        artifacts.put(parent.model_dump(mode="json"), scope, "setup", original.command, original.execution)
        assert journal().inspect(scope, "setup").execution.result_body == original.execution.result_body

        unknown_scope = replace(scope, attempt_id="unknown-" + uuid4().hex)
        runner.failure = TimeoutError("protocol target may have processed the write")
        with pytest.raises(HttpFixtureOutcomeUnknown): lifecycle(journal()).prepare(unknown_scope, recipe, require_work=lambda: None)
        calls = len(runner.commands)
        with pytest.raises(HttpFixtureOutcomeUnknown): lifecycle(journal()).prepare(unknown_scope, recipe, require_work=lambda: None)
        assert len(runner.commands) == calls and journal().inspect(unknown_scope, "setup").execution is None
        assert len(events(journal()._identity(unknown_scope, "setup"))[0]) == 1
        runner.failure = None

        rollback_scope = replace(scope, attempt_id="rollback-" + uuid4().hex)
        rollback_command = access.command(rollback_scope, "setup")
        original_event = PostgresHttpFixtureDispatchJournal._event
        def failed_event(*_args, **_kwargs):
            raise RuntimeError("explicit Outbox transaction failure")
        with monkeypatch.context() as patch:
            patch.setattr(PostgresHttpFixtureDispatchJournal, "_event", failed_event)
            with pytest.raises(RuntimeError): journal().claim(rollback_scope, "setup", rollback_command, require_current=lambda: None)
        assert journal().inspect(rollback_scope, "setup") is None
        assert events(journal()._identity(rollback_scope, "setup")) == ([], [])
        assert PostgresHttpFixtureDispatchJournal._event == original_event

        result_scope = replace(scope, attempt_id="result-rollback-" + uuid4().hex)
        result_command = access.command(result_scope, "setup")
        journal().claim(result_scope, "setup", result_command, require_current=lambda: None)
        execution = runner.execute_owned_http(result_command, environment_id=result_scope.environment_id,
            inventory_hash=result_scope.inventory_hash, artifact_hash=result_scope.artifact_hash, require_work=lambda: None)
        with monkeypatch.context() as patch:
            patch.setattr(PostgresHttpFixtureDispatchJournal, "_event", failed_event)
            with pytest.raises(RuntimeError): journal().complete(result_scope, "setup", result_command, execution, require_current=lambda: None)
        assert journal().inspect(result_scope, "setup").execution is None
        calls = len(runner.commands)
        with pytest.raises(HttpFixtureOutcomeUnknown): lifecycle(journal()).prepare(result_scope, recipe, require_work=lambda: None)
        assert len(runner.commands) == calls
        assert len(events(journal()._identity(result_scope, "setup"))[0]) == 1

        fenced_scope = replace(scope, attempt_id="fenced-" + uuid4().hex)
        fenced_command = access.command(fenced_scope, "setup")
        checks = []
        def revoked_before_commit():
            checks.append(True)
            if len(checks) == 3:
                raise PermissionError("explicit worker/source fence revoked after the flush")
        with pytest.raises(PermissionError): journal().claim(fenced_scope, "setup", fenced_command, require_current=revoked_before_commit)
        assert journal().inspect(fenced_scope, "setup") is None
        assert events(journal()._identity(fenced_scope, "setup")) == ([], [])

        verify_private_pg_fixture_work(parent, recipe, scope, view, artifacts, actor, monkeypatch)

    for table in ("quality_http_fixture_dispatches", "quality_http_fixture_results"):
        with pytest.raises(DBAPIError, match="immutable|append-only|mutation"):
            with session_scope() as session: session.execute(text(f"DELETE FROM {table} WHERE project_id = :project"), {"project": scope.project_id})
    migration = importlib.import_module("apps.api.migrations.versions.0108_http_fixture_journals")
    with session_scope() as session:
        with Operations.context(MigrationContext.configure(session.connection())):
            with pytest.raises(RuntimeError, match="Cannot discard populated original fixture history"):
                migration.downgrade()
        assert session.get(Dispatch, ident) is not None and session.get(Result, ident) is not None
