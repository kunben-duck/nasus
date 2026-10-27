from __future__ import annotations

import asyncio

from apps.api.app.application.agent.turns import ConversationTurnExecutionRequest
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.workflow.conversation_turn_runtime import (
    TemporalConversationTurnWorkflowRuntime,
)
from apps.api.app.infrastructure.workflow.nasus_conversation_turn_workflow import (
    CONVERSATION_TURN_WORKFLOW_TYPE,
)


def test_temporal_conversation_turn_uses_dedicated_task_queue() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.started: dict[str, object] | None = None

        async def start_workflow(self, workflow, payload, *, id, task_queue):
            self.started = {
                "workflow": workflow,
                "payload": payload,
                "id": id,
                "task_queue": task_queue,
            }

    client = FakeClient()

    async def client_factory(config: TemporalGatewayConfig):
        assert config.task_queue == "nasus-agent-goals"
        return client

    runtime = TemporalConversationTurnWorkflowRuntime(
        TemporalGatewayConfig(task_queue="nasus-agent-goals"),
        client_factory=client_factory,
    )
    request = ConversationTurnExecutionRequest(
        turn_id="turn_001",
        conversation_id="conv_001",
        content="Build the system image",
        canonical_action_id=None,
    )

    workflow_id = asyncio.run(runtime.start_turn(request))

    assert workflow_id == "nasus-conversation-turn:turn_001"
    assert client.started == {
        "workflow": CONVERSATION_TURN_WORKFLOW_TYPE,
        "payload": request.model_dump(),
        "id": workflow_id,
        "task_queue": "nasus-agent-goals-conversation-turns",
    }


def test_temporal_conversation_turn_supports_explicit_task_queue() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.task_queue: str | None = None

        async def start_workflow(self, workflow, payload, *, id, task_queue):
            del workflow, payload, id
            self.task_queue = task_queue

    client = FakeClient()

    async def client_factory(config: TemporalGatewayConfig):
        del config
        return client

    runtime = TemporalConversationTurnWorkflowRuntime(
        TemporalGatewayConfig(
            task_queue="nasus-agent-goals",
            conversation_turn_task_queue="nasus-conversation-turns",
        ),
        client_factory=client_factory,
    )

    asyncio.run(
        runtime.start_turn(
            ConversationTurnExecutionRequest(
                turn_id="turn_002",
                conversation_id="conv_001",
                content="Answer the question",
                canonical_action_id=None,
            )
        )
    )

    assert client.task_queue == "nasus-conversation-turns"
