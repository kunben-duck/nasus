from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.system_image.gap_ownership import ASSIGN_GAPS_TOOL, GapOwnershipInput, StoredGapOwnership
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ...domain.platform.rbac import ToolRBAC
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.gap_ownership import ownership_digest
from .conversation_repository import ConversationRepository
from .db_models import AgentGoalRecord, AuditEventRecord, ProjectRoleBindingRecord, ToolInvocationRecord, UserIdentityRecord
from .event_outbox_repository import EventOutboxRepository
from .gap_ownership_models import BuildGapOwnershipRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class GapOwnershipRepository:
    @staticmethod
    def _request(invocation):
        if invocation is None or invocation.tool_id != ASSIGN_GAPS_TOOL:
            raise BuildPlanIntegrityError("Gap revision lost its canonical assignment command.")
        body = query_payload(invocation.input_payload)
        body.pop("confirmed_at", None)
        body.pop("confirmed_by_user", None)
        return GapOwnershipInput.model_validate(body)

    @classmethod
    def _stored(cls, session, row, *, executing_invocation_id=None):
        request = GapOwnershipInput.model_validate(row.request_payload)
        command = session.get(ToolInvocationRecord, row.invocation_id)
        checkpoint = AgentResumeCheckpoint.capture(request.expected_goal)
        receipt = {"kind": "build_gap_ownership", "project_id": row.project_id,
            "completion_invocation_id": row.completion_invocation_id,
            "completion_report_hash": request.completion_report_hash,
            "revision_id": row.revision_id, "revision_hash": row.revision_hash}
        # Only the committing command may inspect its own running row. Public
        # history must also replay Runtime's final status and exact receipt.
        completing = command is not None and command.id == executing_invocation_id and command.status == "running"
        if ((request.project_id, request.completion_invocation_id, request.parent_revision_id, request.parent_revision_hash)
                != (row.project_id, row.completion_invocation_id, row.parent_revision_id, row.parent_revision_hash)
                or ownership_digest(request.model_dump(mode="json"), row.revision_number, row.confirmed_by, row.created_at) != row.revision_hash
                or cls._request(command) != request
                or command.conversation_id != checkpoint.conversation_id
                or not completing and (command.status != "completed" or not command.result_payload
                    or command.result_payload.get("build_gap_ownership") != receipt)
                or command.input_payload.get("confirmed_actor_id") != row.confirmed_by
                or command.input_payload.get("confirmed_by_user") is not True):
            raise BuildPlanIntegrityError("Gap responsibility history failed immutable replay verification.")
        return StoredGapOwnership(row.revision_id, row.revision_hash, row.revision_number, row.invocation_id,
            row.confirmed_by, row.created_at, request)

    @classmethod
    def _history(cls, session, project_id, completion_invocation_id, *, executing_invocation_id=None):
        rows = session.scalars(select(BuildGapOwnershipRecord).where(
            BuildGapOwnershipRecord.completion_invocation_id == completion_invocation_id).order_by(
                BuildGapOwnershipRecord.revision_number).limit(81)).all()
        if len(rows) > 80 or any(row.project_id != project_id for row in rows):
            raise BuildPlanIntegrityError("Gap history exceeds its bound or project scope.")
        history, previous = [], None
        for number, row in enumerate(rows, 1):
            record = cls._stored(session, row, executing_invocation_id=executing_invocation_id)
            if (record.revision_number != number or (record.request.parent_revision_id, record.request.parent_revision_hash)
                    != ((previous.revision_id, previous.revision_hash) if previous else (None, None))):
                raise BuildPlanIntegrityError("Gap responsibility history is missing or has a different predecessor.")
            history.append(record)
            previous = record
        return tuple(history)

    def history(self, project_id, completion_invocation_id):
        with session_scope() as session:
            return self._history(session, project_id, completion_invocation_id)

    @staticmethod
    def _eligible(session, project_id, owner_ids, *, lock=False):
        if not owner_ids:
            return set()
        users = select(UserIdentityRecord).where(UserIdentityRecord.user_id.in_(owner_ids))
        bindings = select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.project_id == project_id,
            ProjectRoleBindingRecord.user_id.in_(owner_ids), ProjectRoleBindingRecord.version_id.is_(None),
            ProjectRoleBindingRecord.session_id.is_(None), ProjectRoleBindingRecord.status == "active")
        if lock:
            users = users.order_by(UserIdentityRecord.user_id).with_for_update().execution_options(populate_existing=True)
            bindings = bindings.order_by(ProjectRoleBindingRecord.binding_id).with_for_update().execution_options(populate_existing=True)
        members = {row.user_id for row in session.scalars(bindings)}
        return {user.user_id for user in session.scalars(users) if user.status == "active" and
            (user.user_id in members or ToolRBAC.normalize_role(user.role) == "platform_admin")}

    def eligible_owners(self, project_id, owner_ids):
        with session_scope() as session:
            return self._eligible(session, project_id, owner_ids)

    def owner_options(self, project_id):
        with session_scope() as session:
            rows = session.scalars(select(UserIdentityRecord).join(ProjectRoleBindingRecord,
                ProjectRoleBindingRecord.user_id == UserIdentityRecord.user_id).where(
                    ProjectRoleBindingRecord.project_id == project_id, ProjectRoleBindingRecord.version_id.is_(None),
                    ProjectRoleBindingRecord.session_id.is_(None), ProjectRoleBindingRecord.status == "active",
                    UserIdentityRecord.status == "active").distinct().order_by(UserIdentityRecord.user_id).limit(201)).all()
            if len(rows) > 200:
                raise BuildPlanIntegrityError("Gap owner selection exceeds its complete project-member bound.")
            return [{"actor_id": row.user_id, "display_name": row.display_name} for row in rows]

    def record(self, request, *, invocation_id, actor_id, created_at, require_current):
        checkpoint = AgentResumeCheckpoint.capture(request.expected_goal)
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            goal = session.scalar(select(AgentGoalRecord).where(AgentGoalRecord.id == checkpoint.goal_id)
                .with_for_update().execution_options(populate_existing=True))
            if goal is None:
                raise BuildPlanIntegrityError("Gap ownership goal is unavailable.")
            checkpoint.require_matches(ConversationRepository._to_goal(goal).model_dump(mode="json"))
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            original = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == request.completion_invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            receipt = original.result_payload.get("build_completion") if original and original.result_payload else None
            if (self._request(command) != request or command.status != "running"
                    or command.conversation_id != checkpoint.conversation_id
                    or command.input_payload.get("confirmed_by_user") is not True
                    or command.input_payload.get("confirmed_actor_id") != actor_id
                    or original is None or original.tool_id != "query.system_image.build_completion.read"
                    or original.status != "completed" or not receipt or receipt.get("report_hash") != request.completion_report_hash
                    or receipt.get("project_id") != request.project_id
                    or original.input_payload.get("expected_goal") != request.expected_goal):
                raise BuildPlanIntegrityError("Gap responsibilities require their exact independently confirmed command and original report.")
            try:
                confirmed = datetime.fromisoformat(command.input_payload["confirmed_at"])
                if confirmed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900:
                    raise ValueError("invalid consent age")
            except (KeyError, TypeError, ValueError) as exc:
                raise BuildPlanIntegrityError("Gap responsibility confirmation is invalid or expired.") from exc
            owners = {item.owner_actor_id for item in request.assignments}
            eligible = self._eligible(session, request.project_id, tuple(owners | {actor_id}), lock=True)
            if not (owners | {actor_id}) <= eligible:
                raise BuildPlanIntegrityError("Gap owner or confirming reviewer is no longer an active project member.")
            history = self._history(session, request.project_id, request.completion_invocation_id, executing_invocation_id=invocation_id)
            existing = next((item for item in history if item.invocation_id == invocation_id), None)
            if existing:
                if existing.request != request:
                    raise BuildPlanIntegrityError("Canonical gap responsibility cannot change its saved request.")
                require_current()
                return existing
            previous = history[-1] if history else None
            if (request.parent_revision_id, request.parent_revision_hash) != (
                    (previous.revision_id, previous.revision_hash) if previous else (None, None)):
                raise BuildPlanIntegrityError("Gap responsibilities changed; reread before assigning.")
            number = len(history) + 1
            if number > 80:
                raise BuildPlanIntegrityError("Gap responsibility history exceeds its complete bound.")
            row = BuildGapOwnershipRecord(revision_id=str(uuid4()), project_id=request.project_id,
                completion_invocation_id=request.completion_invocation_id, invocation_id=invocation_id,
                parent_revision_id=request.parent_revision_id, parent_revision_hash=request.parent_revision_hash,
                revision_number=number, request_payload=request.model_dump(mode="json"), confirmed_by=actor_id,
                created_at=created_at, revision_hash=ownership_digest(request.model_dump(mode="json"), number, actor_id, created_at))
            session.add(row)
            session.flush()
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=created_at, actor=actor_id, actor_kind="user",
                action="system_image.build.gaps.assigned", entity_type="build_gap_ownership", entity_id=row.revision_id,
                status="accepted", summary="Confirmed responsibilities for fixed unresolved build gaps.",
                conversation_id=checkpoint.conversation_id, tool_invocation_id=invocation_id, agent_goal_id=checkpoint.goal_id,
                object_refs=[f"build_gap_ownership:{row.revision_id}"], evidence_refs=[],
                event_metadata={"project_id": request.project_id, "completion_invocation_id": request.completion_invocation_id,
                    "revision_hash": row.revision_hash, "assignment_count": len(request.assignments)}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()),
                event_type="system_image.build.gaps.assigned", occurred_at=created_at, correlation_id=request.project_id,
                entity_type="build_gap_ownership", entity_id=row.revision_id, entity_version=number,
                mutation_kind="append", patch={"project_id": request.project_id},
                query_keys=[["build-gap-ownership", request.project_id, request.completion_invocation_id]]), session=session)
            require_current()
            return self._stored(session, row, executing_invocation_id=invocation_id)
