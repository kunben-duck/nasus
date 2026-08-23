from __future__ import annotations

from typing import Protocol, Sequence

from ...domain.platform.llm_call import LLMCall


class LLMCallAuditPort(Protocol):
    def persist_llm_call(self, call: LLMCall) -> None: ...

    def list_llm_calls(
        self,
        *,
        route: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        agent_goal_id: str | None = None,
        tool_invocation_id: str | None = None,
        limit: int = 100,
    ) -> Sequence[LLMCall]: ...


class LLMCallAuditApplicationService:
    """Write and operational query use cases for redacted model-call facts."""

    def __init__(self, persistence: LLMCallAuditPort) -> None:
        self._persistence = persistence

    def record(self, call: LLMCall) -> None:
        self._persistence.persist_llm_call(call)

    def list_calls(
        self,
        *,
        route: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        agent_goal_id: str | None = None,
        tool_invocation_id: str | None = None,
        limit: int = 100,
    ) -> list[LLMCall]:
        return list(
            self._persistence.list_llm_calls(
                route=route,
                project_id=project_id,
                conversation_id=conversation_id,
                agent_goal_id=agent_goal_id,
                tool_invocation_id=tool_invocation_id,
                limit=max(1, min(limit, 500)),
            )
        )


__all__ = ["LLMCallAuditApplicationService", "LLMCallAuditPort"]
