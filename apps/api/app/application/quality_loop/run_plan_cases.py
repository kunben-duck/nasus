"""Internal command entry: every dispatch guard is produced from original records."""
from threading import Event

from .execution_work_guard import ExecutionWorkGuard
from .http_fixture_diagnostics import fixture_phase
from .run_plan_case_inputs import RunPlanCaseExecutionSelection, PreparedFixtureBoundCaseInputs
from .worker_threads import run_worker_thread
from ...domain.quality_loop.run_plan_case_execution import RunPlanCaseWorkLost


class RunPlanCaseApplicationService:
    def __init__(self, inputs, execution):
        self.inputs, self.execution = inputs, execution

    def read(self, scope):
        # Reuse only source proofs; independently read inputs around the original archive.
        with self.inputs.verified_read_session():
            require_access = self.inputs.historical_access_guard(scope)
            prepared = self.inputs.historical_inputs(scope)
            require_access()
            result = self.execution.read(prepared.plan, prepared.scope, require_access=require_access,
                **({"fixture_inputs": prepared.fixture_inputs} if isinstance(prepared, PreparedFixtureBoundCaseInputs) else {}))
            require_access()
            if self.inputs.historical_inputs(scope) != prepared:
                raise RunPlanCaseWorkLost("historical original case inputs changed during verification")
            require_access()
            return result

    def verify_finished_history(self, scope, expected):
        """Revalidate private archives once at the original job's finish fence."""
        with fixture_phase("case_finish_archive_verification"), self.inputs.verified_read_session():
            require_access = self.inputs.historical_access_guard(scope)
            prepared = self.inputs.historical_inputs(scope)
            require_access()
            history = self.execution.read(prepared.plan, prepared.scope, require_access=require_access,
                **({"fixture_inputs": prepared.fixture_inputs} if isinstance(prepared, PreparedFixtureBoundCaseInputs) else {}))
            if history != expected:
                raise RunPlanCaseWorkLost("original archived case history changed before job completion")
            require_access()

    async def execute(self, selection: RunPlanCaseExecutionSelection, *, invocation_id):
        stopped = Event()

        def require_work():
            if stopped.is_set():
                raise RunPlanCaseWorkLost("original case input preparation stopped; no execution may start")

        try:
            with fixture_phase("case_input_preparation"):
                prepared = await run_worker_thread(lambda: self.inputs.prepare(selection,
                    invocation_id=invocation_id, require_work=require_work), on_cancel=stopped.set)

            def current():
                require_work()
                self.inputs.require_current(prepared, require_work=require_work)
                require_work()

            authority = getattr(self.inputs, "require_live_authority", None)
            guard = (ExecutionWorkGuard(current, lambda: authority(prepared, require_work=require_work))
                     if callable(authority) else current)
            execute_prepared = getattr(self.execution, "execute_prepared", None)
            if isinstance(guard, ExecutionWorkGuard) and callable(execute_prepared):
                return await execute_prepared(prepared, require_current=guard)
            return await self.execution.execute(prepared.plan, prepared.scope, require_current=guard,
                **({"fixture_inputs": prepared.fixture_inputs} if isinstance(prepared, PreparedFixtureBoundCaseInputs) else {}))
        finally:
            stopped.set()
