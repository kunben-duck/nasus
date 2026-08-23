from __future__ import annotations

import asyncio

from apps.api.app.application.agent.agent_models import (
    AgentMemoryItem,
    AgentMemoryLink,
    ConversationMessage,
    ConversationSession,
    ConversationSummaryCheckpoint,
    MessageBlock,
)
from apps.api.app.application.agent.memory import AgentMemoryManager
from apps.api.app.application.agent.ports import (
    AgentMemoryApprovalSnapshot,
    AgentMemoryAssetLaneSnapshot,
    AgentMemoryProjectSnapshot,
    AgentMemoryRunSnapshot,
    AgentMemoryUSSnapshot,
    AgentMemoryVersionSnapshot,
)
from apps.api.app.application.platform.tool_models import ToolDefinition
from apps.api.app.application.system_image.retrieval import (
    SystemImageMemoryHit,
    SystemImageMemorySearchResult,
)


class InMemoryAgentMemoryState:
    def __init__(self, conversation: ConversationSession) -> None:
        self.conversation = conversation
        self.checkpoints: list[ConversationSummaryCheckpoint] = []
        self.memory_items: list[AgentMemoryItem] = []
        self.memory_links: list[AgentMemoryLink] = []
        self.published_checkpoint_ids: list[str] = []

    def get_goal(self, goal_id: str):
        raise KeyError(goal_id)

    def active_goal_for_conversation(self, conversation_id: str):
        assert conversation_id == self.conversation.id
        return None

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        assert conversation_id == self.conversation.id
        return self.conversation

    def list_conversations(self) -> tuple[ConversationSession, ...]:
        return (self.conversation,)

    def available_tools(self) -> tuple[ToolDefinition, ...]:
        return (
            ToolDefinition(
                tool_id="query.system_image.status",
                label="Inspect system image",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Return the current system-image status.",
            ),
        )

    def list_summary_checkpoints(self) -> tuple[ConversationSummaryCheckpoint, ...]:
        return tuple(self.checkpoints)

    def persist_summary_checkpoint(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        conversation.latest_summary_checkpoint_id = checkpoint.id
        self.checkpoints.append(checkpoint)

    async def publish_memory_checkpointed(
        self,
        conversation: ConversationSession,
        checkpoint: ConversationSummaryCheckpoint,
    ) -> None:
        assert conversation.id == self.conversation.id
        self.published_checkpoint_ids.append(checkpoint.id)

    def persist_memory_item(self, item: AgentMemoryItem) -> None:
        self.memory_items.append(item)

    def persist_memory_link(self, link: AgentMemoryLink) -> None:
        self.memory_links.append(link)

    def list_memory_items(self) -> tuple[AgentMemoryItem, ...]:
        return tuple(self.memory_items)

    def session_candidate_refs(self, conversation_id: str) -> tuple[str, ...]:
        assert conversation_id == self.conversation.id
        return ("context_object:candidate-session",)

    def candidate_overlay_refs(self, project_id: str) -> tuple[str, ...]:
        assert project_id == "project_checkout"
        return ("context_overlay:candidate-project:active",)

    def project_snapshot(self, project_id: str) -> AgentMemoryProjectSnapshot | None:
        assert project_id == "project_checkout"
        return AgentMemoryProjectSnapshot(
            id=project_id,
            name="Checkout",
            progress=64,
            risk="medium",
            blocked_items=1,
            pending_approvals=2,
            system_image_status="ready",
        )

    def latest_version_snapshot(self, project_id: str) -> AgentMemoryVersionSnapshot | None:
        assert project_id == "project_checkout"
        return AgentMemoryVersionSnapshot(
            id="version_q3",
            name="2026.Q3",
            status="active",
            us_closed=4,
            us_total=7,
            pending_runs=2,
            pending_approvals=1,
        )

    def us_snapshot(self, us_id: str) -> AgentMemoryUSSnapshot | None:
        assert us_id == "us_payment"
        return AgentMemoryUSSnapshot(
            id=us_id,
            title="Support saved cards",
            owner="qa-owner",
            status="in_progress",
            risk="high",
            progress=55,
            next_action="Generate regression cases",
            asset_lanes=(
                AgentMemoryAssetLaneSnapshot(
                    label="Test cases",
                    status="draft",
                    summary="12 cases generated",
                ),
            ),
        )

    def recent_run_snapshots(self, project_id: str) -> tuple[AgentMemoryRunSnapshot, ...]:
        assert project_id == "project_checkout"
        return (
            AgentMemoryRunSnapshot(
                id="run_smoke",
                title="Checkout smoke",
                status="failed",
                channel="web",
                summary="One payment assertion failed.",
            ),
        )

    def recent_approval_snapshots(
        self,
        project_id: str,
    ) -> tuple[AgentMemoryApprovalSnapshot, ...]:
        assert project_id == "project_checkout"
        return (
            AgentMemoryApprovalSnapshot(
                id="approval_release",
                title="Release approval",
                status="pending",
                summary="Awaiting QA lead.",
            ),
        )


class EmptySystemImageWorkspace:
    def has_project(self, project_id: str) -> bool:
        return False

    def list_baselines(self, project_id: str) -> list:
        return []

    def list_raw_assets(self, project_id: str) -> list:
        return []

    def list_knowledge_objects(self, project_id: str) -> list:
        return []

    def list_context_relationships(self, project_id: str) -> list:
        return []

    def list_quality_metric_snapshots(self, project_id: str) -> list:
        return []


class StaticSystemImageRetriever:
    async def search_project_memory(
        self,
        conversation: ConversationSession,
        query: str,
        *,
        limit: int = 8,
        trace: bool = False,
    ) -> SystemImageMemorySearchResult:
        assert conversation.project_id == "project_checkout"
        assert "saved cards" in query
        assert limit == 8
        return SystemImageMemorySearchResult(
            hits=(
                SystemImageMemoryHit(
                    ref="context_object:checkout-api",
                    kind="api",
                    score=0.94,
                    summary="POST /payments uses the checkout payment service.",
                ),
            ),
            retrieval_run_refs=("retrieval_run:retrieval_checkout",) if trace else (),
        )


def _conversation() -> ConversationSession:
    return ConversationSession(
        id="conversation_checkout",
        session_id="session_checkout",
        title="Checkout quality review",
        space_type="workspace",
        space_id="us_payment",
        project_id="project_checkout",
        version_id="version_q3",
        us_id="us_payment",
        status="active",
        messages=[
            ConversationMessage(
                id="message_user",
                role="user",
                created_at="2026-07-30T10:00:00+00:00",
                blocks=[MessageBlock(type="text", text="Assess saved cards risk.")],
            ),
            ConversationMessage(
                id="message_agent",
                role="assistant",
                created_at="2026-07-30T10:00:01+00:00",
                blocks=[MessageBlock(type="text", text="I will inspect the system image.")],
            ),
        ],
    )


def test_agent_memory_builds_context_from_declared_state_port() -> None:
    conversation = _conversation()
    state = InMemoryAgentMemoryState(conversation)
    manager = AgentMemoryManager(
        state,
        StaticSystemImageRetriever(),
        EmptySystemImageWorkspace(),
    )

    context = asyncio.run(
        manager.build_context(
            conversation,
            tools=list(state.available_tools()),
        )
    )

    assert "[project]" in context.context_snapshot
    assert "name=Checkout" in context.context_snapshot
    assert "version_id=version_q3" in context.context_snapshot
    assert "us_id=us_payment" in context.context_snapshot
    assert "run=run_smoke" in context.context_snapshot
    assert "approval=approval_release" in context.context_snapshot
    assert "query.system_image.status" in context.context_snapshot
    assert "context_object:checkout-api" in context.context_snapshot
    assert context.retrieved_context_refs == ["context_object:checkout-api"]
    assert context.recent_turn_count == 2

    view = asyncio.run(manager.get_context_view(conversation_id=conversation.id))
    assert view["candidate_memory"]["session_only_refs"] == [
        "context_object:candidate-session"
    ]
    assert view["candidate_memory"]["candidate_overlay_refs"] == [
        "context_overlay:candidate-project:active"
    ]


def test_agent_memory_persists_items_links_and_checkpoints_through_port() -> None:
    conversation = _conversation()
    state = InMemoryAgentMemoryState(conversation)
    manager = AgentMemoryManager(
        state,
        StaticSystemImageRetriever(),
        EmptySystemImageWorkspace(),
    )

    item = manager.record_item(
        memory_scope="project_long_term",
        owner_ref="project:project_checkout",
        summary="Saved-card failures require payment API regression coverage.",
        source_refs=["run:run_smoke", "run:run_smoke"],
        object_refs=["context_object:checkout-api"],
        evidence_refs=["evidence:trace-1"],
    )
    checkpoint = asyncio.run(
        manager.create_summary_checkpoint(
            conversation_id=conversation.id,
            created_by="user",
        )
    )

    assert state.memory_items == [item]
    assert {link.link_kind for link in state.memory_links} == {
        "belongs_to",
        "derived_from",
        "supports",
        "evidenced_by",
    }
    assert checkpoint in state.checkpoints
    assert state.published_checkpoint_ids == [checkpoint.id]
    assert conversation.latest_summary_checkpoint_id == checkpoint.id
