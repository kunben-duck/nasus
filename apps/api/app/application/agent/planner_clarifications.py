"""Validate planner clarification text rather than fabricate missing context."""
from ...domain.agent.runtime_models import ClarificationRequest, OrchestratorDecision


CLARIFICATION_INSTRUCTIONS = (
    'For clarification return {"kind":"clarification","question":"...","reason":"...","missing_context":[]}. '
    "The question must be nonempty, concrete and in the user's language. Distinguish missing inputs from "
    "unavailable capabilities: if no registered tool supports the requested action, explain that it is not "
    "implemented and that nothing was executed; do not request more context or confirmation as if the tool exists."
)


def parse_clarification(payload):
    details = payload if payload.get("question") is not None else payload.get("clarification")
    if not isinstance(details, dict):
        return None
    question = details.get("question")
    if not isinstance(question, str) or not question.strip():
        return None
    missing = details.get("missing_context", [])
    if missing is None:
        missing = []
    if not isinstance(missing, list) or any(not isinstance(item, str) for item in missing):
        return None
    reason = details.get("reason", "planner_clarification")
    if not isinstance(reason, str):
        return None
    return OrchestratorDecision(kind="clarification", clarification=ClarificationRequest(
        question=question.strip(), reason=reason.strip() or "planner_clarification", missing_context=missing,
    ))
