from pydantic import ValidationError

from ..quality_loop.environment_observation_records import EnvironmentRecordQuery
from ..quality_loop.run_plan_environments import RunPlanEnvironmentQuery
from ...domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_TOOL, ENVIRONMENT_RECORD_TOOLS
from .errors import PlatformApplicationError
from .run_plan_receipts import RunPlanReceiptAccess
from .tool_handlers.query_input import query_payload


class EnvironmentRecordReceiptAccess(RunPlanReceiptAccess):
    @staticmethod
    def applies(invocation):
        return invocation.tool_id in ENVIRONMENT_RECORD_TOOLS

    @staticmethod
    def _scope(invocation):
        model = RunPlanEnvironmentQuery if invocation.tool_id == ENVIRONMENT_RECORD_TOOL else EnvironmentRecordQuery
        try:
            return model.model_validate({key: value for key, value in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except ValidationError as exc:
            raise PlatformApplicationError("environment_record_invalid", "Original environment record scope cannot be verified.", 409) from exc

    @staticmethod
    def _receipt(invocation):
        result = invocation.result
        receipt = result.run_plan_environment_record if result else None
        if invocation.status != "completed":
            if receipt is not None:
                raise PlatformApplicationError("environment_record_invalid", "Incomplete command cannot contain environment evidence.", 502)
            return None
        if (result is None or result.invocation_id != invocation.id or result.status != "completed" or type(receipt) is not dict
                or invocation.tool_id == ENVIRONMENT_RECORD_TOOL and (type(receipt.get("metadata")) is not dict
                    or receipt["metadata"].get("invocation_id") != invocation.id)):
            raise PlatformApplicationError("environment_record_invalid", "Original environment receipt cannot be verified.", 502)
        return receipt

    def require_access(self, invocation):
        if self.applies(invocation):
            self._authorize(self.plans.authorize_receipts, ((self._scope(invocation), self._receipt(invocation)),))

    def require_batch_access(self, invocations):
        values = tuple((self._scope(item), self._receipt(item)) for item in invocations if self.applies(item))
        if values:
            self._authorize(self.plans.authorize_receipts, values)

    def broadcast_view(self, invocation):
        value = super().broadcast_view(invocation)
        if self.applies(invocation):
            return value.model_copy(update={"summary": f"Environment evidence command status: {invocation.status}."})
        return value
