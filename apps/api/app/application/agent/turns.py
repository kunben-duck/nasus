from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, AsyncIterator, Callable, Protocol
from uuid import uuid4

from ..platform.account_models import UserProfile
from .agent_models import ConversationTurn, ConversationTurnAccepted
from .message_writer import ConversationMessageWriterApplicationService
from .ports import AgentConversationEventPublisherPort
from .stream_batching import stream_with_idle_flush


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ConversationTurnExecutionRequest:
    turn_id: str
    conversation_id: str
    content: str
    canonical_action_id: str | None
    actor: UserProfile | None = None
    request_id: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "conversation_id": self.conversation_id,
            "content": self.content,
            "canonical_action_id": self.canonical_action_id,
            "actor": self.actor.model_dump() if self.actor is not None else None,
            "request_id": self.request_id,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ConversationTurnExecutionRequest":
        actor_payload = payload.get("actor")
        return cls(
            turn_id=str(payload["turn_id"]),
            conversation_id=str(payload["conversation_id"]),
            content=str(payload["content"]),
            canonical_action_id=(
                str(payload["canonical_action_id"])
                if payload.get("canonical_action_id")
                else None
            ),
            actor=UserProfile(**actor_payload) if isinstance(actor_payload, dict) else None,
            request_id=str(payload["request_id"]) if payload.get("request_id") else None,
        )


class ConversationTurnRepositoryPort(Protocol):
    def create(self, turn: ConversationTurn) -> tuple[ConversationTurn, bool]:
        ...

    def get(self, turn_id: str) -> ConversationTurn | None:
        ...

    def find_idempotent(self, conversation_id: str, idempotency_key: str) -> ConversationTurn | None:
        ...

    def active_for_conversation(self, conversation_id: str) -> ConversationTurn | None:
        ...

    def upsert(self, turn: ConversationTurn) -> None:
        ...


class ConversationTurnGraphPort(Protocol):
    def astream(self, request: ConversationTurnExecutionRequest) -> AsyncIterator[dict[str, Any]]:
        ...


class ConversationTurnWorkflowRuntimePort(Protocol):
    async def start_turn(self, request: ConversationTurnExecutionRequest) -> str:
        ...

    async def cancel_turn(self, turn_id: str, workflow_id: str | None) -> None:
        ...


class ConversationTurnConflict(RuntimeError):
    pass


class ConversationTurnApplicationService:
    """Accepts turns quickly and persists graph stream events as conversation facts."""

    def __init__(
        self,
        repository: ConversationTurnRepositoryPort,
        messages: ConversationMessageWriterApplicationService,
        events: AgentConversationEventPublisherPort,
        graph: ConversationTurnGraphPort,
    ) -> None:
        self._repository = repository
        self._messages = messages
        self._events = events
        self._graph = graph
        self._workflow_runtime: ConversationTurnWorkflowRuntimePort | None = None

    def bind_workflow_runtime(self, runtime: ConversationTurnWorkflowRuntimePort) -> None:
        self._workflow_runtime = runtime

    async def accept_turn(
        self,
        *,
        conversation_id: str,
        content: str,
        idempotency_key: str,
        canonical_action_id: str | None,
        events_url: str,
        actor: UserProfile | None,
        request_id: str | None,
    ) -> ConversationTurnAccepted:
        existing = self._repository.find_idempotent(conversation_id, idempotency_key)
        if existing is not None:
            return self._accepted(existing, events_url)
        active = self._repository.active_for_conversation(conversation_id)
        if active is not None:
            raise ConversationTurnConflict(
                f"Conversation {conversation_id} already has active turn {active.id}."
            )
        user_message = await self._messages.append_text_message(
            conversation_id,
            "user",
            content,
            metadata={
                "initiator_surface": "ui",
                "canonical_action_id": canonical_action_id,
                "idempotency_key": idempotency_key,
            },
        )
        now = _now_iso()
        turn, created = self._repository.create(
            ConversationTurn(
                id=f"turn_{uuid4().hex[:20]}",
                conversation_id=conversation_id,
                user_message_id=user_message.id,
                idempotency_key=idempotency_key,
                status="accepted",
                result={},
                created_at=now,
                updated_at=now,
            )
        )
        if not created:
            return self._accepted(turn, events_url)
        await self._events.publish_turn_event(
            conversation_id,
            turn.id,
            "conversation.turn.accepted",
            {"status": "accepted", "user_message_id": user_message.id},
        )
        if self._workflow_runtime is None:
            raise RuntimeError("Conversation turn workflow runtime is not configured")
        request = ConversationTurnExecutionRequest(
            turn_id=turn.id,
            conversation_id=conversation_id,
            content=content,
            canonical_action_id=canonical_action_id,
            actor=actor,
            request_id=request_id,
        )
        workflow_id = await self._workflow_runtime.start_turn(request)
        current_turn = self.get_turn(turn.id)
        current_turn.workflow_id = workflow_id
        current_turn.updated_at = _now_iso()
        self._repository.upsert(current_turn)
        return self._accepted(current_turn, events_url)

    def get_turn(self, turn_id: str) -> ConversationTurn:
        turn = self._repository.get(turn_id)
        if turn is None:
            raise KeyError(turn_id)
        return turn

    async def cancel_turn(self, conversation_id: str, turn_id: str) -> ConversationTurn:
        turn = self.get_turn(turn_id)
        if turn.conversation_id != conversation_id:
            raise KeyError(turn_id)
        if turn.status in {"completed", "interrupted", "failed"}:
            return turn
        turn.status = "interrupted"
        turn.updated_at = _now_iso()
        turn.completed_at = turn.updated_at
        self._repository.upsert(turn)
        if self._workflow_runtime is not None:
            await self._workflow_runtime.cancel_turn(turn.id, turn.workflow_id)
        if turn.assistant_message_id:
            message = self._find_message(turn)
            if message is not None and message.status == "streaming" and message.stream_id:
                await self._messages.finish_streaming_message(
                    conversation_id,
                    message.id,
                    stream_id=message.stream_id,
                    status="interrupted",
                )
        await self._publish_terminal_turn(turn)
        return turn

    async def execute_turn(
        self,
        request: ConversationTurnExecutionRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> ConversationTurn:
        turn = self.get_turn(request.turn_id)
        if turn.status in {"completed", "interrupted", "failed"}:
            return turn
        turn.status = "planning"
        turn.updated_at = _now_iso()
        self._repository.upsert(turn)

        message_id: str | None = turn.assistant_message_id
        stream_id: str | None = None
        sequence = 0
        pending_delta = ""
        last_flush = monotonic()
        stream_metadata: dict[str, Any] = {}
        if message_id is not None:
            existing_message = self._messages.get_message(
                request.conversation_id,
                message_id,
            )
            if existing_message is not None and existing_message.stream_id:
                stream_id = existing_message.stream_id
                sequence = existing_message.sequence_max or 0

        async def flush_delta() -> None:
            nonlocal pending_delta, sequence, last_flush
            if not pending_delta or not message_id or not stream_id:
                return
            # Retry the same identity if persistence commits before cancellation.
            next_sequence = sequence + 1
            await self._messages.append_stream_delta(
                request.conversation_id,
                message_id,
                stream_id=stream_id,
                sequence=next_sequence,
                delta=pending_delta,
            )
            sequence = next_sequence
            pending_delta = ""
            last_flush = monotonic()

        async def flush_idle_delta() -> None:
            if cancelled and cancelled():
                raise asyncio.CancelledError
            if pending_delta:
                if self.get_turn(turn.id).status == "interrupted":
                    raise asyncio.CancelledError
                await flush_delta()

        stream = stream_with_idle_flush(self._graph.astream(request), flush_idle_delta)
        try:
            async for event in stream:
                if cancelled and cancelled():
                    raise asyncio.CancelledError
                current = self.get_turn(turn.id)
                if current.status == "interrupted":
                    raise asyncio.CancelledError
                kind = str(event.get("kind") or "")
                if kind == "started":
                    stream_metadata.update(dict(event.get("metadata") or {}))
                    if message_id is None:
                        stream_id = f"stream_{uuid4().hex[:20]}"
                        message = await self._messages.start_streaming_message(
                            request.conversation_id,
                            turn_id=turn.id,
                            stream_id=stream_id,
                            metadata=stream_metadata,
                        )
                        message_id = message.id
                        turn.assistant_message_id = message.id
                        turn.status = "streaming"
                        turn.updated_at = _now_iso()
                        self._repository.upsert(turn)
                elif kind == "delta":
                    pending_delta += str(event.get("delta") or "")
                    if monotonic() - last_flush >= 0.05:
                        await flush_delta()
                elif kind == "usage":
                    stream_metadata.update(dict(event.get("metadata") or {}))
                elif kind == "completed":
                    stream_metadata.update(dict(event.get("metadata") or {}))
                    await flush_delta()
                    if message_id and stream_id:
                        await self._messages.finish_streaming_message(
                            request.conversation_id,
                            message_id,
                            stream_id=stream_id,
                            status="completed",
                            metadata=stream_metadata,
                        )
                elif kind == "failed":
                    await flush_delta()
                    error = str(event.get("error") or "Provider stream failed")
                    if message_id and stream_id:
                        await self._messages.finish_streaming_message(
                            request.conversation_id,
                            message_id,
                            stream_id=stream_id,
                            status="failed",
                            metadata=dict(event.get("metadata") or {}),
                            error=error,
                        )
                    raise RuntimeError(error)
                elif kind == "turn_result":
                    turn.result = dict(event.get("result") or {})

            await flush_delta()
            turn.status = "completed"
            turn.updated_at = _now_iso()
            turn.completed_at = turn.updated_at
            self._repository.upsert(turn)
            await self._publish_terminal_turn(turn)
            return turn
        except asyncio.CancelledError:
            turn = self.get_turn(turn.id)
            already_interrupted = turn.status == "interrupted"
            if not already_interrupted:
                turn.status = "interrupted"
                turn.updated_at = _now_iso()
                turn.completed_at = turn.updated_at
            if message_id and stream_id:
                message = self._find_message(turn)
                if message is not None and message.status == "streaming":
                    await flush_delta()
                    await self._messages.finish_streaming_message(
                        request.conversation_id,
                        message_id,
                        stream_id=stream_id,
                        status="interrupted",
                    )
            if not already_interrupted:
                self._repository.upsert(turn)
                await self._publish_terminal_turn(turn)
            return turn
        except Exception as exc:
            turn = self.get_turn(turn.id)
            turn.status = "failed"
            turn.error = str(exc)
            turn.updated_at = _now_iso()
            turn.completed_at = turn.updated_at
            if message_id and stream_id:
                message = self._find_message(turn)
                if message is not None and message.status == "streaming":
                    await flush_delta()
                    await self._messages.finish_streaming_message(
                        request.conversation_id,
                        message_id,
                        stream_id=stream_id,
                        status="failed",
                        error=str(exc),
                    )
            self._repository.upsert(turn)
            await self._publish_terminal_turn(turn)
            return turn

        finally:
            await stream.aclose()

    def _find_message(self, turn: ConversationTurn):
        if turn.assistant_message_id is None:
            return None
        return self._messages.get_message(
            turn.conversation_id,
            turn.assistant_message_id,
        )

    async def _publish_terminal_turn(self, turn: ConversationTurn) -> None:
        await self._events.publish_turn_event(
            turn.conversation_id,
            turn.id,
            f"conversation.turn.{turn.status}",
            {
                "status": turn.status,
                "assistant_message_id": turn.assistant_message_id,
                "result": turn.result,
                "error": turn.error,
            },
        )

    @staticmethod
    def _accepted(turn: ConversationTurn, events_url: str) -> ConversationTurnAccepted:
        return ConversationTurnAccepted(
            turn_id=turn.id,
            conversation_id=turn.conversation_id,
            user_message_id=turn.user_message_id,
            events_url=events_url,
        )


__all__ = [
    "ConversationTurnApplicationService",
    "ConversationTurnConflict",
    "ConversationTurnExecutionRequest",
    "ConversationTurnWorkflowRuntimePort",
]
