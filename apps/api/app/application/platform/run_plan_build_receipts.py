"""Protect original build selections, including canonical acknowledgement recovery."""
import json

from pydantic import ValidationError

from ..quality_loop.run_plan_build_inputs import RunPlanBuildSelection, RunPlanBuildQuery
from ...domain.quality_loop.run_plan_build import RUN_PLAN_BUILD_TOOL, RUN_PLAN_BUILD_PREVIEW_TOOL, RUN_PLAN_BUILD_QUERY_TOOL
from .errors import PlatformApplicationError
from .run_plan_receipts import RunPlanReceiptAccess


RUN_PLAN_BUILD_RECEIPT_TOOLS = frozenset({RUN_PLAN_BUILD_TOOL, RUN_PLAN_BUILD_PREVIEW_TOOL, RUN_PLAN_BUILD_QUERY_TOOL})


class RunPlanBuildReceiptAccess(RunPlanReceiptAccess):
    @staticmethod
    def applies(invocation):
        return invocation.tool_id in RUN_PLAN_BUILD_RECEIPT_TOOLS

    @staticmethod
    def _scope(invocation):
        model = RunPlanBuildQuery if invocation.tool_id == RUN_PLAN_BUILD_QUERY_TOOL else RunPlanBuildSelection
        try:
            return model.model_validate({key: invocation.input_payload[key] for key in model.model_fields if key in invocation.input_payload})
        except ValidationError as exc:
            raise PlatformApplicationError("run_plan_build_receipt_invalid", "Original build receipt scope cannot be verified.", 409) from exc

    def require_access(self, invocation):
        if self.applies(invocation):
            scope = self._scope(invocation)
            operation = getattr(self.plans, "require_receipt_inputs_access", None)
            if not callable(operation):
                raise PlatformApplicationError("run_plan_build_receipt_unavailable", "Original build receipt authorization is unavailable.", 503)
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
            raise PlatformApplicationError("run_plan_build_receipt_unavailable", "Original build receipt authorization is unavailable.", 503)
        self._authorize(operation, tuple(scopes.values()))
