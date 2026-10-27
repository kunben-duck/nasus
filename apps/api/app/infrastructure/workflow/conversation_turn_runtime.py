from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from typing import Awaitable, Callable

from ...application.agent.turns import (
    ConversationTurnApplicationService,
    ConversationTurnExecutionRequest,
    ConversationTurnWorkflowRuntimePort,
)
from ...application.platform.actor_context import actor_scope
from ..config.agent_runtime_config import TemporalGatewayConfig, temporal_gateway_config_from_env
from .nasus_conversation_turn_workflow import CONVERSATION_TURN_WORKFLOW_TYPE


@dataclass
class LocalConversationTurnWorkflowRuntime(ConversationTurnWorkflowRuntimePort):
    application: ConversationTurnApplicationService
    _cancellations: dict[str, Event] = field(default_factory=dict)
    _completions: dict[str, Event] = field(default_factory=dict)
    _tasks: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    async def start_turn(self, request: ConversationTurnExecutionRequest) -> str:
        workflow_id = f"local-conversation-turn:{request.turn_id}"
        cancellation = Event()
        completion = Event()
        with self._lock:
            self._cancellations[request.turn_id] = cancellation
            self._completions[request.turn_id] = completion

        def run() -> None:
            async def execute() -> None:
                loop = asyncio.get_running_loop()
                task = asyncio.create_task(
                    self.application.execute_turn(
                        request,
                        cancelled=cancellation.is_set,
                    )
                )
                with self._lock:
                    self._tasks[request.turn_id] = (loop, task)
                await task

            try:
                if request.actor is not None:
                    with actor_scope(request.actor, request_id=request.request_id):
                        asyncio.run(execute())
                else:
                    asyncio.run(execute())
            finally:
                completion.set()
                with self._lock:
                    self._cancellations.pop(request.turn_id, None)
                    self._completions.pop(request.turn_id, None)
                    self._tasks.pop(request.turn_id, None)

        Thread(
            target=run,
            name=f"nasus-turn-{request.turn_id}",
            daemon=True,
        ).start()
        return workflow_id

    async def cancel_turn(self, turn_id: str, workflow_id: str | None) -> None:
        del workflow_id
        with self._lock:
            cancellation = self._cancellations.get(turn_id)
            completion = self._completions.get(turn_id)
            running = self._tasks.get(turn_id)
        if cancellation is not None:
            cancellation.set()
        if running is not None:
            loop, task = running
            loop.call_soon_threadsafe(task.cancel)
        if completion is not None:
            await asyncio.to_thread(completion.wait, 2.0)


class TemporalConversationTurnWorkflowRuntime(ConversationTurnWorkflowRuntimePort):
    def __init__(
        self,
        config: TemporalGatewayConfig | None = None,
        *,
        client_factory: Callable[[TemporalGatewayConfig], Awaitable[object]] | None = None,
    ) -> None:
        self.config = config or temporal_gateway_config_from_env()
        self._client_factory = client_factory or self._default_client_factory
        self._client = None

    async def start_turn(self, request: ConversationTurnExecutionRequest) -> str:
        client = await self._client_instance()
        workflow_id = f"nasus-conversation-turn:{request.turn_id}"
        await client.start_workflow(
            CONVERSATION_TURN_WORKFLOW_TYPE,
            request.model_dump(),
            id=workflow_id,
            task_queue=self.config.resolved_conversation_turn_task_queue,
        )
        return workflow_id

    async def cancel_turn(self, turn_id: str, workflow_id: str | None) -> None:
        client = await self._client_instance()
        handle = client.get_workflow_handle(
            workflow_id or f"nasus-conversation-turn:{turn_id}"
        )
        await handle.cancel()

    async def _client_instance(self):
        if self._client is None:
            self._client = await self._client_factory(self.config)
        return self._client

    @staticmethod
    async def _default_client_factory(config: TemporalGatewayConfig):
        from temporalio.client import Client

        return await Client.connect(config.address, namespace=config.namespace)


def build_conversation_turn_workflow_runtime(
    application: ConversationTurnApplicationService,
) -> ConversationTurnWorkflowRuntimePort:
    import os

    runtime = os.getenv("NASUS_AGENT_WORKFLOW_RUNTIME", "local").strip().lower()
    if runtime in {"", "local"}:
        return LocalConversationTurnWorkflowRuntime(application)
    if runtime == "temporal":
        return TemporalConversationTurnWorkflowRuntime()
    raise RuntimeError(
        "NASUS_AGENT_WORKFLOW_RUNTIME must be either 'local' or 'temporal'."
    )


__all__ = [
    "LocalConversationTurnWorkflowRuntime",
    "TemporalConversationTurnWorkflowRuntime",
    "build_conversation_turn_workflow_runtime",
]
