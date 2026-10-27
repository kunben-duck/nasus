"""Actual PG/MinIO parent reuse; source and model content remain protocol specimens."""
from collections import Counter
import hashlib

import pytest
from sqlalchemy import event

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_automation_scripts_api import (
    native_scripts, base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping,
)
from apps.api.tests.test_run_plans_api import reviewed_plan_inputs
from apps.api.tests.test_source_access_api import policy as restrict_source


def test_run_plan_reuses_complete_compiled_parent_in_read_only_pg_and_rechecks_real_source_acl(native_scripts, monkeypatch):
    value = native_scripts
    draft, review, reviewer, selection = reviewed_plan_inputs(value)
    service = app.state.container.run_plans
    if engine.dialect.name != "postgresql":
        pytest.skip("an isolated PostgreSQL database is required")
    storage = app.state.container.context_packs.artifacts.storage
    original_parents, original_script, original_bytes = service._parents, service.scripts.read, storage.get_bytes

    def measure(parents):
        counts, objects = Counter(), {}
        def begin(connection):
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        def statement(_connection, _cursor, sql, _parameters, _context, _many):
            counts["sql"] += 1
            assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        def script(*args):
            counts["scripts"] += 1
            return original_script(*args)
        def read(ref, **options):
            body = original_bytes(ref, **options)
            digest = hashlib.sha256(body).hexdigest()
            assert ref not in objects or objects[ref] == digest
            objects[ref] = digest
            counts["objects"] += 1
            return body
        event.listen(engine, "begin", begin)
        event.listen(engine, "before_cursor_execute", statement)
        try:
            with monkeypatch.context() as scoped:
                scoped.setattr(service, "_parents", parents)
                scoped.setattr(service.scripts, "read", script)
                scoped.setattr(storage, "get_bytes", read)
                with actor_scope(UserProfile.model_validate(reviewer["owner"])):
                    response = service._compile(selection, current=True)
        finally:
            event.remove(engine, "before_cursor_execute", statement)
            event.remove(engine, "begin", begin)
        return response, counts, objects

    # Same full pre-optimization algorithm, through the observed authorized ports.
    def observed_control(scope):
        return service.scripts.read(scope.project_id, scope.script_revision_id), service.reviews.read(scope.project_id, scope.review_revision_id)

    before, control_counts, original_objects = measure(observed_control)
    after, production_counts, production_objects = measure(original_parents)
    assert before == after and not after[0]["execution_authorized"]
    assert after[0]["passed_count"] == after[0]["executed_on_target_count"] == 0
    assert original_objects == production_objects and original_objects
    assert control_counts["scripts"] == 2 and production_counts["scripts"] == 1
    assert production_counts["objects"] < control_counts["objects"]
    assert production_counts["sql"] < control_counts["sql"]
    assert draft["metadata"]["script_revision_id"] == review["revision"]["script_revision_id"]

    parent_read = service.reviews.read_with_script
    def revoke_after_verified_parent(*args):
        result = parent_read(*args)
        restrict_source(value)
        return result
    monkeypatch.setattr(service.reviews, "read_with_script", revoke_after_verified_parent)
    with actor_scope(UserProfile.model_validate(reviewer["owner"])), pytest.raises(SourceAccessDenied):
        service.preview(selection)
    assert len(value["script_calls"]) == 1
