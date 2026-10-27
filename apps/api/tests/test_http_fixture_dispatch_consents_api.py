"""Real fixed exweb/PG/MinIO ancestry; private phase transport is a specimen.

After complete canonical parent validation, the transaction fault branches use
an explicit frozen plan reader. They do not prove live target execution, current
review transitions, Temporal orchestration or verified business coverage.
"""
from copy import deepcopy
import importlib
from types import SimpleNamespace
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.http_fixture_journal_access import SavedRunPlanHttpFixtureAccess
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService, HttpFixtureOutcomeUnknown, HttpFixtureScope
from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveParent
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_TOOL
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_TOOL
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.http_fixture_dispatch_consent_models import HttpFixtureDispatchConsentRecord as Consent
from apps.api.app.infrastructure.persistence.http_fixture_dispatch_consent_repository import PostgresHttpFixtureConsentFence, verify_dispatch_consent
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord as Dispatch, HttpFixtureResultRecord as Result
from apps.api.app.infrastructure.persistence.http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal
from apps.api.app.infrastructure.persistence.http_fixture_work_models import HttpFixtureDispatchOwnershipRecord as Ownership
from apps.api.app.infrastructure.persistence.http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.app.infrastructure.storage.http_fixture_artifacts import HttpFixtureExecutionArtifacts
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.tests.test_http_fixtures import manifest, Runner
from apps.api.tests.test_http_bindings import specimen
from apps.api.tests.test_run_plans_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    select_binding_scripts, reviewed_plan_inputs, preview, submit, read,
)
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm


def test_fixed_exweb_fixture_dispatch_consent_atomicity_and_unknown_result(native_scripts, monkeypatch):
    from apps.api.tests.test_automation_input_api import verify_fixed_exweb_archive
    v = native_scripts
    assert v["exweb_commit"] == "fe5827f6b76f77ef34918d8b452ee823142332dc" and v["exweb_file_count"] == 126
    select_binding_scripts(v)
    _, _, _, selection = reviewed_plan_inputs(v)
    inputs = selection.model_dump(mode="json")
    declaration = inputs["fixtures"][0]
    recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
    recipe["setup_steps"][-1]["value_json"] = '"EXPLICIT_INDEPENDENT_EXPECTED"'
    declaration["data_manifest_hash"] = acceptance_digest(recipe)
    inputs["environment"]["base_url"] = "http://127.0.0.1:8080"
    inputs["policy_revision"] = "nasus.run-plan.v2"
    selection = type(selection).model_validate(inputs)
    saved = completed(submit(v, preview(v, selection).json()["request"]))
    ident = saved["result"]["object_refs"][0].split(":", 1)[1]
    view = read(v, ident).json()
    registered = completed(confirm(v, invoke(v, RECIPE_TOOL, {"project_id": v["project_id"],
        "run_plan_id": ident, "run_plan_artifact_hash": view["metadata"]["artifact_hash"], "manifest": recipe}, key=uuid4().hex).json()))
    metadata = registered["result"]["http_fixture_recipe"]["metadata"]
    request = {"project_id": v["project_id"], "recipe_id": metadata["record_id"], "recipe_artifact_hash": metadata["artifact_hash"],
        "attempt_id": "transaction-" + uuid4().hex, "operation": "setup", "timeout_ms": 30000}

    def grant(value):
        result = completed(confirm(v, invoke(v, GRANT_TOOL, value, key=uuid4().hex).json()))
        return result["result"]["http_fixture_grant"]["metadata"]

    service = app.state.container.http_fixture_grants
    actor = UserProfile.model_validate(v["owner"])
    plan = view["artifact"]["plan"]
    scope = HttpFixtureScope(project_id=v["project_id"], attempt_id=request["attempt_id"],
        case_id=recipe["case_id"], parent_digest=plan["plan_digest"], data_manifest_hash=acceptance_digest(recipe),
        environment_id=plan["selection"]["environment"]["environment_id"],
        artifact_hash=plan["selection"]["target_build"]["artifact_hash"],
        inventory_hash=plan["selection"]["environment"]["inventory_hash"], timeout_ms=request["timeout_ms"])
    parent = RunPlanObservationArchiveParent(project_id=v["project_id"], run_plan_id=ident,
        run_plan_artifact_hash=view["metadata"]["artifact_hash"], plan_digest=view["artifact"]["plan"]["plan_digest"])
    with actor_scope(actor):
        full_access = SavedRunPlanHttpFixtureAccess(app.state.container.run_plans, parent, recipe)
        assert full_access.require_scope(scope) == parent.model_dump(mode="json")
        source_pin, members = verify_fixed_exweb_archive(v, v["script_sent"][0])
        assert source_pin["file_count"] == 126 and members > 0
    setup_value = grant(request)
    assert HttpFixtureScope(**setup_value["scope"]) == scope
    with actor_scope(actor):
        setup_pin = service.dispatch_consent(v["project_id"], setup_value["record_id"], scope, "setup")
        access_scope = service.authorization.scope(v["project_id"])
        # Fault isolation only: SQL parents, original consent/actor, private S3,
        # worker clock and immutable transaction writes below remain real.
        frozen = SimpleNamespace(read=lambda *args: deepcopy(view))
        access = SavedRunPlanHttpFixtureAccess(frozen, parent, recipe)
        artifacts = HttpFixtureExecutionArtifacts(ObjectStorage())
        assert artifacts.storage.config.bucket.startswith("nasus-test-")
        journal = PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=actor.id)
        workers = PostgresHttpFixtureWorkRepository(journal)
        current = lambda: service.authorization.require_current(access_scope)
        lease = workers.acquire(scope, "setup", "consent-worker", require_current=current)
        fence = PostgresHttpFixtureConsentFence(service.repository, setup_pin)
        owned = PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=actor.id,
            work_fence=workers.fence(lease), consent_fence=fence)
        command = access.command(scope, "setup")
        with pytest.raises(HttpFixtureInvalid):
            PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=actor.id, consent_fence=fence)
        claim_id = owned._identity(scope, "setup")
        original_claim = fence.claim
        clock = service.repository._clock

        def expired_after_staging(session, dispatch):
            original_claim(session, dispatch)
            session.flush()
            assert session.get(Dispatch, claim_id) is not None and session.get(Ownership, claim_id) is not None
            assert session.get(Consent, claim_id) is not None
            monkeypatch.setattr(service.repository, "_clock", lambda: func.clock_timestamp() + text("INTERVAL '901 seconds'"))

        with monkeypatch.context() as patch:
            patch.setattr(fence, "claim", expired_after_staging)
            with pytest.raises(PermissionError): owned.claim(scope, "setup", command, require_current=current)
        monkeypatch.setattr(service.repository, "_clock", clock)
        with session_scope() as session:
            assert all(session.get(model, claim_id) is None for model in (Dispatch, Ownership, Consent))
            assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == claim_id)) is None
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == claim_id)) is None
        runner = Runner()
        runner.payload = lambda cmd: (specimen(cmd, states=["passed", "passed", "passed", "failed"], status="failed")
            if cmd.metadata["fixture_phase"] == "setup" else specimen(cmd))
        lifecycle = HttpFixtureLifecycleApplicationService(runner, owned, OwnedHttpFixtureObservationVerifier())
        result = lifecycle.prepare(scope, recipe, require_work=current)
        assert result.execution.result.status == "failed" and result.command.steps[-1]["value_json"] == '"EXPLICIT_INDEPENDENT_EXPECTED"'
        assert lifecycle.prepare(scope, recipe, require_work=current) == result and len(runner.commands) == 1
        with session_scope() as session:
            row = session.get(Dispatch, claim_id)
            consent = verify_dispatch_consent(session, row.payload)
            assert row.payload["schema"] == "nasus.http-fixture-dispatch.v3" and consent["grant_id"] == setup_pin.grant_id
            assert session.get(Ownership, claim_id) is not None and session.get(Result, claim_id).status == "failed"
            assert consent["execution_authorized"] is consent["canonical_execution_committed"] is consent["business_coverage_verified"] is False
        without_consent = PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=actor.id, work_fence=workers.fence(lease))
        with pytest.raises(HttpFixtureInvalid): without_consent.complete(scope, "setup", command, result.execution, require_current=current)
        # Cleanup is independently confirmed when needed, not while setup awaits unrelated work.
        cleanup_value = grant({**request, "operation": "cleanup"})
        cleanup_pin = service.dispatch_consent(v["project_id"], cleanup_value["record_id"], scope, "cleanup")
        cleanup_lease = workers.acquire(scope, "cleanup", "cleanup-worker", require_current=current)
        cleanup_journal = PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=actor.id,
            work_fence=workers.fence(cleanup_lease), consent_fence=PostgresHttpFixtureConsentFence(service.repository, cleanup_pin))
        cleanup = HttpFixtureLifecycleApplicationService(runner, cleanup_journal, OwnedHttpFixtureObservationVerifier()).cleanup(scope, recipe, require_work=current)
        assert cleanup.cleanup_verified and not cleanup.business_coverage_verified and not cleanup.baseline_restored
        assert len(runner.commands) == 2 and runner.commands[-1].steps[0]["path"] == "/sessions/session_original/close"
        with monkeypatch.context() as patch:
            patch.setattr(service.repository, "_clock", lambda: func.clock_timestamp() + text("INTERVAL '901 seconds'"))
            assert journal.inspect(scope, "setup").execution.result_body == result.execution.result_body
            with session_scope() as session:
                with pytest.raises(PermissionError): fence.require(session, scope, "setup", command)

    # A separate confirmed attempt tests the uncertain effect path without
    # deleting an original result or rewriting a saved plan/grant/claim.
    unknown_value = grant({**request, "attempt_id": "unknown-" + uuid4().hex})
    unknown_scope = HttpFixtureScope(**unknown_value["scope"])
    with actor_scope(actor):
        unknown_pin = service.dispatch_consent(v["project_id"], unknown_value["record_id"], unknown_scope, "setup")
        unknown_lease = workers.acquire(unknown_scope, "setup", "unknown-worker", require_current=current)
        unknown_journal = PostgresHttpFixtureDispatchJournal(access, artifacts, actor_id=actor.id,
            work_fence=workers.fence(unknown_lease), consent_fence=PostgresHttpFixtureConsentFence(service.repository, unknown_pin))
        runner.failure = TimeoutError("explicit uncertain target effect")
        lifecycle = HttpFixtureLifecycleApplicationService(runner, unknown_journal, OwnedHttpFixtureObservationVerifier())
        before = len(runner.commands)
        with pytest.raises(HttpFixtureOutcomeUnknown): lifecycle.prepare(unknown_scope, recipe, require_work=current)
        with pytest.raises(HttpFixtureOutcomeUnknown): lifecycle.prepare(unknown_scope, recipe, require_work=current)
        assert len(runner.commands) == before + 1
        unknown_id = unknown_journal._identity(unknown_scope, "setup")
        with session_scope() as session:
            assert session.get(Consent, unknown_id) is not None and session.get(Ownership, unknown_id) is not None
            assert session.get(Result, unknown_id) is None

    for statement in ("DELETE FROM quality_http_fixture_dispatch_consents WHERE claim_id=:id",
            "UPDATE quality_http_fixture_dispatch_consents SET grant_id=grant_id WHERE claim_id=:id"):
        with pytest.raises(DBAPIError, match="immutable|append-only|mutation"):
            with session_scope() as session: session.execute(text(statement), {"id": claim_id})
    migration = importlib.import_module("apps.api.migrations.versions.0112_http_fixture_dispatch_consents")
    with session_scope() as session:
        with Operations.context(MigrationContext.configure(session.connection())):
            with pytest.raises(RuntimeError, match="Cannot discard populated original fixture dispatch consent"):
                migration.downgrade()
        assert session.get(Consent, claim_id) is not None
