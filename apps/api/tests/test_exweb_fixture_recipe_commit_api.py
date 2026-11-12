"""Original exweb plan and private MinIO, with an injected late archive fault."""
import os
from traceback import extract_tb
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_EVENT, RECIPE_TOOL, recipe_identity
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.http_fixture_recipe_models import HttpFixtureRecipeRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_http_fixtures import manifest
from apps.api.tests.test_run_plans_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    select_binding_scripts, reviewed_plan_inputs, preview, submit, read,
)
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm


@pytest.mark.skipif(not os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT"), reason="explicit fixed exweb Git export required")
def test_fixed_exweb_recipe_verifies_archive_once_and_rolls_back_late_failure(native_scripts, monkeypatch):
    v = native_scripts
    assert v["exweb_file_count"] == 126 and os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    select_binding_scripts(v)
    _, _, _, selection = reviewed_plan_inputs(v)
    inputs = selection.model_dump(mode="json")
    declaration = inputs["fixtures"][0]
    recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
    declaration["data_manifest_hash"] = acceptance_digest(recipe)
    inputs["policy_revision"] = "nasus.run-plan.v2"
    saved = completed(submit(v, preview(v, type(selection).model_validate(inputs)).json()["request"]))
    plan_id = saved["result"]["object_refs"][0].split(":", 1)[1]
    view = read(v, plan_id).json()
    request = {"project_id": v["project_id"], "run_plan_id": plan_id,
        "run_plan_artifact_hash": view["metadata"]["artifact_hash"], "manifest": recipe}
    service = app.state.container.http_fixture_recipes
    assert service.artifacts.storage.config.bucket.startswith("nasus-test-")
    record, parent, archive, append = service.record, service.plans.read, service.artifacts.read, EventOutboxRepository.append
    trace, errors = [], []
    active = fault = False

    def scoped_record(*args, **kwargs):
        nonlocal active
        active = True
        try:
            return record(*args, **kwargs)
        except Exception as error:
            location = extract_tb(error.__traceback__)[-1]
            errors.append((type(error).__name__, location.name, location.lineno))
            raise
        finally:
            active = False

    def plan_read(*args):
        if active:
            trace.append("plan")
        return parent(*args)

    def archive_read(*args):
        result = archive(*args)
        if not active:
            return result
        if "outbox" not in trace:
            trace.append("write_readback")
            return result
        trace.append("archive")
        return {**result, "fixture_digest": acceptance_digest("injected late corruption")} if fault else result

    def stage_event(repository, event, *, session=None):
        result = append(repository, event, session=session)
        if active and event.event_type == RECIPE_EVENT:
            assert session.get(HttpFixtureRecipeRecord, event.entity_id) is not None
            assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == event.entity_id)) is not None
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == event.event_id)) is not None
            trace.append("outbox")
        return result

    monkeypatch.setattr(service, "record", scoped_record)
    monkeypatch.setattr(service.plans, "read", plan_read)
    monkeypatch.setattr(service.artifacts, "read", archive_read)
    monkeypatch.setattr(EventOutboxRepository, "append", stage_event)

    def register():
        pending = invoke(v, RECIPE_TOOL, request, key=uuid4().hex)
        assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
        response = confirm(v, pending.json())
        assert response.status_code == 200, response.text
        return response.json()

    good = register()
    assert good["status"] == "completed" and trace == ["plan", "write_readback", "outbox", "archive", "plan"], (trace, errors)
    trace.clear()
    fault = True
    rejected = register()
    assert rejected["status"] == "failed" and trace == ["plan", "write_readback", "outbox", "archive"], (trace, errors)
    assert [error[0] for error in errors] == ["RunPlanIntegrityError"]
    bad_id = recipe_identity(rejected["id"])
    with session_scope() as session:
        assert session.get(HttpFixtureRecipeRecord, recipe_identity(good["id"])) is not None
        assert session.get(HttpFixtureRecipeRecord, bad_id) is None
        assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == bad_id)) is None
        assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == bad_id)) is None
