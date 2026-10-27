"""Original native-build authorization, independent of today's operator config."""
import json

from pydantic import ValidationError

from ..quality_loop.native_build_inputs import (
    NATIVE_BUILD_TOOL, NATIVE_BUILD_PREVIEW_TOOL, NATIVE_BUILD_QUERY_TOOL, NATIVE_BUILD_CANCEL_TOOL,
    NativeBuildSelection, NativeBuildCommand, NativeBuildTarget,
)
from .errors import PlatformApplicationError
from .run_plan_build_receipts import RunPlanBuildReceiptAccess


NATIVE_BUILD_RECEIPT_TOOLS = frozenset({
    NATIVE_BUILD_TOOL, NATIVE_BUILD_PREVIEW_TOOL, NATIVE_BUILD_QUERY_TOOL, NATIVE_BUILD_CANCEL_TOOL,
})


class NativeBuildReceiptAccess(RunPlanBuildReceiptAccess):
    @staticmethod
    def applies(invocation):
        return invocation.tool_id in NATIVE_BUILD_RECEIPT_TOOLS

    @staticmethod
    def _scope(invocation):
        model = (NativeBuildCommand if invocation.tool_id == NATIVE_BUILD_TOOL else
                 NativeBuildSelection if invocation.tool_id == NATIVE_BUILD_PREVIEW_TOOL else NativeBuildTarget)
        try:
            return model.model_validate({key: invocation.input_payload[key]
                for key in model.model_fields if key in invocation.input_payload})
        except ValidationError as exc:
            raise PlatformApplicationError("native_build_receipt_invalid", "Original build receipt scope cannot be verified.", 409) from exc

    def require_access(self, invocation):
        if self.applies(invocation):
            scope = self._scope(invocation)
            operation = getattr(self.plans, "require_receipt_inputs_access", None)
            if not callable(operation):
                raise PlatformApplicationError("native_build_receipt_unavailable", "Original build receipt authorization is unavailable.", 503)
            self._authorize(operation, scope)

    def require_batch_access(self, invocations):
        scopes = {}
        for invocation in invocations:
            if self.applies(invocation):
                scope = self._scope(invocation)
                key = (type(scope).__name__, json.dumps(scope.model_dump(mode="json"), sort_keys=True))
                scopes[key] = scope
        if not scopes:
            return
        operation = getattr(self.plans, "require_receipt_inputs_access_many", None)
        if len(scopes) > 128 or not callable(operation):
            raise PlatformApplicationError("native_build_receipt_unavailable", "Original build receipt authorization is unavailable.", 503)
        self._authorize(operation, tuple(scopes.values()))

    def broadcast_view(self, invocation):
        projected = super().broadcast_view(invocation)
        if not self.applies(invocation):
            return projected
        return projected.model_copy(update={"summary": f"Native build command status: {invocation.status}."}, deep=True)
