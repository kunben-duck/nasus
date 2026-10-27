"""Persist confirmed dispatch before Temporal, then execute the original pinned work."""
import asyncio
import logging
import threading
from uuid import uuid4

from ..platform.actor_context import actor_scope
from ..platform.errors import PlatformApplicationError
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.code_index import CodeIndexCancelled
from ...domain.system_image.code_index_generation import CodeIndexLeaseLost
from ...domain.system_image.image_revision import ImageRevisionConflict, ImageRevisionIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ...domain.system_image.structure_work import StructureWorkCancelled, StructureWorkLost
from .structure_builds import StructureBuildApplicationService, StructureBuildCancelled
from .structure_job_ports import StructureJobRepositoryPort, StructureJobWorkflowPort

logger = logging.getLogger(__name__)


class StructureJobApplicationService:
    def __init__(self, application: StructureBuildApplicationService, repository: StructureJobRepositoryPort,
                 workflow: StructureJobWorkflowPort, *, renew_seconds: float = 10):
        self.application, self.repository, self.workflow = application, repository, workflow
        self.renew_seconds = renew_seconds

    @property
    def enabled(self):
        return self.workflow.enabled

    async def dispatch(self, request, invocation_id):
        scope = await asyncio.to_thread(self.application.plans.authorization.scope, request.project_id)
        await asyncio.to_thread(self.repository.register, request, invocation_id, scope.actor_id)
        # A lost Temporal acknowledgement must not erase the committed intent.
        try:
            await self.workflow.start(invocation_id)
        except Exception:
            logger.warning("Structural workflow dispatch deferred for invocation %s", invocation_id)

    async def run(self, invocation_id):
        request, status = await asyncio.to_thread(self.repository.command, invocation_id)
        if status != "running":
            return status
        try:
            lease = await asyncio.to_thread(self.repository.claim, invocation_id, uuid4().hex)
        except StructureWorkCancelled:
            return await asyncio.to_thread(self.repository.finish, invocation_id, "cancelled")
        except StructureWorkLost:
            _, current = await asyncio.to_thread(self.repository.command, invocation_id)
            if current != "running":
                return current
            raise
        stop = threading.Event()
        work = heartbeat = None
        try:
            try:
                actor = await asyncio.to_thread(self.repository.execution, invocation_id)

                def check_current():
                    if stop.is_set():
                        raise StructureBuildCancelled("Structural activity interrupted.")
                    self.repository.require_lease(lease, actor)

                async def execute():
                    with actor_scope(actor):
                        await asyncio.to_thread(self.application.execute, request, invocation_id=invocation_id,
                            work_lease=lease, require_work=check_current)

                async def renew():
                    while True:
                        await asyncio.sleep(self.renew_seconds)
                        await asyncio.to_thread(self.repository.renew, lease)

                work, heartbeat = asyncio.create_task(execute()), asyncio.create_task(renew())
                done, _ = await asyncio.wait({work, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
                if work not in done:
                    await heartbeat
                await work
                return await asyncio.to_thread(self.repository.finish, invocation_id, "completed", lease=lease)
            except (StructureWorkCancelled, StructureBuildCancelled, CodeIndexCancelled):
                stop.set()
                if work is not None:
                    await asyncio.shield(asyncio.gather(work, return_exceptions=True))
                return await asyncio.to_thread(self.repository.finish, invocation_id, "cancelled", lease=lease)
            except (BuildPlanIntegrityError, ImageRevisionIntegrityError, ImageRevisionConflict,
                    SourceAccessDenied, StaleSourceAccessScope, PlatformApplicationError,
                    CodeIndexLeaseLost, ValueError, KeyError, PermissionError, TimeoutError):
                return await asyncio.to_thread(self.repository.finish, invocation_id, "failed", lease=lease)
        except asyncio.CancelledError:
            # An expired/shutting-down activity is not a new business cancellation.
            # Its thread must stop before ownership is released to a retry.
            raise
        finally:
            stop.set()
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            if work is not None:
                await asyncio.shield(asyncio.gather(work, return_exceptions=True))
            try:
                await asyncio.to_thread(self.repository.release, lease)
            except Exception:
                logger.warning("Structural worker release deferred to database expiry")

    async def fail(self, invocation_id):
        return await asyncio.to_thread(self.repository.finish, invocation_id, "failed")
