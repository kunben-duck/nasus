from ..system_image.build_plan_revisions import REVISE_PLAN_TOOL, BuildPlanRevisionInput
from .actor_context import actor_scope
from .errors import PlatformApplicationError
from .invocation_resource_policy import resource_access_failure
from .tool_handlers.query_input import query_payload


class BuildPlanRevisionInvocationResourcePolicy:
    def __init__(self, application, previous):
        self.application, self.previous = application, previous

    def applies(self, invocation):
        return invocation.tool_id == REVISE_PLAN_TOOL or self.previous.applies(invocation)

    def can_access(self, invocation, actor):
        if invocation.tool_id != REVISE_PLAN_TOOL:
            return self.previous.can_access(invocation, actor)
        try:
            body = {key: value for key, value in query_payload(invocation.input_payload).items()
                    if key not in {"confirmed_at", "confirmed_by_user"}}
            request = BuildPlanRevisionInput.model_validate(body)
            with actor_scope(actor):
                self.application.require_access(request)
                if invocation.status == "completed":
                    records = self.application.history(request.project_id, request.root_plan_id, request.goal_id)
                    matches = [item for item in records if item.revision.invocation_id == invocation.id]
                    if len(matches) != 1:
                        raise PlatformApplicationError("resource_receipt_invalid", "Original plan revision could not be verified.", 502)
                    revision = matches[0].revision
                    if (revision.checkpoint, revision.from_plan_id, revision.from_plan_digest,
                            revision.source_manifest_id, revision.parent_revision_id, revision.parent_revision_hash) != (
                            request.checkpoint(), request.from_plan_id, request.from_plan_digest,
                            request.source_manifest_id, request.parent_revision_id, request.parent_revision_hash):
                        raise PlatformApplicationError("resource_receipt_invalid", "Original plan revision could not be verified.", 502)
                    result = invocation.result
                    if (result is None or result.invocation_id != invocation.id or result.status != "completed"
                            or len(result.object_refs) != 2 or set(result.object_refs) != {
                                f"build_plan_revision:{revision.revision_id}", f"build_plan:{revision.plan_id}"}):
                        raise PlatformApplicationError("resource_receipt_invalid", "Original plan revision receipt could not be verified.", 502)
            return True
        except Exception as error:
            return resource_access_failure(invocation, error)

    def broadcast_view(self, invocation):
        if invocation.tool_id != REVISE_PLAN_TOOL:
            return self.previous.broadcast_view(invocation)
        return invocation.model_copy(update={"input_payload": {}, "result": None,
            "idempotency_key": None, "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)
