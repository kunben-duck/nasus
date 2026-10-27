"""Keep a missing-code intent on its original goal, without a mutable build."""
from ...domain.agent.plan_policy import AgentPlanPolicyViolation
from ...domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep
from ...domain.system_image.build_plan import BuildTarget
from ...domain.system_image.source_snapshots import snapshot_digest
from ..system_image.build_preparation import BuildSourceWaitInput


WAIT_REF = "build_source_wait_digest:"
WAIT_REASON = "missing_captured_code"
WAIT_TOOL = "query.system_image.status"


def query_payload(payload):
    from ..platform.tool_handlers.query_input import query_payload as strip_coordination
    return strip_coordination(payload)


def wait_refs(request):
    return [f"project:{request.project_id}", f"build_target:{request.target.target_baseline_id}",
            WAIT_REF + snapshot_digest(request.model_dump(mode="json"))]


class AgentSourceBuildWaitApplicationService:
    def __init__(self, inputs, plans, invocations):
        self.inputs, self.plans, self.invocations = inputs, plans, invocations

    def verify(self, request):
        if request.target.project_id != request.project_id:
            raise ValueError("Waiting target scope changed.")
        scope = self.plans.authorization.scope(request.project_id)
        self.plans.require_target_current(BuildTarget(**request.target.model_dump()))
        self.plans.authorization.require_current(scope)

    def proposal(self, conversation, objective, mode):
        request = self.inputs.waiting_request(conversation.project_id, conversation.version_id, objective, mode)
        self.verify(request)
        return AgentGoalProposal(goal_template="system_image_build", title="Prepare a source-pinned system image",
            summary="Waiting for captured code; optional requirements and tests can be added later.",
            goal_description="Keep the original project and image target while waiting for required inputs.",
            initial_tool_input=request.model_dump(mode="json"), target_refs=wait_refs(request),
            query_keys=[["system-image", request.project_id]], estimated_steps=12,
            kickoff_message="I will keep this goal and its original image target. Add and capture the code sources, then continue this goal; capture does not authorize structure, model calls or publication.")

    def compile(self, proposal):
        try:
            request = BuildSourceWaitInput.model_validate(proposal.initial_tool_input)
            if (proposal.goal_template != "system_image_build" or proposal.planned_tools or proposal.initial_tool_id
                    or proposal.target_refs != wait_refs(request)):
                raise ValueError("Waiting intent changed.")
            self.verify(request)
            return [ToolPlanStep(WAIT_TOOL, {"project_id": request.project_id,
                "build_input_request": request.model_dump(mode="json")},
                reason="Read project status and retain the original target while code capture is missing.")]
        except Exception as exc:
            raise AgentPlanPolicyViolation("build_input_wait_scope_changed", "The original missing-input intent could not be verified.") from exc

    def original(self, goal, *, completed=False):
        try:
            steps = [step for step in goal.steps if step.phase == "acting"
                     and "build_input_request" in step.tool_input_payload]
            if len(steps) != 1 or steps[0].selected_tool_id != WAIT_TOOL:
                raise ValueError("Waiting intent needs its one original status command.")
            step = steps[0]
            payload = query_payload(step.tool_input_payload)
            request = BuildSourceWaitInput.model_validate(payload["build_input_request"])
            if (payload != {"project_id": request.project_id, "build_input_request": request.model_dump(mode="json")}
                    or goal.project_id != request.project_id or goal.goal_template != "system_image_build"
                    or len(goal.target_refs) != len(set(goal.target_refs))
                    or not all(ref in goal.target_refs for ref in wait_refs(request))
                    or len([ref for ref in goal.target_refs if ref.startswith(WAIT_REF)]) != 1):
                raise ValueError("Waiting goal scope changed.")
            self.verify(request)
            if completed:
                invocation = self.invocations.get_tool_invocation(step.tool_invocation_id)
                if (invocation.id != step.tool_invocation_id or invocation.conversation_id != goal.conversation_id
                        or invocation.tool_id != WAIT_TOOL or invocation.status != "completed" or invocation.result is None
                        or invocation.result.status != "completed" or invocation.input_payload.get("agent_goal_id") != goal.id
                        or invocation.result.invocation_id != invocation.id
                        or invocation.result.object_refs != [f"project:{request.project_id}"]
                        or query_payload(invocation.input_payload) != payload):
                    raise ValueError("Waiting status receipt changed.")
            return request, step
        except Exception as exc:
            raise AgentPlanPolicyViolation("build_input_wait_scope_changed", "The original waiting target and status command could not be verified.") from exc

    def continuation(self, goal):
        request, _ = self.original(goal, completed=True)
        if goal.target_refs != wait_refs(request):
            raise AgentPlanPolicyViolation("build_input_wait_scope_changed", "This waiting intent has already fixed its source inputs.")
        return self.inputs.prepare_fixed(request)
