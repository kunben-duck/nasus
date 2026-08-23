from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QualityLoopUseCaseResult:
    summary: str
    project_id: str
    us_id: str
    object_refs: list[str]
    evidence_refs: list[str]
    next_tools: list[str]
    query_keys: list[list[str]]
    assistant_message: str | None = None
    assistant_metadata: dict[str, Any] = field(default_factory=dict)


class QualityLoopApplicationError(ValueError):
    """Raised when a quality-loop command cannot be executed."""

    def __init__(self, summary: str, *, next_tools: list[str] | None = None) -> None:
        super().__init__(summary)
        self.summary = summary
        self.next_tools = next_tools or []


__all__ = ["QualityLoopApplicationError", "QualityLoopUseCaseResult"]
