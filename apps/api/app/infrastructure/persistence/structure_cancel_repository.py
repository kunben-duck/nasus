from datetime import datetime, timezone

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.system_image.structure_builds import StructureBuildBinding
from ...application.system_image.structure_cancel_inputs import STRUCTURE_CANCEL_TOOL, StructureCancelInput, StructureCancelReceipt
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from .db_models import ToolInvocationRecord, UserIdentityRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .structure_build_repository import StructureBuildRepository
from .structure_cancel_models import StructureCancellationRecord as Cancellation
from .structure_job_models import StructureJobRecord as Job, StructureWorkLeaseRecord as Lease
from .structure_job_repository import StructureJobRepository
from .unit_of_work import session_scope


class StructureCancellationRepository:
    @staticmethod
    def _origin(session, request, *, lock=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == request.original_invocation_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        original = session.scalar(query)
        payload = StructureJobRepository._request(original)
        if payload.model_dump() != request.model_dump(exclude={"original_invocation_id"}):
            raise BuildPlanIntegrityError("Structural cancellation differs from its original command.")
        if session.get(Job, original.id) is not None:
            StructureJobRepository._command(session, original.id)
        binding = StructureBuildBinding(**payload.model_dump(), invocation_id=original.id)
        artifact = StructureBuildRepository.existing_in_session(session, binding)
        if original.status == "completed" and artifact is None:
            raise BuildPlanIntegrityError("Completed structural command has no candidate.")
        return original, payload, artifact

    def require_origin(self, request):
        with session_scope() as session:
            original, _, _ = self._origin(session, request)
            StructureJobRepository.cancellation_in_session(session, original)

    def inspect(self, request):
        with session_scope() as session:
            original, _, artifact = self._origin(session, request)
            cancellation = StructureJobRepository.cancellation_in_session(session, original)
            return original.status, cancellation is not None, artifact is not None

    def cancel_confirmed(self, request, *, invocation_id, actor_id, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            require_current()
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            user = session.get(UserIdentityRecord, actor_id)
            if (command is None or command.tool_id != STRUCTURE_CANCEL_TOOL or command.status != "running"
                    or command.id == request.original_invocation_id
                    or command.input_payload.get("confirmed_by_user") is not True
                    or command.input_payload.get("confirmed_actor_id") != actor_id
                    or user is None or user.status != "active"
                    or StructureCancelInput.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                        if key not in {"confirmed_at", "confirmed_by_user"}}) != request):
                raise BuildPlanIntegrityError("Structural cancellation requires its independent confirmed command.")
            now = session.scalar(select(func.clock_timestamp()))
            try:
                confirmed = datetime.fromisoformat(command.input_payload["confirmed_at"])
                # Canonical confirmation is stamped by this API process, not PG.
                # PG remains the sole clock for worker ownership and intent time.
                if confirmed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900:
                    raise ValueError("expired")
            except (KeyError, TypeError, ValueError):
                raise BuildPlanIntegrityError("Structural cancellation confirmation expired.")
            original, payload, artifact = self._origin(session, request, lock=True)
            previous = StructureJobRepository.cancellation_in_session(session, original)
            if artifact is not None:
                outcome = "already_committed"
            elif original.status in {"completed", "failed", "cancelled"}:
                outcome = "already_terminal"
            else:
                if previous is None:
                    session.add(Cancellation(original_invocation_id=original.id, cancellation_invocation_id=invocation_id,
                        project_id=request.project_id, actor_id=actor_id, command_hash=StructureJobRepository._hash(original),
                        request_payload=request.model_dump(), requested_at=now))
                    session.flush()
                    StructureJobRepository._event(session, original, "system_image.build.structure.cancel_requested",
                        {"caused_by": invocation_id})
                work = session.scalar(select(Lease).where(Lease.invocation_id == original.id)
                    .with_for_update().execution_options(populate_existing=True))
                live = work is not None and work.expires_at > now
                # Old inline work has no durable ownership row. It must observe
                # the intent and acknowledge, never be reported stopped early.
                queued = original.status != "running" or session.get(Job, original.id) is not None
                if not live and queued:
                    StructureJobRepository.terminate_in_session(session, original, payload, "cancelled", actor_id, work,
                        caused_by=invocation_id)
                    outcome = "cancelled"
                else:
                    outcome = "already_requested" if previous is not None else "cancel_requested"
            require_current()
            return StructureCancelReceipt(request=request, outcome=outcome, original_status=original.status)
