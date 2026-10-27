"""Canonical PG/MinIO ancestry and ledger; builder and Docker transport are specimens."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import inspect, select, text, update

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.domain.quality_loop.environment_observation_record import (
    ENVIRONMENT_RECORD_TOOL, ENVIRONMENT_RECORD_QUERY_TOOL, ENVIRONMENT_RECORD_EVENT, ENVIRONMENT_EVENT_FIELDS,
)
from apps.api.app.domain.quality_loop.environment_health_record import HEALTH_RECORD_TOOL, HEALTH_RECORD_QUERY_TOOL
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.environment_observation_models import EnvironmentObservationRecord as Record
from apps.api.app.infrastructure.persistence.environment_health_models import EnvironmentHealthRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from apps.api.tests.test_owned_target_environment import Commands, spec
from apps.api.tests.test_run_plan_builds_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    prepared_binding, submit_binding, read_binding,
)
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count
from apps.api.tests.test_source_access_api import policy as restrict_source


def test_canonical_native_inventory_record_confirmation_history_integrity_and_atomic_rollback(native_scripts, spec, monkeypatch):
    v = native_scripts
    owned = replace(spec, project_id=v["project_id"])
    environment = {"environment_id": owned.environment_id, "kind": "local", "base_url": "http://127.0.0.1:8080",
        "inventory_hash": owned.digest, "isolation": "Operator-owned internal namespace; configuration observation only"}
    v = prepared_binding(v, monkeypatch, environment=environment)
    bound = completed(submit_binding(v))
    binding_id = bound["result"]["object_refs"][0].split(":", 1)[1]
    binding = read_binding(v, binding_id).json()
    request = {"project_id": v["project_id"], "run_plan_id": v["original_plan"]["metadata"]["run_plan_id"],
        "run_plan_artifact_hash": v["original_plan"]["metadata"]["artifact_hash"], "build_binding_id": binding_id,
        "build_binding_artifact_hash": binding["metadata"]["artifact_hash"]}
    commands = Commands(owned)
    commands.body = binding["metadata"]["target_artifact_hash"][7:].encode() + b"  /app/target.jar\n"
    native = OwnedTargetEnvironmentInspector(owned, command=commands)
    class Environment:
        def policy_digest(self, project, ident, *, require_work):
            assert (project, ident) == (owned.project_id, owned.environment_id)
            require_work()
            return owned.digest
        def inspect(self, project, ident, digest, *, require_work):
            assert (project, ident) == (owned.project_id, owned.environment_id)
            return native.inspect(digest, require_work=require_work)
    monkeypatch.setattr(app.state.container.run_plan_environments, "environments", Environment())
    assert count(v, Record) == 0
    pending = invoke(v, ENVIRONMENT_RECORD_TOOL, request, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert commands.calls == [] and count(v, Record) == 0
    with session_scope() as session:
        original = session.get(ToolInvocationRecord, pending.json()["id"])
        payload = {**original.input_payload, "confirmed_by_user": True, "confirmed_actor_id": v["owner"]["id"],
            "confirmed_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()}
        session.execute(update(ToolInvocationRecord).where(ToolInvocationRecord.id == original.id).values(input_payload=payload, status="running"))
    # Direct repository reservation also rejects stale canonical confirmation before inspection.
    service = app.state.container.environment_observation_records
    from apps.api.app.application.quality_loop.run_plan_environments import RunPlanEnvironmentQuery
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ValueError):
            service.record(RunPlanEnvironmentQuery.model_validate(request), invocation_id=pending.json()["id"],
                recorded_at=datetime.now(timezone.utc).isoformat())
    assert commands.calls == [] and count(v, Record) == 0

    fault_hits = []
    original_append = EventOutboxRepository.append
    def fail_after_append(repository, event, **kwargs):
        result = original_append(repository, event, **kwargs)
        if event.event_type == ENVIRONMENT_RECORD_EVENT:
            session = kwargs["session"]
            assert session.scalar(select(Record).where(Record.record_id == event.entity_id)) is not None
            assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.action == ENVIRONMENT_RECORD_EVENT,
                AuditEventRecord.entity_id == event.entity_id)) is not None
            session.flush()
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == event.event_id)) is not None
            fault_hits.append(event.entity_id)
            raise RuntimeError("late original environment ledger fault")
        return result
    monkeypatch.setattr(EventOutboxRepository, "append", fail_after_append)
    failed_pending = invoke(v, ENVIRONMENT_RECORD_TOOL, request, key=uuid4().hex)
    failed = confirm(v, failed_pending.json())
    assert failed.status_code == 200 and failed.json()["status"] == "failed", failed.text
    assert len(fault_hits) == 1 and count(v, Record) == 0
    with session_scope() as session:
        assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.action == ENVIRONMENT_RECORD_EVENT,
            AuditEventRecord.entity_id == fault_hits[0])) is None
        assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == fault_hits[0],
            SSEEventOutboxRecord.event_type == ENVIRONMENT_RECORD_EVENT)) is None
    monkeypatch.setattr(EventOutboxRepository, "append", original_append)

    saved_pending = invoke(v, ENVIRONMENT_RECORD_TOOL, request, key=uuid4().hex)
    saved = completed(confirm(v, saved_pending.json()))
    receipt = saved["result"]["run_plan_environment_record"]
    metadata = receipt["metadata"]
    record_id = metadata["record_id"]
    assert metadata["durable_native_observation_verified"] is True
    assert metadata["environment_fully_verified"] is metadata["execution_authorized"] is metadata["business_coverage_verified"] is False
    assert metadata["automated_count"] == metadata["executed_on_target_count"] == metadata["passed_count"] == 0
    assert "container_id" not in str(saved) and "127.0.0.1" not in str(saved)
    assert count(v, Record) == 1
    calls = len(commands.calls)
    url = f"/v1/projects/{v['project_id']}/quality/run-plan-environments/{record_id}"
    view = v["client"].get(url, headers=v["headers"])
    assert view.status_code == 200 and view.headers["cache-control"] == "private, no-store", view.text
    assert view.json()["archive"]["observation"]["inventory"]["target"]["container_id"] == owned.container_id
    assert view.json()["metadata"] == metadata
    monkeypatch.setattr(app.state.container.run_plan_environments, "environments", None)
    queried = completed(invoke(v, ENVIRONMENT_RECORD_QUERY_TOOL, {"project_id": v["project_id"], "record_id": record_id}))
    assert queried["result"]["run_plan_environment_record"] == receipt and len(commands.calls) == calls
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.record(RunPlanEnvironmentQuery.model_validate(request), invocation_id=saved["id"],
            recorded_at=datetime.now(timezone.utc).isoformat()) == metadata
        replay = EventOutboxRepository().list_after(stream_kind="conversation",
            stream_id=v["conversation"].json()["id"], after_event_id=None, limit=500)
    events = [item for item in replay if item.event_type == ENVIRONMENT_RECORD_EVENT]
    assert len(events) == 1 and events[0].patch == {key: metadata[key] for key in ENVIRONMENT_EVENT_FIELDS}
    assert "container_id" not in str(events[0].model_dump())
    assert len(commands.calls) == calls

    with engine.connect() as connection:
        schema = inspect(connection)
        assert {item["name"] for item in schema.get_columns(Record.__tablename__)} == {column.name for column in Record.__table__.columns}
        actual_fks = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
            for item in schema.get_foreign_keys(Record.__tablename__)}
        expected_fks = {(tuple(element.parent.name for element in constraint.elements),
            next(iter(constraint.elements)).column.table.name, tuple(element.column.name for element in constraint.elements))
            for constraint in Record.__table__.foreign_key_constraints}
        assert actual_fks == expected_fks
    for operation in ("UPDATE quality_run_plan_environment_records SET status='recorded' WHERE record_id=:id",
            "DELETE FROM quality_run_plan_environment_records WHERE record_id=:id"):
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(Exception): connection.execute(text(operation), {"id": record_id})
            transaction.rollback()
    migration = importlib.import_module("apps.api.migrations.versions.0105_environment_observations")
    with engine.connect() as connection:
        transaction = connection.begin()
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="Cannot discard"): migration.downgrade()
        transaction.rollback()

    artifacts = service.artifacts
    original_read = artifacts.read
    monkeypatch.setattr(artifacts, "read", lambda *args, **kwargs: {"schema": "corrupt"})
    corrupt = v["client"].get(url, headers=v["headers"])
    assert corrupt.status_code == 502 and corrupt.headers["cache-control"] == "private, no-store", corrupt.text
    broken_receipt = v["client"].get(f"/v1/tool-invocations/{queried['id']}", headers=v["headers"])
    assert broken_receipt.status_code == 502, broken_receipt.text
    monkeypatch.setattr(artifacts, "read", original_read)
    assert v["client"].get(url, headers=v["headers"]).status_code == 200
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    granted = v["client"].put(membership, headers=v["headers"], json={"role": "qa_lead"})
    assert granted.status_code == 200, granted.text
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    restrict_source(v)
    def private_read_forbidden(*args, **kwargs):
        pytest.fail("revoked source access must be checked before private inventory bytes")
    monkeypatch.setattr(artifacts, "read", private_read_forbidden)
    denied = v["client"].get(url, headers=v["member_headers"])
    assert denied.status_code == 403 and denied.headers["cache-control"] == "private, no-store", denied.text
    assert len(commands.calls) == calls


def test_fixed_exweb_native_environment_record_uses_original_build_and_live_inventory(native_scripts, tmp_path, monkeypatch):
    from apps.api.tests.exweb_owned_deployment import OriginalExwebDeployment
    from apps.api.app.infrastructure.runner.configured_target_environments import ConfiguredOwnedTargetEnvironments
    from apps.api.app.infrastructure.runner.native_maven_build import bounded_command
    from apps.api.app.application.quality_loop.run_plan_environment_health import RunPlanEnvironmentHealthApplicationService
    from apps.api.app.application.quality_loop.run_plan_environments import RunPlanEnvironmentQuery
    from apps.api.app.application.quality_loop.http_fixture_journal_access import NativeSavedRunPlanHttpFixtureAccess
    from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
    from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveParent
    from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
    from apps.api.app.domain.quality_loop.http_fixture_target import native_fixture_environment
    from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentInvalid
    from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord
    from scripts.exweb_http_fixture_probe import recipe as session_recipe

    v = native_scripts
    assert v["real_build"] and len(v["exweb_files"]) == 126
    assert os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    deployment = OriginalExwebDeployment(tmp_path / "owned-original-environment")
    report = {"commit": v["exweb_commit"], "git_tree_hash": v["exweb_tree_hash"], "source_file_count": 126,
        "verified": False, "native_builder_is_actual": True, "native_environment_is_actual": True,
        "postgres_and_minio_are_actual": True, "model_transport_specimen": True, "scheduler_transport_specimen": True,
        "business_oracles_are_protocol_specimens": True, "external_model_called": False,
        "fixture_preflight_verified": False, "fixture_commands_executed": 0,
        "fixture_worker_fence_is_protocol_specimen": True,
        "execution_authorized": False, "business_coverage_verified": False, "full_quality_closure_verified": False}
    def start_original(built):
        with actor_scope(UserProfile.model_validate(v["owner"])):
            return deployment.start(built, app.state.container.native_builds)
    def fixture_recipe(declaration):
        # Fixed native session paths, but the upstream case/oracle remains an
        # explicit protocol specimen. Preflight never sends these HTTP actions.
        return {**session_recipe(declaration["case_id"]),
            **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
    try:
        v = prepared_binding(v, monkeypatch, environment=start_original, fixture_recipe=fixture_recipe)
        monkeypatch.setenv("NASUS_TARGET_ENVIRONMENT_REGISTRY", str(deployment.registry))
        bound = completed(submit_binding(v))
        binding_id = bound["result"]["object_refs"][0].split(":", 1)[1]
        binding = read_binding(v, binding_id).json()
        request = {"project_id": v["project_id"], "run_plan_id": v["original_plan"]["metadata"]["run_plan_id"],
            "run_plan_artifact_hash": v["original_plan"]["metadata"]["artifact_hash"], "build_binding_id": binding_id,
            "build_binding_artifact_hash": binding["metadata"]["artifact_hash"]}
        adapter = app.state.container.run_plan_environments.environments
        assert isinstance(adapter, ConfiguredOwnedTargetEnvironments)
        commands = []
        def actual_command(args, **kwargs):
            commands.append(tuple(args))
            return bounded_command(args, **kwargs)
        monkeypatch.setattr(adapter, "command", actual_command)
        pending = invoke(v, ENVIRONMENT_RECORD_TOOL, request, key=uuid4().hex)
        assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
        assert not commands and count(v, Record) == 0
        saved = completed(confirm(v, pending.json()))
        metadata = saved["result"]["run_plan_environment_record"]["metadata"]
        assert commands and any(command[:2] == ("docker", "exec") for command in commands)
        assert metadata["durable_native_observation_verified"] is True
        assert count(v, Record) == 1
        url = f"/v1/projects/{v['project_id']}/quality/run-plan-environments/{metadata['record_id']}"
        original = v["client"].get(url, headers=v["headers"])
        assert original.status_code == 200 and original.headers["cache-control"] == "private, no-store", original.text
        value = original.json()
        inventory = value["archive"]["observation"]["inventory"]
        assert inventory["target"]["container_id"] == deployment.spec.container_id
        assert inventory["network_id"] == deployment.spec.network_id
        assert inventory["artifact_hash"] == v["original_build"]["receipt"]["artifact"]["content_hash"]
        assert inventory["operator_policy_digest"] == deployment.spec.digest
        assert {item["container_id"] for item in inventory["dependency_instances"]} == {item.container_id for item in deployment.spec.dependencies}
        assert metadata["environment_fully_verified"] is metadata["execution_authorized"] is metadata["business_coverage_verified"] is False
        assert metadata["automated_count"] == metadata["executed_on_target_count"] == metadata["passed_count"] == 0
        # Actual original-instance health is a separate internal observation, not
        # a modification of the saved canonical inventory or execution authority.
        with actor_scope(UserProfile.model_validate(v["owner"])):
            health = RunPlanEnvironmentHealthApplicationService(app.state.container.run_plan_environments, adapter).inspect(
                RunPlanEnvironmentQuery.model_validate(request))
        assert health["dependency_health_verified"] and health["target_health_verified"]
        assert health["observation"].inventory_hash == metadata["inventory_hash"]
        assert health["execution_authorized"] is health["environment_fully_verified"] is False
        assert health["observation"].inventory["dependency_health_verified"] is False
        assert v["client"].get(url, headers=v["headers"]).json() == value
        report.update(native_health_observed=True, health_observation_hash=health["observation"].content_hash,
            health_checks=[{key: check[key] for key in ("role", "probe", "response_hash", "byte_count")}
                for check in health["observation"].checks], health_is_internal_not_independently_registered=True,
            dependency_health_verified=True, target_health_verified=True)
        # A new independently confirmed command archives new health evidence;
        # the original inventory and the internal observation are not promoted.
        assert app.state.container.run_plan_environment_health.health is adapter
        assert count(v, EnvironmentHealthRecord) == 0
        before_health_record = len(commands)
        health_pending = invoke(v, HEALTH_RECORD_TOOL, request, key=uuid4().hex)
        assert health_pending.status_code == 200 and health_pending.json()["status"] == "waiting_confirmation", health_pending.text
        assert len(commands) == before_health_record and count(v, EnvironmentHealthRecord) == 0
        health_saved = completed(confirm(v, health_pending.json()))
        health_metadata = health_saved["result"]["run_plan_health_record"]["metadata"]
        assert health_metadata["dependency_health_verified"] is health_metadata["target_health_verified"] is True
        assert health_metadata["inventory_hash"] == metadata["inventory_hash"]
        assert health_metadata["environment_fully_verified"] is health_metadata["execution_authorized"] is health_metadata["business_coverage_verified"] is False
        assert health_metadata["automated_count"] == health_metadata["executed_on_target_count"] == health_metadata["passed_count"] == 0
        assert count(v, EnvironmentHealthRecord) == 1 and count(v, Record) == 1
        health_url = f"/v1/projects/{v['project_id']}/quality/run-plan-health/{health_metadata['record_id']}"
        health_original = v["client"].get(health_url, headers=v["headers"])
        assert health_original.status_code == 200 and health_original.headers["cache-control"] == "private, no-store", health_original.text
        health_value = health_original.json()
        assert health_value["metadata"] == health_metadata
        assert health_value["archive"]["observation"]["inventory"] == inventory
        assert v["client"].get(url, headers=v["headers"]).json() == value
        assert "response_base64" not in str(health_saved) and "container_id" not in str(health_saved)
        report.update(health_is_internal_not_independently_registered=False,
            health_record_invocation_id=health_saved["id"], health_record_metadata=health_metadata)
        plan, manifest = v["original_plan"], v["fixture_manifest"]
        native_pin = native_fixture_environment(plan, manifest, value)
        parent = RunPlanObservationArchiveParent(project_id=v["project_id"], run_plan_id=request["run_plan_id"],
            run_plan_artifact_hash=request["run_plan_artifact_hash"], plan_digest=plan["metadata"]["plan_digest"])
        scope = HttpFixtureScope(v["project_id"], "native-preflight-" + uuid4().hex, manifest["case_id"],
            parent.plan_digest, acceptance_digest(manifest), metadata["environment_id"],
            metadata["target_artifact_hash"], metadata["inventory_hash"], 10000)
        access = NativeSavedRunPlanHttpFixtureAccess(app.state.container.run_plans, parent, manifest,
            app.state.container.environment_observation_records, native_pin,
            environment_health=app.state.container.run_plan_environment_health)
        work_checks = []
        def work():
            work_checks.append(True)
        with actor_scope(UserProfile.model_validate(v["owner"])):
            command = access.command(scope, "setup")
            before_preflight = len(commands)
            assert access.require_dispatch(scope, "setup", command, require_work=work) is None
            assert len(commands) > before_preflight and len(work_checks) > 3
            after_preflight = len(commands)
            def lost_worker():
                raise PermissionError("Explicit worker-loss control; no dispatch permitted")
            with pytest.raises(PermissionError, match="worker-loss control"):
                access.require_dispatch(scope, "setup", command, require_work=lost_worker)
            assert len(commands) == after_preflight
            redis = next(item for item in deployment.spec.dependencies if item.role == "redis")
            deployment.probe.command(["docker", "stop", "--time", "2", redis.container_id])
            with pytest.raises(NativeEnvironmentInvalid):
                access.require_dispatch(scope, "setup", command, require_work=work)
            deployment.probe.command(["docker", "start", redis.container_id])
            with pytest.raises(NativeEnvironmentInvalid):
                access.require_dispatch(scope, "setup", command, require_work=work)
            # An original instance epoch is never replaced by the restarted one.
            before_history = len(commands)
            assert access.require_scope(scope) == parent.model_dump(mode="json")
            assert len(commands) == before_history
        assert count(v, HttpFixtureDispatchRecord) == 0
        assert v["client"].get(url, headers=v["headers"]).json() == value
        assert v["client"].get(health_url, headers=v["headers"]).json() == health_value
        report.update(fixture_preflight_verified=True, fixture_original_inventory_hash=scope.inventory_hash,
            fixture_manifest_hash=scope.data_manifest_hash, fixture_dependency_stop_rejected=True,
            fixture_dependency_restart_rejected=True, fixture_worker_loss_rejected_before_docker=True,
            fixture_preflight_did_not_create_journal=True, fixture_historical_read_without_live_probe_verified=True)
        inspected = len(commands)
        report["cleanup"] = deployment.close()
        assert report["cleanup"]["verified"] and not deployment.registry.exists()
        replay = v["client"].get(url, headers=v["headers"])
        assert replay.status_code == 200 and replay.json() == value, replay.text
        query = completed(invoke(v, ENVIRONMENT_RECORD_QUERY_TOOL, {"project_id": v["project_id"], "record_id": metadata["record_id"]}))
        assert query["result"]["run_plan_environment_record"] == saved["result"]["run_plan_environment_record"]
        health_replay = v["client"].get(health_url, headers=v["headers"])
        assert health_replay.status_code == 200 and health_replay.json() == health_value, health_replay.text
        health_query = completed(invoke(v, HEALTH_RECORD_QUERY_TOOL,
            {"project_id": v["project_id"], "record_id": health_metadata["record_id"]}))
        assert health_query["result"]["run_plan_health_record"] == health_saved["result"]["run_plan_health_record"]
        assert "response_base64" not in str(health_query) and "container_id" not in str(health_query)
        assert len(commands) == inspected
        assert "container_id" not in str(query) and "127.0.0.1" not in str(query)
        assert read_binding(v, binding_id).json() == binding
        report.update(verified=True, native_build_invocation_id=v["original_build"]["invocation_id"],
            target_artifact_hash=inventory["artifact_hash"], original_binding_metadata=binding["metadata"],
            environment_metadata=metadata, historical_read_without_docker_verified=True,
            original_code_export_deleted=not v["code_root"].exists())
    finally:
        report["cleanup"] = deployment.close()
        destination = os.environ.get("EXWEB_NATIVE_ENVIRONMENT_RECORD_REPORT")
        if destination:
            with Path(destination).open("x") as stream:
                json.dump(report, stream, indent=2)
        assert report["cleanup"]["verified"]
