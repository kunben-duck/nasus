from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from ...application.agent.agent_models import ConversationSession
from ...application.platform.project_models import ProjectCard
from ...application.system_image.system_image_models import (
    BaselineRecord,
    ContextRelationship,
    KnowledgeObject,
    QualityMetricSnapshot,
    RawAssetRecord,
)
from ...domain.agent.memory import AgentMemoryContext


@dataclass(frozen=True)
class AgentPlanningProjectionState:
    """Read-only projections required to compile state-aware Agent plans."""

    projects: Mapping[str, ProjectCard]
    raw_assets: Mapping[str, list[RawAssetRecord]]
    knowledge_objects: Mapping[str, list[KnowledgeObject]]
    context_relationships: Mapping[str, list[ContextRelationship]]
    quality_metric_snapshots: Mapping[str, list[QualityMetricSnapshot]]
    baselines: Mapping[str, list[BaselineRecord]]


@dataclass(frozen=True)
class AgentPlanningRuntimeAdapters:
    """Runtime queries that cannot be represented by compatibility projections."""

    source_binding_incomplete: Callable[[str], bool]
    known_tool_ids: Callable[[], frozenset[str]]


@dataclass(frozen=True)
class AgentPlannerContextAdapters:
    """Explicit cross-domain reads used to construct planner context."""

    memory_context: Callable[[ConversationSession], Awaitable[AgentMemoryContext]]
    conversation_summary_fallback: Callable[[ConversationSession], str]
    quality_state: Callable[[str | None, str | None], dict[str, str]]


__all__ = [
    "AgentPlanningProjectionState",
    "AgentPlanningRuntimeAdapters",
    "AgentPlannerContextAdapters",
]
