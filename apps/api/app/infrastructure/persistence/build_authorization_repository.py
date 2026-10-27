from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...domain.agent.image_plan_policy import BUILD_GOAL_TEMPLATES
from ...domain.agent.image_plan_phases import active_phase_start
from ...domain.system_image.build_authorization import (
    AUTHORIZE_BUILD_TOOL, STRUCTURE_BUILD_TOOL, ApprovedBuildBudget,
    BuildExecutionAuthorization, authorization_from_dict,
)
from ...domain.system_image.build_plan import BuildPlanIntegrityError, decode_build_plan
from ...application.platform.tool_models import EventPayload
from .build_authorization_models import BuildAuthorizationRecord, BuildWorkReservationRecord
from .db_models import AgentGoalRecord, BaselineRecord, ConversationRecord, ProjectRecord, ToolInvocationRecord, VersionRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_repository import SourceSnapshotRepository
from .structure_build_models import StructureBuildArtifactRecord
from .unit_of_work import session_scope
from .conversation_repository import ConversationRepository
from .image_plan_phase_repository import ImagePlanPhaseRepository
from .build_target_projection_v1 import require_current_build_target


PIN_KEYS = ("project_id", "plan_id", "plan_digest", "target_baseline_id")


class BuildAuthorizationRepository:
    @staticmethod
    def _read(row):
        result = authorization_from_dict(row.payload)
        if (result.digest != row.content_hash or any(getattr(result, key) != getattr(row, key) for key in (
                "authorization_id", "project_id", "plan_id", "goal_id", "authorization_invocation_id"))):
            raise BuildPlanIntegrityError("Saved execution consent failed integrity verification.")
        return result

    @staticmethod
    def _goal(session, invocation, project_id):
        goal = session.scalar(select(AgentGoalRecord).where(
            AgentGoalRecord.id == invocation.input_payload.get("agent_goal_id")).with_for_update())
        conversation = session.get(ConversationRecord, invocation.conversation_id) if invocation.conversation_id else None
        if (goal is None or goal.project_id != project_id or goal.conversation_id != invocation.conversation_id
                or goal.status != "running" or goal.goal_template not in BUILD_GOAL_TEMPLATES
                or conversation is None or conversation.project_id != project_id
                or invocation.initiator_surface != "agent_loop" or invocation.initiator_actor != "agent"):
            raise BuildPlanIntegrityError("Execution consent requires its running project AgentGoal.")
        phases, start = ImagePlanPhaseRepository.scope_in_session(session, ConversationRepository._to_goal(goal))
        if phases:
            phase = phases[-1].phase
            if (invocation.input_payload.get("target_baseline_id") != phase.target_baseline_id
                    or BuildAuthorizationRepository._target(session, project_id, phase.target_baseline_id) != phase.target_version_id):
                raise BuildPlanIntegrityError("The prepared phase target version changed; no consent can be transferred.")
        matching = [item for item in goal.steps[start:] if item.get("selected_tool_id") == invocation.tool_id
                    and item.get("phase") == "acting" and item.get("status") in {"pending", "running", "blocked"}
                    and all(item.get("tool_input_payload", {}).get(key) == invocation.input_payload.get(key) for key in PIN_KEYS)]
        if len(matching) != 1:
            raise BuildPlanIntegrityError("Invocation is not the goal's approved pending work item.")
        step = matching[0]
        if step.get("tool_invocation_id") not in {None, "", invocation.id}:
            raise BuildPlanIntegrityError("Goal step is already bound to another invocation.")
        if invocation.tool_id == AUTHORIZE_BUILD_TOOL and step.get("tool_input_payload", {}).get("budget") != invocation.input_payload.get("budget"):
            raise BuildPlanIntegrityError("Execution budget differs from the proposed goal step.")
        return goal

    @staticmethod
    def _target(session, project_id, baseline_id):
        project = session.scalar(select(ProjectRecord).where(ProjectRecord.id == project_id).with_for_update())
        baseline = session.scalar(select(BaselineRecord).where(BaselineRecord.id == baseline_id).with_for_update())
        if project is None or baseline is None or baseline.project_id != project_id:
            raise BuildPlanIntegrityError("Execution consent target is not a project baseline.")
        if baseline.source_version_id:
            version = session.scalar(select(VersionRecord).where(VersionRecord.id == baseline.source_version_id).with_for_update())
            if version is None or version.project_id != project_id:
                raise BuildPlanIntegrityError("Execution consent target version is not in this project.")
        return baseline.source_version_id

    def authorize(self, request, plan, *, invocation_id, actor_id, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            invocation = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            if (invocation is None or invocation.tool_id != AUTHORIZE_BUILD_TOOL or invocation.status != "running"
                    or invocation.input_payload.get("confirmed_by_user") is not True
                    or any(invocation.input_payload.get(key) != value for key, value in request.model_dump().items())):
                raise BuildPlanIntegrityError("Only a confirmed canonical invocation can grant execution consent.")
            goal = self._goal(session, invocation, request.project_id)
            require_current_build_target(session, plan.proposal, baseline_id=request.target_baseline_id)
            target_version = self._target(session, request.project_id, request.target_baseline_id)
            envelope = BuildExecutionAuthorization(
                authorization_id=f"buildauth_{invocation_id}", project_id=request.project_id, goal_id=goal.id,
                conversation_id=goal.conversation_id, plan_id=request.plan_id, plan_digest=request.plan_digest,
                source_manifest_id=plan.proposal.intent.source_manifest_id,
                source_manifest_hash=plan.proposal.intent.source_manifest_hash,
                target_baseline_id=request.target_baseline_id, target_version_id=target_version,
                authorization_invocation_id=invocation_id, authorized_by=actor_id,
                confirmed_at=invocation.input_payload.get("confirmed_at"),
                budget=ApprovedBuildBudget(**request.budget.model_dump()))
            existing = session.scalar(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal.id,
                BuildAuthorizationRecord.plan_id == request.plan_id))
            if existing is not None:
                if self._read(existing) != envelope:
                    raise BuildPlanIntegrityError("The goal already has different immutable execution consent.")
            else:
                envelope.require_time_available()
                session.add(BuildAuthorizationRecord(authorization_id=envelope.authorization_id, project_id=envelope.project_id,
                    plan_id=envelope.plan_id, goal_id=goal.id, authorization_invocation_id=invocation_id,
                    payload=asdict(envelope), content_hash=envelope.digest))
                self._event(session, "system_image.build.authorized", envelope, invocation_id)
            session.flush()
            require_current()
            return envelope

    @classmethod
    def validate_grant_in_session(cls, session, invocation, *, reserve=False):
        row = session.scalar(select(BuildAuthorizationRecord).where(
            BuildAuthorizationRecord.goal_id == invocation.input_payload.get("agent_goal_id"),
            BuildAuthorizationRecord.plan_id == invocation.input_payload.get("plan_id")))
        if row is None:
            goal_id = invocation.input_payload.get("agent_goal_id")
            goal = session.get(AgentGoalRecord, goal_id) if goal_id else None
            if goal is not None and active_phase_start(ConversationRepository._to_goal(goal)):
                raise BuildPlanIntegrityError("The active plan phase needs its own independent execution consent.")
            if goal is not None and session.scalar(select(BuildAuthorizationRecord.authorization_id).where(
                    BuildAuthorizationRecord.goal_id == goal_id).limit(1)) is not None:
                raise BuildPlanIntegrityError("Work cannot fall back to confirmation for a differently authorized plan.")
            return None
        grant = cls._read(row)
        if (invocation.tool_id != STRUCTURE_BUILD_TOOL or invocation.status not in {"pending", "running"}
                or invocation.conversation_id != grant.conversation_id
                or any(invocation.input_payload.get(key) != getattr(grant, key) for key in PIN_KEYS)):
            raise BuildPlanIntegrityError("Work differs from the immutable execution consent.")
        cls._goal(session, invocation, grant.project_id)
        from .build_plan_models import BuildPlanRecord
        plan_row = session.get(BuildPlanRecord, grant.plan_id)
        if plan_row is None or plan_row.project_id != grant.project_id:
            raise BuildPlanIntegrityError("Approved build plan is missing.")
        proposal = decode_build_plan(plan_row.payload)
        if proposal.digest != grant.plan_digest or plan_row.plan_digest != grant.plan_digest:
            raise BuildPlanIntegrityError("Approved build plan digest changed.")
        require_current_build_target(session, proposal, baseline_id=grant.target_baseline_id)
        if cls._target(session, grant.project_id, grant.target_baseline_id) != grant.target_version_id:
            raise BuildPlanIntegrityError("Approved target version changed; new execution consent is required.")
        authorization_invocation = session.get(ToolInvocationRecord, grant.authorization_invocation_id)
        if authorization_invocation is None or authorization_invocation.status != "completed":
            raise BuildPlanIntegrityError("Execution consent command did not complete.")
        reservation = session.get(BuildWorkReservationRecord, invocation.id)
        if reservation is not None:
            if reservation.authorization_id != grant.authorization_id or reservation.work_item_id != "structure":
                raise BuildPlanIntegrityError("Work reservation differs from the execution consent.")
        elif reserve:
            reservations = session.scalars(select(BuildWorkReservationRecord).where(
                BuildWorkReservationRecord.authorization_id == grant.authorization_id)).all()
            if len(reservations) >= grant.budget.max_tool_calls or any(item.work_item_id == "structure" for item in reservations):
                raise BuildPlanIntegrityError("Approved work attempt or tool-call budget has been consumed.")
            grant.require_time_available()
            session.add(BuildWorkReservationRecord(invocation_id=invocation.id,
                authorization_id=grant.authorization_id, work_item_id="structure"))
            cls._event(session, "system_image.build.work.reserved", grant, invocation.id)
        else:
            raise BuildPlanIntegrityError("Execution consent has not reserved this canonical invocation.")
        if session.get(StructureBuildArtifactRecord, invocation.id) is None:
            grant.require_time_available()
        return grant

    def reserve(self, invocation_id, *, require_current):
        with session_scope() as session:
            invocation = session.get(ToolInvocationRecord, invocation_id)
            if invocation is None:
                raise BuildPlanIntegrityError("Canonical invocation does not exist.")
            SourceSnapshotRepository._lock(session, invocation.input_payload.get("project_id"))
            invocation = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
                .with_for_update().execution_options(populate_existing=True))
            grant = self.validate_grant_in_session(session, invocation, reserve=True)
            session.flush()
            require_current()
            return grant is not None

    @staticmethod
    def _event(session, event_type, grant, invocation_id):
        EventOutboxRepository().append(EventPayload(
            event_id=str(uuid4()), event_type=event_type, occurred_at=datetime.now(timezone.utc).isoformat(),
            correlation_id=grant.project_id, entity_type="image_build_authorization", entity_id=grant.authorization_id,
            entity_version=0, mutation_kind="append", patch={"project_id": grant.project_id,
                "authorization_id": grant.authorization_id, "goal_id": grant.goal_id, "invocation_id": invocation_id},
            query_keys=[["system-image-build-plans", grant.project_id]]), session=session)
