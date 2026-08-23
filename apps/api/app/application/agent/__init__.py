"""Agent application services.

This package intentionally uses lazy exports. The root compatibility
`models.py` re-exports Agent contract DTOs during the DDD migration, and eager
imports from this package would otherwise create circular dependencies through
agent services that still consume compatibility models.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "AgentApplicationService",
    "AgentGoal",
    "AgentGoalBudgetUpdateRequest",
    "AgentGoalCreateRequest",
    "AgentGoalFeedbackRequest",
    "AgentGoalExplanationApplicationService",
    "AgentGoalLifecycleApplicationService",
    "AgentGoalProjectionApplicationService",
    "AgentGraphRuntime",
    "AgentMemoryCheckpointRequest",
    "AgentMemoryItem",
    "AgentMemoryLink",
    "AgentMemoryManager",
    "AgentReply",
    "AgentReplyApplicationService",
    "AgentReplyGenerationPort",
    "AgentReplyMemoryPort",
    "AgentReplyMessageWriterPort",
    "AgentReplyModelSettingsPort",
    "AgentService",
    "AgentStep",
    "AgentPlannerContextApplicationService",
    "AgentSwarmCoordinator",
    "AgentSwarmCreateRequest",
    "AgentSwarmRun",
    "AgentWorkerAssignment",
    "ConversationArchiveRequest",
    "ConversationCreateRequest",
    "ConversationFallbackApplicationService",
    "ConversationLink",
    "ConversationManagementApplicationService",
    "ConversationMergeRequest",
    "ConversationMessage",
    "ConversationMessageApplicationService",
    "ConversationMessageRequest",
    "ConversationMessageWriterApplicationService",
    "ConversationOrchestrator",
    "ConversationSession",
    "ConversationSummaryCheckpointApplicationService",
    "ConversationSummaryCheckpoint",
    "ConversationSummaryCheckpointService",
    "LangGraphAgentGraphRuntime",
    "LangGraphGateway",
    "LocalAgentGraphRuntime",
    "LocalAgentWorkflowRuntime",
    "MessageBlock",
    "SessionKnowledgeBinding",
    "SpaceType",
    "TemporalAgentWorkflowRuntime",
    "TemporalWorkflowGateway",
    "AgentWorkflowRuntime",
    "AgentGoalPlanCompiler",
    "AgentReplanDecision",
    "AgentReplanRequest",
    "AgentReplanner",
]

_EXPORT_MODULES = {
    "AgentApplicationService": ".use_cases",
    "AgentGoal": ".agent_models",
    "AgentGoalBudgetUpdateRequest": ".agent_models",
    "AgentGoalCreateRequest": ".agent_models",
    "AgentGoalFeedbackRequest": ".agent_models",
    "AgentGoalExplanationApplicationService": ".explanations",
    "AgentGoalLifecycleApplicationService": ".lifecycle",
    "AgentGoalProjectionApplicationService": ".goal_projection",
    "AgentGraphRuntime": ".graph",
    "AgentMemoryCheckpointRequest": ".agent_models",
    "AgentMemoryItem": ".agent_models",
    "AgentMemoryLink": ".agent_models",
    "AgentMemoryManager": ".memory",
    "AgentReply": ".replies",
    "AgentReplyApplicationService": ".replies",
    "AgentReplyGenerationPort": ".reply_ports",
    "AgentReplyMemoryPort": ".reply_ports",
    "AgentReplyMessageWriterPort": ".reply_ports",
    "AgentReplyModelSettingsPort": ".reply_ports",
    "AgentService": ".lifecycle",
    "AgentStep": ".agent_models",
    "AgentPlannerContextApplicationService": ".planner_context",
    "AgentSwarmCoordinator": ".swarm",
    "AgentSwarmCreateRequest": ".agent_models",
    "AgentSwarmRun": ".agent_models",
    "AgentWorkerAssignment": ".agent_models",
    "ConversationArchiveRequest": ".agent_models",
    "ConversationCreateRequest": ".agent_models",
    "ConversationFallbackApplicationService": ".conversation_fallbacks",
    "ConversationLink": ".agent_models",
    "ConversationManagementApplicationService": ".conversations",
    "ConversationMergeRequest": ".agent_models",
    "ConversationMessage": ".agent_models",
    "ConversationMessageApplicationService": ".messages",
    "ConversationMessageRequest": ".agent_models",
    "ConversationMessageWriterApplicationService": ".message_writer",
    "ConversationOrchestrator": ".orchestrator",
    "ConversationSession": ".agent_models",
    "ConversationSummaryCheckpointApplicationService": ".conversation_summary",
    "ConversationSummaryCheckpoint": ".agent_models",
    "ConversationSummaryCheckpointService": ".conversation_summary",
    "LangGraphAgentGraphRuntime": ".graph",
    "LangGraphGateway": ".graph",
    "LocalAgentGraphRuntime": ".graph",
    "LocalAgentWorkflowRuntime": ".workflow",
    "MessageBlock": ".agent_models",
    "SessionKnowledgeBinding": ".agent_models",
    "SpaceType": ".agent_models",
    "TemporalAgentWorkflowRuntime": ".workflow",
    "TemporalWorkflowGateway": ".workflow",
    "AgentWorkflowRuntime": ".workflow",
    "AgentGoalPlanCompiler": ".plans",
    "AgentReplanDecision": ".replanning",
    "AgentReplanRequest": ".replanning",
    "AgentReplanner": ".replanning",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
