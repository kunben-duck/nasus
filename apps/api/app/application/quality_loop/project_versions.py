from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .ports import ProjectVersionWorkspacePort, QualityLoopContextReadPort
from .quality_models import ReleaseReadiness, USItem
from ..platform.project_models import ProjectCard, VersionSummary
from ..platform.tool_models import ToolInvocation
from ..system_image.ports import SystemImageOperationsPort
from ...domain.quality_loop.us_task_start import (
    decide_us_task_item_start,
    decide_us_task_start,
    find_start_task_target,
)
from ...domain.quality_loop.version_participants import (
    decide_version_participants,
    owner_assignments_from_payload,
)
from ...domain.quality_loop.version_risk import decide_version_risk
from ...domain.quality_loop.version_us_import import (
    USImportItemDecision,
    decide_version_us_import,
    raw_us_items_from_payload,
)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


@dataclass(frozen=True)
class ProjectVersionUseCaseResult:
    summary: str
    object_refs: list[str]
    next_tools: list[str]
    evidence_refs: list[str] = field(default_factory=list)
    requires_followup: bool = False
    assistant_message: str | None = None


class ProjectVersionApplicationError(ValueError):
    """Raised when a project/version command cannot be executed."""

    def __init__(self, summary: str) -> None:
        super().__init__(summary)
        self.summary = summary


class ProjectVersionApplicationService:
    """Project, version, and US work item use cases.

    This service is the write-side application boundary for project setup and
    version quality workflow commands. Tool handlers can emit runtime progress,
    but business mutations should enter here instead of reaching into
    the compatibility facade directly.
    """

    def __init__(
        self,
        workspace: ProjectVersionWorkspacePort,
        system_image: SystemImageOperationsPort,
        context_queries: QualityLoopContextReadPort,
    ) -> None:
        self._workspace = workspace
        self._system_image = system_image
        self.context_queries = context_queries

    def create_project_record(self, name: str) -> ProjectCard:
        project_id = f"proj_{_slugify(name)}_{uuid4().hex[:10]}"
        project = ProjectCard(
            id=project_id,
            name=name,
            code=name[:3].upper(),
            summary="Newly created project awaiting source imports and system image initialization.",
            status="draft",
            risk="low",
            progress=12,
            active_version="Not started",
            blocked_items=0,
            pending_approvals=0,
            system_image_status="draft",
        )
        self._workspace.initialize_project(project)
        return project

    def create_version_record(self, project_id: str, name: str) -> VersionSummary:
        versions = self._workspace.list_versions(project_id)
        version = VersionSummary(
            id=f"ver_{_slugify(name)}_{project_id[-6:]}_{len(versions) + 1}",
            name=name,
            status="draft",
            branch_name=f"release/{_slugify(name)}",
            us_total=0,
            us_closed=0,
            pending_runs=0,
            pending_approvals=0,
        )
        project = self._workspace.get_project(project_id)
        project.active_version = name
        self._workspace.save_project(project)
        self._workspace.prepend_version(project_id, version)
        readiness = ReleaseReadiness(
            version_id=version.id,
            status="Draft",
            score=0,
            blockers=0,
            approvals_open=0,
            pending_merge=0,
            execution_health="No runs yet",
            summary="This version branch has been created and is ready for US import, assignment, and quality asset generation.",
            blocker_items=[],
        )
        self._workspace.save_release_readiness(project_id, readiness)
        return version

    def active_or_create_quality_version(self, project_id: str) -> VersionSummary:
        """Resolve the active Version and adopt pre-Version US facts once.

        System-image materialization can discover US facts before the delivery
        workflow has an explicit Version. The first quality-loop command moves
        those facts into the initial Version; later Versions remain isolated.
        """

        versions = self._workspace.list_versions(project_id)
        if versions:
            return versions[0]

        unversioned_items = self._workspace.list_us_items(project_id)
        version = self.create_version_record(project_id, "Initial Quality Loop")
        if unversioned_items:
            self._workspace.save_us_items(
                project_id,
                version.id,
                unversioned_items,
            )
        return version

    def create_project(self, invocation: ToolInvocation) -> ProjectVersionUseCaseResult:
        project_name = str(invocation.input_payload.get("name") or "New Quality Project")
        project = self.create_project_record(project_name)
        return ProjectVersionUseCaseResult(
            summary=f"Created draft project {project.name}",
            assistant_message=(
                f"I created the draft project **{project.name}**. Next we should connect a Git repository, "
                "import US documents, and confirm whether UX boards or historical quality assets are available "
                "before initializing the Official System Image."
            ),
            object_refs=[f"project:{project.id}"],
            next_tools=[
                "system_image.sources.register",
                "system_image.baseline.initialize",
                "version.create",
            ],
        )

    def create_version(self, invocation: ToolInvocation) -> ProjectVersionUseCaseResult:
        project_id = self.project_id_for(invocation)
        if not self._has_project(project_id):
            raise ProjectVersionApplicationError("project_id is required to create a version")

        version_name = str(invocation.input_payload.get("name") or "New Version")
        version = self.create_version_record(project_id, version_name)
        return ProjectVersionUseCaseResult(
            summary=f"Created version {version.name}",
            assistant_message=(
                f"The version branch **{version.name}** is active. "
                "US board, risk pulse, and asset pack generation are now available in Version Space."
            ),
            object_refs=[f"version:{version.id}"],
            next_tools=["quality.scenario.generate"],
        )

    def connect_project_assets(self, invocation: ToolInvocation) -> ProjectVersionUseCaseResult:
        project_id = self._require_project(invocation, "A valid project_id is required before connecting project assets.")
        source_specs = self._system_image.normalize_source_specs(invocation.input_payload.get("source_specs"))
        system_image = self._system_image.register_sources(
            project_id,
            source_specs=source_specs,
            registered_by_actor=invocation.initiator_actor,
            registered_from_invocation_id=invocation.id,
        )
        missing = self._system_image.missing_source_types(project_id)
        if missing:
            summary = (
                "Connected available project assets, but system image source bindings are still incomplete: "
                + ", ".join(missing)
            )
            next_tools = ["project.assets.connect", "system_image.sources.register"]
            requires_followup = True
        else:
            summary = f"Connected {len(system_image.sources)} project asset source groups."
            next_tools = ["system_image.sources.ingest"]
            requires_followup = False

        project = self._workspace.get_project(project_id)
        project.progress = max(project.progress, 18 if requires_followup else 24)
        project.system_image_status = "draft"
        self._workspace.save_project(project)
        return ProjectVersionUseCaseResult(
            summary=summary,
            object_refs=[f"project:{project_id}", *[f"raw_asset:{source.id}" for source in system_image.sources]],
            evidence_refs=[ref for source in system_image.sources for ref in source.evidence_refs],
            next_tools=next_tools,
            requires_followup=requires_followup,
        )

    def import_version_inputs(self, invocation: ToolInvocation) -> ProjectVersionUseCaseResult:
        project_id = self._require_project(invocation, "A valid project_id is required before importing version inputs.")
        version = self._version(project_id, invocation)
        raw_items = raw_us_items_from_payload(invocation.input_payload)
        imported = self._upsert_us_items(project_id, version.id, raw_items)
        version.us_total = len(
            self._workspace.list_us_items(project_id, version.id)
        )
        version.status = "active"
        self._save_version(project_id, version)
        project = self._workspace.get_project(project_id)
        project.progress = max(project.progress, 30)
        project.active_version = version.name
        self._workspace.save_project(project)
        return ProjectVersionUseCaseResult(
            summary=f"Imported {len(imported)} US work item(s) into version {version.name}.",
            object_refs=[f"version:{version.id}", *[f"us:{item.id}" for item in imported]],
            next_tools=["version.participants.assign", "version.risk.initialize", "us.task.start"],
        )

    def bind_version_branch(self, invocation: ToolInvocation) -> ProjectVersionUseCaseResult:
        project_id = self._require_project(invocation, "A valid project_id is required before binding a version branch.")
        version = self._version(project_id, invocation)
        branch_name = str(
            invocation.input_payload.get("branch_name")
            or invocation.input_payload.get("git_branch")
            or version.branch_name
        ).strip()
        if not branch_name:
            raise ProjectVersionApplicationError("branch_name is required before binding a version branch.")
        version.branch_name = branch_name
        version.status = "active"
        self._save_version(project_id, version)
        return ProjectVersionUseCaseResult(
            summary=f"Bound version {version.name} to branch {branch_name}.",
            object_refs=[f"version:{version.id}", f"project:{project_id}"],
            next_tools=["version.inputs.import", "version.risk.initialize"],
        )

    def assign_version_participants(self, invocation: ToolInvocation) -> ProjectVersionUseCaseResult:
        project_id = self._require_project(invocation, "A valid project_id is required before assigning participants.")
        version = self._version(project_id, invocation)
        items = self._workspace.list_us_items(project_id, version.id)
        owner_by_us = owner_assignments_from_payload(invocation.input_payload.get("assignments"))
        default_owner = str(invocation.input_payload.get("owner") or invocation.input_payload.get("default_owner") or "").strip()
        decision = decide_version_participants(items, owner_by_us=owner_by_us, default_owner=default_owner)
        decision_by_id = {item.us_id: item for item in decision.item_decisions}
        updated = [
            item.model_copy(update={"owner": decision_by_id[item.id].owner})
            for item in items
        ]
        self._workspace.save_us_items(project_id, version.id, updated)
        return ProjectVersionUseCaseResult(
            summary=f"Assigned owners for {decision.assigned_count} US work item(s) in version {version.name}.",
            object_refs=[f"version:{version.id}", *[f"us:{item.id}" for item in updated]],
            next_tools=["version.risk.initialize", "us.task.start"],
        )

    def initialize_version_risk(self, invocation: ToolInvocation) -> ProjectVersionUseCaseResult:
        project_id = self._require_project(invocation, "A valid project_id is required before initializing version risk.")
        version = self._version(project_id, invocation)
        items = self._workspace.list_us_items(project_id, version.id)
        decision = decide_version_risk(items)
        decision_by_id = {item.us_id: item for item in decision.item_decisions}
        updated = [
            item.model_copy(
                update={
                    "risk": decision_by_id[item.id].risk,
                    "next_action": decision_by_id[item.id].next_action,
                }
            )
            for item in items
        ]
        version.status = "active"
        version.us_total = len(updated)
        self._workspace.save_us_items(project_id, version.id, updated)
        self._save_version(project_id, version)
        project = self._workspace.get_project(project_id)
        project.risk = decision.project_risk
        project.progress = max(project.progress, decision.project_progress_floor)
        self._workspace.save_project(project)
        return ProjectVersionUseCaseResult(
            summary=decision.summary,
            object_refs=[f"project:{project_id}", f"version:{version.id}", *[f"us:{item.id}" for item in updated]],
            next_tools=["version.progress.get", "us.task.start"],
        )

    async def start_us_task(self, invocation: ToolInvocation) -> ProjectVersionUseCaseResult:
        project_id = self._require_project(invocation, "A valid project_id is required before starting a US task.")
        requested_us_id = str(invocation.input_payload.get("us_id") or "")
        version = self._version(project_id, invocation)
        items = self._workspace.list_us_items(project_id, version.id)
        target = find_start_task_target(items, requested_us_id)
        if target is None:
            raise ProjectVersionApplicationError("A valid us_id is required before starting a US task.")
        item_decision = decide_us_task_item_start(target)
        updated_item = target.model_copy(
            update={
                "status": item_decision.status,
                "progress": item_decision.progress,
                "next_action": item_decision.next_action,
            }
        )
        self._workspace.save_us_item(
            project_id,
            version.id,
            updated_item,
        )
        if self._workspace.has_indexed_system_image_evidence(project_id):
            try:
                await self._system_image.materialize_context(project_id)
            except RuntimeError:
                pass
        context = self.context_queries.current_task_context(project_id, item_decision.us_id)
        profile = self.context_queries.current_quality_profile(project_id, item_decision.us_id)
        decision = decide_us_task_start(target, has_task_context=context is not None)
        return ProjectVersionUseCaseResult(
            summary=decision.summary,
            assistant_message=decision.assistant_message,
            object_refs=[
                f"project:{project_id}",
                f"version:{version.id}",
                f"us:{decision.us_id}",
                *([f"task_context:{context.id}"] if context else []),
                *([f"quality_profile:{profile.id}"] if profile else []),
            ],
            next_tools=decision.next_tools,
            requires_followup=decision.requires_followup,
        )

    def query_keys_for(self, invocation: ToolInvocation) -> list[list[str]]:
        project_id = self.project_id_for(invocation)
        keys: list[list[str]] = []
        if invocation.conversation_id:
            keys.append(["conversation", invocation.conversation_id])
        if project_id:
            keys.extend([["project", project_id], ["dashboard"], ["welcome"]])
            version_id = str(invocation.input_payload.get("version_id") or "")
            versions = self._workspace.list_versions(project_id)
            version = next((item for item in versions if item.id == version_id), None) if version_id else (versions[0] if versions else None)
            if version is not None:
                keys.append(["version", project_id, version.id])
        return keys or [["projects"]]

    def project_id_for(self, invocation: ToolInvocation) -> str:
        project_id = str(invocation.input_payload.get("project_id") or "")
        if not project_id:
            project_id = self._workspace.conversation_project_id(
                invocation.conversation_id
            ) or ""
        return project_id

    def _require_project(self, invocation: ToolInvocation, message: str) -> str:
        project_id = self.project_id_for(invocation)
        if not self._has_project(project_id):
            raise ProjectVersionApplicationError(message)
        return project_id

    def _has_project(self, project_id: str) -> bool:
        return bool(project_id) and self._workspace.has_project(project_id)

    def _upsert_us_items(self, project_id: str, version_id: str, raw_items: list[Any]) -> list[USItem]:
        decision = decide_version_us_import(
            existing_items=self._workspace.list_us_items(project_id, version_id),
            raw_items=raw_items,
            id_factory=lambda: f"us_{uuid4().hex[:8]}",
        )
        imported = [self._us_item_from_import_decision(item) for item in decision.imported_items]
        ordered = [self._us_item_from_import_decision(item) for item in decision.ordered_items]
        self._workspace.save_us_items(project_id, version_id, ordered)
        return imported

    def _version(
        self,
        project_id: str,
        invocation: ToolInvocation,
    ) -> VersionSummary:
        version_id = str(invocation.input_payload.get("version_id") or "")
        versions = self._workspace.list_versions(project_id)
        if version_id:
            matched = next((item for item in versions if item.id == version_id), None)
            if matched is not None:
                return matched
        if versions:
            return versions[0]
        return self.active_or_create_quality_version(project_id)

    def _save_version(
        self,
        project_id: str,
        version: VersionSummary,
    ) -> None:
        self._workspace.save_version(project_id, version)

    @staticmethod
    def _us_item_from_import_decision(item: USImportItemDecision) -> USItem:
        return USItem(
            id=item.id,
            title=item.title,
            owner=item.owner,
            status=item.status,
            risk=item.risk,
            progress=item.progress,
            next_action=item.next_action,
        )


__all__ = [
    "ProjectVersionApplicationError",
    "ProjectVersionApplicationService",
    "ProjectVersionUseCaseResult",
]
