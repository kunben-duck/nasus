"""Canonical PG/MinIO native-target pins; model/build/Docker transports are specimens."""
from copy import deepcopy
from dataclasses import replace
import importlib
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import inspect, select, text, update

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.http_fixture_journal_access import NativeSavedRunPlanHttpFixtureAccess
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.application.quality_loop.run_plan_environment_health import RunPlanEnvironmentHealthApplicationService
from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveParent
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_TOOL
from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_TOOL, GRANT_QUERY_TOOL, GRANT_EVENT, NATIVE_GRANT_SCHEMA
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_TOOL
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentInvalid
from apps.api.app.domain.quality_loop.run_plan import RUN_PLAN_BINDING_SCHEMA
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.http_fixture_grant_models import HttpFixtureGrantRecord
from apps.api.app.infrastructure.persistence.http_fixture_native_grant_models import HttpFixtureNativeGrantRecord
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord
from apps.api.app.infrastructure.persistence.http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal
from apps.api.app.infrastructure.persistence.http_fixture_work_models import HttpFixtureDispatchOwnershipRecord
from apps.api.app.infrastructure.persistence.http_fixture_dispatch_consent_models import HttpFixtureDispatchConsentRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from apps.api.app.infrastructure.runner.owned_target_health import OwnedTargetHealthInspector
from apps.api.tests.test_owned_target_environment import Commands, spec
from apps.api.tests.test_owned_target_health import HealthCommands
from apps.api.tests.test_http_fixtures import manifest
from apps.api.tests.test_run_plan_builds_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    prepared_binding, submit_binding, read_binding,
)
from apps.api.tests.test_run_plans_api import select_binding_scripts
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count


def test_canonical_native_fixture_grant_preserves_original_instance_and_atomic_registration(native_scripts, spec, monkeypatch):
    v = native_scripts
    select_binding_scripts(v)
    owned = replace(spec, project_id=v["project_id"])
    environment = {"environment_id": owned.environment_id, "kind": "local", "base_url": "http://127.0.0.1:8080",
        "inventory_hash": owned.digest, "isolation": "Explicit operator registry and original inventory protocol specimen"}
    def recipe(declaration):
        value = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
        value["setup_steps"][-1]["value_json"] = '"EXPLICIT_INDEPENDENT_EXPECTED"'
        return value
    v = prepared_binding(v, monkeypatch, environment=environment, fixture_recipe=recipe,
        policy_revision=RUN_PLAN_BINDING_SCHEMA)
    declarations = v["original_plan"]["artifact"]["plan"]["selection"]["fixtures"]
    assert len(declarations) == len(v["fixture_manifests"]) == len(v["original_plan"]["artifact"]["plan"]["prepared"]["cases"])
    assert all(declaration["data_manifest_hash"] == acceptance_digest(value)
        for declaration, value in zip(declarations, v["fixture_manifests"]))
    bound = completed(submit_binding(v))
    binding_id = bound["result"]["object_refs"][0].split(":", 1)[1]
    binding = read_binding(v, binding_id).json()
    plan = v["original_plan"]
    request = {"project_id": v["project_id"], "run_plan_id": plan["metadata"]["run_plan_id"],
        "run_plan_artifact_hash": plan["metadata"]["artifact_hash"], "build_binding_id": binding_id,
        "build_binding_artifact_hash": binding["metadata"]["artifact_hash"]}
    commands = Commands(owned)
    commands.body = binding["metadata"]["target_artifact_hash"][7:].encode() + b"  /app/target.jar\n"
    inspector = OwnedTargetEnvironmentInspector(owned, command=commands)
    class Environment:
        def policy_digest(self, project, ident, *, require_work):
            assert (project, ident) == (owned.project_id, owned.environment_id)
            require_work()
            return owned.digest
        def inspect(self, project, ident, digest, *, require_work):
            assert (project, ident) == (owned.project_id, owned.environment_id)
            return inspector.inspect(digest, require_work=require_work)
    monkeypatch.setattr(app.state.container.run_plan_environments, "environments", Environment())
    environment_record = completed(confirm(v, invoke(v, ENVIRONMENT_RECORD_TOOL, request, key=uuid4().hex).json()))
    env_metadata = environment_record["result"]["run_plan_environment_record"]["metadata"]
    recipe_request = {key: request[key] for key in ("project_id", "run_plan_id", "run_plan_artifact_hash")}
    recipe_request["manifest"] = v["fixture_manifest"]
    registered = completed(confirm(v, invoke(v, RECIPE_TOOL, recipe_request, key=uuid4().hex).json()))
    recipe_metadata = registered["result"]["http_fixture_recipe"]["metadata"]
    consent = {"project_id": v["project_id"], "recipe_id": recipe_metadata["record_id"],
        "recipe_artifact_hash": recipe_metadata["artifact_hash"], "attempt_id": "native-" + uuid4().hex,
        "operation": "setup", "timeout_ms": 10000, "policy_revision": NATIVE_GRANT_SCHEMA,
        "environment_record_id": env_metadata["record_id"], "environment_record_artifact_hash": env_metadata["artifact_hash"]}
    calls = len(commands.calls)
    assert env_metadata["inventory_hash"] != env_metadata["operator_policy_digest"]
    original_append, faults = EventOutboxRepository.append, []
    def fail_after_binding(repository, event, **kwargs):
        result = original_append(repository, event, **kwargs)
        if event.event_type == GRANT_EVENT:
            session = kwargs["session"]
            session.flush()
            assert session.get(HttpFixtureGrantRecord, event.entity_id) is not None
            assert session.get(HttpFixtureNativeGrantRecord, event.entity_id) is not None
            faults.append(event.entity_id)
            raise RuntimeError("explicit late native fixture grant registration fault")
        return result
    monkeypatch.setattr(EventOutboxRepository, "append", fail_after_binding)
    failed = confirm(v, invoke(v, GRANT_TOOL, consent, key=uuid4().hex).json())
    assert failed.status_code == 200 and failed.json()["status"] == "failed", failed.text
    assert len(faults) == 1 and count(v, HttpFixtureGrantRecord) == count(v, HttpFixtureNativeGrantRecord) == 0
    with session_scope() as session:
        assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == faults[0])) is None
        assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == faults[0])) is None
    monkeypatch.setattr(EventOutboxRepository, "append", original_append)
    saved = completed(confirm(v, invoke(v, GRANT_TOOL, consent, key=uuid4().hex).json()))
    metadata = saved["result"]["http_fixture_grant"]["metadata"]
    assert metadata["scope"]["inventory_hash"] == env_metadata["inventory_hash"]
    assert metadata["native_environment"]["operator_policy_digest"] == owned.digest
    scope = HttpFixtureScope(**metadata["scope"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        service = app.state.container.http_fixture_grants
        assert service.require_operation(v["project_id"], metadata["record_id"], scope, "setup") == metadata
        parent = RunPlanObservationArchiveParent(project_id=v["project_id"], run_plan_id=request["run_plan_id"],
            run_plan_artifact_hash=request["run_plan_artifact_hash"], plan_digest=plan["metadata"]["plan_digest"])
        access = NativeSavedRunPlanHttpFixtureAccess(app.state.container.run_plans, parent, v["fixture_manifest"],
            app.state.container.environment_observation_records, metadata["native_environment"])
        command = access.command(scope, "setup")
        assert command.metadata["fixture_scope"]["inventory_hash"] == env_metadata["inventory_hash"]
        journal = PostgresHttpFixtureDispatchJournal(access, None, actor_id=v["owner"]["id"])
        with pytest.raises(HttpFixtureInvalid, match="live target health port"):
            journal.claim(scope, "setup", command, require_current=lambda: None)
        health_commands = HealthCommands(owned)
        health_commands.body = commands.body
        class Health(Environment):
            def inspect_health(self, project, ident, digest, *, require_work):
                assert (project, ident) == (owned.project_id, owned.environment_id)
                return OwnedTargetHealthInspector(owned, command=health_commands).inspect(digest, require_work=require_work)
        access.environment_health = RunPlanEnvironmentHealthApplicationService(app.state.container.run_plan_environments, Health())
        health_commands.responses["pg"] = b"0\n"
        with pytest.raises(NativeEnvironmentInvalid, match="epoch or dependency health"):
            journal.claim(scope, "setup", command, require_current=lambda: None)
        claim_id = journal._identity(scope, "setup")
        with session_scope() as session:
            assert all(session.get(model, claim_id) is None for model in
                (HttpFixtureDispatchRecord, HttpFixtureDispatchOwnershipRecord, HttpFixtureDispatchConsentRecord))
            assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == claim_id)) is None
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == claim_id)) is None
        health_commands.responses["pg"] = b"1\n"
        access.require_dispatch(scope, "setup", command, require_work=lambda: None)
        assert health_commands.health_calls == ["pg", "redis", "target"] * 2
        assert count(v, HttpFixtureDispatchRecord) == 0
    queried = completed(invoke(v, GRANT_QUERY_TOOL, {"project_id": v["project_id"], "record_id": metadata["record_id"]}))
    assert queried["result"]["http_fixture_grant"] == saved["result"]["http_fixture_grant"]
    cleanup = completed(confirm(v, invoke(v, GRANT_TOOL, {**consent, "operation": "cleanup"}, key=uuid4().hex).json()))
    assert cleanup["result"]["http_fixture_grant"]["metadata"]["scope_digest"] == metadata["scope_digest"]
    assert len(commands.calls) == calls and count(v, HttpFixtureDispatchRecord) == 0
    assert count(v, HttpFixtureGrantRecord) == count(v, HttpFixtureNativeGrantRecord) == 2
    assert metadata["execution_authorized"] is metadata["business_coverage_verified"] is False
    from apps.api.tests.fixture_parent_read_probe import measure_fixture_parent_reuse
    measure_fixture_parent_reuse(v,
        f"/v1/projects/{v['project_id']}/quality/http-fixture-grants/{metadata['record_id']}",
        saved["result"]["http_fixture_grant"], monkeypatch)
    original_environment_result = deepcopy(environment_record["result"])
    for mutation in ("missing", "int-flag", "inventory", "object"):
        corrupted = deepcopy(original_environment_result)
        if mutation == "missing": corrupted = None
        elif mutation == "int-flag": corrupted["run_plan_environment_record"]["historical_not_live"] = 1
        elif mutation == "inventory": corrupted["run_plan_environment_record"]["metadata"]["inventory_hash"] = acceptance_digest("other")
        else: corrupted["object_refs"] = ["run_plan_environment:other"]
        with session_scope() as session:
            # ORM JSON equality treats True and 1 alike; force the actual SQL mutation.
            session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == environment_record["id"])
                .values(result_payload=corrupted))
        with session_scope() as session:
            persisted = session.get(ToolInvocationRecord, environment_record["id"]).result_payload
            assert acceptance_digest(persisted) == acceptance_digest(corrupted)
            if mutation == "int-flag":
                assert type(persisted["run_plan_environment_record"]["historical_not_live"]) is int
        try:
            denied = v["client"].get(f"/v1/projects/{v['project_id']}/quality/http-fixture-grants/{metadata['record_id']}",
                headers=v["headers"])
            assert denied.status_code == 502, denied.text
            assert len(commands.calls) == calls and count(v, HttpFixtureDispatchRecord) == 0
        finally:
            with session_scope() as session:
                session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == environment_record["id"])
                    .values(result_payload=deepcopy(original_environment_result)))
            with session_scope() as session:
                restored = session.get(ToolInvocationRecord, environment_record["id"]).result_payload
                assert acceptance_digest(restored) == acceptance_digest(original_environment_result)
                assert restored["run_plan_environment_record"]["historical_not_live"] is True
    with engine.connect() as connection:
        schema = inspect(connection)
        actual = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + key for key in fk["referred_columns"]))
            for fk in schema.get_foreign_keys(HttpFixtureNativeGrantRecord.__tablename__)}
        expected = {(tuple(fk.column_keys), tuple(element.target_fullname for element in fk.elements))
            for fk in HttpFixtureNativeGrantRecord.__table__.foreign_key_constraints}
        assert actual == expected
    for sql in ("UPDATE quality_http_fixture_native_grants SET inventory_hash=inventory_hash WHERE grant_id=:id",
            "DELETE FROM quality_http_fixture_native_grants WHERE grant_id=:id"):
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(Exception): connection.execute(text(sql), {"id": metadata["record_id"]})
            transaction.rollback()
    migration = importlib.import_module("apps.api.migrations.versions.0113_fixture_native_grants")
    with engine.connect() as connection:
        transaction = connection.begin()
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="Cannot discard"): migration.downgrade()
        transaction.rollback()
