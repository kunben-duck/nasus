import asyncio
import logging
from datetime import timedelta

from ...application.quality_loop.http_fixture_jobs import HttpFixtureJobTarget
from .generation_runtime import TemporalGenerationRuntime
from .execution_activity_errors import execution_activity_error
from .nasus_http_fixture_workflow import NasusHttpFixtureWorkflow

logger = logging.getLogger(__name__)


class TemporalHttpFixtureRuntime(TemporalGenerationRuntime):
    @property
    def task_queue(self):
        return self.config.task_queue + "-http-fixture"

    async def start(self, invocation_id):
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.common import WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError

        client = await self._client()
        ident = "nasus-http-fixture:" + invocation_id
        try:
            await client.start_workflow(NasusHttpFixtureWorkflow.run, invocation_id, id=ident,
                task_queue=self.task_queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                rpc_timeout=timedelta(seconds=10))
        except WorkflowAlreadyStartedError:
            status = await client.get_workflow_handle(ident).describe(rpc_timeout=timedelta(seconds=10))
            return status.status == WorkflowExecutionStatus.RUNNING
        return True

    async def cancel(self, invocation_id):
        from temporalio.service import RPCError, RPCStatusCode

        client = await self._client()
        try:
            await client.get_workflow_handle("nasus-http-fixture:" + invocation_id).cancel(rpc_timeout=timedelta(seconds=10))
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise


def build_http_fixture_activities():
    from temporalio import activity
    from temporalio.exceptions import ApplicationError

    @activity.defn(name="run_http_fixture")
    async def run_http_fixture(invocation_id: str):
        from ...bootstrap import get_application_container
        stop = asyncio.Event()

        async def heartbeat():
            while not stop.is_set():
                activity.heartbeat({"invocation_id": invocation_id})
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(heartbeat())
        try:
            try:
                return await get_application_container().http_fixture_jobs.run(invocation_id)
            except Exception as error:
                raise execution_activity_error(error, prefix="HttpFixture") from None
        finally:
            stop.set()
            await task

    @activity.defn(name="fail_http_fixture")
    async def fail_http_fixture(invocation_id: str):
        from ...bootstrap import get_application_container
        try:
            return await get_application_container().http_fixture_jobs.fail(invocation_id)
        except Exception:
            raise ApplicationError("Fixture termination deferred until the original worker is fenced.",
                type="HttpFixtureTerminationFailure") from None

    return [run_http_fixture, fail_http_fixture]


async def reconcile_http_fixtures_once(runtime, repository, *, jobs):
    for cancelling in (True, False):
        after_id = None
        query = repository.pending_cancellations if cancelling else repository.pending
        while True:
            page = await asyncio.to_thread(query, after_id=after_id)
            if not page:
                break
            for invocation_id, project_id in page:
                try:
                    if cancelling:
                        await runtime.cancel(invocation_id)
                        await asyncio.to_thread(repository.cancellation_delivered,
                            HttpFixtureJobTarget(project_id=project_id, invocation_id=invocation_id))
                    else:
                        await jobs.deliver(invocation_id)
                except Exception:
                    logger.warning("Fixture workflow delivery deferred for %s", invocation_id)
            after_id = page[-1][0]


async def reconcile_http_fixtures(runtime):
    from ...bootstrap import get_application_container
    jobs = get_application_container().http_fixture_jobs
    repository = jobs.repository
    while True:
        try:
            await reconcile_http_fixtures_once(runtime, repository, jobs=jobs)
        except Exception:
            logger.warning("Fixture workflow reconciliation deferred")
        await asyncio.sleep(5)
