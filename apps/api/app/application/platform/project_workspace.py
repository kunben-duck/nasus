from __future__ import annotations

from typing import Any

from ..quality_loop.quality_models import QualityLoopState
from .project_models import ProjectCreateRequest, VersionCreateRequest, VersionSummary
from .project_workspace_ports import (
    ProjectWorkspaceAuthorizationPort,
    ProjectWorkspaceConversationPort,
    ProjectWorkspaceReadPort,
    ProjectWorkspaceSnapshot,
    ProjectWorkspaceToolPort,
)
from .read_models import ProjectWorkspaceResponse
from .tool_models import ToolInvocationRequest


class ProjectWorkspaceApplicationService:
    """Project workspace commands and PostgreSQL-backed read-model queries."""

    def __init__(
        self,
        *,
        read_model: ProjectWorkspaceReadPort,
        authorization: ProjectWorkspaceAuthorizationPort,
        tool_invocations: ProjectWorkspaceToolPort,
        conversations: ProjectWorkspaceConversationPort,
    ) -> None:
        self._read_model = read_model
        self._authorization = authorization
        self._tool_invocations = tool_invocations
        self._conversations = conversations

    def list_projects(self) -> list[Any]:
        visible_ids = self._authorization.visible_project_ids()
        return [
            project
            for project in self._read_model.list_projects()
            if project.id in visible_ids
        ]

    async def create_project(self, payload: ProjectCreateRequest) -> Any:
        name = payload.name.strip()
        if not name:
            raise ValueError("name is required")
        invocation = await self._tool_invocations.create_tool_invocation(
            ToolInvocationRequest(
                tool_id="project.create",
                input={"name": name},
                initiator_surface="api",
                initiator_actor="user",
            )
        )
        if invocation.status != "completed" or invocation.result is None:
            raise RuntimeError(invocation.summary)
        project_id = _object_ref_id(invocation.result.object_refs, "project")
        project = self._read_model.get_project(project_id) if project_id else None
        if project is None:
            raise RuntimeError("project.create did not return a persisted project object")
        return project

    def get_project_workspace(self, project_id: str) -> ProjectWorkspaceResponse:
        snapshot = self._workspace(project_id)
        current_version_id = snapshot.versions[0].id if snapshot.versions else ""
        primary_us = self._select_project_workspace_us(snapshot)
        return ProjectWorkspaceResponse(
            project=snapshot.project,
            versions=snapshot.versions,
            current_version_id=current_version_id,
            us_items=snapshot.us_items,
            quality_loop_state=self._quality_loop_state(snapshot, primary_us),
            task_context=self._current_task_context(snapshot, primary_us),
            quality_profile=self._current_quality_profile(snapshot, primary_us),
            quality_asset_pack=self._current_quality_asset_pack(snapshot, primary_us),
            asset_lanes=snapshot.asset_lanes.get(primary_us, []),
            runs=snapshot.runs,
            execution_evidence=[
                item
                for item in snapshot.execution_evidence
                if not primary_us or item.us_id == primary_us
            ],
            failure_reports=[
                item
                for item in snapshot.failure_reports
                if not primary_us or item.us_id == primary_us
            ],
            release_decision=self._current_release_decision(
                snapshot,
                primary_us,
                current_version_id,
            ),
            approvals=snapshot.approvals,
        )

    def select_project_workspace_us(self, project_id: str) -> str:
        return self._select_project_workspace_us(self._workspace(project_id))

    @staticmethod
    def _select_project_workspace_us(snapshot: ProjectWorkspaceSnapshot) -> str:
        us_ids = [item.id for item in snapshot.us_items]
        if not us_ids:
            return ""
        us_id_set = set(us_ids)

        release_candidates = [
            decision
            for decision in snapshot.release_decisions
            if decision.us_id in us_id_set
        ]
        if release_candidates:
            return max(release_candidates, key=lambda decision: decision.created_at).us_id or us_ids[0]

        pack_candidates = [
            pack
            for pack in snapshot.quality_asset_packs
            if pack.us_id in us_id_set and pack.parts
        ]
        if pack_candidates:
            return max(pack_candidates, key=lambda pack: pack.updated_at).us_id

        evidence_candidates = [
            evidence
            for evidence in snapshot.execution_evidence
            if evidence.us_id in us_id_set
        ]
        if evidence_candidates:
            return max(evidence_candidates, key=lambda evidence: evidence.captured_at).us_id or us_ids[0]

        lane_candidates: list[tuple[str, str]] = []
        for us_id in us_ids:
            for lane in snapshot.asset_lanes.get(us_id, []):
                if lane.status not in {"", "not_started"}:
                    lane_candidates.append((lane.updated_at, us_id))
        if lane_candidates:
            return max(lane_candidates, key=lambda item: item[0])[1]
        return us_ids[0]

    def current_task_context(self, project_id: str, us_id: str | None = None) -> Any:
        return self._current_task_context(self._workspace(project_id), us_id)

    @staticmethod
    def _current_task_context(snapshot: ProjectWorkspaceSnapshot, us_id: str | None = None) -> Any:
        if us_id:
            return next((context for context in snapshot.task_contexts if context.us_id == us_id), None)
        return snapshot.task_contexts[0] if snapshot.task_contexts else None

    def current_quality_profile(self, project_id: str, us_id: str | None = None) -> Any:
        return self._current_quality_profile(self._workspace(project_id), us_id)

    @staticmethod
    def _current_quality_profile(snapshot: ProjectWorkspaceSnapshot, us_id: str | None = None) -> Any:
        if us_id:
            return next((profile for profile in snapshot.quality_profiles if profile.us_id == us_id), None)
        return snapshot.quality_profiles[0] if snapshot.quality_profiles else None

    def current_quality_asset_pack(self, project_id: str, us_id: str | None = None) -> Any:
        return self._current_quality_asset_pack(self._workspace(project_id), us_id)

    @staticmethod
    def _current_quality_asset_pack(snapshot: ProjectWorkspaceSnapshot, us_id: str | None = None) -> Any:
        if us_id:
            return next((pack for pack in snapshot.quality_asset_packs if pack.us_id == us_id), None)
        return snapshot.quality_asset_packs[0] if snapshot.quality_asset_packs else None

    def current_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> Any:
        return self._current_release_decision(self._workspace(project_id), us_id, version_id)

    @staticmethod
    def _current_release_decision(
        snapshot: ProjectWorkspaceSnapshot,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> Any:
        if version_id and us_id:
            exact = next(
                (
                    item
                    for item in snapshot.release_decisions
                    if item.version_id == version_id and item.us_id == us_id
                ),
                None,
            )
            if exact is not None:
                return exact
        return snapshot.release_decisions[-1] if snapshot.release_decisions else None

    def quality_loop_state(self, project_id: str, us_id: str) -> QualityLoopState:
        return self._quality_loop_state(self._workspace(project_id), us_id)

    @staticmethod
    def _quality_loop_state(snapshot: ProjectWorkspaceSnapshot, us_id: str) -> QualityLoopState:
        if not us_id:
            return QualityLoopState(
                status="no_us",
                stage_index=0,
                label="No US work item is available yet",
                next_recommended_tools=["system_image.context.materialize"],
            )

        lanes = snapshot.asset_lanes.get(us_id, [])
        lane_status_by_key: dict[str, str] = {}
        for lane in lanes:
            label = lane.label.lower()
            if "scenario" in label:
                lane_status_by_key["scenarios"] = lane.status
            elif "verification" in label:
                lane_status_by_key["verification_plan"] = lane.status
            elif "case" in label:
                lane_status_by_key["cases"] = lane.status
            elif "automation" in label:
                lane_status_by_key["automation"] = lane.status
            elif "release" in label:
                lane_status_by_key["release"] = lane.status
            elif "change document" in label:
                lane_status_by_key["change_document"] = lane.status

        release = snapshot.release_readiness.get(snapshot.versions[0].id) if snapshot.versions else None
        completed_statuses = {"approved", "completed"}
        stage_order = [
            ("scenarios", "quality.scenario.generate"),
            ("verification_plan", "quality.plan.generate"),
            ("cases", "quality.case.generate"),
            ("automation", "automation.generate"),
            ("change_document", "quality.change-doc.generate"),
            ("release", "release.assess"),
        ]
        completed_count = sum(1 for key, _tool in stage_order if lane_status_by_key.get(key) in completed_statuses)
        blockers = list(release.blocker_items if release else [])
        if any(status == "failed" for status in lane_status_by_key.values()):
            blockers.append("A quality asset lane failed and needs human review.")

        if blockers:
            return QualityLoopState(
                status="blocked",
                stage_index=completed_count,
                label="Quality loop blocked",
                release_score=release.score if release else 0,
                blockers=blockers,
                next_recommended_tools=["query.governance.status", "release.assess"],
            )
        if completed_count == len(stage_order):
            return QualityLoopState(
                status="ready_for_release",
                stage_index=len(stage_order),
                label="Quality loop ready for release review",
                release_score=release.score if release else 0,
                next_recommended_tools=["release.assess", "query.governance.status"],
            )

        next_tool = next(
            (tool for key, tool in stage_order if lane_status_by_key.get(key) not in completed_statuses),
            "quality.scenario.generate",
        )
        if completed_count == 0 and all(status in {"not_started", ""} for status in lane_status_by_key.values()):
            label = "Quality loop not started"
            status = "not_started"
        else:
            label = f"Quality loop in progress: {completed_count}/{len(stage_order)} stages complete"
            status = "in_progress"
        return QualityLoopState(
            status=status,
            stage_index=completed_count,
            label=label,
            release_score=release.score if release else 0,
            next_recommended_tools=[next_tool],
        )

    def list_versions(self, project_id: str) -> list[VersionSummary]:
        return self._workspace(project_id).versions

    async def create_version(self, project_id: str, payload: VersionCreateRequest) -> VersionSummary:
        name = payload.name.strip()
        if not name:
            raise ValueError("name is required")
        if self._read_model.get_project(project_id) is None:
            raise KeyError(project_id)
        self._authorization.require_project_access(project_id)
        invocation = await self._tool_invocations.create_tool_invocation(
            ToolInvocationRequest(
                tool_id="version.create",
                input={"project_id": project_id, "name": name},
                initiator_surface="api",
                initiator_actor="user",
            )
        )
        if invocation.status != "completed" or invocation.result is None:
            raise RuntimeError(invocation.summary)
        version_id = _object_ref_id(invocation.result.object_refs, "version")
        if version_id is None:
            raise RuntimeError("version.create did not return a version object")
        version = next(
            (item for item in self._workspace(project_id).versions if item.id == version_id),
            None,
        )
        if version is None:
            raise RuntimeError(f"version {version_id} was not persisted after tool execution")
        return version

    def get_workspace_data(self, project_id: str, us_id: str) -> dict[str, Any]:
        snapshot = self._workspace(project_id)
        us = next((item for item in snapshot.us_items if item.id == us_id), None)
        if us is None:
            raise KeyError(us_id)
        version = snapshot.versions[0] if snapshot.versions else None
        return {
            "project": snapshot.project,
            "version": version,
            "us_item": us,
            "asset_lanes": snapshot.asset_lanes.get(us_id, []),
            "quality_loop_state": self._quality_loop_state(snapshot, us_id),
            "task_context": self._current_task_context(snapshot, us_id),
            "quality_profile": self._current_quality_profile(snapshot, us_id),
            "conversation": self._conversations.get_or_create_conversation(
                "workspace",
                us_id,
                f"{us_id} Workspace",
                project_id=project_id,
                version_id=version.id if version else None,
                us_id=us_id,
            ),
            "runs": snapshot.runs,
            "approvals": snapshot.approvals,
        }

    def list_runs(self, project_id: str) -> list[Any]:
        return self._workspace(project_id).runs

    def get_run_detail(self, project_id: str, run_id: str) -> Any:
        self._authorization.require_project_access(project_id)
        detail = self._read_model.get_run_detail(project_id, run_id)
        if detail is None:
            raise KeyError(run_id)
        return detail

    def list_approvals(self, project_id: str) -> list[Any]:
        return self._workspace(project_id).approvals

    def get_approval_detail(self, project_id: str, approval_id: str) -> Any:
        self._authorization.require_project_access(project_id)
        detail = self._read_model.get_approval_detail(project_id, approval_id)
        if detail is None:
            raise KeyError(approval_id)
        return detail

    def get_release_readiness(self, project_id: str) -> Any:
        snapshot = self._workspace(project_id)
        if not snapshot.versions:
            return None
        return snapshot.release_readiness.get(snapshot.versions[0].id)

    def _workspace(self, project_id: str) -> ProjectWorkspaceSnapshot:
        self._authorization.require_project_access(project_id)
        snapshot = self._read_model.load_workspace(project_id)
        if snapshot is None:
            raise KeyError(project_id)
        return snapshot


def _object_ref_id(refs: list[str], prefix: str) -> str | None:
    marker = f"{prefix}:"
    for ref in refs:
        if ref.startswith(marker):
            return ref.split(":", 1)[1]
    return None


__all__ = ["ProjectWorkspaceApplicationService"]
