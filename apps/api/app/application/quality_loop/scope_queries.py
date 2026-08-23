from __future__ import annotations

from .quality_models import RunDetail
from .ports import QualityLoopScopeWorkspacePort
from ..platform.tool_models import ToolInvocation


class QualityLoopScopeQueryApplicationService:
    """Resolve quality-loop project, US, run, and cache-scope keys."""

    def __init__(self, workspace: QualityLoopScopeWorkspacePort) -> None:
        self._workspace = workspace

    def resolve_scope(self, invocation: ToolInvocation) -> tuple[str, str] | None:
        project_id = str(invocation.input_payload.get("project_id") or "")
        us_id = str(invocation.input_payload.get("us_id") or "")

        project_id, us_id = self._merge_conversation_scope(
            invocation,
            project_id,
            us_id,
        )
        if us_id:
            owner_project_id = self._workspace.project_id_for_us(us_id)
            if owner_project_id is None:
                return None
            if project_id and project_id != owner_project_id:
                return None
            project_id = owner_project_id
        if not us_id and project_id:
            us_id = self._workspace.first_us_id(project_id) or ""
        if not project_id or not us_id:
            return None
        return project_id, us_id

    def resolve_failure_scope(
        self,
        invocation: ToolInvocation,
    ) -> tuple[str, str, RunDetail] | None:
        project_id = str(invocation.input_payload.get("project_id") or "")
        us_id = str(invocation.input_payload.get("us_id") or "")
        run_id = str(invocation.input_payload.get("run_id") or "")

        project_id, us_id = self._merge_conversation_scope(
            invocation,
            project_id,
            us_id,
        )
        if run_id:
            owner_project_id = self._workspace.project_id_for_run(run_id)
            if owner_project_id is None:
                return None
            if project_id and project_id != owner_project_id:
                return None
            project_id = owner_project_id
        if not project_id:
            return None

        runs = self._workspace.list_run_details(project_id)
        if run_id:
            run = next((item for item in runs if item.id == run_id), None)
            if run is None:
                return None
        else:
            run = next((item for item in runs if item.status == "failed"), None)
        if run is None:
            return None

        if not us_id:
            us_id = (
                run.us_id
                or self._workspace.us_id_for_run_evidence(project_id, run.id)
                or self._workspace.first_us_id(project_id)
                or ""
            )
        if not project_id or not us_id:
            return None

        owner_project_id = self._workspace.project_id_for_us(us_id)
        if owner_project_id is None or owner_project_id != project_id:
            return None
        return project_id, us_id, run

    def query_keys_for(
        self,
        invocation: ToolInvocation,
        project_id: str,
        us_id: str,
    ) -> list[list[str]]:
        keys = [
            ["project", project_id],
            ["workspace", project_id, us_id],
            ["runs", project_id],
            ["governance", project_id],
        ]
        if invocation.conversation_id:
            keys.insert(0, ["conversation", invocation.conversation_id])
        return keys

    def _merge_conversation_scope(
        self,
        invocation: ToolInvocation,
        project_id: str,
        us_id: str,
    ) -> tuple[str, str]:
        conversation = self._workspace.conversation_scope(
            invocation.conversation_id
        )
        if conversation is None:
            return project_id, us_id

        project_id = project_id or conversation.project_id or (
            conversation.space_id
            if conversation.space_type == "project"
            else ""
        )
        us_id = us_id or conversation.us_id or (
            conversation.space_id
            if conversation.space_type == "workspace"
            else ""
        )
        return project_id, us_id


__all__ = ["QualityLoopScopeQueryApplicationService"]
