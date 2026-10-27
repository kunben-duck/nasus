"""Remove runtime coordination fields without accepting arbitrary tool inputs."""

CONTEXT_KEYS = frozenset({
    "idempotency_key", "agent_goal_id", "agent_step_id", "agent_plan_step_id",
    "requested_tool_id", "user_message", "planner_kind", "stream_reply",
    "version_id", "us_id", "task_id", "conversation_id",
    "agent_loop_iteration_id", "agent_loop_attempt",
    "goal_template", "goal_description", "tool_plan_index", "tool_plan_reason",
    "confirmed_actor_id",
    "fixture_claim_protocol",
    "case_claim_protocol",
})


def query_payload(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in CONTEXT_KEYS}
