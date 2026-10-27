from dataclasses import asdict
from datetime import datetime, timezone
import json
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload
from ...application.system_image.investigations import INVESTIGATE_TOOL, InvestigationInput, StoredInvestigation
from ...application.platform.tool_handlers.query_input import query_payload
from ...domain.system_image.build_plan import BuildPlanIntegrityError, MAX_PLAN_BYTES
from ...domain.system_image.investigation import decode_investigation
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.agent.image_plan_phases import phase_target_refs
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from .db_models import AgentGoalRecord, ConversationRecord, ToolInvocationRecord, UserIdentityRecord
from .event_outbox_repository import EventOutboxRepository
from .investigation_models import InvestigationRevisionRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .structure_build_models import StructureBuildArtifactRecord
from .unit_of_work import session_scope
from .conversation_repository import ConversationRepository
from .image_plan_phase_repository import ImagePlanPhaseRepository


class InvestigationRepository:
    def require_checkpoint(self, expected_goal):
        checkpoint = AgentResumeCheckpoint.capture(expected_goal)
        with session_scope() as session:
            goal = session.get(AgentGoalRecord, checkpoint.goal_id)
            if goal is None:
                raise BuildPlanIntegrityError("Completion goal is unavailable.")
            checkpoint.require_matches(ConversationRepository._to_goal(goal).model_dump(mode="json"))

    @staticmethod
    def _goal(session, request, *, lock=False):
        query = select(AgentGoalRecord).where(AgentGoalRecord.id == request.goal_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        goal = session.scalar(query)
        if (goal is None or goal.project_id != request.project_id
                or goal.goal_template not in {"system_image_build", "system_image_investigation"}):
            raise BuildPlanIntegrityError("Investigation must retain the same pinned project goal.")
        records, _ = ImagePlanPhaseRepository.scope_in_session(session, ConversationRepository._to_goal(goal))
        known_plans = {record.phase.plan_id for record in records}
        if f"build_plan:{request.plan_id}" not in goal.target_refs and request.plan_id not in known_plans:
            raise BuildPlanIntegrityError("Investigation plan is not part of this goal's immutable history.")
        conversation = session.get(ConversationRecord, goal.conversation_id)
        if conversation is None or conversation.project_id != request.project_id:
            raise BuildPlanIntegrityError("Investigation goal conversation scope differs.")
        return goal

    def require_goal(self, request):
        with session_scope() as session:
            self._goal(session, request)

    def has_structure_artifact(self, request, image_revision_id, baseline_id):
        with session_scope() as session:
            return session.scalar(select(StructureBuildArtifactRecord.invocation_id).where(
                StructureBuildArtifactRecord.project_id == request.project_id,
                StructureBuildArtifactRecord.plan_id == request.plan_id,
                StructureBuildArtifactRecord.plan_digest == request.plan_digest,
                StructureBuildArtifactRecord.image_revision_id == image_revision_id,
                StructureBuildArtifactRecord.target_baseline_id == baseline_id).limit(1)) is not None

    @staticmethod
    def _hash(request, review, number):
        return snapshot_digest({"request": request.model_dump(mode="json"), "review": asdict(review),
                                "revision_number": number})

    @classmethod
    def _stored(cls, row):
        if len(json.dumps(row.review_payload, ensure_ascii=False).encode()) > MAX_PLAN_BYTES:
            raise BuildPlanIntegrityError("Investigation exceeds the bounded artifact size.")
        request = InvestigationInput.model_validate(row.request_payload)
        review = decode_investigation(row.review_payload)
        if ((row.project_id, row.plan_id, row.goal_id, row.image_revision_id, row.parent_revision_id)
                != (request.project_id, request.plan_id, request.goal_id, request.image_revision_id, request.parent_revision_id)
                or not 1 <= row.revision_number <= 80
                or review.image_revision_id != request.image_revision_id
                or review.image_artifact_hash != request.image_artifact_hash
                or cls._hash(request, review, row.revision_number) != row.revision_hash):
            raise BuildPlanIntegrityError("Investigation record failed its scope or digest check.")
        return StoredInvestigation(row.revision_id, row.revision_hash, request, row.revision_number, row.created_at, review)

    def read(self, project_id, revision_id):
        with session_scope() as session:
            row = session.get(InvestigationRevisionRecord, revision_id)
            if row is None or row.project_id != project_id:
                raise KeyError("investigation revision not found")
            if row.parent_revision_id:
                parent = session.get(InvestigationRevisionRecord, row.parent_revision_id)
                if (parent is None or (parent.project_id, parent.plan_id, parent.goal_id, parent.revision_number + 1)
                        != (row.project_id, row.plan_id, row.goal_id, row.revision_number)):
                    raise BuildPlanIntegrityError("Investigation parent is not its same-goal predecessor.")
            elif row.revision_number != 1:
                raise BuildPlanIntegrityError("Investigation root sequence is invalid.")
            return self._stored(row)

    def record(self, request, review, *, invocation_id, actor_id, created_at, require_current):
        payload = json.loads(json.dumps(asdict(review), ensure_ascii=False))
        if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_PLAN_BYTES:
            raise BuildPlanIntegrityError("Investigation exceeds its artifact size bound.")
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            goal = self._goal(session, request, lock=True)
            invocation = session.scalar(select(ToolInvocationRecord).where(
                ToolInvocationRecord.id == invocation_id).with_for_update())
            body = query_payload(invocation.input_payload) if invocation else {}
            confirmed = body.pop("confirmed_at", None)
            consent = body.pop("confirmed_by_user", None)
            actor = session.get(UserIdentityRecord, actor_id)
            if (invocation is None or invocation.tool_id != INVESTIGATE_TOOL or invocation.status != "running"
                    or InvestigationInput.model_validate(body) != request or consent is not True or not isinstance(confirmed, str)
                    or actor is None or actor.status != "active"
                    or invocation.input_payload.get("confirmed_actor_id") != actor_id
                    or (invocation.conversation_id and invocation.conversation_id != goal.conversation_id)
                    or invocation.input_payload.get("agent_goal_id", request.goal_id) != request.goal_id):
                raise BuildPlanIntegrityError("Investigation requires its exact independently confirmed canonical command.")
            if (goal.status in {"cancelled", "failed", "completed"}
                    or (invocation.input_payload.get("agent_goal_id") and goal.status != "running")):
                raise BuildPlanIntegrityError("Stopped goal cannot commit new investigation work.")
            try:
                timestamp = datetime.fromisoformat(confirmed)
                elapsed = (datetime.now(timezone.utc) - timestamp).total_seconds()
                if timestamp.tzinfo is None or not 0 <= elapsed <= 900:
                    raise ValueError("expired consent")
            except (TypeError, ValueError) as exc:
                raise BuildPlanIntegrityError("Investigation confirmation is invalid or expired.") from exc
            existing = session.scalar(select(InvestigationRevisionRecord).where(
                InvestigationRevisionRecord.invocation_id == invocation_id))
            if existing is not None:
                stored = self._stored(existing)
                if stored.request != request or stored.review != review:
                    raise BuildPlanIntegrityError("Canonical investigation command cannot change its evidence.")
                require_current()
                return stored
            if f"build_plan:{request.plan_id}" not in phase_target_refs(ConversationRepository._to_goal(goal)):
                raise BuildPlanIntegrityError("New investigation work must belong to the active plan phase.")
            latest = session.scalar(select(InvestigationRevisionRecord).where(
                InvestigationRevisionRecord.project_id == request.project_id,
                InvestigationRevisionRecord.plan_id == request.plan_id,
                InvestigationRevisionRecord.goal_id == request.goal_id).order_by(
                    InvestigationRevisionRecord.revision_number.desc()).limit(1))
            if (request.parent_revision_id, request.parent_revision_hash) != (
                    latest.revision_id if latest else None, latest.revision_hash if latest else None):
                raise BuildPlanIntegrityError("Investigation parent is no longer current; reread without repeating work.")
            number = latest.revision_number + 1 if latest else 1
            if number > 80 or review.consumed_review_calls != number:
                raise BuildPlanIntegrityError("Investigation review budget or revision sequence is invalid.")
            row = InvestigationRevisionRecord(revision_id=str(uuid4()), project_id=request.project_id,
                plan_id=request.plan_id, goal_id=request.goal_id, image_revision_id=request.image_revision_id,
                parent_revision_id=request.parent_revision_id, invocation_id=invocation_id, revision_number=number,
                revision_hash=self._hash(request, review, number), request_payload=request.model_dump(mode="json"),
                review_payload=payload, created_by=actor_id, created_at=created_at)
            session.add(row)
            session.flush()
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()),
                event_type="system_image.build.investigation.revised", occurred_at=created_at,
                correlation_id=request.project_id, entity_type="image_investigation_revision", entity_id=row.revision_id,
                entity_version=0, mutation_kind="append", patch={"project_id": request.project_id},
                query_keys=[["system-image-build-investigations", request.project_id]]), session=session)
            require_current()
            return self._stored(row)
