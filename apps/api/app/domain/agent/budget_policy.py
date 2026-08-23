from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable, Protocol

from .runtime_models import ModelUsage


class AgentBudgetGoal(Protocol):
    max_steps: int
    max_model_calls: int
    max_thinking_tokens: int
    max_runtime_seconds: int
    max_no_progress_observations: int
    steps_completed: int
    model_calls_used: int
    thinking_input_tokens_used: int
    thinking_output_tokens_used: int
    thinking_tokens_used: int
    no_progress_observations: int
    started_at: str | None
    last_progress_at: str | None
    last_progress_fingerprint: str | None
    budget_exhausted_reason: str | None


@dataclass(frozen=True)
class AgentBudgetDecision:
    exhausted: bool
    reason: str | None = None
    summary: str = ""


def evaluate_agent_budget(
    goal: AgentBudgetGoal,
    *,
    now: datetime | None = None,
) -> AgentBudgetDecision:
    checks = (
        (
            goal.steps_completed >= goal.max_steps,
            "max_steps",
            f"Step budget exhausted ({goal.steps_completed}/{goal.max_steps}).",
        ),
        (
            goal.model_calls_used >= goal.max_model_calls,
            "max_model_calls",
            f"Model-call budget exhausted ({goal.model_calls_used}/{goal.max_model_calls}).",
        ),
        (
            goal.thinking_tokens_used >= goal.max_thinking_tokens,
            "max_thinking_tokens",
            f"Thinking-token budget exhausted ({goal.thinking_tokens_used}/{goal.max_thinking_tokens}).",
        ),
        (
            _runtime_seconds(goal.started_at, now=now) >= goal.max_runtime_seconds,
            "max_runtime_seconds",
            f"Runtime budget exhausted ({_runtime_seconds(goal.started_at, now=now)}/{goal.max_runtime_seconds}s).",
        ),
        (
            goal.no_progress_observations >= goal.max_no_progress_observations,
            "max_no_progress_observations",
            (
                "No-progress observation budget exhausted "
                f"({goal.no_progress_observations}/{goal.max_no_progress_observations})."
            ),
        ),
    )
    for exhausted, reason, summary in checks:
        if exhausted:
            return AgentBudgetDecision(True, reason, summary)
    return AgentBudgetDecision(False)


def record_model_usage(goal: AgentBudgetGoal, usage: ModelUsage) -> None:
    goal.model_calls_used += max(0, usage.model_calls)
    goal.thinking_input_tokens_used += max(0, usage.input_tokens)
    goal.thinking_output_tokens_used += max(0, usage.output_tokens)
    goal.thinking_tokens_used = (
        goal.thinking_input_tokens_used + goal.thinking_output_tokens_used
    )


def observation_progress_fingerprint(
    *,
    tool_id: str,
    status: str,
    summary: str,
    object_refs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    next_recommended_tools: Iterable[str] = (),
    requires_followup: bool = False,
) -> str:
    payload = {
        "tool_id": tool_id,
        "status": status,
        "summary": " ".join(summary.split()),
        "object_refs": sorted(set(object_refs)),
        "evidence_refs": sorted(set(evidence_refs)),
        "next_recommended_tools": sorted(set(next_recommended_tools)),
        "requires_followup": requires_followup,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def record_observation_progress(
    goal: AgentBudgetGoal,
    *,
    fingerprint: str,
    occurred_at: str,
) -> bool:
    if goal.last_progress_fingerprint == fingerprint:
        goal.no_progress_observations += 1
        return False
    goal.last_progress_fingerprint = fingerprint
    goal.last_progress_at = occurred_at
    goal.no_progress_observations = 0
    return True


def _runtime_seconds(started_at: str | None, *, now: datetime | None) -> int:
    if not started_at:
        return 0
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0, int((current - started).total_seconds()))


__all__ = [
    "AgentBudgetDecision",
    "evaluate_agent_budget",
    "observation_progress_fingerprint",
    "record_model_usage",
    "record_observation_progress",
]
