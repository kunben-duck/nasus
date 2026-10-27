"""Reauthorize original static evidence; history never reparses or dispatches."""
from pydantic import ValidationError

from ..quality_loop.run_plan_locators import RUN_PLAN_LOCATOR_QUERY_TOOL, RunPlanLocatorQuery
from .errors import PlatformApplicationError
from .run_plan_environment_receipts import RunPlanEnvironmentReceiptAccess
from .tool_handlers.query_input import query_payload


class RunPlanLocatorReceiptAccess(RunPlanEnvironmentReceiptAccess):
    @staticmethod
    def applies(invocation):
        return invocation.tool_id == RUN_PLAN_LOCATOR_QUERY_TOOL

    @staticmethod
    def _scope(invocation):
        try:
            return RunPlanLocatorQuery.model_validate(query_payload(invocation.input_payload))
        except ValidationError as exc:
            raise PlatformApplicationError("locator_receipt_invalid", "Original locator query cannot be verified.", 409) from exc

    @staticmethod
    def _receipt(invocation):
        result = invocation.result
        value = result.run_plan_locators if result else None
        if invocation.status != "completed":
            if value is not None:
                raise PlatformApplicationError("locator_receipt_invalid", "Incomplete query cannot contain locator evidence.", 502)
            return None
        if (result is None or result.invocation_id != invocation.id or result.status != "completed" or type(value) is not dict):
            raise PlatformApplicationError("locator_receipt_invalid", "Original static locator evidence is unavailable.", 502)
        return value

    def broadcast_view(self, invocation):
        value = super().broadcast_view(invocation)
        if self.applies(invocation):
            return value.model_copy(update={"summary": f"Static locator query status: {invocation.status}."})
        return value
