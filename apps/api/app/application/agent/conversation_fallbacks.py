from __future__ import annotations

from typing import Any

from ..platform.read_models import ReadModelSummaryService


class ConversationFallbackApplicationService:
    """Build fallback assistant text when the planner has no direct answer."""

    def __init__(self, summaries: ReadModelSummaryService) -> None:
        self.summaries = summaries

    def fallback_text(self, conversation: Any) -> str:
        return self.summaries.conversation_summary_fallback(conversation)


__all__ = ["ConversationFallbackApplicationService"]
