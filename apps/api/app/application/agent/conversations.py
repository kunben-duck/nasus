from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from .agent_models import (
    ConversationArchiveRequest,
    ConversationCreateRequest,
    ConversationLink,
    ConversationMergeRequest,
    ConversationMessage,
    ConversationSession,
)
from .ports import ConversationManagementStatePort
from ..platform.errors import PlatformApplicationError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationManagementApplicationService:
    """Conversation lifecycle, discovery, archive, and merge use cases."""

    def __init__(self, state: ConversationManagementStatePort) -> None:
        self._state = state

    def ensure_conversation(self, payload: ConversationCreateRequest) -> ConversationSession:
        return self.get_or_create_conversation(
            payload.space_type,
            payload.space_id,
            payload.title or payload.space_id,
            project_id=payload.project_id,
            version_id=payload.version_id,
            us_id=payload.us_id,
        )

    def resolve_conversation_scope(
        self,
        space_type: str,
        space_id: str,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        us_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        return self._state.resolve_scope(
            space_type,
            space_id,
            project_id=project_id,
            version_id=version_id,
            us_id=us_id,
        )

    def get_or_create_conversation(
        self,
        space_type: str,
        space_id: str,
        title: str,
        *,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        us_id: Optional[str] = None,
    ) -> ConversationSession:
        resolved_project_id, resolved_version_id, resolved_us_id = self.resolve_conversation_scope(
            space_type,
            space_id,
            project_id=project_id,
            version_id=version_id,
            us_id=us_id,
        )
        if resolved_project_id:
            self._state.require_project_access(resolved_project_id)
        owner_key = (
            f"project:{resolved_project_id}"
            if resolved_project_id
            else f"user:{self._state.current_user_id()}"
        )
        key = (space_type, space_id, owner_key)
        conversation = self._state.find_conversation(
            space_type=space_type,
            space_id=space_id,
            owner_key=owner_key,
        )
        if conversation is not None:
            self._state.require_conversation_access(conversation)
            return conversation

        conversation_id = f"conv_{uuid4().hex[:10]}"
        conversation = ConversationSession(
            id=conversation_id,
            session_id=f"session_{uuid4().hex[:8]}",
            title=title,
            space_type=space_type,  # type: ignore[arg-type]
            space_id=space_id,
            project_id=resolved_project_id,
            version_id=resolved_version_id,
            us_id=resolved_us_id,
            initiator_id=self._state.current_user_id(),
            status="draft",
            messages=[],
            agent_goals=[],
            tool_invocations=[],
        )
        self._state.persist_conversation(conversation, lookup_key=key)
        return conversation

    def list_conversations(
        self,
        *,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        space_type: Optional[str] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> list[ConversationSession]:
        conversations = [
            conversation
            for conversation in self._state.list_conversations()
            if self._state.can_access_conversation(conversation)
        ]
        if project_id:
            conversations = [conversation for conversation in conversations if conversation.project_id == project_id]
        if version_id:
            conversations = [conversation for conversation in conversations if conversation.version_id == version_id]
        if space_type:
            conversations = [conversation for conversation in conversations if conversation.space_type == space_type]
        if status:
            conversations = [conversation for conversation in conversations if conversation.status == status]
        if q:
            needle = q.lower()
            conversations = [
                conversation
                for conversation in conversations
                if needle in conversation.title.lower()
                or any(
                    block.text and needle in block.text.lower()
                    for message in conversation.messages
                    for block in message.blocks
                )
            ]
        return conversations

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        conversation = self._state.get_conversation(conversation_id)
        self._state.require_conversation_access(conversation)
        return conversation

    def list_conversation_messages(
        self,
        conversation_id: str,
        before_message_id: Optional[str] = None,
    ) -> list[ConversationMessage]:
        messages = self.get_conversation(conversation_id).messages
        if before_message_id is None:
            return messages
        for index, message in enumerate(messages):
            if message.id == before_message_id:
                return messages[:index]
        return messages

    def archive_conversation(
        self,
        conversation_id: str,
        payload: ConversationArchiveRequest,
    ) -> ConversationSession:
        conversation = self.get_conversation(conversation_id)
        if payload.archive:
            conversation.status = "archived"
            conversation.archived_at = _now_iso()
        else:
            conversation.status = "active" if conversation.messages else "draft"
            conversation.archived_at = None
        self._state.persist_conversation(conversation)
        return conversation

    def merge_conversations(self, conversation_id: str, payload: ConversationMergeRequest) -> dict[str, Any]:
        source = self.get_conversation(conversation_id)
        target = self.get_conversation(payload.target_conversation_id)
        if source.project_id != target.project_id:
            raise PlatformApplicationError(
                "conversation_scope_mismatch",
                "Conversations from different project scopes cannot be merged.",
                409,
            )

        target.messages.extend(deepcopy(source.messages))
        target.agent_goals.extend(deepcopy(source.agent_goals))
        target.last_message_at = target.messages[-1].created_at if target.messages else target.last_message_at
        target.status = "active" if target.messages else target.status

        source.status = "merged"
        source.merged_into_conversation_id = target.id

        link = ConversationLink(
            id=f"cl_{uuid4().hex[:10]}",
            left_conversation_id=source.id,
            right_conversation_id=target.id,
            link_kind="merged_from",
            reason="merged through API request",
            confidence=1.0,
            created_at=_now_iso(),
        )
        self._state.persist_conversation_link(link)
        source.related_conversation_ids.append(target.id)
        target.related_conversation_ids.append(source.id)
        self._state.persist_conversation(source)
        self._state.persist_conversation(target)
        return {"target_conversation_id": target.id, "link": link}

    def search_conversations(self, q: str) -> dict[str, Any]:
        matches = self.list_conversations(q=q)
        message_hits = []
        needle = q.lower()
        for conversation in matches:
            for message in conversation.messages:
                for block in message.blocks:
                    if block.text and needle in block.text.lower():
                        message_hits.append(
                            {
                                "conversation_id": conversation.id,
                                "message_id": message.id,
                                "excerpt": block.text[:180],
                            }
                        )
                        break

        matched_conversation_ids = {conversation.id for conversation in matches}
        related_links = [
            link
            for link in self._state.list_conversation_links()
            if link.left_conversation_id in matched_conversation_ids
            or link.right_conversation_id in matched_conversation_ids
        ]
        return {
            "query": q,
            "conversations": matches,
            "message_hits": message_hits,
            "related_links": related_links,
        }
