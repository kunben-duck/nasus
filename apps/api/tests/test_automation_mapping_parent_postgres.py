"""Actual isolated PG/MinIO full-input comparison; content remains protocol specimens."""
from collections import Counter
import hashlib
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.quality_loop.automation_inputs import AutomationInputSelection
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_test_design_mapping_read_postgres import original_mapping, staging, mapping, generation_result, design_scope, publication, documents, evidence_api
from apps.api.tests.test_source_access_api import policy as restrict_source


def measure_input_read(value, selection, mode, mapping_port, monkeypatch):
    service = app.state.container.automation_inputs
    storage = app.state.container.context_packs.artifacts.storage
    result_read, generation_read, bytes_read = service.results.read, getattr(service.generation, mode), storage.get_bytes
    counts, objects = Counter(), {}
    def begin(connection):
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    def statement(_connection, _cursor, sql, _parameters, _context, _many):
        counts["sql"] += 1
        assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
    def result(*args):
        counts["results"] += 1
        return result_read(*args)
    def generation(*args):
        counts["generation"] += 1
        return generation_read(*args)
    def read(ref, **options):
        body = bytes_read(ref, **options)
        digest = hashlib.sha256(body).hexdigest()
        assert ref not in objects or objects[ref] == digest
        objects[ref] = digest
        counts["objects"] += 1
        return body
    event.listen(engine, "begin", begin)
    event.listen(engine, "before_cursor_execute", statement)
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(service, "mappings", mapping_port)
            scoped.setattr(service.results, "read", result)
            scoped.setattr(service.generation, mode, generation)
            scoped.setattr(storage, "get_bytes", read)
            with actor_scope(UserProfile.model_validate(value["owner"])):
                response = getattr(service, mode)(selection)
    finally:
        event.remove(engine, "before_cursor_execute", statement)
        event.remove(engine, "begin", begin)
    return response, counts, objects


@pytest.mark.parametrize("original_mapping", ["single", "partitioned"], indirect=True)
@pytest.mark.parametrize("mode", ["prepare", "replay"])
def test_mapping_parent_preserves_full_input_under_read_only_pg_and_keeps_fresh_generation(original_mapping, monkeypatch, mode):
    value = original_mapping
    if engine.dialect.name != "postgresql":
        pytest.skip("an isolated PostgreSQL database is required")
    service = app.state.container.automation_inputs
    mappings = service.mappings
    assert mappings.results is service.results
    head = value["original_head"]
    selection = AutomationInputSelection(project_id=value["project_id"], mapping_revision_id=head["revision"]["revision_id"],
        mapping_artifact_hash=head["revision"]["artifact_hash"], case_ids=tuple(head["assessment"]["accepted_case_ids"]))
    legacy = SimpleNamespace(read=mappings.read, resolve=mappings.resolve)
    before, control, before_objects = measure_input_read(value, selection, mode, legacy, monkeypatch)
    after, production, after_objects = measure_input_read(value, selection, mode, mappings, monkeypatch)
    assert before == after and before_objects == after_objects and before_objects
    assert production["results"] == (2 if mode == "prepare" else 1)
    assert control["results"] == production["results"] * 2
    assert production["generation"] == control["generation"] == (2 if mode == "prepare" else 1)
    assert production["sql"] < control["sql"] and production["objects"] < control["objects"]
    assert not after["generation_authorized"] and not after["execution_authorized"]
    assert after["automated_count"] == after["executed_on_target_count"] == after["passed_count"] == 0


@pytest.mark.parametrize("original_mapping", ["single", "partitioned"], indirect=True)
def test_actual_source_revocation_after_verified_mapping_parent_discards_full_preview(original_mapping, monkeypatch):
    value = original_mapping
    head = value["original_head"]
    service = app.state.container.automation_inputs
    selection = AutomationInputSelection(project_id=value["project_id"], mapping_revision_id=head["revision"]["revision_id"],
        mapping_artifact_hash=head["revision"]["artifact_hash"], case_ids=tuple(head["assessment"]["accepted_case_ids"]))
    membership = value["client"].put(f"/v1/projects/{value['project_id']}/members/{value['member']['id']}",
        headers=value["headers"], json={"role": "qa_lead"})
    assert membership.status_code == 200, membership.text
    actor = UserProfile.model_validate(value["member"])
    with actor_scope(actor):
        assert service.prepare(selection)["passed_count"] == 0
    parent_read = service.mappings.read_with_result
    def revoked(*args):
        result = parent_read(*args)
        restrict_source(value)
        return result
    monkeypatch.setattr(service.mappings, "read_with_result", revoked)
    with actor_scope(actor), pytest.raises(SourceAccessDenied):
        service.prepare(selection)
