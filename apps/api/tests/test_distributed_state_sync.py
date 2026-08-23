from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.distributed_state_sync import (
    DistributedStateSynchronizationApplicationService,
    DistributedStateSynchronizationDependencies,
)


def _service(conversations):
    goals = {}

    service = DistributedStateSynchronizationApplicationService(
        DistributedStateSynchronizationDependencies(
            persist_goal=lambda goal: goals.__setitem__(goal.id, goal),
            get_conversation=conversations.get,
        )
    )
    return service, goals


def test_distributed_state_sync_persists_remote_goal_idempotently() -> None:
    conversation = SimpleNamespace(id="conversation-1", agent_goals=[])
    service, goals = _service({conversation.id: conversation})
    goal = SimpleNamespace(id="goal-1", conversation_id=conversation.id)

    service.accept_remote_goal(goal)
    replacement = SimpleNamespace(id=goal.id, conversation_id=conversation.id)
    service.accept_remote_goal(replacement)

    assert goals[goal.id] is replacement


def test_distributed_state_sync_rejects_unknown_remote_conversation() -> None:
    service, goals = _service({})
    goal = SimpleNamespace(id="goal-1", conversation_id="missing")

    with pytest.raises(RuntimeError, match="unknown conversation"):
        service.accept_remote_goal(goal)

    assert goal.id not in goals
