from dataclasses import asdict
from datetime import datetime, timezone
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.system_image.build_plan_revisions import (
    REVISE_PLAN_TOOL, BuildPlanRevisionGoal, BuildPlanRevisionInput, StoredBuildPlanRevision,
)
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.build_plan_revisions import BuildPlanRevision, REVISION_PAUSE_REASONS
from .build_plan_models import BuildPlanRecord
from .build_plan_repository import BuildPlanRepository
from .build_plan_revision_models import BuildPlanRevisionRecord
from .conversation_repository import ConversationRepository
from .db_models import AgentGoalRecord, AuditEventRecord, ConversationRecord, ToolInvocationRecord, UserIdentityRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope


class BuildPlanRevisionRepository:
    @staticmethod
    def _goal(session, project_id, root_plan_id, goal_id, *, lock=False):
        statement = select(AgentGoalRecord).where(AgentGoalRecord.id == goal_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        goal = session.scalar(statement)
        conversation = session.get(ConversationRecord, goal.conversation_id) if goal else None
        if (goal is None or goal.project_id != project_id or conversation is None
                or conversation.project_id != project_id
                or goal.goal_template not in {"system_image_build", "system_image_investigation"}
                or f"build_plan:{root_plan_id}" not in goal.target_refs):
            raise BuildPlanIntegrityError("Plan revision must retain the original project goal.")
        return goal

    @staticmethod
    def _stored(row):
        payload = dict(row.payload)
        payload["checkpoint"] = AgentResumeCheckpoint.from_payload(payload["checkpoint"])
        revision = BuildPlanRevision(**payload)
        revision.require_valid()
        if (revision.revision_id, revision.project_id, revision.goal_id, revision.root_plan_id,
                revision.from_plan_id, revision.plan_id, revision.parent_revision_id,
                revision.revision_number, revision.invocation_id, revision.digest) != (
                row.revision_id, row.project_id, row.goal_id, row.root_plan_id, row.from_plan_id,
                row.plan_id, row.parent_revision_id, row.revision_number, row.invocation_id, row.revision_hash):
            raise BuildPlanIntegrityError("Revision ledger failed its scope or hash check.")
        return StoredBuildPlanRevision(revision, row.revision_hash)

    def history(self, project_id, root_plan_id, goal_id):
        with session_scope() as session:
            self._goal(session, project_id, root_plan_id, goal_id)
            rows = session.scalars(select(BuildPlanRevisionRecord).where(
                BuildPlanRevisionRecord.project_id == project_id, BuildPlanRevisionRecord.goal_id == goal_id
            ).order_by(BuildPlanRevisionRecord.revision_number).limit(81)).all()
            return [self._stored(row) for row in rows]

    def eligible_goals(self, project_id, root_plan_id):
        with session_scope() as session:
            rows = session.scalars(select(AgentGoalRecord).where(
                AgentGoalRecord.project_id == project_id, AgentGoalRecord.status == "paused",
                AgentGoalRecord.pause_reason.in_((*REVISION_PAUSE_REASONS, "build_plan_phase_prepared")),
                AgentGoalRecord.goal_template.in_({"system_image_build", "system_image_investigation"}),
                AgentGoalRecord.target_refs.cast(JSONB).contains([f"build_plan:{root_plan_id}"])
            ).order_by(AgentGoalRecord.id).limit(20)).all()
            for row in rows:
                self._goal(session, project_id, root_plan_id, row.id)
            return [BuildPlanRevisionGoal(row.id, row.title, row.pause_reason) for row in rows]

    def record(self, request, proposal, *, actor_id, invocation_id, created_at, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            goal = self._goal(session, request.project_id, request.root_plan_id, request.goal_id, lock=True)
            command = session.scalar(select(ToolInvocationRecord).where(
                ToolInvocationRecord.id == invocation_id).with_for_update())
            body = query_payload(command.input_payload) if command else {}
            confirmed, consent = body.pop("confirmed_at", None), body.pop("confirmed_by_user", None)
            actor = session.get(UserIdentityRecord, actor_id)
            if (command is None or command.tool_id != REVISE_PLAN_TOOL or command.status != "running"
                    or BuildPlanRevisionInput.model_validate(body) != request or consent is not True
                    or actor is None or actor.status != "active"
                    or command.input_payload.get("confirmed_actor_id") != actor_id
                    or command.conversation_id != goal.conversation_id
                    or command.input_payload.get("agent_goal_id", goal.id) != goal.id):
                raise BuildPlanIntegrityError("Plan revision needs its exact independent canonical confirmation.")
            try:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(confirmed)).total_seconds()
                if not 0 <= elapsed <= 900:
                    raise ValueError("expired confirmation")
            except (TypeError, ValueError) as exc:
                raise BuildPlanIntegrityError("Plan revision confirmation is invalid or expired.") from exc
            checkpoint = request.checkpoint()
            existing = session.scalar(select(BuildPlanRevisionRecord).where(
                BuildPlanRevisionRecord.invocation_id == invocation_id))
            if existing is not None:
                saved = self._stored(existing)
                item = saved.revision
                if (item.project_id, item.goal_id, item.root_plan_id, item.from_plan_id,
                        item.from_plan_digest, item.source_manifest_id, item.plan_digest, item.checkpoint,
                        item.parent_revision_id, item.parent_revision_hash) != (
                        request.project_id, request.goal_id, request.root_plan_id, request.from_plan_id,
                        request.from_plan_digest, request.source_manifest_id, proposal.digest, checkpoint,
                        request.parent_revision_id, request.parent_revision_hash):
                    raise BuildPlanIntegrityError("A canonical revision cannot change its original proposal.")
                require_current()
                return saved
            checkpoint.require_matches(ConversationRepository._to_goal(goal).model_dump(mode="json"))
            if goal.status != "paused" or goal.pause_reason not in REVISION_PAUSE_REASONS:
                raise BuildPlanIntegrityError("Source enrichment requires a paused review checkpoint.")
            latest = session.scalar(select(BuildPlanRevisionRecord).where(
                BuildPlanRevisionRecord.goal_id == goal.id).order_by(BuildPlanRevisionRecord.revision_number.desc()).limit(1))
            parent = self._stored(latest) if latest else None
            if (request.root_plan_id, request.from_plan_id, request.parent_revision_id, request.parent_revision_hash) != (
                    parent.revision.root_plan_id if parent else request.from_plan_id,
                    parent.revision.plan_id if parent else request.root_plan_id,
                    parent.revision.revision_id if parent else None, parent.revision_hash if parent else None):
                raise BuildPlanIntegrityError("Plan revision parent changed; reread before submitting another proposal.")
            number = parent.revision.revision_number + 1 if parent else 1
            if number > 80:
                raise BuildPlanIntegrityError("Plan revision ledger is full.")
            old_row = session.get(BuildPlanRecord, request.from_plan_id)
            if old_row is None or BuildPlanRepository._stored(session, old_row).plan_digest != request.from_plan_digest:
                raise BuildPlanIntegrityError("Original plan failed its fixed-input check.")
            # Reuse immutable proposals by digest, but never copy any old grant or work reservation.
            row = session.scalar(select(BuildPlanRecord).where(BuildPlanRecord.project_id == request.project_id,
                BuildPlanRecord.plan_digest == proposal.digest))
            if row is None:
                row = BuildPlanRecord(plan_id=str(uuid4()), project_id=request.project_id,
                    manifest_id=proposal.intent.source_manifest_id, plan_digest=proposal.digest,
                    payload=json.loads(json.dumps(asdict(proposal))), created_at=created_at, created_by=actor_id,
                    state=proposal.state)
                session.add(row)
                session.flush()
            stored = BuildPlanRepository._stored(session, row)
            if stored.proposal != proposal:
                raise BuildPlanIntegrityError("Revised plan digest collision.")
            revision = BuildPlanRevision(str(uuid4()), request.project_id, goal.id, request.root_plan_id,
                request.from_plan_id, request.from_plan_digest, row.plan_id, row.plan_digest,
                proposal.intent.source_manifest_id, proposal.intent.source_manifest_hash,
                request.parent_revision_id, request.parent_revision_hash, number, checkpoint, invocation_id, created_at)
            revision.require_valid()
            saved = BuildPlanRevisionRecord(revision_id=revision.revision_id, project_id=revision.project_id,
                goal_id=revision.goal_id, root_plan_id=revision.root_plan_id, from_plan_id=revision.from_plan_id,
                plan_id=revision.plan_id, parent_revision_id=revision.parent_revision_id,
                revision_number=number, invocation_id=invocation_id, payload=asdict(revision), revision_hash=revision.digest)
            session.add(saved)
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=created_at, actor=actor_id,
                actor_kind="user", action="system_image.build.plan.revised", entity_type="image_build_plan_revision",
                entity_id=revision.revision_id, status="accepted", summary="Same-goal source enrichment proposal saved; no execution grant transferred.",
                conversation_id=goal.conversation_id, tool_invocation_id=invocation_id, agent_goal_id=goal.id,
                object_refs=[], evidence_refs=[], event_metadata={"project_id": request.project_id}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()),
                event_type="system_image.build.plan.revised", occurred_at=created_at, correlation_id=request.project_id,
                entity_type="image_build_plan_revision", entity_id=revision.revision_id, entity_version=0,
                mutation_kind="append", patch={"project_id": request.project_id},
                query_keys=[["system-image-build-plans", request.project_id]]), session=session)
            session.flush()
            require_current()
            return self._stored(saved)
