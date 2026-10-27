"""Original command attribution for metadata-only RunPlan fact events."""
from ...domain.quality_loop.run_plan import RunPlanIntegrityError
from .db_models import ToolInvocationRecord


def verify_run_plan_event_envelope(session, event, row, *, entity_type, query_key, error=RunPlanIntegrityError):
    command = session.get(ToolInvocationRecord, row.invocation_id)
    if (command is None or event.entity_type != entity_type
            or event.correlation_id != row.project_id or event.occurred_at != row.recorded_at
            or event.conversation_id != command.conversation_id
            or event.agent_goal_id != command.input_payload.get("agent_goal_id")
            or event.mutation_kind != "append" or event.snapshot_hint is not True
            or event.query_keys != [[query_key, row.project_id]] or event.payload != {}
            or any(getattr(event, key) is not None for key in (
                "tool_invocation_id", "agent_step_id", "swarm_run_id", "assignment_id", "task_id", "run_id"))):
        raise error("RunPlan fact event differs from its original command envelope")
