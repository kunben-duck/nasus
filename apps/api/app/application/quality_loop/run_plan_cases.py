"""Internal command entry: every dispatch guard is produced from original records."""
from threading import Event

from .run_plan_case_inputs import RunPlanCaseExecutionSelection, PreparedFixtureBoundCaseInputs
from .worker_threads import run_worker_thread
from ...domain.quality_loop.run_plan_case_execution import RunPlanCaseWorkLost


class RunPlanCaseApplicationService:
    def __init__(self, inputs, execution):
        self.inputs, self.execution = inputs, execution

    def read(self, scope):
        prepared = self.inputs.historical_inputs(scope)
        def require_access():
            current = self.inputs.historical_inputs(scope)
            if current != prepared:
                raise RunPlanCaseWorkLost("historical original case inputs changed during verification")
        return self.execution.read(prepared.plan, prepared.scope, require_access=require_access,
            **({"fixture_inputs": prepared.fixture_inputs} if isinstance(prepared, PreparedFixtureBoundCaseInputs) else {}))

    async def execute(self, selection: RunPlanCaseExecutionSelection, *, invocation_id):
        stopped = Event()

        def require_work():
            if stopped.is_set():
                raise RunPlanCaseWorkLost("original case input preparation stopped; no execution may start")

        try:
            prepared = await run_worker_thread(lambda: self.inputs.prepare(selection,
                invocation_id=invocation_id, require_work=require_work), on_cancel=stopped.set)

            def current():
                require_work()
                self.inputs.require_current(prepared, require_work=require_work)
                require_work()

            return await self.execution.execute(prepared.plan, prepared.scope, require_current=current,
                **({"fixture_inputs": prepared.fixture_inputs} if isinstance(prepared, PreparedFixtureBoundCaseInputs) else {}))
        finally:
            stopped.set()
