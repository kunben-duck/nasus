from __future__ import annotations

import re
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..agent.agent_models import ConversationSession
from ..quality_loop.quality_models import (
    ApprovalSummary,
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    QualityLoopState,
    ReleaseDecision,
    RunSummary,
    USItem,
)
from ..system_image.system_image_models import QualityProfile, TaskContext
from .project_models import ProjectCard, VersionSummary
from .read_query_ports import AgentQueryReadPort


class DocumentationEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    body: str = Field(alias="copy", serialization_alias="copy")
    category: str


class DashboardResponse(BaseModel):
    active_projects: int
    running_versions: int
    blocked_items: int
    pending_approvals: int
    failed_runs: int
    projects: List[ProjectCard]


class BuildResponse(BaseModel):
    drafts: List[ProjectCard]
    imports_health: List[str]
    provider_health: str


class WelcomeResponse(BaseModel):
    recent_projects: List[ProjectCard]
    recent_versions: List[VersionSummary]
    recent_conversations: List[ConversationSession]


class ProjectWorkspaceResponse(BaseModel):
    project: ProjectCard
    versions: List[VersionSummary]
    current_version_id: str
    us_items: List[USItem]
    quality_loop_state: QualityLoopState
    task_context: Optional[TaskContext] = None
    quality_profile: Optional[QualityProfile] = None
    quality_asset_pack: Optional[QualityAssetPack] = None
    asset_lanes: List[AssetLane]
    runs: List[RunSummary]
    execution_evidence: List[ExecutionEvidence] = Field(default_factory=list)
    failure_reports: List[FailureReport] = Field(default_factory=list)
    release_decision: Optional[ReleaseDecision] = None
    approvals: List[ApprovalSummary]


class ReadModelSummaryService:
    """Cross-domain read-model summaries used by agent-facing query tools."""

    def __init__(self, state: AgentQueryReadPort) -> None:
        self._state = state

    def dashboard_summary(self, lowered: str = "") -> str:
        projects = list(self._state.list_projects())
        if not projects:
            return (
                "There are no active projects yet. Create a project and connect its code "
                "repository to initialize the first system image."
            )
        riskiest_project = max(
            projects,
            key=lambda project: (project.blocked_items, project.pending_approvals, 100 - project.progress),
        )
        if "risk" in lowered or "riskiest" in lowered or "风险" in lowered:
            return (
                f"{riskiest_project.name} is currently the riskiest active project because it has "
                f"{riskiest_project.blocked_items} blocked items, "
                f"{riskiest_project.pending_approvals} pending approvals, "
                f"and its active version is still only {riskiest_project.progress}% through the closure path."
            )

        return (
            f"There are {len(projects)} active projects across "
            f"{sum(len(self._state.list_versions(project.id)) for project in projects)} running versions. "
            f"The portfolio currently has {sum(project.blocked_items for project in projects)} "
            f"blocked items, {sum(project.pending_approvals for project in projects)} "
            f"pending approvals, and "
            f"{sum(1 for project in projects for run in self._state.list_runs(project.id) if run.status == 'failed')} failed runs."
        )

    def project_status_summary(self, project_id: str) -> str:
        project = self._state.get_project(project_id)
        versions = self._state.list_versions(project_id)
        active_version = versions[0] if versions else None
        summary = (
            f"{project.name} is {project.progress}% through its quality loop. "
            f"The Official System Image is {project.system_image_status}, "
            f"the active version is {active_version.name if active_version else 'not started'}, "
            f"and there are {project.blocked_items} blocked items with {project.pending_approvals} approvals still open."
        )
        memory_summary = self.recent_project_agent_memory_summary(project_id)
        return f"{summary} {memory_summary}" if memory_summary else summary

    def version_status_summary(self, project_id: str, version_id: str) -> str:
        versions = self._state.list_versions(project_id)
        version = next((item for item in versions if item.id == version_id), versions[0] if versions else None)
        us_items = self._state.list_us_items(project_id)
        high_risk = sum(1 for item in us_items if item.risk == "high")
        if version is None:
            return "No active version branch exists yet. Create a version to start US assignment and quality closure."
        return (
            f"{version.name} is currently {version.status}. "
            f"{version.us_closed} of {version.us_total or len(us_items)} US items are closed, "
            f"{version.pending_runs} runs are still pending, and {high_risk} US items remain in the high-risk bucket."
        )

    def workspace_status_summary(self, us_id: str) -> str:
        lanes = self._state.list_asset_lanes(us_id)
        ready = [lane.label for lane in lanes if lane.status in {"approved", "ready_for_review"}]
        drafting = [lane.label for lane in lanes if lane.status in {"drafting", "not_started"}]
        return (
            f"For {us_id}, the ready lanes are {', '.join(ready) if ready else 'none yet'}, "
            f"while {', '.join(drafting) if drafting else 'no remaining lanes'} still need work. "
            "You can continue with case generation, automation drafting, or execution preparation from here."
        )

    def knowledge_status_summary(self, project_id: str) -> str:
        project = self._state.get_project(project_id)
        summary = (
            f"{project.name} currently has an active system image and version-scoped knowledge changes awaiting promotion. "
            "The most relevant hotspots are checkout flow recovery, payment gateway fallback, and quality asset packs "
            "linked to the active release branch."
        )
        memory_summary = self.recent_project_agent_memory_summary(project_id)
        return f"{summary} {memory_summary}" if memory_summary else summary

    def system_image_status_summary(self, project_id: str) -> str:
        image = self._state.get_system_image(project_id)
        indexed = sum(1 for source in image.sources if source.ingestion_status == "indexed")
        metric_groups = ", ".join(sorted({metric.metric_group for metric in image.metric_snapshots})) or "none"
        summary = (
            f"{image.project.name} system image is {image.project.system_image_status}. "
            f"{indexed}/{len(image.sources)} source groups are indexed across code, historical US docs, and test assets. "
            f"It currently has {len(image.objects)} objects, {len(image.relationships)} relationships, "
            f"and metric groups: {metric_groups}."
        )
        memory_summary = self.recent_project_agent_memory_summary(project_id)
        return f"{summary} {memory_summary}" if memory_summary else summary

    def recent_project_agent_memory_summary(self, project_id: str, *, limit: int = 2) -> str:
        owner_ref = f"project:{project_id}"
        memory_items = sorted(
            [
                item
                for item in self._state.list_agent_memory_items()
                if item.owner_ref == owner_ref
                and item.memory_scope == "project_long_term"
                and item.status == "active"
            ],
            key=lambda item: item.created_at,
        )
        if not memory_items:
            return ""
        excerpts = [re.sub(r"\s+", " ", item.summary).strip()[:260] for item in memory_items[-limit:]]
        return "Recent Agent memory: " + " | ".join(excerpts)

    def run_status_summary(self, project_id: str) -> str:
        runs = self._state.list_runs(project_id)
        if not runs:
            return "No runs have been materialized for this project yet."
        latest = runs[0]
        return (
            f"The latest run is {latest.title} on {latest.channel} and it is currently {latest.status}. "
            f"Summary: {latest.summary}. The next best action is to inspect failure evidence and decide whether "
            "healing should stay automated or fall back to human review."
        )

    def governance_status_summary(self, project_id: str) -> str:
        approvals = self._state.list_approvals(project_id)
        waiting = [approval for approval in approvals if approval.status == "waiting_approval"]
        if waiting:
            first = waiting[0]
            return (
                f"There are {len(waiting)} approval items waiting in governance. "
                f"The top item is {first.title}: {first.summary}. Resolve that first if you want the release gate to progress."
            )
        return "Governance is currently clear. There are no waiting approvals blocking the project at this moment."

    def conversation_summary_fallback(self, conversation: Any) -> str:
        if conversation.space_type == "welcome":
            return (
                "You can start from Build to create a new project, connect Git, US documents, and UX boards, or open "
                "Dashboard to inspect project progress and release risk across the portfolio."
            )
        if conversation.space_type == "dashboard":
            return self.dashboard_summary("")
        if conversation.space_type == "project":
            project_id = conversation.project_id or conversation.space_id
            return self.project_status_summary(project_id)
        if conversation.space_type == "version":
            projects = self._state.list_projects()
            project_id = conversation.project_id or (
                projects[0].id if projects else conversation.space_id
            )
            versions = self._state.list_versions(project_id)
            version_id = conversation.version_id or (
                versions[0].id if versions else ""
            )
            return self.version_status_summary(project_id, version_id)
        if conversation.space_type == "workspace":
            return self.workspace_status_summary(conversation.us_id or conversation.space_id)
        if conversation.space_type == "knowledge":
            project_id = conversation.project_id or conversation.space_id
            return self.knowledge_status_summary(project_id)
        if conversation.space_type == "runs":
            project_id = conversation.project_id or conversation.space_id
            return self.run_status_summary(project_id)
        if conversation.space_type == "governance":
            project_id = conversation.project_id or conversation.space_id
            return self.governance_status_summary(project_id)
        if conversation.space_type == "documentation":
            return (
                "Nasus uses an agent-first workflow: conversation drives tool invocation, tool invocation materializes "
                "project, version, run, and governance objects, and all important actions remain visible through the "
                "workspace shell."
            )
        if conversation.space_type == "build":
            return (
                "You can create a project, connect Git, import US documents, import UX boards, and initialize the "
                "Official System Image from here."
            )
        return (
            "I can help with project creation, version setup, dashboard progress checks, or quality asset generation. "
            "Tell me which step you want to move forward."
        )


__all__ = [
    "BuildResponse",
    "DashboardResponse",
    "DocumentationEntry",
    "ProjectWorkspaceResponse",
    "ReadModelSummaryService",
    "WelcomeResponse",
]
