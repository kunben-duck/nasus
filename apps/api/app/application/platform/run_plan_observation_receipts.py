import json

from pydantic import ValidationError

from ..quality_loop.run_plan_observation_records import (
    ObservationRecordRequest, ObservationRecordQuery, OBSERVATION_RECORD_QUERY_TOOL, OBSERVATION_RECORD_TOOLS,
)
from .errors import PlatformApplicationError
from .run_plan_receipts import RunPlanReceiptAccess


class RunPlanObservationReceiptAccess(RunPlanReceiptAccess):
    @staticmethod
    def applies(invocation):
        return invocation.tool_id in OBSERVATION_RECORD_TOOLS

    @staticmethod
    def _scope(invocation):
        model = ObservationRecordQuery if invocation.tool_id == OBSERVATION_RECORD_QUERY_TOOL else ObservationRecordRequest
        try:
            return model.model_validate({key: invocation.input_payload[key] for key in model.model_fields if key in invocation.input_payload})
        except ValidationError as exc:
            raise PlatformApplicationError("observation_receipt_invalid", "Original observation scope cannot be verified.", 409) from exc

    def require_access(self, invocation):
        if self.applies(invocation):
            self._authorize(self.plans.require_receipt_inputs_access, self._scope(invocation))

    def require_batch_access(self, invocations):
        scopes = {}
        for invocation in invocations:
            if self.applies(invocation):
                scope = self._scope(invocation)
                scopes[json.dumps(scope.model_dump(mode="json"), sort_keys=True)] = scope
        if scopes:
            self._authorize(self.plans.require_receipt_inputs_access_many, tuple(scopes.values()))
