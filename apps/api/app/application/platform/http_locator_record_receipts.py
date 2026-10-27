from pydantic import ValidationError

from ..quality_loop.environment_observation_records import EnvironmentRecordQuery
from ..quality_loop.run_plan_locators import RunPlanLocatorQuery
from ...domain.quality_loop.http_locator_record import LOCATOR_RECORD_TOOL, LOCATOR_RECORD_TOOLS
from .environment_record_receipts import EnvironmentRecordReceiptAccess
from .errors import PlatformApplicationError
from .tool_handlers.query_input import query_payload


class HttpLocatorRecordReceiptAccess(EnvironmentRecordReceiptAccess):
    @staticmethod
    def applies(invocation):
        return invocation.tool_id in LOCATOR_RECORD_TOOLS

    @staticmethod
    def _scope(invocation):
        model = RunPlanLocatorQuery if invocation.tool_id == LOCATOR_RECORD_TOOL else EnvironmentRecordQuery
        try:
            return model.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except ValidationError as exc:
            raise PlatformApplicationError("locator_record_invalid", "Original locator scope cannot be verified.", 409) from exc

    @staticmethod
    def _receipt(invocation):
        result = invocation.result
        receipt = result.run_plan_locator_record if result else None
        if invocation.status != "completed":
            if receipt is not None:
                raise PlatformApplicationError("locator_record_invalid", "Incomplete command cannot contain locator evidence.", 502)
            return None
        if (result is None or result.invocation_id != invocation.id or result.status != "completed" or type(receipt) is not dict
                or invocation.tool_id == LOCATOR_RECORD_TOOL and (type(receipt.get("metadata")) is not dict
                    or receipt["metadata"].get("invocation_id") != invocation.id)):
            raise PlatformApplicationError("locator_record_invalid", "Original locator receipt cannot be verified.", 502)
        return receipt

    def broadcast_view(self, invocation):
        value = super().broadcast_view(invocation)
        if self.applies(invocation):
            return value.model_copy(update={"summary": f"Locator evidence command status: {invocation.status}."})
        return value
