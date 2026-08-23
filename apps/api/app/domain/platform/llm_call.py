from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


LLMCallRoute = Literal["chat", "embedding", "rerank"]
LLMCallMode = Literal["live", "fallback"]
LLMCallOutcome = Literal["success", "fallback", "error", "skipped"]
LLMUsageSource = Literal["provider", "estimated", "none"]


@dataclass(frozen=True)
class LLMCallContext:
    """Non-sensitive business correlation attached to one model route call."""

    purpose: str
    prompt_id: str | None = None
    prompt_version: str | None = None
    project_id: str | None = None
    version_id: str | None = None
    task_id: str | None = None
    conversation_id: str | None = None
    agent_goal_id: str | None = None
    tool_invocation_id: str | None = None


@dataclass(frozen=True)
class LLMCall:
    """Durable, redacted fact for one call through the Model Gateway."""

    id: str
    occurred_at: datetime
    route: LLMCallRoute
    purpose: str
    provider: str
    model_name: str
    selected_provider: str
    selected_model_name: str
    runtime_mode: LLMCallMode
    outcome: LLMCallOutcome
    reason: str
    prompt_id: str | None = None
    prompt_version: str | None = None
    project_id: str | None = None
    version_id: str | None = None
    task_id: str | None = None
    conversation_id: str | None = None
    agent_goal_id: str | None = None
    tool_invocation_id: str | None = None
    model_calls: int = 0
    input_token_count: int = 0
    output_token_count: int = 0
    usage_source: LLMUsageSource = "none"
    latency_ms: int = 0
    input_item_count: int = 0
    output_item_count: int = 0
    request_hash: str = ""
    response_hash: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.purpose:
            raise ValueError("LLMCall requires id and purpose")
        for value in (
            self.model_calls,
            self.input_token_count,
            self.output_token_count,
            self.latency_ms,
            self.input_item_count,
            self.output_item_count,
        ):
            if value < 0:
                raise ValueError("LLMCall counters cannot be negative")


__all__ = [
    "LLMCall",
    "LLMCallContext",
    "LLMCallMode",
    "LLMCallOutcome",
    "LLMCallRoute",
    "LLMUsageSource",
]
