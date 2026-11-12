"""Compose the guarded original-input path; no public command or Temporal replacement."""
import os

from ...application.quality_loop.execution_work_guard import ExecutionWorkGuard
from ...application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
from ...application.quality_loop.run_plan_case_fixtures import RunPlanCaseFixtureApplicationService
from ...application.quality_loop.run_plan_case_inputs import PreparedRunPlanCaseInputs, RunPlanCaseInputApplicationService
from ...application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
from ...application.quality_loop.worker_threads import run_worker_thread
from ...domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from ..persistence.run_plan_case_execution_repository import PostgresRunPlanCaseExecutionRepository
from ..storage.run_plan_case_artifacts import RunPlanCaseArtifacts
from .http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from .owned_target_http import ConfiguredOwnedTargetHttpRunner


class ConfiguredRunPlanCaseWorker:
    def __init__(self, journal, verifier, artifacts, *, node_executable):
        self.journal, self.verifier, self.artifacts, self.node_executable = journal, verifier, artifacts, node_executable

    async def _configured_worker(self, check):
        # Optional target configuration must not prevent unrelated API startup.
        # Validate the executable before acquiring any case dispatch slot.
        def configured():
            check()
            return ConfiguredOwnedTargetHttpRunner(node_executable=self.node_executable)
        runner = await run_worker_thread(configured)
        return RunPlanCaseExecutionApplicationService(runner, self.verifier, self.journal, self.artifacts)

    async def execute(self, plan, scope, *, require_current, fixture_inputs=None):
        worker = await self._configured_worker(require_current)
        return await worker.execute(plan, scope, require_current=require_current,
            **({"fixture_inputs": fixture_inputs} if fixture_inputs is not None else {}))

    async def execute_prepared(self, prepared, *, require_current):
        if not isinstance(prepared, PreparedRunPlanCaseInputs) or not isinstance(require_current, ExecutionWorkGuard):
            raise RunPlanCaseExecutionInvalid("case runner configuration requires prepared original inputs and live authority")
        worker = await self._configured_worker(require_current.poll)
        return await worker.execute_prepared(prepared, require_current=require_current)

    def read(self, plan, scope, *, require_access, fixture_inputs=None):
        worker = RunPlanCaseExecutionApplicationService(None, self.verifier, self.journal, self.artifacts)
        return worker.read(plan, scope, require_access=require_access,
            **({"fixture_inputs": fixture_inputs} if fixture_inputs is not None else {}))


def compose_run_plan_cases(original_inputs, environments, locators, fixture_jobs, health, storage):
    journal, verifier = PostgresRunPlanCaseExecutionRepository(), OwnedHttpFixtureObservationVerifier()
    prerequisites = RunPlanCaseFixtureApplicationService(fixture_jobs, verifier)
    inputs = RunPlanCaseInputApplicationService(original_inputs, environments, locators, prerequisites, health, journal)
    worker = ConfiguredRunPlanCaseWorker(journal, verifier, RunPlanCaseArtifacts(storage),
        node_executable=os.environ.get("NASUS_HTTP_FIXTURE_NODE", ""))
    return RunPlanCaseApplicationService(inputs, worker)
