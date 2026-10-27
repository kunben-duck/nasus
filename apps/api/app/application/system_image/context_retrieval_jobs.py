import asyncio
import logging

from ..platform.actor_context import actor_scope
from ...domain.system_image.image_revision import ImageRevisionIntegrityError

logger = logging.getLogger(__name__)

class ContextRetrievalJobApplicationService:
    """Temporal dispatch is separate from execution; ToolRuntime never awaits model batches."""

    def __init__(self, application, workflow):
        self.application, self.workflow = application, workflow
        self.repository = application.repository

    async def dispatch(self, request, invocation_id):
        scope = await asyncio.to_thread(self.application.indexes._scope, request.project_id, exporting=True)
        await asyncio.to_thread(self.repository.require_running, request, invocation_id, scope.actor_id)
        await self.workflow.start(invocation_id)

    async def run(self, invocation_id):
        request, status = await asyncio.to_thread(self.repository.command, invocation_id)
        if status != "running":
            return status
        try:
            _, _, actor = await asyncio.to_thread(self.repository.execution, invocation_id)
            with actor_scope(actor):
                await self.application.execute(request, invocation_id=invocation_id)
                return "completed"
        except asyncio.CancelledError:
            await asyncio.to_thread(self.repository.finish, request.project_id, invocation_id, "cancelled",
                "Context retrieval cancelled. No partial AC mapping is usable; reserved calls are not resent.")
            raise
        except (ValueError, KeyError, PermissionError, ImageRevisionIntegrityError):
            return await asyncio.to_thread(self.repository.finish, request.project_id, invocation_id, "failed",
                "Context retrieval failed validation or has an uncertain provider outcome. Preview and confirm a new operation; partial mappings are not usable.")

    async def cancel(self, project_id, invocation_id):
        self.application.indexes._scope(project_id, exporting=True)
        request, _ = await asyncio.to_thread(self.repository.command, invocation_id)
        if request.project_id != project_id:
            raise ImageRevisionIntegrityError("context retrieval cancellation project mismatch")
        status = await asyncio.to_thread(self.repository.finish, project_id, invocation_id, "cancelled",
            "Context retrieval cancelled. Completed batches remain private; no partial AC mapping is usable.")
        if status == "cancelled":
            try:
                await self.workflow.cancel(invocation_id)
                await asyncio.to_thread(self.repository.cancellation_delivered, project_id, invocation_id)
            except Exception:
                # The durable receipt remains pending; the worker retries delivery.
                logger.warning("Context retrieval cancellation delivery deferred")
        return status
