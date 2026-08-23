from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import (
    ConversationLink,
    ConversationMessage,
    ConversationSession,
    MessageBlock,
)
from apps.api.app.application.agent.conversation_summary import (
    ConversationSummaryCheckpointApplicationService,
)
from apps.api.app.application.agent.message_writer import (
    ConversationMessageWriterApplicationService,
)
from apps.api.app.application.agent.plans import AgentGoalPlanCompiler
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep
from apps.api.app.infrastructure.agent.application_ports import (
    LegacyAgentConversationEventPublisher,
    LegacyAgentGraphStateAdapter,
    LegacyAgentGoalExplanationQueryAdapter,
    LegacyAgentGoalLifecycleStateAdapter,
    LegacyAgentGoalProjectionStateAdapter,
    LegacyAgentLoopStateAdapter,
    LegacyAgentMemoryStateAdapter,
    LegacyAgentPlannerContextAdapter,
    LegacyAgentPlanStateAdapter,
    LegacyAgentSwarmStateAdapter,
    LegacyAgentWorkflowStateAdapter,
    LegacyConversationMessageStateAdapter,
    LegacyConversationMessageRuntimeAdapter,
    LegacyConversationManagementStateAdapter,
    LegacyConversationSummaryStateAdapter,
)
from apps.api.app.infrastructure.agent.conversation_management_dependencies import (
    AgentConversationManagementPersistenceAdapters,
    AgentConversationManagementProjectionState,
    AgentConversationManagementRuntimeAdapters,
)
from apps.api.app.infrastructure.agent.graph_state_dependencies import (
    AgentGraphLookupAdapters,
    AgentGraphMemoryAdapters,
    AgentGraphToolRuntimeAdapters,
)
from apps.api.app.infrastructure.agent.memory_state_dependencies import (
    AgentMemoryCandidateProjectionState,
    AgentMemoryEventAdapters,
    AgentMemoryPersistenceAdapters,
    AgentMemoryProjectionState,
    AgentMemoryRuntimeAdapters,
    AgentMemoryWorkspaceProjectionState,
    CompatibilityAgentMemoryCandidateQueries,
    CompatibilityAgentMemoryWorkspaceQueries,
)
from apps.api.app.infrastructure.agent.goal_state_dependencies import (
    AgentGoalLifecycleAdapters,
    AgentGoalLifecycleState,
    AgentGoalProjectionPersistenceAdapters,
    AgentGoalProjectionState,
    AgentLoopRuntimeAdapters,
)
from apps.api.app.infrastructure.agent.conversation_runtime_dependencies import (
    AgentConversationRuntimeAdapters,
)
from apps.api.app.infrastructure.agent.conversation_state_dependencies import (
    AgentConversationCheckpointAdapters,
    AgentConversationEventAdapters,
    AgentConversationPersistenceAdapters,
    AgentConversationProjectionState,
    AgentGoalExplanationAdapters,
)
from apps.api.app.infrastructure.agent.planning_dependencies import (
    AgentPlannerContextAdapters,
    AgentPlanningProjectionState,
    AgentPlanningRuntimeAdapters,
)
from apps.api.app.infrastructure.agent.swarm_state_dependencies import (
    AgentSwarmEventAdapters,
    AgentSwarmPersistenceAdapters,
    AgentSwarmProjectionState,
)
from apps.api.app.infrastructure.agent.workflow_state_dependencies import (
    AgentWorkflowRuntimeAdapters,
)
from apps.api.app.application.platform.scope_resolution import (
    ProjectScopeResolutionApplicationService,
)
from apps.api.app.infrastructure.platform.scope_resolution import (
    CompatibilityProjectScopeProjection,
)


@dataclass
class FakeConversationState:
    conversation: ConversationSession
    persisted_messages: list[ConversationMessage] = field(default_factory=list)
    checkpoint_calls: int = 0

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        if conversation_id != self.conversation.id:
            raise KeyError(conversation_id)
        return self.conversation

    def persist_message(
        self,
        conversation: ConversationSession,
        message: ConversationMessage,
    ) -> None:
        assert conversation is self.conversation
        self.persisted_messages.append(message)

    async def maybe_create_summary_checkpoint(self, conversation: ConversationSession):
        assert conversation is self.conversation
        self.checkpoint_calls += 1
        return None


@dataclass
class FakeConversationEvents:
    message_events: list[tuple[str, str]] = field(default_factory=list)
    summary_events: list[tuple[str, str]] = field(default_factory=list)

    async def publish_message_created(
        self,
        conversation_id: str,
        message: ConversationMessage,
    ) -> None:
        self.message_events.append((conversation_id, message.id))

    async def publish_summary_updated(
        self,
        conversation_id: str,
        checkpoint_id: str,
    ) -> None:
        self.summary_events.append((conversation_id, checkpoint_id))


@dataclass
class FakeSummaryState:
    checkpoints: list = field(default_factory=list)
    persisted: list = field(default_factory=list)

    def list_summary_checkpoints(self):
        return tuple(self.checkpoints)

    def persist_summary_checkpoint(self, conversation, checkpoint) -> None:
        self.checkpoints.append(checkpoint)
        self.persisted.append((conversation.id, checkpoint.id))


@dataclass
class FakePlanState:
    source_binding_missing: bool = False
    source_statuses: tuple[str, ...] = ("indexed",)
    materialized: bool = True
    baseline_ready: bool = False
    tools: frozenset[str] = frozenset(
        {
            "system_image.sources.register",
            "system_image.sources.ingest",
            "system_image.context.materialize",
            "system_image.baseline.initialize",
        }
    )

    def project_exists(self, project_id: str) -> bool:
        return project_id == "project-1"

    def source_binding_incomplete(self, project_id: str) -> bool:
        return self.source_binding_missing

    def source_ingestion_statuses(self, project_id: str) -> tuple[str, ...]:
        return self.source_statuses

    def has_materialized_context(self, project_id: str) -> bool:
        return self.materialized

    def has_ready_official_baseline(self, project_id: str) -> bool:
        return self.baseline_ready

    def known_tool_ids(self) -> frozenset[str]:
        return self.tools


def _conversation() -> ConversationSession:
    return ConversationSession(
        id="conversation-1",
        session_id="session-1",
        title="Agent port test",
        space_type="build",
        space_id="build",
    )


def _message(index: int) -> ConversationMessage:
    return ConversationMessage(
        id=f"message-{index}",
        role="user" if index % 2 == 0 else "assistant",
        created_at=f"2026-01-01T00:00:{index:02d}+00:00",
        blocks=[MessageBlock(type="text", text=f"message body {index}")],
    )


def test_conversation_management_adapter_uses_explicit_state_and_dependencies() -> None:
    conversation = _conversation()
    conversation.space_type = "workspace"
    conversation.space_id = "us-1"
    link = ConversationLink(
        id="link-1",
        left_conversation_id=conversation.id,
        right_conversation_id="conversation-2",
        link_kind="related",
        reason="Shared quality context",
        confidence=0.9,
        created_at="2026-01-01T00:00:00+00:00",
    )
    calls: list[tuple[str, object]] = []
    state = AgentConversationManagementProjectionState(
        conversations={},
        conversation_index={},
        conversation_links={},
    )
    scope_resolution = ProjectScopeResolutionApplicationService(
        CompatibilityProjectScopeProjection(
            versions={"project-1": [SimpleNamespace(id="version-1")]},
            us_items={"project-1": [SimpleNamespace(id="us-1")]},
        )
    )
    adapter = LegacyConversationManagementStateAdapter(
        state,
        AgentConversationManagementPersistenceAdapters(
            upsert_conversation=lambda current: calls.append(
                ("conversation", current.id)
            ),
            upsert_conversation_link=lambda current: calls.append(
                ("link", current.id)
            ),
        ),
        AgentConversationManagementRuntimeAdapters(
            resolve_scope=scope_resolution.resolve_conversation_scope,
            current_user_id=lambda: "user-1",
            require_project_access=lambda project_id: calls.append(
                ("project_access", project_id)
            ),
            require_conversation_access=lambda current: calls.append(
                ("conversation_access", current.id)
            ),
            can_access_conversation=lambda current: current.id == conversation.id,
        ),
    )

    assert adapter.resolve_scope("workspace", "us-1") == (
        "project-1",
        "version-1",
        "us-1",
    )
    assert adapter.current_user_id() == "user-1"
    adapter.require_project_access("project-1")
    adapter.require_conversation_access(conversation)
    assert adapter.can_access_conversation(conversation) is True
    lookup_key = ("workspace", "us-1", "user:user-1")
    adapter.persist_conversation(conversation, lookup_key=lookup_key)
    assert adapter.find_conversation(
        space_type="workspace",
        space_id="us-1",
        owner_key="user:user-1",
    ) is conversation
    adapter.persist_conversation_link(link)

    assert adapter.get_conversation(conversation.id) is conversation
    assert adapter.list_conversations() == (conversation,)
    assert adapter.list_conversation_links() == (link,)
    assert calls == [
        ("project_access", "project-1"),
        ("conversation_access", conversation.id),
        ("conversation", conversation.id),
        ("link", link.id),
    ]


def test_message_writer_runs_against_explicit_state_and_event_ports() -> None:
    conversation = _conversation()
    state = FakeConversationState(conversation)
    events = FakeConversationEvents()
    writer = ConversationMessageWriterApplicationService(state, events)

    message = asyncio.run(
        writer.append_text_message(
            conversation.id,
            "user",
            "Build the system image",
            metadata={"source": "test"},
        )
    )

    assert conversation.status == "active"
    assert conversation.messages == [message]
    assert state.persisted_messages == [message]
    assert state.checkpoint_calls == 1
    assert events.message_events == [(conversation.id, message.id)]


def test_summary_checkpoint_runs_against_explicit_state_and_event_ports() -> None:
    conversation = _conversation()
    conversation.messages = [_message(index) for index in range(10)]
    state = FakeSummaryState()
    events = FakeConversationEvents()
    service = ConversationSummaryCheckpointApplicationService(state, events)

    checkpoint = asyncio.run(service.maybe_create_checkpoint(conversation))

    assert checkpoint is not None
    assert conversation.latest_summary_checkpoint_id == checkpoint.id
    assert state.persisted == [(conversation.id, checkpoint.id)]
    assert events.summary_events == [(conversation.id, checkpoint.id)]


def test_plan_compiler_reads_only_the_plan_state_port() -> None:
    compiler = AgentGoalPlanCompiler(FakePlanState())
    proposal = AgentGoalProposal(
        goal_template="system_image_build",
        title="Build system image",
        summary="Build the project baseline",
        goal_description="Materialize the current code knowledge.",
        target_refs=["project:project-1"],
    )

    steps = compiler.compile_tool_plan(proposal)

    assert [step.tool_id for step in steps] == ["system_image.baseline.initialize"]


def test_plan_compiler_rejects_unknown_tools_through_the_port_contract() -> None:
    compiler = AgentGoalPlanCompiler(FakePlanState())
    proposal = AgentGoalProposal(
        goal_template="manual",
        title="Unknown tool",
        summary="Reject an invalid plan",
        goal_description="Validate the tool catalog boundary.",
        planned_tools=[ToolPlanStep(tool_id="unknown.tool", input_payload={})],
    )

    with pytest.raises(ValueError, match="unknown tools"):
        compiler.compile_tool_plan(proposal)


def test_plan_state_adapter_reads_only_explicit_projections_and_runtime_queries() -> None:
    state = AgentPlanningProjectionState(
        projects={"project-1": SimpleNamespace(id="project-1")},
        raw_assets={
            "project-1": [
                SimpleNamespace(ingestion_status="indexed"),
                SimpleNamespace(ingestion_status="indexed"),
            ]
        },
        knowledge_objects={"project-1": [SimpleNamespace(id="object-1")]},
        context_relationships={
            "project-1": [SimpleNamespace(id="relationship-1")]
        },
        quality_metric_snapshots={
            "project-1": [SimpleNamespace(id="metric-1")]
        },
        baselines={
            "project-1": [
                SimpleNamespace(kind="official", status="ready")
            ]
        },
    )
    adapter = LegacyAgentPlanStateAdapter(
        state,
        AgentPlanningRuntimeAdapters(
            source_binding_incomplete=lambda project_id: project_id == "blocked",
            known_tool_ids=lambda: frozenset({"system_image.context.materialize"}),
        ),
    )

    assert adapter.project_exists("project-1") is True
    assert adapter.source_binding_incomplete("project-1") is False
    assert adapter.source_ingestion_statuses("project-1") == (
        "indexed",
        "indexed",
    )
    assert adapter.has_materialized_context("project-1") is True
    assert adapter.has_ready_official_baseline("project-1") is True
    assert adapter.known_tool_ids() == frozenset(
        {"system_image.context.materialize"}
    )


def test_planner_context_adapter_delegates_to_explicit_cross_domain_queries() -> None:
    conversation = _conversation()
    memory_context = SimpleNamespace(summary="remembered project context")
    calls: list[tuple[str, object]] = []
    async def memory_context_builder(current):
        calls.append(("memory", current.id))
        return memory_context

    adapter = LegacyAgentPlannerContextAdapter(
        AgentPlannerContextAdapters(
            memory_context=memory_context_builder,
            conversation_summary_fallback=lambda current: (
                calls.append(("summary", current.id)) or "Fallback summary"
            ),
            quality_state=lambda project_id, us_id: (
                calls.append(("quality", (project_id, us_id)))
                or {"quality_state": "ready"}
            ),
        )
    )

    assert asyncio.run(adapter.memory_context(conversation)) is memory_context
    assert adapter.conversation_summary_fallback(conversation) == "Fallback summary"
    assert adapter.quality_state("project-1", "us-1") == {
        "quality_state": "ready"
    }
    assert calls == [
        ("memory", conversation.id),
        ("summary", conversation.id),
        ("quality", ("project-1", "us-1")),
    ]


def test_conversation_runtime_adapter_delegates_main_agent_command_surface() -> None:
    conversation = _conversation()
    invocation = SimpleNamespace(id="tool-1")
    goal = SimpleNamespace(id="goal-1", title="Build image", status="paused")
    calls: list[tuple[str, object]] = []

    async def append_message(conversation_id, role, text, **kwargs):
        calls.append(("append", (conversation_id, role, text, kwargs)))
        return SimpleNamespace(id="message-1")

    async def plan_message(current, content):
        calls.append(("plan", (current.id, content)))
        return SimpleNamespace(kind="direct_answer")

    async def create_tool(request):
        calls.append(("create_tool", request))
        return invocation

    async def start_goal(conversation_id, proposal):
        calls.append(("start_goal", (conversation_id, proposal)))
        return goal

    async def resume_goal(goal_id):
        calls.append(("resume", goal_id))
        return goal

    async def confirm_tool(invocation_id):
        calls.append(("confirm", invocation_id))
        return invocation

    adapter = LegacyConversationMessageRuntimeAdapter(
        AgentConversationRuntimeAdapters(
            get_conversation=lambda conversation_id: conversation,
            append_message=append_message,
            plan_message=plan_message,
            fallback_text=lambda current: "Fallback",
            create_tool_invocation=create_tool,
            start_goal_from_proposal=start_goal,
            is_confirmation_message=lambda content: content == "confirm",
            list_tool_invocations=lambda **kwargs: [invocation],
            is_paused_goal=lambda goal_id: goal_id == goal.id,
            resume_goal=resume_goal,
            get_tool_invocation=lambda invocation_id: invocation,
            confirm_tool_invocation=confirm_tool,
            active_goal_for_conversation=lambda conversation_id: goal,
            project_goal=lambda current: calls.append(("project", current.id)),
            record_source_binding_received=lambda current, source_types: (
                calls.append(("audit", (current.id, tuple(source_types))))
            ),
        )
    )

    assert adapter.get_conversation(conversation.id) is conversation
    assert asyncio.run(
        adapter.append_message(
            conversation.id,
            "user",
            "Build",
            metadata={"source": "test"},
        )
    ).id == "message-1"
    assert asyncio.run(adapter.plan_message(conversation, "Build")).kind == (
        "direct_answer"
    )
    assert adapter.fallback_text(conversation) == "Fallback"
    assert asyncio.run(adapter.create_tool_invocation("request")) is invocation
    assert asyncio.run(
        adapter.start_goal_from_proposal(conversation.id, "proposal")
    ) is goal
    assert adapter.is_confirmation_message("confirm") is True
    assert adapter.list_tool_invocations(
        conversation_id=conversation.id,
        status="waiting_confirmation",
    ) == [invocation]
    assert adapter.is_paused_goal(goal.id) is True
    assert asyncio.run(adapter.resume_goal(goal.id)) is goal
    assert adapter.get_tool_invocation(invocation.id) is invocation
    assert asyncio.run(adapter.confirm_tool_invocation(invocation.id)) is invocation
    assert adapter.active_goal_for_conversation(conversation.id) is goal
    adapter.project_goal(goal)
    adapter.record_source_binding_received(goal, source_types=["code", "us_doc"])
    assert ("project", goal.id) in calls
    assert ("audit", (goal.id, ("code", "us_doc"))) in calls


def test_conversation_state_adapters_use_explicit_projection_and_persistence() -> None:
    conversation = _conversation()
    message = _message(1)
    checkpoint = SimpleNamespace(id="checkpoint-1")
    calls: list[tuple[str, object]] = []
    state = AgentConversationProjectionState(
        conversations={conversation.id: conversation},
        summary_checkpoints={},
    )
    persistence = AgentConversationPersistenceAdapters(
        append_message=lambda conversation_id, current: calls.append(
            ("append", (conversation_id, current.id))
        ),
        upsert_conversation=lambda current: calls.append(
            ("conversation", current.id)
        ),
        upsert_summary_checkpoint=lambda current: calls.append(
            ("checkpoint", current.id)
        ),
    )

    async def maybe_create_summary(current):
        calls.append(("maybe_summary", current.id))
        return checkpoint

    message_state = LegacyConversationMessageStateAdapter(
        state,
        persistence,
        AgentConversationCheckpointAdapters(
            maybe_create_summary_checkpoint=maybe_create_summary,
        ),
    )
    summary_state = LegacyConversationSummaryStateAdapter(state, persistence)

    assert message_state.get_conversation(conversation.id) is conversation
    message_state.persist_message(conversation, message)
    assert asyncio.run(
        message_state.maybe_create_summary_checkpoint(conversation)
    ) is checkpoint
    summary_state.persist_summary_checkpoint(conversation, checkpoint)

    assert summary_state.list_summary_checkpoints() == (checkpoint,)
    assert calls == [
        ("append", (conversation.id, message.id)),
        ("conversation", conversation.id),
        ("maybe_summary", conversation.id),
        ("checkpoint", checkpoint.id),
        ("conversation", conversation.id),
    ]


def test_conversation_event_adapter_preserves_canonical_sse_envelopes() -> None:
    message = _message(2)
    calls: list[tuple[tuple, dict]] = []

    async def push_event(*args, **kwargs):
        calls.append((args, kwargs))

    events = LegacyAgentConversationEventPublisher(
        AgentConversationEventAdapters(push_event=push_event)
    )

    asyncio.run(events.publish_message_created("conversation-1", message))
    asyncio.run(events.publish_summary_updated("conversation-1", "checkpoint-1"))

    assert calls[0][0] == ("conversation-1",)
    assert calls[0][1]["event_type"] == "conversation.message.created"
    assert calls[0][1]["entity_type"] == "conversation"
    assert calls[0][1]["payload"]["message_id"] == message.id
    assert calls[1][1]["event_type"] == "conversation.summary.updated"
    assert calls[1][1]["patch"] == {
        "latest_summary_checkpoint_id": "checkpoint-1"
    }


def test_goal_explanation_adapter_delegates_only_read_queries() -> None:
    goal = SimpleNamespace(id="goal-1")
    checkpoint = SimpleNamespace(goal_id=goal.id)
    invocation = SimpleNamespace(id="tool-1")
    memory = SimpleNamespace(id="memory-1")
    audit = SimpleNamespace(id="audit-1")
    calls: list[tuple[str, object]] = []
    adapter = LegacyAgentGoalExplanationQueryAdapter(
        AgentGoalExplanationAdapters(
            get_goal=lambda goal_id: calls.append(("goal", goal_id)) or goal,
            get_checkpoint=lambda goal_id: (
                calls.append(("checkpoint", goal_id)) or checkpoint
            ),
            get_tool_invocation=lambda invocation_id: (
                calls.append(("invocation", invocation_id)) or invocation
            ),
            list_tool_invocations=lambda **kwargs: (
                calls.append(("invocations", kwargs)) or [invocation]
            ),
            list_agent_memory_items=lambda **kwargs: (
                calls.append(("memory", kwargs)) or [memory]
            ),
            list_audit_events=lambda **kwargs: (
                calls.append(("audit", kwargs)) or [audit]
            ),
        )
    )

    assert adapter.get_goal(goal.id) is goal
    assert adapter.get_checkpoint(goal.id) is checkpoint
    assert adapter.get_tool_invocation(invocation.id) is invocation
    assert adapter.list_tool_invocations(agent_goal_id=goal.id) == [invocation]
    assert adapter.list_agent_memory_items(source_ref=f"agent_goal:{goal.id}") == [
        memory
    ]
    assert adapter.list_audit_events(agent_goal_id=goal.id) == [audit]
    assert calls == [
        ("goal", goal.id),
        ("checkpoint", goal.id),
        ("invocation", invocation.id),
        ("invocations", {"agent_goal_id": goal.id}),
        ("memory", {"source_ref": f"agent_goal:{goal.id}"}),
        ("audit", {"agent_goal_id": goal.id}),
    ]


def test_goal_projection_adapter_uses_explicit_state_and_persistence() -> None:
    conversation = _conversation()
    goal = SimpleNamespace(id="goal-1", conversation_id=conversation.id)
    calls: list[tuple[str, str]] = []
    adapter = LegacyAgentGoalProjectionStateAdapter(
        AgentGoalProjectionState(
            conversations={conversation.id: conversation},
        ),
        AgentGoalProjectionPersistenceAdapters(
            upsert_goal=lambda current: calls.append(("goal", current.id)),
            upsert_conversation=lambda current: calls.append(
                ("conversation", current.id)
            ),
        ),
    )

    assert adapter.get_conversation(conversation.id) is conversation
    adapter.persist_goal_projection(conversation, goal)
    assert calls == [
        ("goal", goal.id),
        ("conversation", conversation.id),
    ]


def test_goal_lifecycle_adapter_delegates_state_and_side_effects() -> None:
    conversation = _conversation()
    goal = SimpleNamespace(
        id="goal-1",
        conversation_id=conversation.id,
        status="running",
        title="Build system image",
    )
    message = _message(3)
    calls: list[tuple[str, object]] = []
    state = AgentGoalLifecycleState(
        goals={},
        conversations={conversation.id: conversation},
    )

    async def append_text_message(conversation_id, role, text, **kwargs):
        calls.append(("message", (conversation_id, role, text, kwargs)))
        return message

    async def push_goal_event(*args, **kwargs):
        calls.append(("goal_event", (args, kwargs)))

    async def push_conversation_event(*args, **kwargs):
        calls.append(("conversation_event", (args, kwargs)))

    effects = AgentGoalLifecycleAdapters(
        project_goal=lambda current: calls.append(("project", current.id)),
        record_goal_audit_event=lambda current, **kwargs: calls.append(
            ("audit", (current.id, kwargs))
        ),
        append_text_message=append_text_message,
        push_goal_event=push_goal_event,
        push_conversation_event=push_conversation_event,
    )
    adapter = LegacyAgentGoalLifecycleStateAdapter(state, effects)

    adapter.create_goal(goal)
    conversation.agent_goals = [goal]
    adapter.persist_goal(goal)
    assert adapter.has_goal(goal.id) is True
    assert adapter.get_goal(goal.id) is goal
    assert adapter.list_goals_for_conversation(conversation.id) == (goal,)
    adapter.record_goal_audit(
        goal,
        action="agent.goal.created",
        status=goal.status,
        summary="Goal created",
        actor="user-1",
        actor_kind="user",
    )
    assert asyncio.run(
        adapter.append_assistant_message(
            conversation.id,
            "Goal created",
            metadata={"goal_id": goal.id},
        )
    ) is message
    asyncio.run(adapter.publish_interrupted(goal))
    asyncio.run(adapter.publish_feedback(goal, "Continue with more evidence"))

    assert state.goals[goal.id] is goal
    assert [call for call in calls if call[0] == "project"] == [
        ("project", goal.id),
        ("project", goal.id),
    ]
    assert any(call[0] == "audit" for call in calls)
    assert any(call[0] == "message" for call in calls)
    assert len([call for call in calls if call[0] == "goal_event"]) == 2
    assert len([call for call in calls if call[0] == "conversation_event"]) == 0


def test_agent_loop_adapter_uses_explicit_runtime_and_goal_effects() -> None:
    conversation = _conversation()
    goal = SimpleNamespace(
        id="goal-1",
        conversation_id=conversation.id,
        status="proposed",
        title="Assess release readiness",
    )
    message = _message(5)
    calls: list[tuple[str, object]] = []

    async def append_text_message(conversation_id, role, text, **kwargs):
        calls.append(("message", (conversation_id, role, text, kwargs)))
        return message

    async def push_goal_event(*args, **kwargs):
        calls.append(("goal_event", (args, kwargs)))

    async def push_conversation_event(*args, **kwargs):
        calls.append(("conversation_event", (args, kwargs)))

    effects = AgentGoalLifecycleAdapters(
        project_goal=lambda current: calls.append(("project", current.id)),
        record_goal_audit_event=lambda current, **kwargs: calls.append(
            ("audit", (current.id, kwargs))
        ),
        append_text_message=append_text_message,
        push_goal_event=push_goal_event,
        push_conversation_event=push_conversation_event,
    )
    adapter = LegacyAgentLoopStateAdapter(
        AgentLoopRuntimeAdapters(
            get_conversation=lambda conversation_id: conversation,
            create_goal=lambda payload: calls.append(("create", payload)) or goal,
            get_goal=lambda goal_id: goal,
        ),
        effects,
    )
    payload = SimpleNamespace(goal_description="Assess the version")

    assert adapter.get_conversation(conversation.id) is conversation
    assert adapter.create_goal(payload) is goal
    assert adapter.get_goal(goal.id) is goal
    adapter.record_goal_audit(
        goal,
        action="agent.goal.proposed",
        status=goal.status,
        summary="Goal proposed",
    )
    asyncio.run(adapter.publish_goal_proposed(goal, graph_kind="quality_loop"))
    assert asyncio.run(
        adapter.append_assistant_message(conversation.id, "Goal proposed")
    ) is message

    assert ("create", payload) in calls
    assert any(call[0] == "audit" for call in calls)
    conversation_event = next(
        call for call in calls if call[0] == "conversation_event"
    )
    assert conversation_event[1][0][1] == "conversation.agent_goal.proposed"
    assert conversation_event[1][0][5]["graph_kind"] == "quality_loop"


def test_agent_graph_adapter_uses_explicit_runtime_and_effect_ports() -> None:
    conversation = _conversation()
    goal = SimpleNamespace(
        id="goal-1",
        conversation_id=conversation.id,
        status="running",
        title="Build system image",
        query_keys=[
            ["project", "project-1"],
            ["system-image", "project-1"],
            ["conversation", conversation.id],
        ],
    )
    invocation = SimpleNamespace(id="invocation-1")
    message = _message(7)
    checkpoint = SimpleNamespace(id="checkpoint-1")
    memory_item = SimpleNamespace(id="memory-1")
    memory_context = SimpleNamespace(summary="project memory")
    calls: list[tuple[str, object]] = []

    async def create_tool(payload):
        calls.append(("create_tool", payload))
        return invocation

    async def confirm_tool(invocation_id):
        calls.append(("confirm_tool", invocation_id))
        return invocation

    def get_tool(invocation_id):
        calls.append(("get_tool", invocation_id))
        if invocation_id == "missing":
            raise KeyError(invocation_id)
        return invocation

    async def create_checkpoint(**kwargs):
        calls.append(("checkpoint", kwargs))
        return checkpoint

    async def build_memory_context(current):
        calls.append(("memory_context", current.id))
        return memory_context

    async def append_text_message(conversation_id, role, text, **kwargs):
        calls.append(("message", (conversation_id, role, text, kwargs)))
        return message

    async def push_goal_event(*args, **kwargs):
        calls.append(("goal_event", (args, kwargs)))

    async def push_conversation_event(*args, **kwargs):
        calls.append(("conversation_event", (args, kwargs)))

    goal_effects = AgentGoalLifecycleAdapters(
        project_goal=lambda current: calls.append(("project", current.id)),
        record_goal_audit_event=lambda current, **kwargs: calls.append(
            ("audit", (current.id, kwargs))
        ),
        append_text_message=append_text_message,
        push_goal_event=push_goal_event,
        push_conversation_event=push_conversation_event,
    )
    adapter = LegacyAgentGraphStateAdapter(
        AgentGraphLookupAdapters(
            get_goal=lambda goal_id: goal,
            get_conversation=lambda conversation_id: conversation,
        ),
        AgentGraphToolRuntimeAdapters(
            create_tool_invocation=create_tool,
            confirm_tool_invocation=confirm_tool,
            get_tool_invocation=get_tool,
            available_tool_ids=lambda: iter(
                ["system_image.sources.ingest", "quality.scope.generate"]
            ),
        ),
        AgentGraphMemoryAdapters(
            create_summary_checkpoint=create_checkpoint,
            record_memory_item=lambda **kwargs: (
                calls.append(("memory_item", kwargs)) or memory_item
            ),
                build_memory_context=build_memory_context,
        ),
        goal_effects,
    )

    payload = SimpleNamespace(tool_id="system_image.sources.ingest")
    assert adapter.get_goal(goal.id) is goal
    assert adapter.get_conversation(conversation.id) is conversation
    assert asyncio.run(adapter.create_tool_invocation(payload)) is invocation
    assert asyncio.run(
        adapter.confirm_tool_invocation(invocation.id)
    ) is invocation
    assert adapter.get_tool_invocation_or_none(invocation.id) is invocation
    assert adapter.get_tool_invocation_or_none("missing") is None
    adapter.persist_goal(goal)
    adapter.record_goal_audit(
        goal,
        action="agent.goal.step.updated",
        status=goal.status,
        summary="Graph step updated",
    )
    asyncio.run(
        adapter.publish_goal_event(
            goal,
            "agent.goal.updated",
            {"status": goal.status},
        )
    )
    assert asyncio.run(
        adapter.append_assistant_message(
            conversation.id,
            "System image is ready",
            tool_refs=[invocation.id],
            object_refs=["baseline:baseline-1"],
        )
    ) is message
    assert asyncio.run(
        adapter.create_memory_checkpoint(
            conversation_id=conversation.id,
            agent_goal_id=goal.id,
        )
    ) is checkpoint
    assert adapter.record_memory_item(
        memory_scope="project",
        owner_ref="project:project-1",
        summary="System image ready",
        source_refs=[f"agent_goal:{goal.id}"],
        object_refs=["baseline:baseline-1"],
        evidence_refs=[invocation.id],
        link_refs=[("baseline:baseline-1", "project:project-1", 1.0)],
    ) is memory_item
    assert asyncio.run(adapter.build_memory_context(goal)) is memory_context
    assert adapter.available_tool_ids() == (
        "system_image.sources.ingest",
        "quality.scope.generate",
    )

    assert ("project", goal.id) in calls
    assert any(call[0] == "audit" for call in calls)
    goal_event = next(call for call in calls if call[0] == "goal_event")
    expected_query_keys = [
        ["conversation", conversation.id],
        ["agent-goal", goal.id],
        ["agent-memory", goal.id],
        ["project", "project-1"],
        ["system-image", "project-1"],
    ]
    assert goal_event[1][0][4] == expected_query_keys
    assert not any(call[0] == "conversation_event" for call in calls)
    assert ("memory_context", conversation.id) in calls


def test_agent_memory_adapter_uses_explicit_projection_and_query_ports() -> None:
    conversation = _conversation()
    goal = SimpleNamespace(id="goal-1", conversation_id=conversation.id)
    checkpoint = SimpleNamespace(id="checkpoint-1")
    memory_item = SimpleNamespace(id="memory-1")
    memory_link = SimpleNamespace(id="link-1")
    tool = SimpleNamespace(tool_id="query.system_image.status")
    calls: list[tuple[str, object]] = []
    state = AgentMemoryProjectionState(
        conversations={conversation.id: conversation},
        summary_checkpoints={},
        memory_items={},
        memory_links={},
    )
    candidate_queries = CompatibilityAgentMemoryCandidateQueries(
        AgentMemoryCandidateProjectionState(
            session_knowledge_bindings={
                "binding-1": SimpleNamespace(
                    conversation_id=conversation.id,
                    candidate_object_ref="context_object:candidate-1",
                ),
                "binding-2": SimpleNamespace(
                    conversation_id="conversation-other",
                    candidate_object_ref="context_object:other",
                ),
            },
            context_object_overlays={
                "project-1": [
                    SimpleNamespace(id="overlay-1", status="candidate"),
                    SimpleNamespace(id="overlay-2", status="merged"),
                ]
            },
        )
    )
    workspace_queries = CompatibilityAgentMemoryWorkspaceQueries(
        AgentMemoryWorkspaceProjectionState(
            projects={
                "project-1": SimpleNamespace(
                    id="project-1",
                    name="Checkout",
                    progress=72,
                    risk="medium",
                    blocked_items=1,
                    pending_approvals=2,
                    system_image_status="ready",
                )
            },
            versions={
                "project-1": [
                    SimpleNamespace(
                        id="version-1",
                        name="2026.Q3",
                        status="active",
                        us_closed=5,
                        us_total=8,
                        pending_runs=2,
                        pending_approvals=1,
                    )
                ]
            },
            us_items={
                "version-1": [
                    SimpleNamespace(
                        id="us-1",
                        title="Saved cards",
                        owner="qa-owner",
                        status="in_progress",
                        risk="high",
                        progress=55,
                        next_action="Generate regression cases",
                    )
                ]
            },
            asset_lanes={
                "us-1": [
                    SimpleNamespace(
                        label="Test cases",
                        status="draft",
                        summary="12 cases",
                    )
                ]
            },
            runs={
                "project-1": [
                    SimpleNamespace(
                        id="run-1",
                        title="Checkout smoke",
                        status="failed",
                        channel="web",
                        summary="One assertion failed",
                    )
                ]
            },
            approvals={
                "project-1": [
                    SimpleNamespace(
                        id="approval-1",
                        title="Release approval",
                        status="pending",
                        summary="Awaiting QA lead",
                    )
                ]
            },
        )
    )

    async def push_event(*args, **kwargs):
        calls.append(("event", (args, kwargs)))

    adapter = LegacyAgentMemoryStateAdapter(
        state,
        AgentMemoryPersistenceAdapters(
            upsert_summary_checkpoint=lambda current: calls.append(
                ("checkpoint", current.id)
            ),
            upsert_conversation=lambda current: calls.append(
                ("conversation", current.id)
            ),
            upsert_memory_item=lambda current: calls.append(
                ("memory_item", current.id)
            ),
            upsert_memory_link=lambda current: calls.append(
                ("memory_link", current.id)
            ),
        ),
        AgentMemoryRuntimeAdapters(
            get_goal=lambda goal_id: goal,
            active_goal_for_conversation=lambda conversation_id: goal,
            available_tools=lambda: iter([tool]),
        ),
        AgentMemoryEventAdapters(push_event=push_event),
        candidate_queries,
        workspace_queries,
    )

    assert adapter.get_goal(goal.id) is goal
    assert adapter.active_goal_for_conversation(conversation.id) is goal
    assert adapter.get_conversation(conversation.id) is conversation
    assert adapter.list_conversations() == (conversation,)
    assert adapter.available_tools() == (tool,)
    adapter.persist_summary_checkpoint(conversation, checkpoint)
    assert adapter.list_summary_checkpoints() == (checkpoint,)
    assert conversation.latest_summary_checkpoint_id == checkpoint.id
    asyncio.run(adapter.publish_memory_checkpointed(conversation, checkpoint))
    adapter.persist_memory_item(memory_item)
    adapter.persist_memory_link(memory_link)
    assert adapter.list_memory_items() == (memory_item,)
    assert adapter.session_candidate_refs(conversation.id) == (
        "context_object:candidate-1",
    )
    assert adapter.candidate_overlay_refs("project-1") == (
        "context_overlay:overlay-1:candidate",
    )
    assert adapter.project_snapshot("project-1").name == "Checkout"
    assert adapter.latest_version_snapshot("project-1").name == "2026.Q3"
    assert adapter.us_snapshot("us-1").asset_lanes[0].summary == "12 cases"
    assert adapter.recent_run_snapshots("project-1")[0].status == "failed"
    assert (
        adapter.recent_approval_snapshots("project-1")[0].status
        == "pending"
    )

    assert state.memory_items[memory_item.id] is memory_item
    assert state.memory_links[memory_link.id] is memory_link
    assert ("checkpoint", checkpoint.id) in calls
    assert ("conversation", conversation.id) in calls
    assert ("memory_item", memory_item.id) in calls
    assert ("memory_link", memory_link.id) in calls
    event_call = next(call for call in calls if call[0] == "event")
    assert event_call[1][1]["event_type"] == "agent.memory.checkpointed"


def test_agent_swarm_adapter_uses_explicit_projection_and_effect_ports() -> None:
    swarm = SimpleNamespace(
        id="swarm-1",
        parent_goal_id="goal-1",
        conversation_id="conversation-1",
    )
    calls: list[tuple[str, object]] = []
    state = AgentSwarmProjectionState(swarms={})

    async def push_event(*args, **kwargs):
        calls.append(("event", (args, kwargs)))

    adapter = LegacyAgentSwarmStateAdapter(
        state,
        AgentSwarmPersistenceAdapters(
            upsert_swarm=lambda current: calls.append(
                ("persist", current.id)
            ),
        ),
        AgentSwarmEventAdapters(push_event=push_event),
    )

    adapter.persist_swarm(swarm)
    assert adapter.get_swarm(swarm.id) is swarm
    asyncio.run(
        adapter.publish_swarm_event(
            swarm,
            "agent.swarm.completed",
            {"status": "completed"},
        )
    )

    assert state.swarms[swarm.id] is swarm
    assert ("persist", swarm.id) in calls
    event_call = next(call for call in calls if call[0] == "event")
    event_args = event_call[1][0]
    assert event_args[:6] == (
        swarm.conversation_id,
        "agent.swarm.completed",
        "agent_swarm",
        swarm.id,
        "patch",
        {
            "status": "completed",
            "agent_goal_id": swarm.parent_goal_id,
            "swarm_run_id": swarm.id,
        },
    )
    assert event_args[6] == [
        ["conversation", swarm.conversation_id],
        ["agent-swarm", swarm.id],
        ["agent-swarms", swarm.conversation_id],
    ]


def test_agent_workflow_adapter_uses_explicit_runtime_callbacks() -> None:
    goal = SimpleNamespace(id="goal-1", workflow_id="workflow-1")
    remote_goal = SimpleNamespace(id="goal-remote", workflow_id="workflow-remote")
    calls: list[tuple[str, object]] = []
    adapter = LegacyAgentWorkflowStateAdapter(
        AgentWorkflowRuntimeAdapters(
            get_goal=lambda goal_id: calls.append(("get", goal_id)) or goal,
            accept_remote_goal=lambda current: calls.append(
                ("accept", current.id)
            ),
        )
    )

    assert adapter.workflow_id_for_goal(goal.id) == goal.workflow_id
    adapter.accept_remote_goal(remote_goal)

    assert calls == [
        ("get", goal.id),
        ("accept", remote_goal.id),
    ]
