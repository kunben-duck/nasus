import asyncio
import logging
from uuid import uuid4

from ..platform.actor_context import actor_scope
from .generation_executor import GenerationOutcomeUnknown
from .generation_job_ports import GenerationJobRepositoryPort, GenerationJobWorkflowPort, GenerationRecoveryRequest, GenerationHistoryRequest
from .test_design_results import TestDesignResultIntegrityError
from .generation_work_lease import GenerationLeaseBusy, GenerationLeaseLost, run_with_generation_lease
from .generation_batch_recovery import GenerationBatchRecoveryRequest
from ...domain.quality_loop.acceptance_specification import acceptance_digest

logger = logging.getLogger(__name__)


class GenerationJobApplicationService:
    def __init__(self, application, repository: GenerationJobRepositoryPort, workflow: GenerationJobWorkflowPort, *, batch_recovery=None):
        self.application, self.repository, self.workflow = application, repository, workflow
        self.batch_recovery = batch_recovery

    async def dispatch(self, request, invocation_id):
        access = self.application._access(request.project_id)
        await asyncio.to_thread(self.repository.require_running, request, invocation_id, access.actor_id)
        await self.workflow.start(invocation_id)

    async def run(self, invocation_id):
        request, status = await asyncio.to_thread(self.repository.command, invocation_id)
        if status != "running":
            return status
        try:
            lease = await asyncio.to_thread(self.repository.claim_lease, request.project_id, invocation_id, uuid4().hex)
        except GenerationLeaseLost:
            _, current = await asyncio.to_thread(self.repository.command, invocation_id)
            if current != "running":
                return current
            raise

        async def execute(require_work):
            try:
                _, source, actor = await asyncio.to_thread(self.repository.execution, invocation_id)
                with actor_scope(actor):
                    if isinstance(request, GenerationBatchRecoveryRequest):
                        if self.batch_recovery is None:
                            raise TestDesignResultIntegrityError("batch recovery application is unavailable")
                        await asyncio.to_thread(self.batch_recovery.recover, request, lease=lease)
                    elif isinstance(request, GenerationRecoveryRequest):
                        await self.application.recover(request, source, authority_invocation_id=invocation_id, require_work=require_work)
                    else:
                        options = {"work_lease": lease} if getattr(self.application, "batch_executor", None) is not None else {}
                        await self.application.execute(request, invocation_id=invocation_id, require_work=require_work, **options)
                return await asyncio.to_thread(self.repository.finish, request.project_id, invocation_id,
                    "completed", "Draft generation archived.", lease=lease)
            except (ValueError, KeyError, PermissionError, GenerationOutcomeUnknown):
                return await self.fail(invocation_id, lease=lease)

        try:
            return await run_with_generation_lease(self.repository, lease, execute)
        except asyncio.CancelledError:
            try:
                await asyncio.to_thread(self.repository.finish, request.project_id, invocation_id, "cancelled",
                    "Generation cancelled. Provider reservations and private replies are retained; no automatic resend.", lease=lease)
            except (GenerationLeaseBusy, GenerationLeaseLost):
                # A replaced worker cannot cancel its successor.
                pass
            raise
        finally:
            try:
                await asyncio.to_thread(self.repository.release_lease, lease)
            except Exception:
                logger.warning("Generation lease release deferred to database expiry")
        # Infrastructure exceptions reach Temporal's bounded activity retry.
        # The executor replays committed replies and never resends a reservation.

    async def fail(self, invocation_id, *, lease=None):
        request, _ = await asyncio.to_thread(self.repository.command, invocation_id)
        return await asyncio.to_thread(self.repository.finish, request.project_id, invocation_id, "failed",
            "Generation ended without a committed draft. Inspect the job: an archived reply may be explicitly recovered; unknown calls are never resent.", lease=lease)

    def history(self, request: GenerationHistoryRequest):
        request = GenerationHistoryRequest.model_validate(request.model_dump(mode="json"))
        access = self.application._access(request.project_id)
        self.application.generation.scopes.read_inputs(request.project_id, request.scope_revision_id, request.scope_artifact_hash)
        page = self.repository.history(request)
        items = []
        for item in page["commands"]:
            source = item["source_request"]
            if (source.project_id != request.project_id or source.scope_revision_id != request.scope_revision_id
                    or source.scope_artifact_hash != request.scope_artifact_hash or source.execution is None):
                raise TestDesignResultIntegrityError("generation history source scope mismatch")
            for binding_id in source.execution.source_binding_ids:
                access.require_binding(binding_id)
            items.append({key: item[key] for key in ("invocation_id", "source_invocation_id", "tool_id", "status")})
        self.application.authorization.require_current(access)
        return {"request": request.model_dump(mode="json"), "items": items,
            "next_after_id": page["next_after_id"], "has_running": page["has_running"],
            "generation_authorized": False, "execution_authorized": False}

    def read(self, project_id, invocation_id):
        access = self.application._access(project_id)
        request, status = self.repository.command(invocation_id)
        _, source, actor_id = self.repository.inspection(invocation_id)
        if request.project_id != project_id:
            raise PermissionError("generation job belongs to another project")
        if source.execution is None:
            raise TestDesignResultIntegrityError("legacy generation has no native lifecycle consent")
        for binding_id in source.execution.source_binding_ids:
            access.require_binding(binding_id)
        recovering = isinstance(request, (GenerationRecoveryRequest, GenerationBatchRecoveryRequest))
        source_id = request.invocation_id if recovering else invocation_id
        stored = self.application.repository.get(project_id, source_id)
        batch_executor = getattr(self.application, "batch_executor", None)
        batch = batch_executor.receipts.repository.inspect(source, source_id, actor_id) if batch_executor else None
        if batch is not None and stored is not None:
            raise TestDesignResultIntegrityError("generation has both single and batch native reservations")
        result = self.application.results.repository.by_invocation(project_id, source_id)
        if result is not None and recovering and result.get("recovery_invocation_id") != invocation_id:
            result = None
        reply = stored.get("reply") if stored else None
        recovery = None
        if status == "failed" and actor_id == access.actor_id and not recovering and reply and result is None:
            recovery = GenerationRecoveryRequest(project_id=project_id, invocation_id=invocation_id,
                request_hash=acceptance_digest(source.model_dump(mode="json")),
                reply_artifact_hash=reply["artifact_hash"], response_hash=reply["response_hash"]).model_dump(mode="json")
        self.application.authorization.require_current(access)
        value = {"project_id": project_id, "invocation_id": invocation_id, "status": status,
            "source_invocation_id": source_id, "scope_revision_id": source.scope_revision_id,
            "call_reserved": stored is not None, "reply_archived": reply is not None,
            "provider_outcome_unknown": stored is not None and reply is None,
            "generation_id": result["generation_id"] if result else None, "recovery_request": recovery,
            "execution_authorized": False}
        if batch is not None:
            if (status == "failed" and actor_id == access.actor_id and not recovering and result is None
                    and batch["archived_calls"] == batch["call_count"] and self.batch_recovery is not None):
                offered = self.batch_recovery.offer(source, source_id)
                recovery = offered.model_dump(mode="json") if offered is not None else None
            value.update(batch_progress=batch, call_reserved=batch["claimed_calls"] > 0,
                reply_archived=batch["archived_calls"] == batch["call_count"],
                provider_outcome_unknown=batch["unknown_calls"] > 0, recovery_request=recovery)
        self.application.authorization.require_current(access)
        return value

    async def cancel(self, request, *, control_id):
        access = self.application._access(request.project_id)
        # Administrators can stop a disabled actor's job without inheriting egress consent.
        await asyncio.to_thread(self.read, request.project_id, request.invocation_id)
        status = await asyncio.to_thread(self.repository.finish, request.project_id, request.invocation_id, "cancelled",
            "Generation cancelled. Archived replies remain private; charged or unknown calls are not refunded or resent.",
            control_id=control_id, actor_id=access.actor_id,
            require_current=lambda: self.application.authorization.require_current(access))
        if status == "cancelled":
            try:
                await self.workflow.cancel(request.invocation_id)
                await asyncio.to_thread(self.repository.cancellation_delivered, request.project_id, request.invocation_id)
            except Exception:
                logger.warning("Generation cancellation delivery deferred")
        return status
