"""Compose the guarded original-input path; no public command or Temporal replacement."""
import os

from ...application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
from ...application.quality_loop.run_plan_case_fixtures import RunPlanCaseFixtureApplicationService
from ...application.quality_loop.run_plan_case_inputs import RunPlanCaseInputApplicationService
from ...application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
from ...application.quality_loop.worker_threads import run_worker_thread
from ..persistence.run_plan_case_execution_repository import PostgresRunPlanCaseExecutionRepository
from ..storage.run_plan_case_artifacts import RunPlanCaseArtifacts
from .http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from .owned_target_http import ConfiguredOwnedTargetHttpRunner


class ConfiguredRunPlanCaseWorker:
    def __init__(self, journal, verifier, artifacts, *, node_executable):
        self.journal, self.verifier, self.artifacts, self.node_executable = journal, verifier, artifacts, node_executable

    async def execute(self, plan, scope, *, require_current, fixture_inputs=None):
        # Optional target configuration must not prevent unrelated API startup.
        # Validate the executable before acquiring any case dispatch slot.
        def configured():
            require_current()
            return ConfiguredOwnedTargetHttpRunner(node_executable=self.node_executable)
        runner = await run_worker_thread(configured)
        worker = RunPlanCaseExecutionApplicationService(runner, self.verifier, self.journal, self.artifacts)
        return await worker.execute(plan, scope, require_current=require_current,
            **({"fixture_inputs": fixture_inputs} if fixture_inputs is not None else {}))

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
