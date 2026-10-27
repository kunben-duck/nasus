"""Real PG/MinIO comparison; model/oracle content remains explicit protocol specimens."""
from collections import Counter
import hashlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.run_plan_environments import RunPlanEnvironmentQuery
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_automation_input_api import verify_fixed_exweb_archive
from apps.api.tests.test_run_plan_builds_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    prepared_binding, submit_binding, read_binding,
)
from apps.api.tests.test_semantic_evaluations_api import completed
from apps.api.tests.test_source_access_api import policy as restrict_source


def verify_parent(value, monkeypatch):
    assert engine.dialect.name == "postgresql"
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
    command = completed(submit_binding(value))
    binding_id = command["result"]["object_refs"][0].split(":", 1)[1]
    response = read_binding(value, binding_id)
    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    container = app.state.container
    service, bindings, plans = container.run_plan_environments, container.run_plan_builds, container.run_plans
    assert service.bindings is bindings and bindings.plans is plans
    query = RunPlanEnvironmentQuery(project_id=value["project_id"], run_plan_id=metadata["run_plan_id"],
        run_plan_artifact_hash=metadata["run_plan_artifact_hash"], build_binding_id=metadata["binding_id"],
        build_binding_artifact_hash=metadata["artifact_hash"])
    storage = container.context_packs.artifacts.storage
    original_plan, original_bytes = plans.read, storage.get_bytes

    def measure(port):
        counts, objects = Counter(), {}
        def begin(connection):
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        def statement(_connection, _cursor, sql, _parameters, _context, _many):
            counts["sql"] += 1
            assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        def plan(*args):
            counts["plans"] += 1
            return original_plan(*args)
        def body(ref, **options):
            data = original_bytes(ref, **options)
            digest = hashlib.sha256(data).hexdigest()
            assert ref not in objects or objects[ref] == digest
            objects[ref] = digest
            counts["objects"] += 1
            return data
        event.listen(engine, "begin", begin)
        event.listen(engine, "before_cursor_execute", statement)
        try:
            with monkeypatch.context() as scoped:
                scoped.setattr(service, "bindings", port)
                scoped.setattr(plans, "read", plan)
                scoped.setattr(storage, "get_bytes", body)
                with actor_scope(UserProfile.model_validate(value["owner"])):
                    result = service.original_inputs(query, current=True)
        finally:
            event.remove(engine, "before_cursor_execute", statement)
            event.remove(engine, "begin", begin)
        return result, counts, objects

    before, control, original_objects = measure(SimpleNamespace(read=bindings.read))
    after, production, production_objects = measure(bindings)
    assert before == after and original_objects == production_objects and original_objects
    assert control["plans"] == 2 and production["plans"] == 1
    assert production["sql"] < control["sql"] and production["objects"] < control["objects"]
    assert after[0]["current_use"]["execution_authorized"] is after[1]["current_use"]["execution_authorized"] is False
    assert after[1]["artifact"]["binding"]["automated_count"] == 0
    assert after[1]["artifact"]["binding"]["executed_on_target_count"] == 0
    assert after[1]["artifact"]["binding"]["passed_count"] == 0
    print(json.dumps({"scope": "environment_original_parent_read_only", "control": dict(control),
        "production": dict(production), "unique_original_objects": len(original_objects),
        "full_response_hash": acceptance_digest(after), "target_execution_verified": False,
        "full_quality_closure_verified": False}, sort_keys=True))

    membership = value["client"].put(f"/v1/projects/{value['project_id']}/members/{value['member']['id']}",
        headers=value["headers"], json={"role": "qa_lead"})
    assert membership.status_code == 200, membership.text
    actor = UserProfile.model_validate(value["member"])
    with actor_scope(actor):
        assert service.original_inputs(query, current=False) == after
    original_pair = bindings.read_with_plan
    def revoked(*args):
        pair = original_pair(*args)
        restrict_source(value)
        return pair
    monkeypatch.setattr(bindings, "read_with_plan", revoked)
    with actor_scope(actor), pytest.raises(StaleSourceAccessScope):
        service.original_inputs(query, current=False)
    monkeypatch.setattr(bindings, "read_with_plan", original_pair)
    with actor_scope(actor), pytest.raises(SourceAccessDenied):
        service.original_inputs(query, current=False)
    assert len(value["script_calls"]) == 1


def test_environment_parent_read_preserves_full_originals_and_final_real_source_acl(native_scripts, monkeypatch):
    value = prepared_binding(native_scripts, monkeypatch)
    verify_parent(value, monkeypatch)


def test_fixed_exweb_environment_parent_read_preserves_all_original_archives(native_scripts, monkeypatch):
    value = prepared_binding(native_scripts, monkeypatch)
    assert value["real_build"] and value["exweb_commit"] == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert len(value["exweb_files"]) == 126
    with actor_scope(UserProfile.model_validate(value["owner"])):
        pin, members = verify_fixed_exweb_archive({**value, "exweb_exported": value["code_roots"][0]}, value["script_sent"][0])
    assert pin["file_count"] == 126 and members == 725
    verify_parent(value, monkeypatch)
