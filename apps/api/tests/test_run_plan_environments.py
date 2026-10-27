"""Read-port specimens; not a canonical deployment, target execution or business gold."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.run_plan_environment_receipts import RunPlanEnvironmentReceiptAccess
from apps.api.app.application.platform.tool_handlers.run_plan_environments import RunPlanEnvironmentToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_receipt_access import require_receipt_access
from apps.api.app.application.platform.tool_test_design_scope import ToolTestDesignScopeObservationApplicationService
from apps.api.app.application.quality_loop.run_plan_environments import (
    RUN_PLAN_ENVIRONMENT_QUERY_TOOL, RunPlanEnvironmentApplicationService, RunPlanEnvironmentQuery,
)
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentInvalid
from apps.api.app.domain.quality_loop.run_plan_build import compile_run_plan_build
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from apps.api.tests.test_owned_target_environment import Commands, spec
from apps.api.tests.test_run_plan_builds import binding_inputs, refresh_pins


@pytest.fixture
def state(spec):
    spec = replace(spec, project_id="p")
    plan, selection, builds = binding_inputs()
    native = OwnedTargetEnvironmentInspector(spec, command=Commands(spec))
    target = plan["artifact"]["plan"]["selection"]["environment"]
    target.update(environment_id=spec.environment_id, kind="local", base_url="http://127.0.0.1:8080", inventory_hash=spec.digest)
    payload = selection.model_dump(mode="json")
    refresh_pins(plan, payload, builds)
    bound = compile_run_plan_build(plan, payload, builds)
    plan["metadata"].update(project_id="p", run_plan_id="plan", plan_digest=bound["plan_digest"],
        image_revision_id=bound["source_pin"]["image_revision_id"], manifest_id=bound["source_pin"]["manifest_id"])
    binding = {"metadata": {"project_id": "p", "binding_id": "binding", "run_plan_id": "plan",
        "artifact_hash": acceptance_digest(bound), "run_plan_artifact_hash": plan["metadata"]["artifact_hash"],
        "plan_digest": bound["plan_digest"], "image_revision_id": plan["metadata"]["image_revision_id"],
        "manifest_id": plan["metadata"]["manifest_id"], "target_artifact_hash": bound["target_artifact_hash"]},
        "artifact": {"binding": bound}, "current_use": {"inputs_current": True}}
    query = RunPlanEnvironmentQuery(project_id="p", run_plan_id="plan", run_plan_artifact_hash=plan["metadata"]["artifact_hash"],
        build_binding_id="binding", build_binding_artifact_hash=binding["metadata"]["artifact_hash"])
    actions, auth = [], SimpleNamespace(role="qa_lead", revoked=False)
    def current(scope=None):
        actions.append("access")
        if auth.revoked: raise SourceAccessDenied("revoked")
    def scope(project):
        current()
        return SimpleNamespace(project_id=project, actor_id="reviewer", effective_project_role=auth.role)
    authorization = SimpleNamespace(scope=scope, require_current=current)
    @contextmanager
    def read_session():
        actions.append("scope-open")
        yield
        actions.append("scope-close")
    def plan_read(project, ident):
        assert (project, ident) == ("p", "plan")
        actions.append("plan")
        return plan
    def binding_read(project, ident):
        assert (project, ident) == ("p", "binding")
        actions.append("binding")
        return binding
    def policy(project, ident, *, require_work):
        assert (project, ident) == ("p", spec.environment_id)
        actions.append("policy")
        require_work()
        return spec.digest
    def inspect(project, ident, artifact_hash, *, require_work):
        assert (project, ident) == ("p", spec.environment_id)
        actions.append("native")
        native.command.body = artifact_hash[7:].encode() + b"  /app/target.jar\n"
        return native.inspect(artifact_hash, require_work=require_work)
    environments = SimpleNamespace(policy_digest=policy, inspect=inspect)
    service = RunPlanEnvironmentApplicationService(SimpleNamespace(read=plan_read, verified_read_session=read_session),
        SimpleNamespace(read=binding_read), authorization, environments)
    return SimpleNamespace(service=service, plan=plan, binding=binding, query=query, spec=spec, actions=actions, auth=auth,
        environments=environments, native=native)


def test_original_saved_plan_build_and_owned_environment_are_checked_before_and_after(state):
    before = deepcopy((state.plan, state.binding))
    value = state.service.inspect(state.query)
    assert value["query"] == state.query.model_dump(mode="json")
    assert value["target_artifact_hash"] == state.binding["metadata"]["target_artifact_hash"]
    assert value["operator_policy_digest"] == state.spec.digest
    assert value["native_artifact_attested"] and value["isolation_configuration_attested"]
    assert value["historical_not_live"] and not value["durable_native_observation_verified"]
    assert not value["environment_fully_verified"] and not value["execution_authorized"] and not value["business_coverage_verified"]
    assert value["automated_count"] == value["executed_on_target_count"] == value["passed_count"] == 0
    assert "target" not in value and "container_id" not in str(value) and "127.0.0.1" not in str(value)
    assert state.actions.count("native") == 1 and state.actions.count("plan") == state.actions.count("binding") == 2
    assert state.actions.index("plan") < state.actions.index("native") < len(state.actions) - 1
    assert state.actions.count("scope-open") == state.actions.count("scope-close") == 1
    assert (state.plan, state.binding) == before


@pytest.mark.parametrize("role", ["viewer", "tester", "developer"])
def test_current_reviewer_role_is_required_before_reading_or_docker(state, role):
    state.auth.role = role
    with pytest.raises(SourceAccessDenied): state.service.inspect(state.query)
    assert "plan" not in state.actions and "native" not in state.actions


@pytest.mark.parametrize("fault", ["plan-hash", "binding-hash", "parent", "image", "manifest", "target-jar", "stale-plan", "stale-binding", "policy", "origin", "kind"])
def test_wrong_original_pin_or_noncurrent_input_cannot_inspect_an_arbitrary_target(state, fault):
    if fault == "plan-hash": state.plan["metadata"]["artifact_hash"] = acceptance_digest("wrong")
    if fault == "binding-hash": state.binding["metadata"]["artifact_hash"] = acceptance_digest("wrong")
    if fault == "parent": state.binding["metadata"]["run_plan_id"] = "other"
    if fault in {"image", "manifest"}: state.binding["metadata"]["image_revision_id" if fault == "image" else "manifest_id"] = "other"
    if fault == "target-jar": state.binding["metadata"]["target_artifact_hash"] = acceptance_digest("wrong")
    if fault == "stale-plan": state.plan["current_use"]["inputs_current"] = False
    if fault == "stale-binding": state.binding["current_use"]["inputs_current"] = "true"
    declaration = state.plan["artifact"]["plan"]["selection"]["environment"]
    if fault == "policy": declaration["inventory_hash"] = acceptance_digest("other-policy")
    if fault == "origin": declaration["base_url"] = "http://developer-host:8000"
    if fault == "kind": declaration["kind"] = "staging"
    with pytest.raises((RunPlanIntegrityError, RunPlanChanged, NativeEnvironmentInvalid)):
        state.service.inspect(state.query)
    assert "native" not in state.actions


@pytest.mark.parametrize("fault", ["revocation", "current-input", "operator-policy", "binding"])
def test_changes_during_native_inspection_invalidate_the_whole_result(state, fault):
    inspect = state.environments.inspect
    def changed(*args, **kwargs):
        value = inspect(*args, **kwargs)
        if fault == "revocation": state.auth.revoked = True
        if fault == "current-input": state.plan["current_use"]["inputs_current"] = False
        if fault == "binding": state.binding["artifact"]["binding"]["builds"][0]["note"] = "changed"
        if fault == "operator-policy": state.environments.policy_digest = lambda *args, **kwargs: acceptance_digest("other")
        return value
    state.environments.inspect = changed
    with pytest.raises((SourceAccessDenied, RunPlanChanged)): state.service.inspect(state.query)


def test_historical_receipt_reauthorization_never_reads_docker_or_operator_registry(state):
    receipt = state.service.inspect(state.query)
    state.plan["current_use"]["inputs_current"] = False
    state.actions.clear()
    def forbidden(*args, **kwargs): raise AssertionError("no implicit Docker recovery")
    state.environments.inspect = state.environments.policy_digest = forbidden
    state.service.require_receipt_inputs_access_many((state.query, state.query))
    assert state.service.authorize_historical_receipt(state.query, receipt) == receipt
    assert "native" not in state.actions and "policy" not in state.actions
    state.auth.revoked = True
    with pytest.raises(SourceAccessDenied): state.service.authorize_historical_receipt(state.query, receipt)


@pytest.mark.parametrize("field,value", [("execution_authorized", True), ("passed_count", 1), ("passed_count", False),
    ("environment_fully_verified", True), ("native_artifact_attested", 1), ("durable_native_observation_verified", True),
    ("remaining_gates", []), ("observed_at", "2026-10-10T00:00:00"), ("container_id", "arbitrary"),
    ("operator_policy_digest", "sha256:" + "0" * 64), ("environment_id", "other")])
def test_historical_observation_cannot_gain_authority_or_change_original_inputs(state, field, value):
    receipt = state.service.inspect(state.query)
    receipt[field] = value
    with pytest.raises((ValidationError, RunPlanIntegrityError)):
        state.service.authorize_historical_receipt(state.query, receipt)


def invocation(state, receipt=None):
    return ToolInvocation(id="query-original", tool_id=RUN_PLAN_ENVIRONMENT_QUERY_TOOL, status="completed", summary="private",
        input_payload={**state.query.model_dump(mode="json"), "idempotency_key": "private-key"}, idempotency_key="private-key",
        result=ToolResult(invocation_id="query-original", status="completed", summary="private", run_plan_environment=receipt))


def test_receipt_policy_enforces_access_and_redacts_shared_conversation_and_sse(state):
    receipt = state.service.inspect(state.query)
    command = invocation(state, receipt)
    policy = RunPlanEnvironmentReceiptAccess(state.service)
    policy.require_access(command)
    policy.require_batch_access((command, command))
    view = policy.broadcast_view(command)
    assert view.input_payload == {} and view.result is None and view.idempotency_key is None
    assert "private" not in str(view.model_dump()) and command.result.run_plan_environment == receipt
    with pytest.raises(PlatformApplicationError) as unavailable: require_receipt_access(None, command)
    assert unavailable.value.status_code == 503
    with pytest.raises(PlatformApplicationError) as unavailable: RunPlanEnvironmentReceiptAccess(object()).require_access(command)
    assert unavailable.value.status_code == 503
    state.auth.revoked = True
    with pytest.raises(PlatformApplicationError) as denied: policy.require_access(command)
    assert denied.value.status_code == 403


def test_canonical_handler_and_agent_observer_share_original_scope_without_reinspection(state):
    command, events = invocation(state), []
    async def emit(*values): events.append(values)
    access = SimpleNamespace(require_invocation_project_scope=lambda value: None)
    handler = RunPlanEnvironmentToolHandler(state.service, SimpleNamespace(emit_tool_status=emit), access)
    asyncio.run(handler.handle(command))
    assert events[-1][1] == "completed"
    command.result = events[-1][-1]
    receipt = command.result.run_plan_environment
    assert observation_receipt_fingerprint(command.result)
    state.actions.clear()
    observer = ToolTestDesignScopeObservationApplicationService(SimpleNamespace(get_tool_invocation=lambda ident: command),
        None, access, run_plan_environments=state.service)
    assert observer.describe(command.id, "p") == receipt
    assert "native" not in state.actions and "policy" not in state.actions
    with pytest.raises(PlatformApplicationError): observer.describe(command.id, "other")
    command.result.run_plan_environment = {**receipt, "passed_count": 1}
    with pytest.raises(ValidationError): observer.describe(command.id, "p")


def test_query_rejects_request_selected_container_url_inline_result_or_authority(state):
    for field, value in (("container_id", "arbitrary"), ("base_url", "http://host"), ("inventory", {}), ("execution_authorized", True)):
        with pytest.raises(ValidationError):
            RunPlanEnvironmentQuery.model_validate({**state.query.model_dump(mode="json"), field: value})


@pytest.mark.parametrize("fault", ["absent-result", "absent-receipt", "result-owner", "result-status", "query-status",
    "execution-authority", "passed-count", "target-hash", "operator-policy", "query", "naive-time", "extra-field"])
def test_generic_single_and_batch_reads_reject_invalid_historical_receipts_without_docker(state, fault):
    receipt = state.service.inspect(state.query)
    command = invocation(state, receipt)
    if fault == "absent-result": command.result = None
    if fault == "absent-receipt": command.result.run_plan_environment = None
    if fault == "result-owner": command.result.invocation_id = "other"
    if fault == "result-status": command.result.status = "failed"
    if fault == "query-status": command.status = "failed"
    if fault == "execution-authority": receipt["execution_authorized"] = True
    if fault == "passed-count": receipt["passed_count"] = 1
    if fault == "target-hash": receipt["target_artifact_hash"] = acceptance_digest("another-build")
    if fault == "operator-policy": receipt["operator_policy_digest"] = acceptance_digest("another-environment")
    if fault == "query": receipt["query"]["run_plan_id"] = "other"
    if fault == "naive-time": receipt["observed_at"] = "2026-10-10T00:00:00"
    if fault == "extra-field": receipt["private_source"] = "not permitted"
    if command.result and fault not in {"absent-receipt"}:
        command.result.run_plan_environment = receipt
    state.actions.clear()
    policy = RunPlanEnvironmentReceiptAccess(state.service)
    for operation in (lambda: policy.require_access(command), lambda: policy.require_batch_access((command,))):
        with pytest.raises(PlatformApplicationError) as invalid:
            operation()
        assert invalid.value.status_code == 502
    assert "native" not in state.actions and "policy" not in state.actions


def test_incomplete_query_has_only_original_input_access_and_batch_rechecks_current_cohort(state):
    command = invocation(state)
    command.status, command.result = "running", None
    state.actions.clear()
    policy = RunPlanEnvironmentReceiptAccess(state.service)
    policy.require_access(command)
    assert state.actions.count("plan") == 1 and "native" not in state.actions
    receipt = state.service.inspect(state.query)
    completed = invocation(state, receipt)
    cohorts = []
    def require_current_many(scopes):
        cohorts.append(scopes)
        for scope in scopes: state.service.authorization.require_current(scope)
    state.service.authorization.require_current_many = require_current_many
    state.actions.clear()
    policy.require_batch_access((completed, command))
    assert len(cohorts) == 1 and len(cohorts[0]) == 1
    assert "native" not in state.actions and "policy" not in state.actions
    original = state.service.bindings.read
    def revoke(*args):
        result = original(*args)
        state.auth.revoked = True
        return result
    state.service.bindings.read = revoke
    with pytest.raises(PlatformApplicationError) as denied: policy.require_batch_access((completed,))
    assert denied.value.status_code == 403
