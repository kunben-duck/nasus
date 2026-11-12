"""Port specimens: exact inventory archival, never canonical deployment or business gold."""
import asyncio
from contextvars import copy_context
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
from apps.api.app.application.platform.environment_record_receipts import EnvironmentRecordReceiptAccess
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.tool_handlers.environment_observation_records import EnvironmentObservationRecordToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_test_design_scope import ToolTestDesignScopeObservationApplicationService
from apps.api.app.application.quality_loop.environment_observation_records import EnvironmentObservationRecordApplicationService, EnvironmentRecordQuery
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.environment_observation_record import (
    ENVIRONMENT_RECORD_TOOL, ENVIRONMENT_RECORD_QUERY_TOOL, FALSE_AUTHORITIES, ZERO_COUNTS,
    validate_environment_archive,
)
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_run_plan_environments import state
from apps.api.tests.test_owned_target_environment import spec


class Artifacts:
    def __init__(self):
        self.values, self.actions = {}, []

    def put(self, project, value):
        digest = acceptance_digest(value)
        self.values[(project, digest)] = deepcopy(value)
        self.actions.append("put")
        return digest, digest

    def read(self, project, ref, digest):
        assert ref == digest
        self.actions.append("read")
        value = deepcopy(self.values[(project, digest)])
        if acceptance_digest(value) != digest:
            raise RunPlanIntegrityError("bad private archive")
        return value


class Repository:
    def __init__(self):
        self.values, self.confirmed, self.before_commit = {}, True, None

    def committed(self, request, *, actor_id, invocation_id, require_access):
        require_access()
        if not self.confirmed:
            raise RunPlanIntegrityError("missing independent confirmation")
        previous = next((item for item in self.values.values() if item["metadata"]["invocation_id"] == invocation_id), None)
        return deepcopy(previous["metadata"]) if previous else None

    def record(self, request, payload, ref, metadata, *, require_access):
        if self.before_commit:
            self.before_commit()
        require_access()
        self.values[metadata["record_id"]] = {"metadata": deepcopy(metadata), "artifact_ref": ref,
            "request": request.model_dump(mode="json")}
        return deepcopy(metadata)

    def read(self, project, ident):
        value = deepcopy(self.values[ident])
        assert value["metadata"]["project_id"] == project
        return value


@pytest.fixture
def service(state):
    repository, artifacts = Repository(), Artifacts()
    return SimpleNamespace(application=EnvironmentObservationRecordApplicationService(state.service, artifacts, repository),
        repository=repository, artifacts=artifacts, state=state)


def save(service, invocation="confirmed-command"):
    return service.application.record(service.state.query, invocation_id=invocation,
        recorded_at=datetime.now(timezone.utc).isoformat())


def test_full_original_inventory_archived_without_promoting_authority_and_historical_replay_has_no_native_work(service):
    metadata = save(service)
    assert metadata["durable_native_observation_verified"] is True
    assert all(metadata[key] is False for key in FALSE_AUTHORITIES)
    assert all(type(metadata[key]) is int and metadata[key] == 0 for key in ZERO_COUNTS)
    view = service.application.read("p", metadata["record_id"])
    assert view["archive"]["observation"]["inventory"]["target"]["container_id"] == service.state.spec.container_id
    assert view["archive"]["request"] == service.state.query.model_dump(mode="json")
    assert service.state.actions.count("native") == 1
    receipt = service.application.receipt("p", metadata["record_id"])
    assert "container_id" not in str(receipt) and "127.0.0.1" not in str(receipt)
    service.state.plan["current_use"]["inputs_current"] = False
    service.state.environments.inspect = lambda *args, **kwargs: pytest.fail("historical read must not inspect")
    service.state.environments.policy_digest = lambda *args, **kwargs: pytest.fail("historical read must not load registry")
    assert save(service) == metadata
    assert service.application.receipt("p", metadata["record_id"]) == receipt
    service.application.authorize_receipts(((EnvironmentRecordQuery(project_id="p", record_id=metadata["record_id"]), receipt),))
    assert len(service.artifacts.values) == len(service.repository.values) == 1


def test_confirmation_checked_before_native_work_or_archive(service):
    service.repository.confirmed = False
    with pytest.raises(RunPlanIntegrityError): save(service)
    assert "native" not in service.state.actions and not service.artifacts.values and not service.repository.values


@pytest.mark.parametrize("fault", ["revoked", "stale", "corrupt-archive"])
def test_late_revocation_parent_change_or_archive_damage_prevents_fact_commit(service, fault):
    def changed():
        if fault == "revoked": service.state.auth.revoked = True
        if fault == "stale": service.state.plan["current_use"]["inputs_current"] = False
        if fault == "corrupt-archive":
            next(iter(service.artifacts.values.values()))["observation"]["inventory"]["native_artifact_attested"] = False
    service.repository.before_commit = changed
    with pytest.raises((SourceAccessDenied, RunPlanChanged, RunPlanIntegrityError)): save(service)
    assert not service.repository.values


def test_revoked_read_cannot_touch_private_inventory(service):
    metadata = save(service)
    service.artifacts.actions.clear()
    service.state.auth.revoked = True
    with pytest.raises(SourceAccessDenied): service.application.read("p", metadata["record_id"])
    assert service.artifacts.actions == []


def test_environment_parent_port_returns_complete_verified_copies_and_rechecks_each_read(service):
    metadata = save(service)
    original = service.application.read("p", metadata["record_id"])
    view, parent = service.application.read_with_plan("p", metadata["record_id"])
    assert view == original and parent == service.state.plan
    parent["metadata"]["artifact_hash"] = acceptance_digest("caller-mutated")
    view["archive"]["parents"]["target_artifact_hash"] = acceptance_digest("caller-mutated")
    service.state.plan["current_use"]["inputs_current"] = False
    next_view, next_parent = service.application.read_with_plan("p", metadata["record_id"])
    assert next_view == original and next_parent == service.state.plan
    assert next_parent["current_use"]["inputs_current"] is False
    assert service.state.actions.count("native") == 1
    service.artifacts.actions.clear()
    service.state.auth.revoked = True
    with pytest.raises(SourceAccessDenied):
        service.application.read_with_plan("p", metadata["record_id"])
    assert not service.artifacts.actions


def test_environment_parent_port_rejects_revocation_after_private_inventory_read(service, monkeypatch):
    metadata = save(service)
    read = service.artifacts.read
    def revoked(*args):
        value = read(*args)
        service.state.auth.revoked = True
        return value
    monkeypatch.setattr(service.artifacts, "read", revoked)
    with pytest.raises(SourceAccessDenied):
        service.application.read_with_plan("p", metadata["record_id"])
    assert service.state.actions.count("native") == 1


def test_environment_bound_parent_read_rejects_wrong_query_and_stale_inputs_before_private_read(service):
    metadata = save(service)
    ident, query = metadata["record_id"], service.state.query
    wrong = query.model_copy(update={"build_binding_artifact_hash": acceptance_digest("other build binding")})
    service.artifacts.actions.clear()
    with pytest.raises(RunPlanIntegrityError, match="read scope differs"):
        service.application.read_with_parents(wrong, ident, current=True)
    service.state.plan["current_use"]["inputs_current"] = False
    with pytest.raises(RunPlanChanged):
        service.application.read_with_parents(query, ident, current=True)
    assert not service.artifacts.actions

    view, plan, binding = service.application.read_with_parents(query, ident)
    assert view["metadata"] == metadata and plan["current_use"]["inputs_current"] is False
    assert binding["metadata"]["artifact_hash"] == query.build_binding_artifact_hash
    binding["metadata"]["artifact_hash"] = acceptance_digest("caller changed returned view")
    assert service.application.read_with_parents(query, ident)[2]["metadata"]["artifact_hash"] == query.build_binding_artifact_hash


def test_case_environment_parent_reuse_keeps_fresh_archives_and_brackets_the_complete_batch(service):
    metadata = save(service)
    app, ident, query = service.application, metadata["record_id"], service.state.query
    state = service.state
    state.actions.clear()
    service.artifacts.actions.clear()
    with app.case_parent_read_session(query, ident, current=True) as (view, plan, _binding):
        assert state.actions.count("plan") == 1
        for _ in range(4):
            actual, saved = app.read_with_plan("p", ident)
            assert actual == view and saved == plan
            saved["metadata"]["artifact_hash"] = acceptance_digest("caller copy only")
        assert state.actions.count("plan") == state.actions.count("binding") == 1
        assert service.artifacts.actions == ["read"] * 5
        inherited = copy_context()
    assert state.actions.count("plan") == state.actions.count("binding") == 2
    assert service.artifacts.actions == ["read"] * 6
    assert app._case_parents.get() is None
    assert inherited.run(app.read_with_plan, "p", ident)[0] == view
    assert state.actions.count("plan") == 3
    assert "native" not in state.actions


@pytest.mark.parametrize("fault", ["revoked", "archive", "plan"])
def test_case_environment_parent_reuse_rejects_changes_and_closes_on_failure(service, fault):
    metadata = save(service)
    app, ident, query = service.application, metadata["record_id"], service.state.query
    expected = {"revoked": SourceAccessDenied, "archive": RunPlanIntegrityError, "plan": RunPlanChanged}[fault]
    with pytest.raises(expected):
        with app.case_parent_read_session(query, ident, current=True):
            if fault == "plan":
                app.read_with_plan("p", ident)
                service.state.plan["current_use"]["inputs_current"] = False
            else:
                service.artifacts.actions.clear()
                if fault == "revoked":
                    service.state.auth.revoked = True
                else:
                    value = next(iter(service.artifacts.values.values()))
                    value["observation"]["inventory"]["native_artifact_attested"] = False
                app.read_with_plan("p", ident)
    assert app._case_parents.get() is None
    if fault == "revoked":
        assert service.artifacts.actions == []


def test_case_environment_parent_reuse_does_not_cross_records_tasks_or_threads(service):
    app, query = service.application, service.state.query
    one, other = save(service)["record_id"], save(service, "another-confirmed-command")["record_id"]
    service.state.actions.clear()

    async def child():
        return app.read_with_plan("p", one)

    async def verify():
        with app.case_parent_read_session(query, one) as (view, plan, _binding):
            assert await asyncio.create_task(child()) == (view, plan)
            assert await asyncio.to_thread(app.read_with_plan, "p", one) == (view, plan)
            assert app.read_with_plan("p", other)[0]["metadata"]["record_id"] == other
            assert app.read_with_plan("p", one) == (view, plan)
            assert service.state.actions.count("plan") == 4
    asyncio.run(verify())
    assert service.state.actions.count("plan") == 5


def test_case_locator_plan_cannot_escape_or_rebind_the_verified_case_read(service):
    app, query = service.application, service.state.query
    record_id = save(service)["record_id"]
    access = app.inspections._access(query.project_id)
    pin = (query.project_id, query.run_plan_id, query.run_plan_artifact_hash)
    read = lambda: app.case_locator_plan(*pin, access=access)

    async def denied_in_another_task():
        with pytest.raises(RunPlanIntegrityError, match="active original case parent"):
            read()

    async def verify():
        with app.case_parent_read_session(query, record_id) as (_, plan, _):
            candidate = read()
            assert candidate == plan and candidate is not plan
            candidate["metadata"]["artifact_hash"] = acceptance_digest("caller mutation")
            assert read() == plan
            with pytest.raises(RunPlanIntegrityError, match="another case plan"):
                app.case_locator_plan(*pin[:2], acceptance_digest("other plan"), access=access)
            with pytest.raises(SourceAccessDenied, match="case source access changed"):
                app.case_locator_plan(*pin, access=object())
            await asyncio.create_task(denied_in_another_task())
            with pytest.raises(RunPlanIntegrityError, match="active original case parent"):
                await asyncio.to_thread(read)

    with pytest.raises(RunPlanIntegrityError, match="active original case parent"):
        read()
    asyncio.run(verify())
    with pytest.raises(RunPlanIntegrityError, match="active original case parent"):
        read()


@pytest.mark.parametrize("fault", ["project", "record", "actor", "time", "request", "parent", "inventory", "observed-time", "extra",
    "schema", "parent-extra", "bad-digest"])
def test_archive_cannot_be_rebound_or_promote_native_inventory(service, fault):
    metadata = save(service)
    archive = service.application.read("p", metadata["record_id"])["archive"]
    if fault == "project": archive["project_id"] = "other"
    if fault == "record": archive["record_id"] = "other"
    if fault == "actor": archive["actor_id"] = ""
    if fault == "time": archive["recorded_at"] = "2026-10-10T00:00:00"
    if fault == "request": archive["request"]["build_binding_id"] = "other"
    if fault == "parent": archive["parents"]["target_artifact_hash"] = acceptance_digest("other")
    if fault == "inventory":
        archive["observation"]["inventory"]["execution_authorized"] = True
        archive["observation"]["inventory_hash"] = acceptance_digest(archive["observation"]["inventory"])
    if fault == "observed-time": archive["observation"]["observed_at"] = "2026-10-10T00:00:00"
    if fault == "extra": archive["extra"] = True
    if fault == "schema": archive["schema"] = "caller-imported"
    if fault == "parent-extra": archive["parents"]["execution_authorized"] = True
    if fault == "bad-digest": archive["request"]["run_plan_artifact_hash"] = "not-a-hash"
    with pytest.raises(ValueError):
        validate_environment_archive(archive, service.state.query.model_dump(mode="json"), service.state.plan, service.state.binding)


@pytest.mark.parametrize("fault", ["true-to-one", "false-to-zero", "count-to-bool", "extra", "query", "missing"])
def test_receipt_reverified_against_fact_not_python_coercion_or_tool_json(service, fault):
    metadata = save(service)
    receipt = service.application.receipt("p", metadata["record_id"])
    query = EnvironmentRecordQuery(project_id="p", record_id=metadata["record_id"])
    if fault == "true-to-one": receipt["metadata"]["durable_native_observation_verified"] = 1
    if fault == "false-to-zero": receipt["metadata"]["execution_authorized"] = 0
    if fault == "count-to-bool": receipt["metadata"]["passed_count"] = False
    if fault == "extra": receipt["metadata"]["extra"] = True
    if fault == "query": query = query.model_copy(update={"record_id": "other"})
    if fault == "missing": receipt.pop("metadata")
    with pytest.raises((RunPlanIntegrityError, KeyError)):
        service.application.authorize_receipts(((query, receipt),))


def test_canonical_handlers_metadata_only_receipts_redacted_broadcast_and_fingerprint(service):
    emitted = []
    async def emit(*args): emitted.append(args)
    access = SimpleNamespace(require_invocation_project_scope=lambda invocation: None)
    handler = EnvironmentObservationRecordToolHandler(service.application, SimpleNamespace(emit_tool_status=emit), access)
    invocation = ToolInvocation(id="confirmed-command", tool_id=ENVIRONMENT_RECORD_TOOL, label="Record", status="running",
        summary="Record original environment",
        input_payload={**service.state.query.model_dump(mode="json"), "confirmed_by_user": True},
        scope="central", risk_level="medium", confirmation_mode="user_confirm")
    asyncio.run(handler.handle(invocation))
    result = emitted[-1][-1]
    assert result.status == "completed" and "container_id" not in result.model_dump_json()
    completed = invocation.model_copy(update={"status": "completed", "result": result})
    policy = EnvironmentRecordReceiptAccess(service.application)
    policy.require_access(completed)
    redacted = policy.broadcast_view(completed)
    assert redacted.input_payload == {} and redacted.result is None
    key = observation_receipt_fingerprint(result)
    changed = result.model_copy(update={"run_plan_environment_record": {"different": True}})
    assert observation_receipt_fingerprint(changed) != key
    emitted.clear()
    query = ToolInvocation(id="read-command", tool_id=ENVIRONMENT_RECORD_QUERY_TOOL, label="Read", status="running",
        summary="Read original environment",
        input_payload={"project_id": "p", "record_id": result.run_plan_environment_record["metadata"]["record_id"]},
        scope="central", risk_level="low", confirmation_mode="none")
    asyncio.run(handler.handle(query))
    assert emitted[-1][-1].run_plan_environment_record == result.run_plan_environment_record
    queried = query.model_copy(update={"status": "completed", "result": emitted[-1][-1]})
    observation = ToolTestDesignScopeObservationApplicationService(
        SimpleNamespace(get_tool_invocation=lambda ident: queried), None, access, environment_records=service.application)
    assert observation.describe(queried.id, "p") == result.run_plan_environment_record
    with pytest.raises(PlatformApplicationError): observation.describe(queried.id, "another-project")
    broken = completed.model_copy(update={"result": ToolResult(invocation_id="wrong", status="completed", summary="wrong",
        run_plan_environment_record=result.run_plan_environment_record)})
    with pytest.raises(PlatformApplicationError) as error: policy.require_access(broken)
    assert error.value.status_code == 502
