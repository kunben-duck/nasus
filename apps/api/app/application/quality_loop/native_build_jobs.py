import asyncio
import logging
from typing import Protocol
from uuid import uuid4

from ..platform.actor_context import actor_scope
from ..platform.errors import PlatformApplicationError
from .generation_work_lease import GenerationLeaseLost, run_with_generation_lease
from ...domain.quality_loop.native_build import NativeBuildExecutionFailed

logger = logging.getLogger(__name__)


class NativeBuildWorkflowPort(Protocol):
    async def start(self, invocation_id): ...
    async def cancel(self, invocation_id): ...


class NativeBuildJobApplicationService:
    def __init__(self, application, repository, workflow: NativeBuildWorkflowPort):
        self.application, self.repository, self.workflow = application, repository, workflow

    async def dispatch(self, request, invocation_id):
        access = await asyncio.to_thread(self.application._access, request.project_id, execute=True)
        await asyncio.to_thread(self.repository.require_running, request, invocation_id, access.actor_id)
        await self.workflow.start(invocation_id)

    async def run(self, invocation_id):
        request, status = await asyncio.to_thread(self.repository.command, invocation_id)
        if status != "running":
            return status
        lease = await asyncio.to_thread(self.repository.claim_lease, request.project_id, invocation_id, uuid4().hex)

        async def execute(require_work):
            try:
                command, actor = await asyncio.to_thread(self.repository.execution, invocation_id)
                with actor_scope(actor):
                    await self.application.execute(command, invocation_id=invocation_id, lease=lease, require_work=require_work)
                return await asyncio.to_thread(self.repository.finish, request.project_id, invocation_id, "completed", lease=lease)
            except (ValueError, KeyError, PermissionError, NativeBuildExecutionFailed, PlatformApplicationError):
                return await self.fail(invocation_id, lease=lease)

        try:
            return await run_with_generation_lease(self.repository, lease, execute)
        except asyncio.CancelledError:
            try:
                await asyncio.to_thread(self.repository.finish, request.project_id, invocation_id, "cancelled", lease=lease)
            except GenerationLeaseLost:
                pass
            raise
        except GenerationLeaseLost:
            _, terminal = await asyncio.to_thread(self.repository.command, invocation_id)
            if terminal != "running":
                return terminal
            raise
        finally:
            try:
                await asyncio.to_thread(self.repository.release_lease, lease)
            except Exception:
                logger.warning("Native build lease release deferred to expiry")

    async def fail(self, invocation_id, *, lease=None):
        request, _ = await asyncio.to_thread(self.repository.command, invocation_id)
        return await asyncio.to_thread(self.repository.finish, request.project_id, invocation_id, "failed", lease=lease)

    async def cancel(self, request, *, control_id):
        access = await asyncio.to_thread(self.application._access, request.project_id, execute=True)
        await asyncio.to_thread(self.application.read, request.project_id, request.invocation_id)
        status = await asyncio.to_thread(self.repository.finish, request.project_id, request.invocation_id, "cancelled",
            control_id=control_id, actor_id=access.actor_id,
            require_current=lambda: self.application.authorization.require_current(access))
        if status == "cancelled":
            try:
                await self.workflow.cancel(request.invocation_id)
                await asyncio.to_thread(self.repository.cancellation_delivered, request.project_id, request.invocation_id)
            except Exception:
                logger.warning("Native build cancellation delivery deferred")
        return status
