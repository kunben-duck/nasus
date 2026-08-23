from __future__ import annotations

from typing import Any, Protocol

from ...domain.agent.memory import AgentMemoryContext
from ...domain.platform.llm_call import LLMCallContext
from ..platform.model_settings import StudioSettings
from .agent_models import ConversationMessage, ConversationSession


class AgentReplyGenerationResult(Protocol):
    content: str
    provider: str
    model_name: str
    mode: str
    reason: str
    llm_call_id: str | None


class AgentReplyMemoryPort(Protocol):
    """Builds the governed memory package for one Agent model call."""

    async def build_context(
        self,
        conversation: ConversationSession,
        *,
        trace_retrieval: bool = False,
    ) -> AgentMemoryContext:
        ...


class AgentReplyGenerationPort(Protocol):
    """Executes the selected chat-model route without exposing provider details."""

    async def generate_reply(
        self,
        *,
        settings: StudioSettings,
        system_prompt: str,
        user_message: str,
        context_snapshot: str,
        history_snapshot: str,
        fallback_text: str,
        custom_api_key: str | None = None,
        call_context: LLMCallContext | None = None,
    ) -> AgentReplyGenerationResult:
        ...


class AgentReplyModelSettingsPort(Protocol):
    """Resolves the active model route and its secret at call time."""

    def get_settings(self) -> StudioSettings:
        ...

    def get_custom_model_api_key(self, model_route: str = "chat") -> str:
        ...


class AgentReplyMessageWriterPort(Protocol):
    """Persists assistant output through the canonical conversation writer."""

    async def append_text_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        tone: str | None = None,
        metadata: dict[str, Any] | None = None,
        tool_refs: list[str] | None = None,
        object_refs: list[str] | None = None,
    ) -> ConversationMessage:
        ...


__all__ = [
    "AgentReplyGenerationPort",
    "AgentReplyGenerationResult",
    "AgentReplyMemoryPort",
    "AgentReplyMessageWriterPort",
    "AgentReplyModelSettingsPort",
]
