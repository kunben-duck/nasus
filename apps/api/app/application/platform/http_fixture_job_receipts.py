from ...domain.quality_loop.http_fixture_command import FIXTURE_JOB_TOOLS
from .run_plan_receipts import RunPlanReceiptAccess


class HttpFixtureJobReceiptAccess(RunPlanReceiptAccess):
    @staticmethod
    def applies(invocation):
        return invocation.tool_id in FIXTURE_JOB_TOOLS

    def require_access(self, invocation):
        if self.applies(invocation):
            self._authorize(self.plans.authorize_receipts, (invocation,))

    def require_batch_access(self, invocations):
        selected = tuple(item for item in invocations if self.applies(item))
        if selected:
            self._authorize(self.plans.authorize_receipts, selected)

    def broadcast_view(self, invocation):
        value = super().broadcast_view(invocation)
        if self.applies(invocation):
            return value.model_copy(update={"summary": f"Fixture operation command status: {invocation.status}."})
        return value
