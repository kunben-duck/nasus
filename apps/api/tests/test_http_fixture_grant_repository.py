"""Explicit repository/clock doubles; real PG assertions are separate."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.tool_models import ToolResult
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.http_fixture_grant_models import HttpFixtureGrantRecord as Record
from apps.api.app.infrastructure.persistence.http_fixture_native_grant_models import HttpFixtureNativeGrantRecord
from apps.api.app.infrastructure.persistence.http_fixture_grant_repository import HttpFixtureGrantRepository
from apps.api.app.infrastructure.persistence.http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from apps.api.tests.test_http_fixture_grants import grant_specimen


def repository_specimen(monkeypatch):
    _, request, state, value = grant_specimen()
    payload = deepcopy(state["grants"][value["record_id"]])
    fields = {column.name for column in Record.__table__.columns} - {"payload", "content_hash"}
    row = Record(**{key: value[key] for key in fields}, payload=payload, content_hash=acceptance_digest(payload))
    result = ToolResult(invocation_id=value["invocation_id"], status="completed", summary="Scope permission only",
        http_fixture_grant={"metadata": value, "historical_not_live": True},
        object_refs=["http_fixture_grant:" + value["record_id"]]).model_dump(mode="json")
    command = SimpleNamespace(id=value["invocation_id"], status="completed", result_payload=result)
    current = {"now": datetime.fromisoformat(value["recorded_at"])}

    class Session:
        def get(self, model, ident):
            if model is Record:
                assert ident == value["record_id"]
                return row
            if model is HttpFixtureNativeGrantRecord:
                assert ident == value["record_id"]
                return None
            assert model is ToolInvocationRecord and ident == command.id
            return command

        def scalar(self, statement):
            assert "clock_timestamp()" in str(statement)
            return current["now"]

    @contextmanager
    def session_scope():
        yield Session()

    monkeypatch.setattr("apps.api.app.infrastructure.persistence.http_fixture_grant_repository.session_scope", session_scope)
    monkeypatch.setattr(HttpFixtureGrantRepository, "_request", staticmethod(lambda cmd: request))
    monkeypatch.setattr(HttpFixtureGrantRepository, "_canonical", classmethod(lambda cls, *args, **kwargs: command))
    monkeypatch.setattr(HttpFixtureGrantRepository, "_parents", staticmethod(lambda *args: {
        "project_id": request.project_id, "case_id": value["scope"]["case_id"],
        "plan_digest": value["scope"]["parent_digest"], "data_manifest_hash": value["scope"]["data_manifest_hash"]}))
    monkeypatch.setattr(PostgresHttpFixtureWorkRepository, "_actor_current", staticmethod(lambda *args: None))
    repository = HttpFixtureGrantRepository()
    kwargs = {"actor_id": value["actor_id"], "scope": HttpFixtureScope(**value["scope"]),
        "operation": value["operation"], "source_scope_digest": value["source_scope_digest"]}
    return repository, request, row, command, current, kwargs


@pytest.mark.parametrize("offset,allowed", [(-1, False), (0, True), (899.999999, True), (900, False), (901, False)])
def test_original_db_clock_interval_is_half_open_and_never_accepts_future_or_expired_consent(monkeypatch, offset, allowed):
    repository, request, row, _, current, kwargs = repository_specimen(monkeypatch)
    current["now"] += timedelta(seconds=offset)
    if allowed:
        repository.require_live(request.project_id, row.record_id, **kwargs)
    else:
        with pytest.raises(PermissionError): repository.require_live(request.project_id, row.record_id, **kwargs)


@pytest.mark.parametrize("status", ["running", "failed"])
def test_incomplete_original_command_history_is_not_live_consent(monkeypatch, status):
    repository, request, row, command, _, kwargs = repository_specimen(monkeypatch)
    command.status = status
    with pytest.raises(PermissionError): repository.require_live(request.project_id, row.record_id, **kwargs)
    assert repository.read(request.project_id, row.record_id) == row.payload


@pytest.mark.parametrize("change", ["int_permission", "execution_authorized", "missing_result", "foreign_object", "foreign_command"])
def test_completed_original_result_must_retain_exact_consent_not_a_rehashed_replacement(monkeypatch, change):
    repository, request, row, command, _, kwargs = repository_specimen(monkeypatch)
    if change == "int_permission": command.result_payload["http_fixture_grant"]["metadata"]["scope_permission_recorded"] = 1
    elif change == "execution_authorized": command.result_payload["http_fixture_grant"]["metadata"]["execution_authorized"] = True
    elif change == "missing_result": command.result_payload = None
    elif change == "foreign_object": command.result_payload["object_refs"] = ["http_fixture_grant:foreign"]
    else: command.result_payload["invocation_id"] = "another-command"
    with pytest.raises(RunPlanIntegrityError): repository.read(request.project_id, row.record_id)
    with pytest.raises(RunPlanIntegrityError): repository.require_live(request.project_id, row.record_id, **kwargs)


def test_one_attempt_can_contain_independently_bound_cases_of_the_same_original_plan():
    _, _, _, value = grant_specimen()
    scope = HttpFixtureScope(**value["scope"])
    parent = {"run_plan_id": "original", "run_plan_artifact_hash": acceptance_digest("original plan")}
    other_case = replace(scope, case_id="another-case", data_manifest_hash=acceptance_digest("other case manifest"))
    HttpFixtureGrantRepository._require_attempt_anchor(value, parent, other_case, value["actor_id"], parent)


@pytest.mark.parametrize("field", ["plan", "plan_hash", "actor", "target", "inventory", "environment", "timeout"])
def test_other_case_does_not_let_an_attempt_switch_original_plan_actor_or_target(field):
    _, _, _, value = grant_specimen()
    scope = HttpFixtureScope(**value["scope"])
    scope = replace(scope, case_id="another-case", data_manifest_hash=acceptance_digest("other case manifest"))
    parent = {"run_plan_id": "original", "run_plan_artifact_hash": acceptance_digest("original plan")}
    original = deepcopy(parent)
    actor = value["actor_id"]
    if field == "plan": parent["run_plan_id"] = "another"
    elif field == "plan_hash": parent["run_plan_artifact_hash"] = acceptance_digest("another plan")
    elif field == "actor": actor = "another-admin"
    elif field == "target": scope = replace(scope, artifact_hash=acceptance_digest("another target"))
    elif field == "inventory": scope = replace(scope, inventory_hash=acceptance_digest("another inventory"))
    elif field == "environment": scope = replace(scope, environment_id="another environment")
    else: scope = replace(scope, timeout_ms=1000)
    with pytest.raises(RunPlanIntegrityError):
        HttpFixtureGrantRepository._require_attempt_anchor(value, parent, scope, actor, original)
