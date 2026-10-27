from __future__ import annotations

import asyncio
from contextlib import suppress
import sys
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional, TypedDict

from ...application.agent.messages import ConversationMessageApplicationService
from ...application.agent.turn_stream import turn_stream_scope
from ...application.agent.turns import ConversationTurnExecutionRequest
from ..config.agent_runtime_config import LangGraphGatewayConfig, langgraph_gateway_config_from_env

if TYPE_CHECKING:
    from langgraph.types import StreamWriter


class _ConversationTurnGraphState(TypedDict, total=False):
    conversation_id: str
    content: str
    canonical_action_id: Optional[str]
    turn_id: str
    prepared: dict[str, Any]
    route: str
    result: dict[str, Any]


class LangGraphConversationTurnGateway:
    """LangGraph anti-corruption adapter for one complete conversation turn."""

    def __init__(
        self,
        messages: ConversationMessageApplicationService,
        *,
        config: LangGraphGatewayConfig | None = None,
        compiled_graph: Any | None = None,
    ) -> None:
        self._messages = messages
        self.config = config or langgraph_gateway_config_from_env()
        self._compiled_graph = compiled_graph
        self._emitters: dict[str, Callable[[dict[str, Any]], None]] = {}

    async def astream(
        self,
        request: ConversationTurnExecutionRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        state: _ConversationTurnGraphState = {
            "conversation_id": request.conversation_id,
            "content": request.content,
            "canonical_action_id": request.canonical_action_id,
            "turn_id": request.turn_id,
        }
        invocation_config = {
            "configurable": {
                "thread_id": f"nasus-conversation-turn:{request.turn_id}",
            }
        }
        if self.config.checkpoint_backend == "postgres":
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL LangGraph checkpointing requires langgraph-checkpoint-postgres."
                ) from exc
            async with AsyncPostgresSaver.from_conn_string(
                self.config.psycopg_connection_string
            ) as saver:
                await saver.setup()
                graph = self._compile_graph(saver)
                async for event in self._stream_graph(
                    graph,
                    state,
                    invocation_config,
                ):
                    yield event
            return
        graph = self._graph()
        async for event in self._stream_graph(graph, state, invocation_config):
            yield event

    async def _stream_graph(
        self,
        graph: Any,
        state: _ConversationTurnGraphState,
        invocation_config: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        if sys.version_info >= (3, 11):
            async for event in graph.astream(
                state,
                config=invocation_config,
                stream_mode="custom",
            ):
                yield event
            return

        # LangGraph 0.6's async StreamWriter reads a ContextVar that is not
        # propagated by its Python 3.9 task runner. Keep the compatibility
        # bridge inside this infrastructure adapter; production Python 3.11+
        # always uses the native custom stream above.
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        turn_id = state["turn_id"]
        self._emitters[turn_id] = queue.put_nowait

        async def consume_graph() -> None:
            async for _ in graph.astream(
                state,
                config=invocation_config,
                stream_mode="updates",
            ):
                pass

        task = asyncio.create_task(consume_graph())
        try:
            while not task.done() or not queue.empty():
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
            await task
        finally:
            self._emitters.pop(turn_id, None)
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def _write_event(
        self,
        state: _ConversationTurnGraphState,
        writer: "StreamWriter",
        event: dict[str, Any],
    ) -> None:
        if sys.version_info >= (3, 11):
            writer(event)
            return
        emitter = self._emitters.get(state["turn_id"])
        if emitter is None:
            raise RuntimeError("Conversation turn stream emitter is unavailable")
        emitter(event)

    def _graph(self):
        if self._compiled_graph is None:
            from langgraph.checkpoint.memory import MemorySaver

            self._compiled_graph = self._compile_graph(MemorySaver())
        return self._compiled_graph

    def _compile_graph(self, checkpointer: Any):
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(_ConversationTurnGraphState)
        graph.add_node("load_context", self._load_context)
        graph.add_node("plan", self._plan)
        graph.add_node("route", self._route_node)
        graph.add_node("clarify", self._clarify)
        graph.add_node("invoke_tool", self._invoke_tool)
        graph.add_node("start_goal", self._start_goal)
        graph.add_node("generate_reply", self._generate_reply)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "plan")
        graph.add_edge("plan", "route")
        graph.add_conditional_edges(
            "route",
            self._route,
            {
                "clarify": "clarify",
                "invoke_tool": "invoke_tool",
                "start_goal": "start_goal",
                "generate_reply": "generate_reply",
                "finalize": "finalize",
            },
        )
        for node in ("clarify", "invoke_tool", "start_goal", "generate_reply"):
            graph.add_edge(node, "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(checkpointer=checkpointer)

    async def _load_context(self, state: _ConversationTurnGraphState):
        self._messages.validate_conversation(state["conversation_id"])
        return {}

    async def _plan(self, state: _ConversationTurnGraphState):
        prepared = await self._messages.prepare_message(
            state["conversation_id"],
            state["content"],
            canonical_action_id=state.get("canonical_action_id"),
        )
        route = str(prepared.get("route") or "finalize")
        if route == "finalize":
            result = self._serialize_result(dict(prepared.get("result") or {}))
            return {
                "prepared": {"route": route, "result": result},
                "route": route,
                "result": result,
            }
        return {"prepared": prepared, "route": route}

    async def _route_node(self, state: _ConversationTurnGraphState):
        return {"route": state.get("route", "finalize")}

    @staticmethod
    def _route(state: _ConversationTurnGraphState) -> str:
        return {
            "clarification": "clarify",
            "tool_plan": "invoke_tool",
            "agent_goal": "start_goal",
            "direct_answer": "generate_reply",
            "finalize": "finalize",
        }.get(state.get("route", "finalize"), "generate_reply")

    async def _clarify(self, state: _ConversationTurnGraphState):
        return await self._execute(state)

    async def _invoke_tool(self, state: _ConversationTurnGraphState):
        return await self._execute(state)

    async def _start_goal(self, state: _ConversationTurnGraphState):
        return await self._execute(state)

    async def _generate_reply(
        self,
        state: _ConversationTurnGraphState,
        *,
        writer: StreamWriter,
    ):
        with turn_stream_scope(
            lambda event: self._write_event(state, writer, event)
        ):
            return await self._execute(state)

    async def _execute(self, state: _ConversationTurnGraphState):
        result = await self._messages.execute_prepared(
            state["conversation_id"],
            state["content"],
            state["prepared"],
            turn_id=state["turn_id"],
        )
        return {"result": self._serialize_result(result)}

    async def _finalize(
        self,
        state: _ConversationTurnGraphState,
        *,
        writer: StreamWriter,
    ):
        self._write_event(
            state,
            writer,
            {"kind": "turn_result", "result": state.get("result", {})},
        )
        return {}

    @staticmethod
    def _serialize_result(result: dict[str, Any]) -> dict[str, Any]:
        serialized: dict[str, Any] = {}
        for key, value in result.items():
            if isinstance(value, list):
                serialized[key] = [
                    item.model_dump() if hasattr(item, "model_dump") else item
                    for item in value
                ]
            else:
                serialized[key] = value.model_dump() if hasattr(value, "model_dump") else value
        return serialized


__all__ = ["LangGraphConversationTurnGateway"]
