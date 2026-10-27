"""Actual PG/MinIO original-parent comparison; target/model transports are specimens."""
from collections import Counter
from contextlib import nullcontext
from dataclasses import asdict
import hashlib
import json

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.http_fixture_dispatch_consent import HttpFixtureDispatchConsent
from apps.api.app.application.quality_loop.http_fixture_execution import HttpFixtureExecutionInputs
from apps.api.app.application.quality_loop.http_fixture_grants import HttpFixtureGrantApplicationService, HttpFixtureGrantRequest
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.application.quality_loop.http_fixture_journal_access import NativeSavedRunPlanHttpFixtureAccess
from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveParent
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_grant import NATIVE_GRANT_SCHEMA
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal
from apps.api.app.infrastructure.storage.http_fixture_artifacts import HttpFixtureExecutionArtifacts
from apps.api.tests.test_automation_input_api import verify_fixed_exweb_archive
from apps.api.tests.test_http_fixture_execution_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping,
    native_scripts, spec, composed_fixture_execution,
)


class _ExpandedOriginalGrantService(HttpFixtureGrantApplicationService):
    """Previous application algorithm; every discarded parent is fully read again."""
    def require_operation(self, project_id, record_id, scope, operation):
        with self.recipes.verified_read_session():
            access = self._access(project_id)
            value = self.read(project_id, record_id)["metadata"]
            request = HttpFixtureGrantRequest.model_validate(self.repository.read(project_id, record_id)["request"])
            if (not isinstance(scope, HttpFixtureScope) or type(operation) is not str
                    or operation != request.operation or self._inputs(request, current=True) != scope
                    or value["actor_id"] != access.actor_id or value["source_scope_digest"] != access.fingerprint):
                raise SourceAccessDenied("fixture grant is not this actor's exact current operation and scope")
            self.repository.require_live(project_id, record_id, actor_id=access.actor_id, scope=scope,
                operation=operation, source_scope_digest=access.fingerprint)
            self.authorization.require_current(access)
            return value

    def execution_inputs(self, selection, *, live):
        with self.recipes.verified_read_session():
            access = self._access(selection.project_id)
            metadata = self.read(selection.project_id, selection.grant_id)["metadata"]
            if (metadata["schema"] != NATIVE_GRANT_SCHEMA or metadata["grant_digest"] != selection.grant_digest
                    or metadata["operation"] != selection.operation):
                raise RunPlanIntegrityError("fixture worker needs its exact original native operation permission")
            payload = self.repository.read(selection.project_id, selection.grant_id)
            request = HttpFixtureGrantRequest.model_validate(payload["request"])
            scope, native = self._resolved_inputs(request, current=live)
            consent = HttpFixtureDispatchConsent(grant_id=selection.grant_id, grant_digest=metadata["grant_digest"],
                actor_id=metadata["actor_id"], source_scope_digest=metadata["source_scope_digest"],
                scope=scope, operation=selection.operation)
            if live and consent != self.dispatch_consent(selection.project_id, selection.grant_id, scope, selection.operation):
                raise RunPlanIntegrityError("fixture permission changed before worker input resolution")
            recipe = self.recipes.read(selection.project_id, request.recipe_id)
            original = recipe["archive"]["request"]
            if recipe["metadata"]["artifact_hash"] != request.recipe_artifact_hash:
                raise RunPlanIntegrityError("fixture worker definition no longer matches its original grant")
            parent = RunPlanObservationArchiveParent(project_id=selection.project_id,
                run_plan_id=original["run_plan_id"], run_plan_artifact_hash=original["run_plan_artifact_hash"],
                plan_digest=scope.parent_digest)
            self.authorization.require_current(access)
            return HttpFixtureExecutionInputs(selection, scope, parent, original["manifest"], native, consent, access)


def test_fixed_exweb_grant_input_reads_preserve_complete_originals_and_independent_live_checks(
        composed_fixture_execution, monkeypatch):
    fixture = composed_fixture_execution
    value, service = fixture.v, fixture.executor.grants
    assert engine.dialect.name == "postgresql"
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
    assert value["real_build"] and value["exweb_commit"] == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert len(value["exweb_files"]) == 126
    with actor_scope(fixture.actor):
        pin, members = verify_fixed_exweb_archive({**value, "exweb_exported": value["code_roots"][0]}, value["script_sent"][0])
    assert pin["file_count"] == 126 and members == 725
    control = _ExpandedOriginalGrantService(service.recipes, service.repository, environment_records=service.environment_records)
    storage = service.recipes.artifacts.storage
    original_bytes = storage.get_bytes
    originals = ((service.recipes, "read", "recipes"), (service.recipes, "read_with_plan", "recipes"),
        (service.recipes.plans, "read", "plans"), (service.environment_records, "read", "environments"),
        (service.repository, "read", "grants"), (service.repository, "require_live", "live"))
    model_calls = len(value["script_calls"])

    def measure(reader, live):
        counts, objects = Counter(live=0), {}
        def begin(connection):
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        def statement(connection, _cursor, sql, _parameters, _context, _many):
            counts["sql"] += 1
            counts["sql_primary" if connection.engine is engine else "sql_other_pools"] += 1
            assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        def body(ref, **options):
            data = original_bytes(ref, **options)
            digest = hashlib.sha256(data).hexdigest()
            assert ref not in objects or objects[ref] == digest
            objects[ref] = digest
            counts["objects"] += 1
            return data
        event.listen(engine, "begin", begin)
        event.listen(Engine, "before_cursor_execute", statement)
        try:
            with monkeypatch.context() as scoped:
                scoped.setattr(storage, "get_bytes", body)
                for owner, name, key in originals:
                    original = getattr(owner, name)
                    def counted(*args, original=original, key=key, **kwargs):
                        counts[key] += 1
                        return original(*args, **kwargs)
                    scoped.setattr(owner, name, counted)
                with actor_scope(fixture.actor):
                    result = reader.execution_inputs(fixture.chosen, live=live)
        finally:
            event.remove(Engine, "before_cursor_execute", statement)
            event.remove(engine, "begin", begin)
        return result, counts, objects

    for live in (False, True):
        before, expanded, original_objects = measure(control, live)
        after, production, production_objects = measure(service, live)
        assert before == after and original_objects == production_objects and original_objects
        assert expanded["recipes"] == (5 if live else 3) and production["recipes"] == (2 if live else 1)
        assert expanded["environments"] == expanded["grants"] == (4 if live else 2)
        assert production["environments"] == production["grants"] == (2 if live else 1)
        assert expanded["live"] == production["live"] == int(live)
        assert production["objects"] < expanded["objects"] and production["sql"] < expanded["sql"]
        assert after.manifest == value["fixture_manifest"]
        assert after.native_environment["inventory_hash"] == fixture.environment_metadata["inventory_hash"]
        assert after.selection == fixture.chosen and not fixture.runner.commands
        assert len(value["script_calls"]) == model_calls
        scope = after.access_scope
        full_input = {"selection": after.selection.model_dump(mode="json"), "scope": asdict(after.scope),
            "parent": after.parent.model_dump(mode="json"), "manifest": after.manifest,
            "native_environment": after.native_environment, "consent": asdict(after.consent),
            "access_scope": {**asdict(scope), "binding_ids": sorted(scope.binding_ids), "source_ids": sorted(scope.source_ids)}}
        print(json.dumps({"scope": "complete_original_grant_input_read_only", "live": live,
            "control": dict(expanded), "production": dict(production), "unique_original_objects": len(original_objects),
            "full_input_hash": acceptance_digest(full_input), "target_executed": False,
            "business_gold": False, "capacity_or_p95_acceptance": False}, sort_keys=True))


class _ExpandedOriginalJournalAccess(NativeSavedRunPlanHttpFixtureAccess):
    """Control algorithm reads the complete plan again inside environment verification."""
    def _scope_inputs(self, scope):
        return self.plans.read(scope.project_id, self.parent.run_plan_id), None


def test_fixed_exweb_journal_scope_reuses_complete_verified_environment_parent(composed_fixture_execution, monkeypatch):
    fixture = composed_fixture_execution
    value, executor = fixture.v, fixture.executor
    assert engine.dialect.name == "postgresql" and value["real_build"]
    assert value["exweb_commit"] == "fe5827f6b76f77ef34918d8b452ee823142332dc" and len(value["exweb_files"]) == 126
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
    with actor_scope(fixture.actor):
        pin, members = verify_fixed_exweb_archive({**value, "exweb_exported": value["code_roots"][0]}, value["script_sent"][0])
        inputs = executor.grants.execution_inputs(fixture.chosen, live=False)
    assert pin["file_count"] == 126 and members == 725
    factory = executor.runtimes
    access = factory._access(inputs)
    control = _ExpandedOriginalJournalAccess(factory.plans, inputs.parent, inputs.manifest,
        factory.environment_records, inputs.native_environment, environment_health=factory.environment_health)
    storage = executor.grants.recipes.artifacts.storage
    original_bytes = storage.get_bytes
    model_calls = len(value["script_calls"])

    def measure(reader):
        counts, objects = Counter(), {}
        def begin(connection):
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        def statement(connection, _cursor, sql, _parameters, _context, _many):
            counts["sql"] += 1
            counts["sql_primary" if connection.engine is engine else "sql_other_pools"] += 1
            assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        def body(ref, **options):
            data = original_bytes(ref, **options)
            digest = hashlib.sha256(data).hexdigest()
            assert ref not in objects or objects[ref] == digest
            objects[ref] = digest
            counts["objects"] += 1
            return data
        event.listen(engine, "begin", begin)
        event.listen(Engine, "before_cursor_execute", statement)
        try:
            with monkeypatch.context() as scoped:
                scoped.setattr(storage, "get_bytes", body)
                for owner, name, key in ((factory.plans, "read", "plans"),
                        (factory.environment_records, "read", "environments"),
                        (factory.environment_records, "read_with_plan", "environments")):
                    original = getattr(owner, name)
                    def counted(*args, original=original, key=key, **kwargs):
                        counts[key] += 1
                        return original(*args, **kwargs)
                    scoped.setattr(owner, name, counted)
                with actor_scope(fixture.actor):
                    result = reader._read_scope(inputs.scope)
        finally:
            event.remove(Engine, "before_cursor_execute", statement)
            event.remove(engine, "begin", begin)
        return result, counts, objects

    before, expanded, original_objects = measure(control)
    after, production, production_objects = measure(access)
    assert before == after and original_objects == production_objects and original_objects
    assert expanded["plans"] == 2 and production["plans"] == 1
    assert expanded["environments"] == production["environments"] == 1
    assert production["objects"] < expanded["objects"] and production["sql"] < expanded["sql"]
    assert not fixture.runner.commands and len(value["script_calls"]) == model_calls
    print(json.dumps({"scope": "complete_original_fixture_journal_scope_read_only", "control": dict(expanded),
        "production": dict(production), "unique_original_objects": len(original_objects),
        "full_input_hash": acceptance_digest(after), "target_executed": False,
        "business_gold": False, "capacity_or_p95_acceptance": False}, sort_keys=True))


def test_fixed_exweb_journal_operation_reuses_immutable_proof_without_skipping_original_reads(
        composed_fixture_execution, monkeypatch):
    fixture = composed_fixture_execution
    value, executor = fixture.v, fixture.executor
    assert engine.dialect.name == "postgresql" and value["real_build"]
    assert value["exweb_commit"] == "fe5827f6b76f77ef34918d8b452ee823142332dc" and len(value["exweb_files"]) == 126
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
    with actor_scope(fixture.actor):
        pin, members = verify_fixed_exweb_archive({**value, "exweb_exported": value["code_roots"][0]}, value["script_sent"][0])
        inputs = executor.grants.execution_inputs(fixture.chosen, live=False)
    assert pin["file_count"] == 126 and members == 725
    storage, factory = executor.grants.recipes.artifacts.storage, executor.runtimes
    original_bytes, model_calls = storage.get_bytes, len(value["script_calls"])

    def measure(reuse):
        counts, objects, full_inputs = Counter(), {}, []
        access = factory._access(inputs)
        journal = PostgresHttpFixtureDispatchJournal(access, HttpFixtureExecutionArtifacts(storage), actor_id=fixture.actor.id)
        read_scope = access._read_scope

        def original_scope(scope):
            original = read_scope(scope)
            counts["original_scopes"] += 1
            full_inputs.append(acceptance_digest(original))
            return original

        def begin(connection):
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        def statement(connection, _cursor, sql, _parameters, _context, _many):
            counts["sql"] += 1
            counts["sql_primary" if connection.engine is engine else "sql_other_pools"] += 1
            assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
            assert "FOR UPDATE" not in sql.upper()
        def body(ref, **options):
            data = original_bytes(ref, **options)
            digest = hashlib.sha256(data).hexdigest()
            assert ref not in objects or objects[ref] == digest
            objects[ref] = digest
            counts["objects"] += 1
            return data

        event.listen(engine, "begin", begin)
        # Verified snapshots use their own bounded engine, not the live pool.
        event.listen(Engine, "before_cursor_execute", statement)
        try:
            with monkeypatch.context() as scoped:
                scoped.setattr(access, "_read_scope", original_scope)
                scoped.setattr(storage, "get_bytes", body)
                if not reuse:
                    scoped.setattr(journal, "_read_session", nullcontext)
                for owner, name, key in ((factory.plans, "read", "plans"),
                        (factory.environment_records, "read_with_plan", "environments")):
                    original = getattr(owner, name)
                    def counted(*args, original=original, key=key, **kwargs):
                        counts[key] += 1
                        return original(*args, **kwargs)
                    scoped.setattr(owner, name, counted)
                with actor_scope(fixture.actor):
                    result = journal.inspect(inputs.scope, "setup", read_only=True)
        finally:
            event.remove(Engine, "before_cursor_execute", statement)
            event.remove(engine, "begin", begin)
        return result, counts, objects, full_inputs

    before, expanded, original_objects, original_inputs = measure(False)
    after, production, production_objects, production_inputs = measure(True)
    assert before is after is None and original_objects == production_objects and original_objects
    assert original_inputs == production_inputs and len(set(original_inputs)) == 1
    assert expanded["original_scopes"] == production["original_scopes"] == 3
    assert expanded["plans"] == production["plans"] == 3
    assert expanded["environments"] == production["environments"] == 3
    assert expanded["sql_other_pools"] > 0 and production["sql_other_pools"] > 0
    assert production["objects"] < expanded["objects"] and production["sql"] < expanded["sql"]
    assert not fixture.runner.commands and len(value["script_calls"]) == model_calls
    print(json.dumps({"scope": "complete_original_fixture_journal_operation_read_only", "control": dict(expanded),
        "production": dict(production), "unique_original_objects": len(original_objects),
        "full_input_hash": original_inputs[0], "target_executed": False,
        "business_gold": False, "capacity_or_p95_acceptance": False}, sort_keys=True))
