"""Quality-loop application services.

This package uses lazy exports so the root compatibility `models.py` can
re-export quality-loop contract DTOs during the DDD migration without creating
eager import cycles through use-case services.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "ApprovalDetail",
    "ApprovalSummary",
    "AssetLane",
    "ExecutionEvidence",
    "FailureReport",
    "ConflictEntry",
    "MergedResolution",
    "ProjectVersionApplicationError",
    "ProjectVersionApplicationService",
    "ProjectVersionUseCaseResult",
    "ProjectVersionWorkspacePort",
    "QualityAssetPackReadPort",
    "QualityAssetPackWorkspacePort",
    "QualityAssetProgressWorkspacePort",
    "QualityAssetPackApplicationService",
    "QualityAssetProgressApplicationService",
    "QualityAutomationExecutionPort",
    "QualityExecutionEvidenceReadPort",
    "QualityFailureWorkspacePort",
    "QualityImageWorkspacePort",
    "QualityLoopContextQueryApplicationService",
    "QualityLoopContextReadPort",
    "QualityLoopContextWorkspacePort",
    "QualityLoopConversationScope",
    "QualityLoopReleaseDecisionReadPort",
    "QualityAssetPack",
    "QualityAssetGenerationMetadata",
    "QualityAssetPart",
    "QualityGenerationError",
    "QualityGenerationPort",
    "QualityGenerationRequest",
    "QualityGenerationResult",
    "QualityLoopApplicationError",
    "QualityLoopApplicationService",
    "QualityFailureReportApplicationService",
    "QualityImageUpdateApplicationService",
    "QualityStepCompletionApplicationService",
    "QualityLoopState",
    "QualityLoopReleaseDecisionQueryApplicationService",
    "QualityLoopScopeQueryApplicationService",
    "QualityLoopScopeWorkspacePort",
    "QualityLoopUseCaseResult",
    "QualityReleaseReadinessApplicationService",
    "QualityRunExecutionApplicationService",
    "QualityRunExecutionResult",
    "QualityLoopVersionContextApplicationService",
    "ReleaseDecision",
    "ReleaseReadiness",
    "RunDetail",
    "RunSummary",
    "USItem",
]

_EXPORT_MODULES = {
    "ConflictEntry": ".governance_models",
    "MergedResolution": ".governance_models",
    "ApprovalDetail": ".quality_models",
    "ApprovalSummary": ".quality_models",
    "AssetLane": ".quality_models",
    "ExecutionEvidence": ".quality_models",
    "FailureReport": ".quality_models",
    "ProjectVersionApplicationError": ".project_versions",
    "ProjectVersionApplicationService": ".project_versions",
    "ProjectVersionUseCaseResult": ".project_versions",
    "ProjectVersionWorkspacePort": ".ports",
    "QualityAssetPackReadPort": ".ports",
    "QualityAssetPackWorkspacePort": ".ports",
    "QualityAssetProgressWorkspacePort": ".ports",
    "QualityAssetPackApplicationService": ".asset_packs",
    "QualityAssetProgressApplicationService": ".asset_progress",
    "QualityAutomationExecutionPort": ".runner_port",
    "QualityExecutionEvidenceReadPort": ".ports",
    "QualityFailureWorkspacePort": ".ports",
    "QualityImageWorkspacePort": ".ports",
    "QualityLoopContextQueryApplicationService": ".context_queries",
    "QualityLoopContextReadPort": ".ports",
    "QualityLoopContextWorkspacePort": ".ports",
    "QualityLoopConversationScope": ".ports",
    "QualityLoopReleaseDecisionReadPort": ".ports",
    "QualityAssetPack": ".quality_models",
    "QualityAssetGenerationMetadata": ".quality_models",
    "QualityAssetPart": ".quality_models",
    "QualityGenerationError": ".generation",
    "QualityGenerationPort": ".generation",
    "QualityGenerationRequest": ".generation",
    "QualityGenerationResult": ".generation",
    "QualityLoopApplicationError": ".results",
    "QualityLoopApplicationService": ".use_cases",
    "QualityFailureReportApplicationService": ".failure_reports",
    "QualityImageUpdateApplicationService": ".quality_image_updates",
    "QualityLoopState": ".quality_models",
    "QualityLoopReleaseDecisionQueryApplicationService": ".release_decision_queries",
    "QualityLoopScopeQueryApplicationService": ".scope_queries",
    "QualityLoopScopeWorkspacePort": ".ports",
    "QualityLoopUseCaseResult": ".results",
    "QualityReleaseReadinessApplicationService": ".release_readiness",
    "QualityRunExecutionApplicationService": ".run_execution",
    "QualityRunExecutionResult": ".run_execution",
    "QualityStepCompletionApplicationService": ".quality_steps",
    "QualityLoopVersionContextApplicationService": ".version_context",
    "ReleaseDecision": ".quality_models",
    "ReleaseReadiness": ".quality_models",
    "RunDetail": ".quality_models",
    "RunSummary": ".quality_models",
    "USItem": ".quality_models",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
