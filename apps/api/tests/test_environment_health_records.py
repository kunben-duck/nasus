"""Protocol specimens for original health archives, not real execution coverage."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.health_record_receipts import HealthRecordReceiptAccess
from apps.api.app.application.platform.tool_handlers.environment_health_records import EnvironmentHealthRecordToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_test_design_scope import ToolTestDesignScopeObservationApplicationService
from apps.api.app.application.quality_loop.environment_health_records import EnvironmentHealthRecordApplicationService
from apps.api.app.application.quality_loop.environment_observation_records import EnvironmentRecordQuery
from apps.api.app.domain.quality_loop.environment_health_record import (
    HEALTH_RECORD_TOOL, HEALTH_RECORD_QUERY_TOOL, HEALTH_FALSE_AUTHORITIES, ZERO_COUNTS, validate_health_archive,
)
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_environment_observation_records import Artifacts, Repository
from apps.api.tests.test_owned_target_environment import spec
from apps.api.tests.test_owned_target_health import health_service
from apps.api.tests.test_run_plan_environments import state


@pytest.fixture
def service(state):
    health, commands, port = health_service(state)
    repository, artifacts = Repository(), Artifacts()
    return SimpleNamespace(application=EnvironmentHealthRecordApplicationService(health, artifacts, repository),
        repository=repository, artifacts=artifacts, state=state, commands=commands, port=port)


def save(service, invocation="independent-health-command"):
    return service.application.record(service.state.query, invocation_id=invocation,
        recorded_at=datetime.now(timezone.utc).isoformat())


def test_original_three_responses_are_archived_but_receipts_are_metadata_only_and_not_live(service):
    metadata = save(service)
    assert metadata["dependency_health_verified"] is metadata["target_health_verified"] is True
    assert all(metadata[key] is False for key in HEALTH_FALSE_AUTHORITIES)
    assert all(type(metadata[key]) is int and metadata[key] == 0 for key in ZERO_COUNTS)
    view = service.application.read("p", metadata["record_id"])
    assert view["archive"]["observation"]["inventory"]["dependency_health_verified"] is False
    assert len(view["archive"]["observation"]["checks"]) == 3
    assert service.commands.health_calls == ["pg", "redis", "target"]
    receipt = service.application.receipt("p", metadata["record_id"])
    assert "response_base64" not in str(receipt) and "container_id" not in str(receipt) and "127.0.0.1" not in str(receipt)
    service.state.plan["current_use"]["inputs_current"] = False
    service.port.inspect_health = lambda *args, **kwargs: pytest.fail("historical replay must not inspect")
    service.port.policy_digest = lambda *args, **kwargs: pytest.fail("historical replay must not load registry")
    assert save(service) == metadata
    service.application.authorize_receipts(((EnvironmentRecordQuery(project_id="p", record_id=metadata["record_id"]), receipt),))
    assert len(service.repository.values) == len(service.artifacts.values) == 1


def test_unhealthy_original_response_is_saved_without_relabeling_and_no_execution_authority(service):
    service.commands.responses["target"] = b'{"status":"DOWN"}\n503'
    metadata = save(service)
    assert metadata["target_health_verified"] is False and metadata["dependency_health_verified"] is True
    assert metadata["health_checks"][2]["healthy"] is False and metadata["execution_authorized"] is False


def test_confirmation_rejected_before_any_probe_or_private_archive(service):
    service.repository.confirmed = False
    with pytest.raises(RunPlanIntegrityError): save(service)
    assert not service.commands.calls and not service.repository.values and not service.artifacts.values


@pytest.mark.parametrize("fault", ["revoked", "stale", "archive"])
def test_late_acl_source_or_private_byte_change_prevents_commit(service, fault):
    def changed():
        if fault == "revoked": service.state.auth.revoked = True
        if fault == "stale": service.state.plan["current_use"]["inputs_current"] = False
        if fault == "archive": next(iter(service.artifacts.values.values()))["observation"]["checks"][0]["response_base64"] = "MAo="
    service.repository.before_commit = changed
    with pytest.raises((SourceAccessDenied, RunPlanChanged, RunPlanIntegrityError)): save(service)
    assert not service.repository.values


def test_source_acl_checked_before_reading_private_health_bytes(service):
    metadata = save(service)
    service.artifacts.actions.clear()
    service.state.auth.revoked = True
    with pytest.raises(SourceAccessDenied): service.application.read("p", metadata["record_id"])
    assert not service.artifacts.actions


@pytest.mark.parametrize("fault", ["schema", "actor", "time", "record", "request", "parent", "inventory", "extra", "missing-probe", "order", "body", "promoted"])
def test_archive_requires_exact_original_scope_and_complete_bytes(service, fault):
    metadata = save(service)
    archive = service.application.read("p", metadata["record_id"])["archive"]
    if fault == "schema": archive["schema"] = "imported-health"
    if fault == "actor": archive["actor_id"] = ""
    if fault == "time": archive["recorded_at"] = "2026-10-11T00:00:00"
    if fault == "record": archive["record_id"] = "another"
    if fault == "request": archive["request"]["build_binding_id"] = "another"
    if fault == "parent": archive["parents"]["environment_id"] = "another"
    if fault == "inventory": archive["observation"]["inventory_hash"] = "sha256:" + "1" * 64
    if fault == "extra": archive["observation"]["execution_authorized"] = True
    if fault == "missing-probe": archive["observation"]["checks"].pop()
    if fault == "order": archive["observation"]["checks"].reverse()
    if fault == "body": archive["observation"]["checks"][0]["response_base64"] = "MAo="
    if fault == "promoted": archive["observation"]["checks"][0]["healthy"] = True
    with pytest.raises(ValueError):
        validate_health_archive(archive, service.state.query.model_dump(mode="json"), service.state.plan, service.state.binding)


@pytest.mark.parametrize("field,value", [("dependency_health_verified", 1), ("execution_authorized", 0),
    ("passed_count", False), ("health_hash", "sha256:" + "1" * 64)])
def test_receipt_cannot_relabel_authority_or_health_digest(service, field, value):
    metadata = save(service)
    receipt = deepcopy(service.application.receipt("p", metadata["record_id"]))
    receipt["metadata"][field] = value
    with pytest.raises(RunPlanIntegrityError):
        service.application.authorize_receipts(((EnvironmentRecordQuery(project_id="p", record_id=metadata["record_id"]), receipt),))


def test_canonical_handlers_receipts_and_broadcast_remain_private(service):
    emitted = []
    async def emit(*args): emitted.append(args)
    handler = EnvironmentHealthRecordToolHandler(service.application, SimpleNamespace(emit_tool_status=emit),
        SimpleNamespace(require_invocation_project_scope=lambda invocation: None))
    invocation = ToolInvocation(id="independent-health-command", tool_id=HEALTH_RECORD_TOOL,
        status="running", summary="Health specimen", input_payload=service.state.query.model_dump(mode="json"))
    asyncio.run(handler.handle(invocation))
    result = emitted[-1][-1]
    assert result.status == "completed" and observation_receipt_fingerprint(result)
    assert "response_base64" not in str(result) and "container_id" not in str(result)
    completed = invocation.model_copy(update={"status": "completed", "result": result})
    policy = HealthRecordReceiptAccess(service.application)
    policy.require_access(completed)
    broadcast = policy.broadcast_view(completed)
    assert broadcast.input_payload == {} and broadcast.result is None
    query = EnvironmentRecordQuery(project_id="p", record_id=result.run_plan_health_record["metadata"]["record_id"])
    queried = ToolInvocation(id="query-health", tool_id=HEALTH_RECORD_QUERY_TOOL, status="completed", summary="Health query specimen", input_payload=query.model_dump(mode="json"),
        result=ToolResult(invocation_id="query-health", status="completed", summary="Health query specimen", run_plan_health_record=result.run_plan_health_record))
    policy.require_batch_access((completed, queried))
    observation = ToolTestDesignScopeObservationApplicationService(
        SimpleNamespace(get_tool_invocation=lambda ident: queried), None,
        SimpleNamespace(require_invocation_project_scope=lambda invocation: None), health_records=service.application)
    assert observation.describe("query-health", "p") == result.run_plan_health_record
    with pytest.raises(PlatformApplicationError): observation.describe("query-health", "other")
    service.state.auth.revoked = True
    with pytest.raises(SourceAccessDenied): observation.describe("query-health", "p")
    service.state.auth.revoked = False
    with pytest.raises(PlatformApplicationError):
        policy.require_access(completed.model_copy(update={"status": "running"}))
