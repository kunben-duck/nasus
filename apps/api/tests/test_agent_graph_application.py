from __future__ import annotations

import asyncio
from types import SimpleNamespace

from apps.api.app.application.agent.agent_models import (
    AgentGoal,
    AgentGoalCreateRequest,
    AgentStep,
    ConversationSession,
)
from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.application.agent.loop import AgentLoopRuntime
from apps.api.app.application.platform.tool_models import (
    ToolInvocation,
    ToolInvocationRequest,
)
from apps.api.app.domain.agent.memory import AgentMemoryContext
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep
from apps.api.app.domain.agent.state_machine import AgentGoalStateMachine


class StaticPlanCompiler:
    def compile_tool_plan(
        self,
        proposal: AgentGoalProposal,
    ) -> list[ToolPlanStep]:
        return list(proposal.planned_tools)

    def compile_followup_tool_plan(self, goal: AgentGoal) -> list[ToolPlanStep]:
        return []


class InMemoryAgentGraphState:
    def __init__(self, conversation: ConversationSession) -> None:
        self.conversation = conversation
        self.goals: dict[str, AgentGoal] = {}
        self.invocations: dict[str, ToolInvocation] = {}
        self.persisted_goal_ids: list[str] = []
        self.audits: list[dict] = []
        self.events: list[tuple[str, str, dict]] = []
        self.messages: list[dict] = []
        self.memory_checkpoints: list[tuple[str, str]] = []
        self.memory_items: list[dict] = []
        self.next_invocation_status = "completed"

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self.goals[goal_id]

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        assert conversation_id == self.conversation.id
        return self.conversation

    async def create_tool_invocation(
        self,
        payload: ToolInvocationRequest,
    ) -> ToolInvocation:
        invocation = ToolInvocation(
            id=f"invocation_{len(self.invocations) + 1}",
            conversation_id=payload.conversation_id,
            tool_id=payload.tool_id,
            status=self.next_invocation_status,
            summary=f"{payload.tool_id} accepted",
            initiator_surface=payload.initiator_surface,
            initiator_actor=payload.initiator_actor,
            target_scope=payload.target_scope,
            input_payload=dict(payload.input),
        )
        self.invocations[invocation.id] = invocation
        return invocation

    async def confirm_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        invocation = self.invocations[invocation_id]
        invocation.status = "completed"
        return invocation

    def get_tool_invocation_or_none(
        self,
        invocation_id: str,
    ) -> ToolInvocation | None:
        return self.invocations.get(invocation_id)

    def persist_goal(self, goal: AgentGoal) -> None:
        self.goals[goal.id] = goal
        self.persisted_goal_ids.append(goal.id)

    def record_goal_audit(
        self,
        goal: AgentGoal,
        *,
        action: str,
        status: str | None,
        summary: str,
        metadata: dict | None = None,
    ) -> None:
        self.audits.append(
            {
                "goal_id": goal.id,
                "action": action,
                "status": status,
                "summary": summary,
                "metadata": metadata or {},
            }
        )

    async def publish_goal_event(
        self,
        goal: AgentGoal,
        event_type: str,
        patch: dict,
    ) -> None:
        self.events.append((goal.id, event_type, dict(patch)))

    async def append_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        metadata: dict | None = None,
        tool_refs: list[str] | None = None,
        object_refs: list[str] | None = None,
    ):
        message = SimpleNamespace(
            id=f"message_{len(self.messages) + 1}",
            metadata=metadata or {},
        )
        self.messages.append(
            {
                "id": message.id,
                "conversation_id": conversation_id,
                "text": text,
                "metadata": metadata or {},
                "tool_refs": tool_refs or [],
                "object_refs": object_refs or [],
            }
        )
        return message

    async def create_memory_checkpoint(
        self,
        *,
        conversation_id: str,
        agent_goal_id: str,
    ):
        self.memory_checkpoints.append((conversation_id, agent_goal_id))
        return SimpleNamespace(id=f"checkpoint_{agent_goal_id}")

    def record_memory_item(self, **payload):
        self.memory_items.append(payload)
        return SimpleNamespace(id=f"memory_{len(self.memory_items)}")

    async def build_memory_context(self, goal: AgentGoal) -> AgentMemoryContext:
        return AgentMemoryContext(
            system_prompt="Nasus Agent",
            context_snapshot="[project]\nproject_id=project_checkout",
            history_snapshot="No prior turns.",
            recent_turn_count=0,
            checkpoint_count=0,
        )

    def available_tool_ids(self) -> tuple[str, ...]:
        return ("query.system_image.status",)


class InMemoryAgentLoopState:
    def __init__(self, conversation: ConversationSession) -> None:
        self.conversation = conversation
        self.goals: dict[str, AgentGoal] = {}
        self.audits: list[dict] = []
        self.proposed: list[tuple[str, str]] = []
        self.messages: list[dict] = []

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        assert conversation_id == self.conversation.id
        return self.conversation

    def create_goal(self, payload: AgentGoalCreateRequest) -> AgentGoal:
        goal = AgentGoal(
            id="goal_loop",
            conversation_id=payload.conversation_id,
            project_id=payload.project_id,
            us_id=payload.us_id,
            goal_template=payload.goal_template,
            goal_description=payload.goal_description,
            target_refs=list(payload.target_refs),
            query_keys=list(payload.query_keys),
            planner_kind=payload.planner_kind,
            planning_summary=payload.planning_summary,
            title=payload.title,
            status="pending",
            summary=payload.summary,
            autonomy_level=payload.autonomy_level,
            max_steps=payload.max_steps,
            max_model_calls=payload.max_model_calls,
            max_thinking_tokens=payload.max_thinking_tokens,
            max_runtime_seconds=payload.max_runtime_seconds,
            max_no_progress_observations=payload.max_no_progress_observations,
            model_calls_used=payload.model_calls_used,
            thinking_input_tokens_used=payload.thinking_input_tokens_used,
            thinking_output_tokens_used=payload.thinking_output_tokens_used,
            thinking_tokens_used=(
                payload.thinking_input_tokens_used
                + payload.thinking_output_tokens_used
            ),
            steps=list(payload.steps or []),
        )
        self.goals[goal.id] = goal
        return goal

    def get_goal(self, goal_id: str) -> AgentGoal:
        return self.goals[goal_id]

    def record_goal_audit(self, goal: AgentGoal, **payload) -> None:
        self.audits.append({"goal_id": goal.id, **payload})

    async def publish_goal_proposed(
        self,
        goal: AgentGoal,
        *,
        graph_kind: str,
    ) -> None:
        self.proposed.append((goal.id, graph_kind))

    async def append_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        metadata: dict | None = None,
    ):
        self.messages.append(
            {
                "conversation_id": conversation_id,
                "text": text,
                "metadata": metadata or {},
            }
        )
        return SimpleNamespace(id=f"message_{len(self.messages)}")


class RecordingGraphRuntime:
    graph_kind = "test_graph"

    def __init__(self) -> None:
        self.started: list[tuple[str, AgentGoalProposal]] = []

    async def start(self, goal_id: str, proposal: AgentGoalProposal) -> None:
        self.started.append((goal_id, proposal))

    async def resume(self, goal_id: str) -> AgentGoal:
        raise AssertionError("resume is not exercised by this test")

    def steps_for_proposal(self, proposal: AgentGoalProposal):
        return [
            AgentStep(
                id="step_think",
                title="Plan next action",
                status="pending",
            )
        ]


def test_agent_loop_runs_against_ports_and_binds_project_context() -> None:
    conversation = ConversationSession(
        id="conversation_1",
        session_id="session_1",
        title="Checkout",
        space_type="project",
        space_id="project_checkout",
        project_id="project_checkout",
    )
    state = InMemoryAgentLoopState(conversation)
    graph = RecordingGraphRuntime()
    loop = AgentLoopRuntime(state, graph)
    proposal = AgentGoalProposal(
        goal_template="status_query",
        title="Inspect quality state",
        summary="Inspect current project state.",
        goal_description="Query project status.",
        kickoff_message="I will inspect the current project state.",
    )

    goal = asyncio.run(loop.start_goal(conversation.id, proposal))

    assert goal.target_refs == ["project:project_checkout"]
    assert state.audits[-1]["action"] == "agent.goal.proposed"
    assert state.proposed == [(goal.id, "test_graph")]
    assert state.messages[-1]["metadata"]["agent_runtime"] == "goal_kickoff"
    assert graph.started[0][0] == goal.id
    assert graph.started[0][1].target_refs == ["project:project_checkout"]


def test_local_agent_graph_completes_no_tool_goal_through_ports() -> None:
    conversation = ConversationSession(
        id="conversation_1",
        session_id="session_1",
        title="Checkout",
        space_type="project",
        space_id="project_checkout",
        project_id="project_checkout",
    )
    state = InMemoryAgentGraphState(conversation)
    runtime = LocalAgentGraphRuntime(
        state,
        AgentGoalStateMachine(),
        StaticPlanCompiler(),
    )
    proposal = AgentGoalProposal(
        goal_template="direct_answer",
        title="Summarize context",
        summary="Summarize the available context.",
        goal_description="Answer without changing product facts.",
    )
    goal = AgentGoal(
        id="goal_no_tool",
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        title=proposal.title,
        status="pending",
        summary=proposal.summary,
        steps=runtime.steps_for_proposal(proposal),
    )
    state.goals[goal.id] = goal

    asyncio.run(runtime.start(goal.id, proposal))

    assert goal.status == "completed"
    assert {step.status for step in goal.steps} == {"completed"}
    assert state.invocations == {}
    assert state.memory_checkpoints == [(conversation.id, goal.id)]
    assert state.messages[-1]["metadata"]["agent_runtime"] == "goal_completion"
    assert any(
        event_type == "agent.step.thinking.delta"
        for _, event_type, _ in state.events
    )
    thinking_patch = next(
        patch
        for _, event_type, patch in state.events
        if event_type == "agent.step.thinking.delta"
    )
    assert thinking_patch["stream_id"] == "goal_no_tool:step_think:thinking"
    assert thinking_patch["sequence"] == 1
    assert thinking_patch["chunk_index"] == 0
    assert thinking_patch["is_final"] is True
    assert thinking_patch["agent_step"]["id"] == "step_think"
    assert any(event_type == "agent.step.updated" for _, event_type, _ in state.events)
    assert state.audits[-1]["action"] == "agent.goal.completed"


def test_local_agent_graph_pauses_at_tool_confirmation_gate() -> None:
    conversation = ConversationSession(
        id="conversation_1",
        session_id="session_1",
        title="Checkout",
        space_type="project",
        space_id="project_checkout",
        project_id="project_checkout",
    )
    state = InMemoryAgentGraphState(conversation)
    state.next_invocation_status = "waiting_confirmation"
    runtime = LocalAgentGraphRuntime(
        state,
        AgentGoalStateMachine(),
        StaticPlanCompiler(),
    )
    proposal = AgentGoalProposal(
        goal_template="system_image_build",
        title="Build system image",
        summary="Initialize the project system image.",
        goal_description="Register project sources.",
        planned_tools=[
            ToolPlanStep(
                tool_id="query.system_image.status",
                input_payload={"project_id": "project_checkout"},
                reason="Check the current image state.",
            )
        ],
    )
    goal = AgentGoal(
        id="goal_gate",
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        title=proposal.title,
        status="pending",
        summary=proposal.summary,
        steps=runtime.steps_for_proposal(proposal),
    )
    state.goals[goal.id] = goal

    asyncio.run(runtime.start(goal.id, proposal))

    assert goal.status == "paused"
    assert goal.pause_reason == "waiting_confirmation"
    acting_step = next(step for step in goal.steps if step.phase == "acting")
    assert acting_step.tool_invocation_id in state.invocations
    assert state.invocations[acting_step.tool_invocation_id].status == (
        "waiting_confirmation"
    )
    assert state.memory_checkpoints == []
