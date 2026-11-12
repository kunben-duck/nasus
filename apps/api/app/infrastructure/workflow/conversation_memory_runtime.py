import asyncio
import logging
from datetime import timedelta

from .nasus_memory_workflow import NasusConversationMemoryWorkflow
from .context_retrieval_runtime import TemporalContextRetrievalRuntime
from ..llm.conversation_token_budget import memory_enabled
from ..persistence.db_models import UserIdentityRecord
from ..persistence.unit_of_work import session_scope
from ..platform.account_identity import SQLAlchemyAccountIdentityService
from ...application.platform.actor_context import actor_scope

logger = logging.getLogger(__name__)


class TemporalConversationMemoryRuntime(TemporalContextRetrievalRuntime):
    @property
    def task_queue(self):
        return self.config.task_queue + "-conversation-memory"

    async def start(self, job_id):
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.common import WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError
        client = await self._client()
        ident = "nasus-conversation-memory:" + job_id
        try:
            await client.start_workflow(NasusConversationMemoryWorkflow.run, job_id,
                id=ident, task_queue=self.task_queue, rpc_timeout=timedelta(seconds=10),
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
        except WorkflowAlreadyStartedError:
            description = await client.get_workflow_handle(ident).describe(rpc_timeout=timedelta(seconds=10))
            return description.status == WorkflowExecutionStatus.RUNNING
        return True

    async def cancel(self, job_id):
        from temporalio.service import RPCError, RPCStatusCode
        client = await self._client()
        try:
            await client.get_workflow_handle("nasus-conversation-memory:" + job_id).cancel(
                rpc_timeout=timedelta(seconds=10))
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise


async def execute_memory_job(service, job_id):
    job = service.jobs.get(job_id)
    actor = job.get("actor")
    if not actor:
        claimed = service.jobs.claim(job_id)
        if claimed:
            service.jobs.fail(job_id, "actor_unavailable", claimed["attempts"])
        return service.jobs.get(job_id)
    # Refresh account status and role. Never trust a queued actor profile as authority.
    with session_scope() as session:
        user = session.get(UserIdentityRecord, actor["id"])
        profile = SQLAlchemyAccountIdentityService._profile(user) if user and user.status == "active" else None
    if profile is None:
        claimed = service.jobs.claim(job_id)
        if claimed:
            service.jobs.fail(job_id, "actor_unavailable", claimed["attempts"])
        return service.jobs.get(job_id)
    with actor_scope(profile):
        return await service.run(job_id)


def build_memory_activities():
    from temporalio import activity

    @activity.defn(name="compact_conversation_memory")
    async def compact_conversation_memory(job_id: str):
        from ...bootstrap import get_application_container
        service = get_application_container().conversation_memory
        stop = asyncio.Event()

        async def heartbeat():
            while not stop.is_set():
                activity.heartbeat(job_id)
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(heartbeat())
        try:
            while True:
                result = await execute_memory_job(service, job_id)
                if result["status"] in {"completed", "failed", "superseded"}:
                    return {"status": result["status"], "checkpoint_id": result.get("checkpoint_id")}
                await asyncio.sleep(1)
        finally:
            stop.set()
            await task

    return [compact_conversation_memory]


async def reconcile_memory_jobs(runtime):
    from ...bootstrap import get_application_container
    while True:
        if memory_enabled():
            try:
                repository = get_application_container().conversation_memory.jobs
                for job_id in await asyncio.to_thread(repository.pending):
                    try:
                        if not await runtime.start(job_id):
                            claimed = await asyncio.to_thread(repository.claim, job_id)
                            if claimed:
                                await asyncio.to_thread(repository.fail, job_id, "workflow_ended", claimed["attempts"])
                    except Exception:
                        logger.warning("Conversation memory dispatch deferred for %s", job_id)
            except Exception:
                logger.warning("Conversation memory reconciliation deferred")
        await asyncio.sleep(3)
