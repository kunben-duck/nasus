from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import (
    AgentGoal,
    AgentGoalBudgetUpdateRequest,
    AgentGoalCreateRequest,
    ConversationArchiveRequest,
    ConversationCreateRequest,
    ConversationLink,
    ConversationMergeRequest,
    ConversationSession,
)
from apps.api.app.application.agent.conversations import (
    ConversationManagementApplicationService,
)
from apps.api.app.application.agent.goal_projection import (
    AgentGoalProjectionApplicationService,
)
from apps.api.app.application.agent.lifecycle import (
    AgentGoalLifecycleApplicationService,
)
from apps.api.app.application.agent.messages import (
    ConversationMessageApplicationService,
)
from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal


class InMemoryConversationState:
    def __init__(self) -> None:
        self.conversations: dict[str, ConversationSession] = {}
        self.index: dict[tuple[str, str, str], str] = {}
        self.links: dict[str, ConversationLink] = {}

    def resolve_scope(
        self,
        space_type: str,
        space_id: str,
        *,
        project_id: str | None = None,
        version_id: str | None = None,
        us_id: str | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        if space_type == "project":
            project_id = project_id or space_id
        return project_id, version_id, us_id

    def current_user_id(self) -> str:
        return "user_test"

    def require_project_access(self, project_id: str) -> None:
        assert project_id != "project_denied"

    def require_conversation_access(self, conversation: ConversationSession) -> None:
        assert conversation.initiator_id == "user_test"

    def can_access_conversation(self, conversation: ConversationSession) -> bool:
        return conversation.initiator_id == "user_test"

    def find_conversation(
        self,
        *,
        space_type: str,
        space_id: str,
        owner_key: str,
    ) -> ConversationSession | None:
        conversation_id = self.index.get((space_type, space_id, owner_key))
        return self.conversations.get(conversation_id or "")

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self.conversations[conversation_id]

    def list_conversations(self) -> tuple[ConversationSession, ...]:
        return tuple(self.conversations.values())

    def persist_conversation(
        self,
        conversation: ConversationSession,
        *,
        lookup_key: tuple[str, str, str] | None = None,
    ) -> None:
        self.conversations[conversation.id] = conversation
        if lookup_key is not None:
            self.index[lookup_key] = conversation.id

    def persist_conversation_link(self, link: ConversationLink) -> None:
        self.links[link.id] = link

    def list_conversation_links(self) -> tuple[ConversationLink, ...]:
        return tuple(self.links.values())


class InMemoryGoalProjectionState:
    def __init__(self, conversation: ConversationSession) -> None:
        self.conversation = conversation
        self.persisted_goal_ids: list[str] = []

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        assert conversation_id == self.conversation.id
        return self.conversation

    def persist_goal_projection(
        self,
        conversation: ConversationSession,
        goal: AgentGoal,
    ) -> None:
        assert conversation is self.conversation
        self.persisted_goal_ids.append(goal.id)


class RecordingConversationRuntime:
    def __init__(self, conversation: ConversationSession) -> None:
        self.conversation = conversation
        self.appended: list[tuple[str, str, str]] = []
        self.created_tool_requests = []

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        assert conversation_id == self.conversation.id
        return self.conversation

    async def append_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        *,
        metadata=None,
    ):
        self.appended.append((conversation_id, role, text))
        return SimpleNamespace(id=f"message_{len(self.appended)}")

    async def plan_message(self, conversation: ConversationSession, content: str):
        assert conversation is self.conversation
        return SimpleNamespace(
            kind="direct_answer",
            clarification=None,
            tool_plan=None,
            agent_goal=None,
            direct_answer=SimpleNamespace(
                fallback_text=f"Answer for: {content}",
                query_keys=[["conversation", conversation.id]],
            ),
        )

    def fallback_text(self, conversation: ConversationSession) -> str:
        return f"Fallback for {conversation.title}"

    async def create_tool_invocation(self, request) -> ToolInvocation:
        self.created_tool_requests.append(request)
        return ToolInvocation(
            id="tool_query_answer",
            conversation_id=request.conversation_id,
            tool_id=request.tool_id,
            status="completed",
            summary="Answered from the conversation context.",
            initiator_surface=request.initiator_surface,
            initiator_actor=request.initiator_actor,
            target_scope=request.target_scope,
            input_payload=request.input,
        )

    def active_goal_for_conversation(self, conversation_id: str):
        assert conversation_id == self.conversation.id
        return None

    def is_confirmation_message(self, content: str) -> bool:
        return False


class InMemoryGoalLifecycleState:
    def __init__(self) -> None:
        self.goals: dict[str, AgentGoal] = {}
        self.persisted_goal_ids: list[str] = []
        self.audits: list[dict] = []
        self.messages: list[dict] = []
        self.interrupted_goal_ids: list[str] = []
        self.feedback_events: list[tuple[str, str]] = []

    def create_goal(self, goal: AgentGoal) -> None:
        self.goals[goal.id] = goal

    def persist_goal(self, goal: AgentGoal) -> None:
        self.goals[goal.id] = goal
        self.persisted_goal_ids.append(goal.id)

    def has_goal(self, goal_id: str) -> bool:
        return goal_id in self.goals

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self.goals[goal_id]

    def list_goals_for_conversation(
        self,
        conversation_id: str,
    ) -> tuple[AgentGoal, ...]:
        return tuple(
            goal
            for goal in self.goals.values()
            if goal.conversation_id == conversation_id
        )

    def record_goal_audit(
        self,
        goal: AgentGoal,
        *,
        action: str,
        status: str | None,
        summary: str,
        actor: str,
        actor_kind: str,
        metadata: dict | None = None,
    ) -> None:
        self.audits.append(
            {
                "goal_id": goal.id,
                "action": action,
                "status": status,
                "summary": summary,
                "actor": actor,
                "actor_kind": actor_kind,
                "metadata": metadata or {},
            }
        )

    async def append_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        metadata: dict | None = None,
    ):
        message = {
            "conversation_id": conversation_id,
            "text": text,
            "metadata": metadata or {},
        }
        self.messages.append(message)
        return SimpleNamespace(id=f"message_{len(self.messages)}")

    async def publish_interrupted(self, goal: AgentGoal) -> None:
        self.interrupted_goal_ids.append(goal.id)

    async def publish_feedback(self, goal: AgentGoal, feedback: str) -> None:
        self.feedback_events.append((goal.id, feedback))


class RecordingGoalWorkflowRuntime:
    runtime_kind = "test"

    def __init__(self) -> None:
        self.started: list[tuple[str, AgentGoalProposal]] = []
        self.resumed_goal_ids: list[str] = []

    async def start_goal(
        self,
        conversation_id: str,
        proposal: AgentGoalProposal,
    ) -> AgentGoal:
        self.started.append((conversation_id, proposal))
        return AgentGoal(
            id="goal_runtime",
            conversation_id=conversation_id,
            title=proposal.title,
            status="running",
            summary=proposal.summary,
            steps=[],
        )

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        self.resumed_goal_ids.append(goal_id)
        return AgentGoal(
            id=goal_id,
            conversation_id="conversation_1",
            title="Resumed goal",
            status="running",
            summary="Resumed by the workflow runtime.",
            steps=[],
        )

    def checkpoint(self, goal_id: str):
        return SimpleNamespace(goal_id=goal_id)


def test_conversation_lifecycle_runs_against_state_port() -> None:
    state = InMemoryConversationState()
    service = ConversationManagementApplicationService(state)
    request = ConversationCreateRequest(
        title="Checkout quality",
        space_type="project",
        space_id="project_checkout",
    )

    created = service.ensure_conversation(request)
    repeated = service.ensure_conversation(request)

    assert repeated is created
    assert created.project_id == "project_checkout"
    assert created.initiator_id == "user_test"
    assert service.list_conversations(project_id="project_checkout") == [created]

    archived = service.archive_conversation(
        created.id,
        ConversationArchiveRequest(archive=True),
    )
    assert archived.status == "archived"
    assert archived.archived_at is not None


def test_conversation_merge_persists_relationship_through_port() -> None:
    state = InMemoryConversationState()
    service = ConversationManagementApplicationService(state)
    source = service.ensure_conversation(
        ConversationCreateRequest(
            title="Source",
            space_type="project",
            space_id="project_checkout",
        )
    )
    target = service.get_or_create_conversation(
        "knowledge",
        "project_checkout_graph",
        "Target",
        project_id="project_checkout",
    )

    result = service.merge_conversations(
        source.id,
        ConversationMergeRequest(target_conversation_id=target.id),
    )

    assert source.status == "merged"
    assert source.merged_into_conversation_id == target.id
    assert result["target_conversation_id"] == target.id
    assert result["link"].id in state.links


def test_conversation_message_orchestration_uses_runtime_port() -> None:
    conversation = ConversationSession(
        id="conversation_1",
        session_id="session_1",
        title="Checkout quality",
        space_type="project",
        space_id="project_checkout",
    )
    runtime = RecordingConversationRuntime(conversation)
    service = ConversationMessageApplicationService(runtime)

    result = asyncio.run(
        service.post_message(
            conversation.id,
            "Summarize the current quality state",
        )
    )

    assert runtime.appended == [
        (
            conversation.id,
            "user",
            "Summarize the current quality state",
        )
    ]
    assert runtime.created_tool_requests[0].tool_id == "query.answer"
    assert runtime.created_tool_requests[0].input["fallback_text"].startswith(
        "Answer for:"
    )
    assert result["tool_invocation"].id == "tool_query_answer"


def test_agent_goal_projection_runs_against_state_port() -> None:
    conversation = ConversationSession(
        id="conversation_1",
        session_id="session_1",
        title="Checkout quality",
        space_type="project",
        space_id="project_checkout",
    )
    state = InMemoryGoalProjectionState(conversation)
    service = AgentGoalProjectionApplicationService(state)
    goal = AgentGoal(
        id="goal_1",
        conversation_id=conversation.id,
        project_id="project_checkout",
        title="Build system image",
        status="running",
        summary="Build the project context baseline.",
        steps=[],
    )

    service.upsert_in_conversation(goal)
    goal.status = "completed"
    service.upsert_in_conversation(goal)

    assert len(conversation.agent_goals) == 1
    assert conversation.agent_goals[0].status == "completed"
    assert state.persisted_goal_ids == ["goal_1", "goal_1"]


def test_agent_goal_lifecycle_creates_record_and_audit_through_port() -> None:
    state = InMemoryGoalLifecycleState()
    runtime = RecordingGoalWorkflowRuntime()
    service = AgentGoalLifecycleApplicationService(state, runtime)

    goal = service.create_goal_record(
        AgentGoalCreateRequest(
            conversation_id="conversation_1",
            project_id="project_checkout",
            title="Build checkout context",
            summary="Create the system-image baseline.",
        )
    )

    assert state.goals[goal.id] is goal
    assert goal.status == "pending"
    assert len(goal.steps) == 3
    assert state.audits[-1]["action"] == "agent.goal.created"
    assert state.audits[-1]["actor_kind"] == "system"


def test_agent_goal_lifecycle_interrupts_and_records_feedback_through_port() -> None:
    state = InMemoryGoalLifecycleState()
    runtime = RecordingGoalWorkflowRuntime()
    service = AgentGoalLifecycleApplicationService(state, runtime)
    goal = service.create_goal_record(
        AgentGoalCreateRequest(
            conversation_id="conversation_1",
            title="Generate release evidence",
            summary="Collect quality evidence.",
        )
    )
    goal.status = "running"

    interrupted = asyncio.run(service.interrupt_goal(goal.id))
    with_feedback = asyncio.run(
        service.add_feedback(goal.id, "Prioritize checkout failure evidence.")
    )

    assert interrupted.status == "paused"
    assert interrupted.pause_reason == "user_interrupt"
    assert state.interrupted_goal_ids == [goal.id]
    assert state.feedback_events == [
        (goal.id, "Prioritize checkout failure evidence.")
    ]
    assert state.messages[-1]["conversation_id"] == "conversation_1"
    assert "Prioritize checkout failure evidence." in state.messages[-1]["text"]
    assert [audit["action"] for audit in state.audits[-2:]] == [
        "agent.goal.interrupted",
        "agent.goal.feedback",
    ]
    assert with_feedback is goal


def test_agent_goal_lifecycle_enforces_budget_update_policy() -> None:
    state = InMemoryGoalLifecycleState()
    runtime = RecordingGoalWorkflowRuntime()
    service = AgentGoalLifecycleApplicationService(state, runtime)
    goal = service.create_goal_record(
        AgentGoalCreateRequest(
            conversation_id="conversation_1",
            title="Assess release readiness",
            summary="Evaluate release gates.",
            max_steps=4,
        )
    )
    goal.budget_exhausted_reason = "max_steps"

    updated = service.update_budget(
        goal.id,
        AgentGoalBudgetUpdateRequest(max_steps=8, max_model_calls=6),
    )

    assert updated.max_steps == 8
    assert updated.max_model_calls == 6
    assert updated.budget_exhausted_reason is None
    assert state.audits[-1]["action"] == "agent.goal.budget_updated"
    assert state.audits[-1]["metadata"]["changed_budgets"] == {
        "max_steps": 8,
        "max_model_calls": 6,
    }

    goal.status = "running"
    with pytest.raises(ValueError, match="Pause the AgentGoal"):
        service.update_budget(
            goal.id,
            AgentGoalBudgetUpdateRequest(max_steps=9),
        )


def test_agent_goal_lifecycle_keeps_one_active_goal_per_conversation() -> None:
    state = InMemoryGoalLifecycleState()
    runtime = RecordingGoalWorkflowRuntime()
    service = AgentGoalLifecycleApplicationService(state, runtime)
    existing = service.create_goal_record(
        AgentGoalCreateRequest(
            conversation_id="conversation_1",
            title="Build system image",
            summary="Index the repository.",
        )
    )
    existing.status = "running"

    returned = asyncio.run(
        service.start_from_proposal(
            "conversation_1",
            AgentGoalProposal(
                goal_template="quality_loop",
                title="Generate test scope",
                summary="Generate scope from the active version.",
                goal_description="Create quality scope.",
            ),
        )
    )

    assert returned is existing
    assert runtime.started == []
    assert state.audits[-1]["action"] == "agent.goal.active_goal_guard"
    assert state.messages[-1]["metadata"]["agent_goal_id"] == existing.id
