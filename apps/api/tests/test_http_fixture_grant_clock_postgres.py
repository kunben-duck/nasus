"""Confirmation expiry during full source checks must roll back real PG facts."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_EVENT, GRANT_TOOL, grant_identity
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_TOOL
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.http_fixture_grant_models import HttpFixtureGrantRecord
from apps.api.app.infrastructure.persistence.http_fixture_grant_repository import HttpFixtureGrantRepository
from apps.api.app.infrastructure.persistence.http_fixture_journal_models import HttpFixtureDispatchRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_http_fixtures import manifest
from apps.api.tests.test_run_plans_api import (
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    select_binding_scripts, reviewed_plan_inputs, preview, submit, read,
)
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count


def registered_recipe(value):
    select_binding_scripts(value)
    _, _, _, selection = reviewed_plan_inputs(value)
    inputs = selection.model_dump(mode="json")
    declaration = inputs["fixtures"][0]
    recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
    recipe["setup_steps"][-1]["value_json"] = '"EXPLICIT_INDEPENDENT_EXPECTED"'
    declaration["data_manifest_hash"] = acceptance_digest(recipe)
    inputs["environment"]["base_url"] = "http://127.0.0.1:8080"
    inputs["policy_revision"] = "nasus.run-plan.v2"
    selection = type(selection).model_validate(inputs)
    plan_command = completed(submit(value, preview(value, selection).json()["request"]))
    plan_id = plan_command["result"]["object_refs"][0].split(":", 1)[1]
    plan = read(value, plan_id).json()
    request = {"project_id": value["project_id"], "run_plan_id": plan_id,
        "run_plan_artifact_hash": plan["metadata"]["artifact_hash"], "manifest": recipe}
    result = completed(confirm(value, invoke(value, RECIPE_TOOL, request, key=uuid4().hex).json()))
    return result["result"]["http_fixture_recipe"]["metadata"]


@pytest.mark.parametrize("expires_after_check", [1, 2], ids=["before-first-write", "after-outbox"])
def test_fixture_grant_confirmation_expiry_rolls_back_full_transaction(native_scripts, monkeypatch, expires_after_check):
    value = native_scripts
    assert engine.dialect.name == "postgresql"
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
    metadata = registered_recipe(value)
    request = {"project_id": value["project_id"], "recipe_id": metadata["record_id"],
        "recipe_artifact_hash": metadata["artifact_hash"], "attempt_id": "clock-" + uuid4().hex,
        "operation": "setup", "timeout_ms": 30000}
    repository = app.state.container.http_fixture_grants.repository
    original_issue, original_clock, append = repository.issue, HttpFixtureGrantRepository._clock, EventOutboxRepository.append
    checks, written, errors = [], [], []

    def sql_clock():
        clock = original_clock()
        return clock + text("INTERVAL '901 seconds'") if len(checks) >= expires_after_check else clock

    def issue(*args, require_access, **kwargs):
        def checked():
            require_access()
            checks.append("full original source validation completed")
        try:
            return original_issue(*args, require_access=checked, **kwargs)
        except Exception as exc:
            errors.append(type(exc).__name__)
            raise

    def observed_outbox(outbox, event, **kwargs):
        result = append(outbox, event, **kwargs)
        if event.event_type == GRANT_EVENT:
            session = kwargs["session"]
            session.flush()
            assert session.get(HttpFixtureGrantRecord, event.entity_id) is not None
            assert session.scalar(select(AuditEventRecord).where(AuditEventRecord.entity_id == event.entity_id)) is not None
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == event.event_id)) is not None
            written.append(event.entity_id)
        return result

    monkeypatch.setattr(HttpFixtureGrantRepository, "_clock", staticmethod(sql_clock))
    monkeypatch.setattr(repository, "issue", issue)
    monkeypatch.setattr(EventOutboxRepository, "append", observed_outbox)
    pending = invoke(value, GRANT_TOOL, request, key=uuid4().hex)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    result = confirm(value, pending.json())
    assert result.status_code == 200 and result.json()["status"] == "failed", result.text
    assert errors == ["RunPlanIntegrityError"] and len(checks) == expires_after_check
    assert len(written) == (1 if expires_after_check == 2 else 0)
    assert count(value, HttpFixtureGrantRecord) == count(value, HttpFixtureDispatchRecord) == 0
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.tool_invocation_id == pending.json()["id"], AuditEventRecord.action == GRANT_EVENT)) == 0
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == GRANT_EVENT,
            SSEEventOutboxRecord.entity_id == grant_identity(pending.json()["id"]))) == 0
