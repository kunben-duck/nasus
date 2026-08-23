from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


US_TASK_ANALYSIS_STATUS = "analysis"
US_TASK_PROGRESS_FLOOR = 18
US_TASK_NEXT_ACTION = "Generate test scope"
US_TASK_READY_NEXT_TOOLS = ("quality.scope.generate", "quality.scenario.generate")
US_TASK_MISSING_CONTEXT_NEXT_TOOLS = ("system_image.context.materialize",)


class USStartTaskItemLike(Protocol):
    """Minimal US work-item shape required by task-start policy."""

    id: str
    title: str
    progress: int


@dataclass(frozen=True)
class USStartTaskItemDecision:
    us_id: str
    status: str
    progress: int
    next_action: str


@dataclass(frozen=True)
class USStartTaskDecision:
    us_id: str
    title: str
    updated_item: USStartTaskItemDecision
    summary: str
    assistant_message: str
    next_tools: list[str]
    requires_followup: bool


def requested_or_first_us_id(items: list[USStartTaskItemLike], requested_us_id: str) -> str:
    if requested_us_id:
        return requested_us_id
    first_item = next(iter(items), None)
    return first_item.id if first_item else ""


def find_start_task_target(
    items: list[USStartTaskItemLike],
    requested_us_id: str,
) -> USStartTaskItemLike | None:
    us_id = requested_or_first_us_id(items, requested_us_id)
    return next((item for item in items if item.id == us_id), None)


def decide_us_task_item_start(target: USStartTaskItemLike) -> USStartTaskItemDecision:
    return USStartTaskItemDecision(
        us_id=target.id,
        status=US_TASK_ANALYSIS_STATUS,
        progress=max(target.progress, US_TASK_PROGRESS_FLOOR),
        next_action=US_TASK_NEXT_ACTION,
    )


def decide_us_task_start(
    target: USStartTaskItemLike,
    *,
    has_task_context: bool,
) -> USStartTaskDecision:
    next_tools = US_TASK_READY_NEXT_TOOLS if has_task_context else US_TASK_MISSING_CONTEXT_NEXT_TOOLS
    return USStartTaskDecision(
        us_id=target.id,
        title=target.title,
        updated_item=decide_us_task_item_start(target),
        summary=f"Started quality task for {target.id}.",
        assistant_message=(
            f"I started the quality task for **{target.title}**. Next I can generate scope, scenarios, "
            "cases, automation, and release advice."
        ),
        next_tools=list(next_tools),
        requires_followup=not has_task_context,
    )
