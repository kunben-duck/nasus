"""Historical inspection receipts reauthorize originals, never repeat Docker work."""
from pydantic import ValidationError

from ..quality_loop.run_plan_environments import RunPlanEnvironmentQuery, RUN_PLAN_ENVIRONMENT_QUERY_TOOL
from .errors import PlatformApplicationError
from .run_plan_receipts import RunPlanReceiptAccess
from .tool_handlers.query_input import query_payload


class RunPlanEnvironmentReceiptAccess(RunPlanReceiptAccess):
    @staticmethod
    def applies(invocation):
        return invocation.tool_id == RUN_PLAN_ENVIRONMENT_QUERY_TOOL

    @staticmethod
    def _scope(invocation):
        try:
            return RunPlanEnvironmentQuery.model_validate(query_payload(invocation.input_payload))
        except ValidationError as exc:
            raise PlatformApplicationError("target_receipt_invalid", "Original target inspection scope cannot be verified.", 409) from exc

    @staticmethod
    def _receipt(invocation):
        result = invocation.result
        receipt = result.run_plan_environment if result else None
        if invocation.status != "completed":
            if receipt is not None:
                raise PlatformApplicationError("target_receipt_invalid", "Incomplete target query cannot contain an observation.", 502)
            return None
        if (result is None or result.invocation_id != invocation.id or result.status != "completed"
                or not isinstance(receipt, dict)):
            raise PlatformApplicationError("target_receipt_invalid", "Original target observation cannot be verified.", 502)
        return receipt

    def require_access(self, invocation):
        if self.applies(invocation):
            query = self._scope(invocation)
            receipt = self._receipt(invocation)
            operation = getattr(self.plans, "authorize_historical_receipt" if receipt is not None
                else "require_receipt_inputs_access", None)
            if not callable(operation):
                raise PlatformApplicationError("target_receipt_unavailable", "Original target authorization is unavailable.", 503)
            if receipt is not None:
                self._authorize(operation, query, receipt)
            else:
                self._authorize(operation, query)

    def require_batch_access(self, invocations):
        scopes, receipts = {}, []
        for invocation in invocations:
            if self.applies(invocation):
                query = self._scope(invocation)
                scopes[tuple(query.model_dump(mode="json").values())] = query
                receipt = self._receipt(invocation)
                if receipt is not None:
                    receipts.append((query, receipt))
        if receipts:
            operation = getattr(self.plans, "authorize_historical_receipts", None)
            if len(receipts) > 128 or not callable(operation):
                raise PlatformApplicationError("target_receipt_unavailable", "Original target authorization is unavailable.", 503)
            self._authorize(operation, tuple(receipts))
        if scopes:
            operation = getattr(self.plans, "require_receipt_inputs_access_many", None)
            if not callable(operation):
                raise PlatformApplicationError("target_receipt_unavailable", "Original target authorization is unavailable.", 503)
            self._authorize(operation, tuple(scopes.values()))

    def broadcast_view(self, invocation):
        value = super().broadcast_view(invocation)
        if self.applies(invocation):
            return value.model_copy(update={"summary": f"Target environment query status: {invocation.status}."})
        return value
