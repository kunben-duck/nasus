from ..agent.image_plan_phases import ACTIVATE_PLAN_REVISION_TOOL, ImagePlanPhaseInput
from ...domain.system_image.build_authorization import ApprovedBuildBudget
from .actor_context import actor_scope
from .errors import PlatformApplicationError
from .invocation_resource_policy import resource_access_failure
from .tool_handlers.query_input import query_payload


class ImagePlanPhaseInvocationResourcePolicy:
    def __init__(self, application, previous):
        self.application, self.previous = application, previous

    def applies(self, invocation):
        return invocation.tool_id == ACTIVATE_PLAN_REVISION_TOOL or self.previous.applies(invocation)

    def can_access(self, invocation, actor):
        if invocation.tool_id != ACTIVATE_PLAN_REVISION_TOOL:
            return self.previous.can_access(invocation, actor)
        try:
            request = ImagePlanPhaseInput.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_at", "confirmed_by_user"}})
            with actor_scope(actor):
                self.application.require_access(request)
                if invocation.status == "completed":
                    matches = [item for item in self.application.history(request.project_id, request.root_plan_id, request.goal_id)
                               if item.phase.invocation_id == invocation.id]
                    if len(matches) != 1:
                        raise PlatformApplicationError("resource_receipt_invalid", "Original build phase could not be verified.", 502)
                    phase = matches[0].phase
                    if (phase.checkpoint, phase.revision_id, phase.revision_hash, phase.budget,
                            phase.parent_phase_id, phase.parent_phase_hash) != (
                            request.checkpoint(), request.revision_id, request.revision_hash,
                            ApprovedBuildBudget(**request.budget.model_dump()), request.parent_phase_id, request.parent_phase_hash):
                        raise PlatformApplicationError("resource_receipt_invalid", "Original build phase could not be verified.", 502)
                    result = invocation.result
                    if (result is None or result.invocation_id != invocation.id or result.status != "completed"
                            or len(result.object_refs) != 3 or set(result.object_refs) != {
                                f"build_plan_phase:{phase.phase_id}", f"build_plan:{phase.plan_id}", f"agent_goal:{phase.goal_id}"}):
                        raise PlatformApplicationError("resource_receipt_invalid", "Original build phase receipt could not be verified.", 502)
            return True
        except Exception as error:
            return resource_access_failure(invocation, error)

    def broadcast_view(self, invocation):
        if invocation.tool_id != ACTIVATE_PLAN_REVISION_TOOL:
            return self.previous.broadcast_view(invocation)
        return invocation.model_copy(update={"input_payload": {}, "result": None,
            "idempotency_key": None, "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)
