from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Protocol

from ...application.agent.agent_models import ConversationSession
from ...application.platform.governance_ports import GovernanceWorkspacePort
from ...application.platform.project_models import ProjectCard, VersionSummary
from ...application.platform.tool_models import ToolInvocation
from ...application.quality_loop.governance_models import MergedResolution
from ...application.quality_loop.quality_models import (
    ApprovalDetail,
    ApprovalSummary,
    ExecutionEvidence,
    ReleaseDecision,
    ReleaseReadiness,
    USItem,
)
from ...application.system_image.system_image_models import BaselineRecord


class GovernanceProjectPersistencePort(Protocol):
    def upsert_project(self, project: ProjectCard) -> None: ...
    def replace_versions(self, project_id: str, versions: list[VersionSummary]) -> None: ...


class GovernanceQualityPersistencePort(Protocol):
    def replace_approvals(self, project_id: str, approvals: list[ApprovalDetail]) -> None: ...
    def upsert_release_readiness(self, project_id: str, readiness: ReleaseReadiness) -> None: ...
    def find_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> ReleaseDecision | None: ...
    def upsert_release_decision(self, decision: ReleaseDecision) -> None: ...
    def upsert_merged_resolution(self, resolution: MergedResolution) -> None: ...


class GovernanceConversationRepositoryPort(Protocol):
    def get_conversation(self, conversation_id: str) -> ConversationSession | None: ...


class GovernanceProjectRepositoryPort(Protocol):
    def get_project(self, project_id: str) -> ProjectCard | None: ...
    def upsert_project(self, project: ProjectCard) -> None: ...
    def list_versions(self, project_id: str) -> list[VersionSummary]: ...


class GovernanceQualityRepositoryPort(Protocol):
    def list_us_items(self, project_id: str) -> list[USItem]: ...
    def project_id_for_us(self, us_id: str) -> str | None: ...
    def list_approvals(self, project_id: str) -> list[ApprovalSummary]: ...
    def get_approval_detail(self, project_id: str, approval_id: str) -> ApprovalDetail | None: ...
    def get_release_readiness(self, version_id: str) -> ReleaseReadiness | None: ...
    def upsert_release_readiness(self, project_id: str, readiness: ReleaseReadiness) -> None: ...
    def find_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> ReleaseDecision | None: ...
    def upsert_release_decision(self, decision: ReleaseDecision) -> None: ...
    def list_execution_evidence(self, project_id: str) -> list[ExecutionEvidence]: ...
    def get_merged_resolution(self, resolution_id: str) -> MergedResolution | None: ...
    def list_merged_resolutions(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
    ) -> list[MergedResolution]: ...
    def upsert_merged_resolution(self, resolution: MergedResolution) -> None: ...


class GovernanceCommandRepositoryPort(Protocol):
    def save_approval_and_sync_pending_counts(
        self,
        project_id: str,
        approval: ApprovalDetail,
    ) -> int: ...


class GovernanceSystemImageWorkspacePort(Protocol):
    def list_baselines(self, project_id: str) -> list[BaselineRecord]: ...
    def replace_baselines(self, project_id: str, baselines: list[BaselineRecord]) -> None: ...
    def persist_system_image(self, project_id: str) -> None: ...


@dataclass(frozen=True)
class GovernanceProjectionState:
    projects: MutableMapping[str, ProjectCard]
    versions: MutableMapping[str, list[VersionSummary]]
    us_items: MutableMapping[str, list[USItem]]
    approvals: MutableMapping[str, list[ApprovalSummary]]
    approval_details: MutableMapping[str, ApprovalDetail]
    release_readiness: MutableMapping[str, ReleaseReadiness]
    release_decisions: MutableMapping[str, ReleaseDecision]
    execution_evidence: MutableMapping[str, list[ExecutionEvidence]]
    baselines: MutableMapping[str, list[BaselineRecord]]
    merged_resolutions: MutableMapping[str, MergedResolution]
    conversations: MutableMapping[str, ConversationSession]


@dataclass(frozen=True)
class GovernanceWorkspaceAdapters:
    project_repository: GovernanceProjectPersistencePort
    quality_loop_repository: GovernanceQualityPersistencePort
    require_project_access: Callable[[str], None]
    system_image_workspace: GovernanceSystemImageWorkspacePort


class SQLAlchemyGovernanceWorkspace(GovernanceWorkspacePort):
    """PostgreSQL-backed governance workspace used by production runtime."""

    def __init__(
        self,
        *,
        conversations: GovernanceConversationRepositoryPort,
        projects: GovernanceProjectRepositoryPort,
        quality_loop: GovernanceQualityRepositoryPort,
        commands: GovernanceCommandRepositoryPort,
        require_project_access: Callable[[str], None],
        system_image_workspace: GovernanceSystemImageWorkspacePort,
    ) -> None:
        self._conversations = conversations
        self._projects = projects
        self._quality_loop = quality_loop
        self._commands = commands
        self._require_project_access = require_project_access
        self._system_image = system_image_workspace

    def resolve_project_id(self, invocation: ToolInvocation) -> str | None:
        project_id = str(invocation.input_payload.get("project_id") or "")
        if project_id or not invocation.conversation_id:
            return project_id or None
        conversation = self._conversations.get_conversation(invocation.conversation_id)
        if conversation is None:
            return None
        return conversation.project_id or (
            conversation.space_id if conversation.space_type == "project" else None
        )

    def require_project_access(self, project_id: str) -> None:
        self._require_project_access(project_id)

    def has_project(self, project_id: str) -> bool:
        return bool(project_id) and self._projects.get_project(project_id) is not None

    def get_project(self, project_id: str) -> ProjectCard:
        project = self._projects.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        return project

    def save_project(self, project: ProjectCard) -> None:
        self._projects.upsert_project(project)

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        return self._projects.list_versions(project_id)

    def replace_versions(self, project_id: str, versions: list[VersionSummary]) -> None:
        raise RuntimeError("Production governance does not replace version collections")

    def list_us_items(self, project_id: str) -> list[USItem]:
        return self._quality_loop.list_us_items(project_id)

    def project_id_for_task(self, task_id: str) -> str | None:
        return self._quality_loop.project_id_for_us(task_id)

    def get_approval(self, project_id: str, approval_id: str) -> ApprovalDetail | None:
        return self._quality_loop.get_approval_detail(project_id, approval_id)

    def list_approvals(self, project_id: str) -> list[ApprovalDetail]:
        approvals: list[ApprovalDetail] = []
        for summary in self._quality_loop.list_approvals(project_id):
            detail = self._quality_loop.get_approval_detail(project_id, summary.id)
            if detail is not None:
                approvals.append(detail)
        return approvals

    def replace_approvals(self, project_id: str, approvals: list[ApprovalDetail]) -> None:
        raise RuntimeError("Production governance does not replace approval collections")

    def save_approval(self, project_id: str, approval: ApprovalDetail) -> int:
        return self._commands.save_approval_and_sync_pending_counts(project_id, approval)

    def get_release_readiness(self, version_id: str) -> ReleaseReadiness | None:
        return self._quality_loop.get_release_readiness(version_id)

    def save_release_readiness(self, project_id: str, readiness: ReleaseReadiness) -> None:
        self._quality_loop.upsert_release_readiness(project_id, readiness)

    def find_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> ReleaseDecision | None:
        return self._quality_loop.find_release_decision(project_id, us_id, version_id)

    def save_release_decision(self, decision: ReleaseDecision) -> None:
        self._quality_loop.upsert_release_decision(decision)

    def list_execution_evidence(self, project_id: str) -> list[ExecutionEvidence]:
        return self._quality_loop.list_execution_evidence(project_id)

    def list_baselines(self, project_id: str) -> list[BaselineRecord]:
        return self._system_image.list_baselines(project_id)

    def replace_baselines(self, project_id: str, baselines: list[BaselineRecord]) -> None:
        self._system_image.replace_baselines(project_id, baselines)

    def persist_system_image(self, project_id: str) -> None:
        self._system_image.persist_system_image(project_id)

    def get_merged_resolution(self, resolution_id: str) -> MergedResolution | None:
        return self._quality_loop.get_merged_resolution(resolution_id)

    def list_merged_resolutions(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
    ) -> list[MergedResolution]:
        return self._quality_loop.list_merged_resolutions(project_id, task_id=task_id)

    def save_merged_resolution(self, resolution: MergedResolution) -> None:
        self._quality_loop.upsert_merged_resolution(resolution)


class CompatibilityGovernanceWorkspace(GovernanceWorkspacePort):
    """Explicit adapter over compatibility projections during DDD migration."""

    def __init__(
        self,
        state: GovernanceProjectionState,
        adapters: GovernanceWorkspaceAdapters,
    ) -> None:
        self._state = state
        self._adapters = adapters

    def resolve_project_id(self, invocation: ToolInvocation) -> str | None:
        project_id = str(invocation.input_payload.get("project_id") or "")
        conversation = self._state.conversations.get(invocation.conversation_id or "")
        if not project_id and conversation is not None:
            project_id = conversation.project_id or (
                conversation.space_id if conversation.space_type == "project" else ""
            )
        return project_id or None

    def require_project_access(self, project_id: str) -> None:
        self._adapters.require_project_access(project_id)

    def has_project(self, project_id: str) -> bool:
        return project_id in self._state.projects

    def get_project(self, project_id: str) -> ProjectCard:
        return self._state.projects[project_id].model_copy(deep=True)

    def save_project(self, project: ProjectCard) -> None:
        self._state.projects[project.id] = project.model_copy(deep=True)
        self._adapters.project_repository.upsert_project(project)

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        return [item.model_copy(deep=True) for item in self._state.versions.get(project_id, [])]

    def replace_versions(self, project_id: str, versions: list[VersionSummary]) -> None:
        copies = [item.model_copy(deep=True) for item in versions]
        self._state.versions[project_id] = copies
        self._adapters.project_repository.replace_versions(project_id, copies)

    def list_us_items(self, project_id: str) -> list[USItem]:
        return [item.model_copy(deep=True) for item in self._state.us_items.get(project_id, [])]

    def project_id_for_task(self, task_id: str) -> str | None:
        return next(
            (
                project_id
                for project_id, items in self._state.us_items.items()
                if any(item.id == task_id for item in items)
            ),
            None,
        )

    def get_approval(self, project_id: str, approval_id: str) -> ApprovalDetail | None:
        if approval_id not in {item.id for item in self._state.approvals.get(project_id, [])}:
            return None
        approval = self._state.approval_details.get(approval_id)
        return approval.model_copy(deep=True) if approval is not None else None

    def list_approvals(self, project_id: str) -> list[ApprovalDetail]:
        return [
            self._state.approval_details[item.id].model_copy(deep=True)
            for item in self._state.approvals.get(project_id, [])
            if item.id in self._state.approval_details
        ]

    def replace_approvals(self, project_id: str, approvals: list[ApprovalDetail]) -> None:
        copies = [item.model_copy(deep=True) for item in approvals]
        previous_ids = {item.id for item in self._state.approvals.get(project_id, [])}
        for approval_id in previous_ids - {item.id for item in copies}:
            self._state.approval_details.pop(approval_id, None)
        for item in copies:
            self._state.approval_details[item.id] = item.model_copy(deep=True)
        self._state.approvals[project_id] = [
            ApprovalSummary(**item.model_dump(include={"id", "title", "status", "summary"}))
            for item in copies
        ]
        self._adapters.quality_loop_repository.replace_approvals(project_id, copies)

    def save_approval(self, project_id: str, approval: ApprovalDetail) -> int:
        approvals = [item for item in self.list_approvals(project_id) if item.id != approval.id]
        approvals.append(approval)
        self.replace_approvals(project_id, approvals)
        pending = sum(1 for item in approvals if item.status == "waiting_approval")
        project = self.get_project(project_id)
        project.pending_approvals = pending
        self.save_project(project)
        versions = self.list_versions(project_id)
        if versions:
            versions[0].pending_approvals = pending
            self.replace_versions(project_id, versions)
        return pending

    def get_release_readiness(self, version_id: str) -> ReleaseReadiness | None:
        readiness = self._state.release_readiness.get(version_id)
        return readiness.model_copy(deep=True) if readiness is not None else None

    def save_release_readiness(self, project_id: str, readiness: ReleaseReadiness) -> None:
        self._state.release_readiness[readiness.version_id] = readiness.model_copy(deep=True)
        self._adapters.quality_loop_repository.upsert_release_readiness(project_id, readiness)

    def find_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> ReleaseDecision | None:
        candidates = [
            item
            for item in self._state.release_decisions.values()
            if item.project_id == project_id
            and (us_id is None or item.us_id == us_id)
            and (version_id is None or item.version_id == version_id)
        ]
        if candidates:
            return max(candidates, key=lambda item: item.created_at).model_copy(deep=True)
        persisted = self._adapters.quality_loop_repository.find_release_decision(
            project_id,
            us_id,
            version_id,
        )
        return persisted.model_copy(deep=True) if persisted is not None else None

    def save_release_decision(self, decision: ReleaseDecision) -> None:
        self._state.release_decisions[decision.id] = decision.model_copy(deep=True)
        self._adapters.quality_loop_repository.upsert_release_decision(decision)

    def list_execution_evidence(self, project_id: str) -> list[ExecutionEvidence]:
        return [item.model_copy(deep=True) for item in self._state.execution_evidence.get(project_id, [])]

    def list_baselines(self, project_id: str) -> list[BaselineRecord]:
        return [
            item.model_copy(deep=True)
            for item in self._adapters.system_image_workspace.list_baselines(project_id)
        ]

    def replace_baselines(self, project_id: str, baselines: list[BaselineRecord]) -> None:
        copies = [item.model_copy(deep=True) for item in baselines]
        self._state.baselines[project_id] = copies
        self._adapters.system_image_workspace.replace_baselines(project_id, copies)

    def persist_system_image(self, project_id: str) -> None:
        self._adapters.system_image_workspace.persist_system_image(project_id)

    def get_merged_resolution(self, resolution_id: str) -> MergedResolution | None:
        resolution = self._state.merged_resolutions.get(resolution_id)
        return resolution.model_copy(deep=True) if resolution is not None else None

    def list_merged_resolutions(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
    ) -> list[MergedResolution]:
        return [
            item.model_copy(deep=True)
            for item in self._state.merged_resolutions.values()
            if item.project_id == project_id and (task_id is None or item.task_id == task_id)
        ]

    def save_merged_resolution(self, resolution: MergedResolution) -> None:
        self._state.merged_resolutions[resolution.id] = resolution.model_copy(deep=True)
        self._adapters.quality_loop_repository.upsert_merged_resolution(resolution)


__all__ = [
    "CompatibilityGovernanceWorkspace",
    "GovernanceProjectionState",
    "GovernanceWorkspaceAdapters",
    "SQLAlchemyGovernanceWorkspace",
]
