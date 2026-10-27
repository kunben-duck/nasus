"""Resource prefilters must distinguish denial from unavailable verification."""
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope, current_actor
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.project_access import InvocationAccessScope
from apps.api.app.application.platform.tool_build_completions import BuildCompletionInvocationResourcePolicy
from apps.api.app.application.platform.tool_code_indexes import CodeIndexInvocationResourcePolicy
from apps.api.app.application.platform.tool_gap_ownership import GapOwnershipInvocationResourcePolicy
from apps.api.app.application.platform.tool_image_plan_phases import ImagePlanPhaseInvocationResourcePolicy
from apps.api.app.application.platform.tool_investigations import InvestigationInvocationResourcePolicy
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_plan_revisions import BuildPlanRevisionInvocationResourcePolicy
from apps.api.app.application.platform.tool_structure_cancellations import StructureCancellationInvocationResourcePolicy
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope


HASH = "sha256:" + "a" * 64
FAMILIES = ("code_index", "investigation", "completion", "revision", "phase", "ownership", "cancellation")


def access_view(command, view):
    if view == "command":
        return command
    return InvocationAccessScope(id=command.id, conversation_id=command.conversation_id,
        input_payload=command.input_payload, object_refs=tuple(command.result.object_refs) if command.result else (),
        tool_id=command.tool_id, status=command.status, result=command.result)


def policy_request(family, verify):
    goal = AgentGoal(id="goal", conversation_id="conversation", project_id="project",
        title="Original image goal", summary="Original paused goal", status="paused", steps=[]).model_dump(mode="json")
    application = SimpleNamespace(require_access=verify, require_receipt_access=verify)
    previous = SimpleNamespace(can_access=lambda *_: True, applies=lambda *_: False)
    policies = {
        "code_index": (CodeIndexInvocationResourcePolicy, "query.system_image.code_indexes.status",
            {"project_id": "project", "generation_id": "generation"}),
        "investigation": (InvestigationInvocationResourcePolicy, "system_image.build.investigate",
            {"project_id": "project", "plan_id": "plan", "plan_digest": HASH, "goal_id": "goal",
                "image_revision_id": "image", "image_artifact_hash": HASH}),
        "completion": (BuildCompletionInvocationResourcePolicy, "query.system_image.build_completion.read",
            {"project_id": "project", "investigation_revision_id": "investigation",
                "investigation_revision_hash": HASH, "expected_goal": goal}),
        "revision": (BuildPlanRevisionInvocationResourcePolicy, "system_image.build.plan.revise",
            {"project_id": "project", "goal_id": "goal", "root_plan_id": "plan", "from_plan_id": "plan",
                "from_plan_digest": HASH, "source_manifest_id": "manifest", "expected_goal": goal}),
        "phase": (ImagePlanPhaseInvocationResourcePolicy, "system_image.build.plan.activate_revision",
            {"project_id": "project", "goal_id": "goal", "root_plan_id": "plan", "revision_id": "revision",
                "revision_hash": HASH, "expected_goal": goal, "budget": {"max_tool_calls": 1,
                    "max_model_calls": 0, "max_active_seconds": 60, "max_cost_microusd": 0}}),
        "ownership": (GapOwnershipInvocationResourcePolicy, "system_image.build.gaps.assign",
            {"project_id": "project", "completion_invocation_id": "completion", "completion_report_hash": HASH,
                "expected_goal": goal, "assignments": [{"gap_id": "gap_" + "a" * 64,
                    "owner_actor_id": "reader", "reason": "Investigate the original gap"}]}),
        "cancellation": (StructureCancellationInvocationResourcePolicy, "system_image.build.structure.cancel",
            {"project_id": "project", "original_invocation_id": "structure", "plan_id": "plan",
                "plan_digest": HASH, "target_baseline_id": "baseline"}),
    }
    cls, tool, body = policies[family]
    policy = cls(application) if family == "code_index" else cls(application, previous)
    command = ToolInvocation(id="original", tool_id=tool, status="completed", summary="Original receipt", input_payload=body)
    return policy, command


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("status", [409, 502, 503, 504])
@pytest.mark.parametrize("view", ["command", "audit_scope"])
def test_resource_prefilter_propagates_verification_faults_and_restores_actor(family, status, view):
    reader = UserProfile(id="reader", name="Reader", email="reader@example.com", role="viewer")
    parent = UserProfile(id="parent", name="Parent", email="parent@example.com", role="viewer")
    checked = []
    fault = PlatformApplicationError("receipt_verification_failed", "Original resource could not be verified.", status)

    def verify(request):
        checked.append((request.project_id, current_actor().user.id))
        raise fault

    policy, command = policy_request(family, verify)
    before = command.model_dump(mode="json")
    with actor_scope(parent):
        with pytest.raises(PlatformApplicationError) as raised:
            policy.can_access(access_view(command, view), reader)
        assert raised.value is fault and current_actor().user.id == parent.id
    assert checked == [("project", reader.id)]
    assert command.model_dump(mode="json") == before


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("fault,status", [(RuntimeError("private source URI"), 503),
    (BuildPlanIntegrityError("private original hash"), 502)])
@pytest.mark.parametrize("view", ["command", "audit_scope"])
def test_resource_prefilter_sanitizes_unavailable_or_corrupt_verification(family, fault, status, view):
    checked = []

    def verify(request):
        checked.append(request.project_id)
        raise fault

    policy, command = policy_request(family, verify)
    with pytest.raises(PlatformApplicationError) as raised:
        policy.can_access(access_view(command, view), UserProfile(id="reader", name="Reader", email="reader@example.com", role="viewer"))
    assert raised.value.status_code == status and "private" not in raised.value.message
    assert checked == ["project"]


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("fault", [SourceAccessDenied("private source"), StaleSourceAccessScope("changed policy"),
    PlatformApplicationError("project_access_denied", "Project membership is required.", 403)])
@pytest.mark.parametrize("view", ["command", "audit_scope"])
def test_explicit_denial_remains_a_hidden_resource_without_mutating_history(family, fault, view):
    def verify(_):
        raise fault

    policy, command = policy_request(family, verify)
    before = command.model_dump(mode="json")
    assert policy.can_access(access_view(command, view), UserProfile(id="reader", name="Reader", email="reader@example.com", role="viewer")) is False
    assert command.model_dump(mode="json") == before


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("status", ["pending", "waiting_confirmation", "failed", "completed"])
@pytest.mark.parametrize("view", ["command", "audit_scope"])
def test_invalid_attempt_is_not_confused_with_a_damaged_completed_contract(family, status, view):
    policy, command = policy_request(family, lambda _: pytest.fail("invalid input must not call a resource port"))
    command.input_payload = {}
    command.status = status
    actor = UserProfile(id="reader", name="Reader", email="reader@example.com", role="viewer")
    if status == "completed":
        with pytest.raises(PlatformApplicationError) as raised:
            policy.can_access(access_view(command, view), actor)
        assert raised.value.status_code == 502
    else:
        assert policy.can_access(access_view(command, view), actor) is False


def completed_plan_receipt(family):
    from apps.api.app.application.agent.image_plan_phases import ImagePlanPhaseInput
    from apps.api.app.application.system_image.build_plan_revisions import BuildPlanRevisionInput
    from apps.api.app.domain.system_image.build_authorization import ApprovedBuildBudget

    checked = []
    policy, command = policy_request(family, lambda request: checked.append(request.project_id))
    if family == "revision":
        request = BuildPlanRevisionInput.model_validate(command.input_payload)
        original = SimpleNamespace(invocation_id=command.id, checkpoint=request.checkpoint(),
            from_plan_id=request.from_plan_id, from_plan_digest=request.from_plan_digest,
            source_manifest_id=request.source_manifest_id, parent_revision_id=request.parent_revision_id,
            parent_revision_hash=request.parent_revision_hash, revision_id="revision", plan_id="new-plan")
        record = SimpleNamespace(revision=original)
        refs = ["build_plan_revision:revision", "build_plan:new-plan"]
    else:
        request = ImagePlanPhaseInput.model_validate(command.input_payload)
        original = SimpleNamespace(invocation_id=command.id, checkpoint=request.checkpoint(),
            revision_id=request.revision_id, revision_hash=request.revision_hash,
            budget=ApprovedBuildBudget(**request.budget.model_dump()), parent_phase_id=request.parent_phase_id,
            parent_phase_hash=request.parent_phase_hash, phase_id="phase", plan_id="new-plan", goal_id="goal")
        record = SimpleNamespace(phase=original)
        refs = ["build_plan_phase:phase", "build_plan:new-plan", "agent_goal:goal"]
    records = [record]
    history_calls = []

    def history(project_id, root_plan_id, goal_id):
        history_calls.append((project_id, root_plan_id, goal_id))
        return records

    policy.application.history = history
    command.result = ToolResult(invocation_id=command.id, status="completed", summary="Original saved result", object_refs=refs)
    return policy, command, original, records, checked, history_calls


@pytest.mark.parametrize("family", ["revision", "phase"])
@pytest.mark.parametrize("view", ["command", "audit_scope"])
def test_completed_plan_receipt_requires_its_exact_original_fact(family, view):
    policy, command, _, _, checked, history_calls = completed_plan_receipt(family)
    before = command.model_dump(mode="json")
    actor = UserProfile(id="reader", name="Reader", email="reader@example.com", role="viewer")
    assert policy.can_access(access_view(command, view), actor) is True
    assert checked == ["project"] and history_calls == [("project", "plan", "goal")]
    assert command.model_dump(mode="json") == before


@pytest.mark.parametrize("family", ["revision", "phase"])
@pytest.mark.parametrize("changed", ["missing", "duplicate", "checkpoint", "input_pin", "parent",
    "result_missing", "result_invocation", "result_status", "result_refs", "result_duplicate_ref"])
def test_completed_plan_receipt_corruption_is_an_error_not_a_hidden_record(family, changed):
    policy, command, original, records, checked, history_calls = completed_plan_receipt(family)
    if changed == "missing":
        records.clear()
    elif changed == "duplicate":
        records.append(records[0])
    elif changed == "checkpoint":
        original.checkpoint = "different-original-checkpoint"
    elif changed == "input_pin":
        if family == "revision":
            original.source_manifest_id = "different-original-manifest"
        else:
            original.revision_hash = "sha256:" + "b" * 64
    elif changed == "parent":
        setattr(original, "parent_revision_id" if family == "revision" else "parent_phase_id", "different-parent")
    elif changed == "result_missing":
        command.result = None
    elif changed == "result_invocation":
        command.result.invocation_id = "another-invocation"
    elif changed == "result_status":
        command.result.status = "failed"
    elif changed == "result_refs":
        command.result.object_refs[0] = "private-other-resource"
    else:
        command.result.object_refs.append(command.result.object_refs[0])
    before = command.model_dump(mode="json")
    actor = UserProfile(id="reader", name="Reader", email="reader@example.com", role="viewer")
    with pytest.raises(PlatformApplicationError) as raised:
        policy.can_access(command, actor)
    assert raised.value.status_code == 502 and raised.value.code == "resource_receipt_invalid"
    assert "private" not in raised.value.message
    assert checked == ["project"] and history_calls == [("project", "plan", "goal")]
    assert command.model_dump(mode="json") == before
