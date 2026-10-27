"""Bind confirmed manual plan controls to their original goal before charging."""
from datetime import datetime, timezone

from sqlalchemy import select

from ...application.agent.image_plan_phases import ImagePlanPhaseInput
from ...application.platform.tool_handlers.query_input import query_payload
from ...application.system_image.build_plan_revisions import BuildPlanRevisionInput, REVISE_PLAN_TOOL
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.build_plan_revisions import REVISION_PAUSE_REASONS
from .build_plan_models import BuildPlanRecord
from .build_plan_repository import BuildPlanRepository
from .build_plan_revision_models import BuildPlanRevisionRecord
from .build_plan_revision_repository import BuildPlanRevisionRepository
from .conversation_repository import ConversationRepository
from .db_models import UserIdentityRecord
from .image_plan_phase_repository import ImagePlanPhaseRepository


def confirmed_control_work_key(session, goal, command):
    body = query_payload(command.input_payload)
    confirmed, confirmed_at = body.pop("confirmed_by_user", None), body.pop("confirmed_at", None)
    model = BuildPlanRevisionInput if command.tool_id == REVISE_PLAN_TOOL else ImagePlanPhaseInput
    request = model.model_validate(body)
    actor = session.get(UserIdentityRecord, command.input_payload.get("confirmed_actor_id"))
    if (confirmed is not True or actor is None or actor.status != "active"
            or command.conversation_id != goal.conversation_id
            or (request.project_id, request.goal_id) != (goal.project_id, goal.id)
            or goal.status != "paused" or goal.pause_reason not in REVISION_PAUSE_REASONS):
        raise BuildPlanIntegrityError("Manual tool work requires the original confirmed review checkpoint.")
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(confirmed_at)).total_seconds()
        if not 0 <= elapsed <= 900:
            raise ValueError("expired")
    except (TypeError, ValueError) as exc:
        raise BuildPlanIntegrityError("Manual tool work confirmation is invalid or expired.") from exc
    current = ConversationRepository._to_goal(goal)
    request.checkpoint().require_matches(current.model_dump(mode="json"))
    roots = [ref.removeprefix("build_plan:") for ref in goal.target_refs if ref.startswith("build_plan:")]
    if roots != [request.root_plan_id]:
        raise BuildPlanIntegrityError("Manual tool work cannot change the original plan root.")
    phases, _ = ImagePlanPhaseRepository.scope_in_session(session, current)
    row = session.scalar(select(BuildPlanRevisionRecord).where(
        BuildPlanRevisionRecord.goal_id == goal.id).order_by(BuildPlanRevisionRecord.revision_number.desc()).limit(1))
    latest = BuildPlanRevisionRepository._stored(row) if row else None
    if latest and (latest.revision.project_id, latest.revision.root_plan_id) != (goal.project_id, request.root_plan_id):
        raise BuildPlanIntegrityError("Manual tool work revision belongs to another original plan.")
    if command.tool_id == REVISE_PLAN_TOOL:
        if (request.from_plan_id, request.parent_revision_id, request.parent_revision_hash) != (
                latest.revision.plan_id if latest else request.root_plan_id,
                latest.revision.revision_id if latest else None, latest.revision_hash if latest else None):
            raise BuildPlanIntegrityError("Manual tool work must retain the current revision head.")
        plan = session.get(BuildPlanRecord, request.from_plan_id)
        if (plan is None or plan.project_id != goal.project_id
                or BuildPlanRepository._stored(session, plan).plan_digest != request.from_plan_digest):
            raise BuildPlanIntegrityError("Manual tool work original plan digest changed.")
    else:
        if latest is None or (request.revision_id, request.revision_hash) != (
                latest.revision.revision_id, latest.revision_hash):
            raise BuildPlanIntegrityError("Manual tool work requires the exact current revision.")
        parent = phases[-1] if phases else None
        if (request.parent_phase_id, request.parent_phase_hash) != (
                parent.phase.phase_id if parent else None, parent.phase_hash if parent else None):
            raise BuildPlanIntegrityError("Manual tool work must retain the current phase head.")
        if latest.revision.from_plan_id != (parent.phase.plan_id if parent else request.root_plan_id):
            raise BuildPlanIntegrityError("Manual tool work cannot skip an input revision.")
    return "confirmed-goal-control:" + command.id
