from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from .agent_models import ConversationMessage, ConversationSession, ConversationSummaryCheckpoint
from .ports import AgentConversationEventPublisherPort, ConversationSummaryStatePort


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationSummaryCheckpointService:
    """Conversation summary checkpoint policy for long-running agent sessions."""

    def completed_text_messages(self, conversation: ConversationSession) -> list[ConversationMessage]:
        return [
            message
            for message in conversation.messages
            if message.content_type in {"text", "markdown"} and message.status == "completed"
        ]

    def latest_checkpoint(
        self,
        conversation_id: str,
        checkpoints: Iterable[ConversationSummaryCheckpoint],
    ) -> ConversationSummaryCheckpoint | None:
        matching = [
            checkpoint
            for checkpoint in checkpoints
            if checkpoint.conversation_id == conversation_id
        ]
        if not matching:
            return None
        matching.sort(key=lambda checkpoint: checkpoint.created_at)
        return matching[-1]

    def build_checkpoint(
        self,
        conversation: ConversationSession,
        checkpoints: Iterable[ConversationSummaryCheckpoint],
        *,
        force: bool = False,
        created_by: str = "system",
    ) -> ConversationSummaryCheckpoint | None:
        text_messages = self.completed_text_messages(conversation)
        if len(text_messages) < 8 and not force:
            return None
        if not text_messages:
            return None

        latest_checkpoint = self.latest_checkpoint(conversation.id, checkpoints)
        latest_checkpoint_end = latest_checkpoint.message_range_end if latest_checkpoint else None
        start_index = 0
        if latest_checkpoint_end:
            for index, message in enumerate(text_messages):
                if message.id == latest_checkpoint_end:
                    start_index = index + 1
                    break

        checkpoint_candidates = text_messages[start_index:]
        if not checkpoint_candidates:
            return None
        if len(checkpoint_candidates) < 6 and not force:
            return None

        messages_to_summarize = checkpoint_candidates if force else checkpoint_candidates[:-4]
        if len(messages_to_summarize) < 4 and not force:
            return None

        summary_lines = self._summary_lines(messages_to_summarize)
        if not summary_lines:
            return None

        return ConversationSummaryCheckpoint(
            id=f"chk_{uuid4().hex[:10]}",
            conversation_id=conversation.id,
            message_range_start=messages_to_summarize[0].id,
            message_range_end=messages_to_summarize[-1].id,
            summary_text="\n".join(summary_lines),
            summary_object_refs=[],
            summary_token_count=len(" ".join(summary_lines).split()),
            created_by=created_by,  # type: ignore[arg-type]
            created_at=_now_iso(),
        )

    def _summary_lines(self, messages: list[ConversationMessage]) -> list[str]:
        summary_lines: list[str] = []
        for message in messages[-8:]:
            text = " ".join(block.text.strip() for block in message.blocks if block.text.strip())
            if not text:
                continue
            compact_text = re.sub(r"\s+", " ", text)
            if len(compact_text) > 160:
                compact_text = f"{compact_text[:157]}..."
            actor = "User" if message.role == "user" else "Agent"
            summary_lines.append(f"{actor}: {compact_text}")
        return summary_lines


class ConversationSummaryCheckpointApplicationService:
    """Persists summary checkpoints and publishes conversation memory events."""

    def __init__(
        self,
        state: ConversationSummaryStatePort,
        events: AgentConversationEventPublisherPort,
        policy: ConversationSummaryCheckpointService | None = None,
    ) -> None:
        self._state = state
        self._events = events
        self.policy = policy or ConversationSummaryCheckpointService()

    def latest_checkpoint(self, conversation_id: str) -> ConversationSummaryCheckpoint | None:
        return self.policy.latest_checkpoint(
            conversation_id,
            self._state.list_summary_checkpoints(),
        )

    def build_checkpoint(
        self,
        conversation: ConversationSession,
        *,
        force: bool = False,
        created_by: str = "system",
    ) -> ConversationSummaryCheckpoint | None:
        return self.policy.build_checkpoint(
            conversation,
            self._state.list_summary_checkpoints(),
            force=force,
            created_by=created_by,
        )

    async def maybe_create_checkpoint(self, conversation: ConversationSession) -> ConversationSummaryCheckpoint | None:
        checkpoint = self.build_checkpoint(conversation)
        if checkpoint is None:
            return None

        latest_checkpoint = self.latest_checkpoint(conversation.id)
        if latest_checkpoint and latest_checkpoint.message_range_end == checkpoint.message_range_end:
            return latest_checkpoint

        conversation.latest_summary_checkpoint_id = checkpoint.id
        self._state.persist_summary_checkpoint(conversation, checkpoint)
        await self._events.publish_summary_updated(conversation.id, checkpoint.id)
        return checkpoint
