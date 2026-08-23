from __future__ import annotations

from .ports import QualityLoopContextWorkspacePort
from .quality_models import QualityAssetPack
from ..system_image.system_image_models import QualityProfile, TaskContext


class QualityLoopContextQueryApplicationService:
    """Read current quality-loop context for write-side use cases."""

    def __init__(self, workspace: QualityLoopContextWorkspacePort) -> None:
        self._workspace = workspace

    def current_task_context(self, project_id: str, us_id: str | None = None) -> TaskContext | None:
        contexts = self._workspace.list_task_contexts(project_id)
        if us_id:
            return next((context for context in contexts if context.us_id == us_id), None)
        return contexts[0] if contexts else None

    def current_quality_profile(self, project_id: str, us_id: str | None = None) -> QualityProfile | None:
        profiles = self._workspace.list_quality_profiles(project_id)
        if us_id:
            return next((profile for profile in profiles if profile.us_id == us_id), None)
        return profiles[0] if profiles else None

    def current_quality_asset_pack(self, project_id: str, us_id: str | None = None) -> QualityAssetPack | None:
        if us_id:
            return self._workspace.get_quality_asset_pack(project_id, us_id)
        packs = self._workspace.list_quality_asset_packs(project_id)
        return packs[0] if packs else None

    def planner_quality_state(self, project_id: str | None, us_id: str | None) -> dict[str, str]:
        resolved_project_id = project_id or ""
        resolved_us_id = us_id or ""
        if not resolved_us_id and resolved_project_id:
            first_us = next(
                iter(self._workspace.list_us_items(resolved_project_id)),
                None,
            )
            resolved_us_id = first_us.id if first_us is not None else ""
        if not resolved_project_id and resolved_us_id:
            resolved_project_id = (
                self._workspace.project_id_for_us(resolved_us_id) or ""
            )

        state: dict[str, str] = {"project_id": resolved_project_id, "us_id": resolved_us_id}
        for lane in self._workspace.list_asset_lanes(resolved_us_id):
            label = lane.label.strip().lower()
            if "scenario" in label:
                state["scenarios"] = lane.status
            elif "verification" in label:
                state["verification_plan"] = lane.status
            elif "case" in label:
                state["cases"] = lane.status
            elif "automation" in label:
                state["automation"] = lane.status
            elif "release" in label:
                state["release"] = lane.status
            elif "change document" in label:
                state["change_document"] = lane.status
        if resolved_project_id and resolved_us_id:
            pack = self.current_quality_asset_pack(resolved_project_id, resolved_us_id)
            for part in pack.parts if pack is not None else []:
                if part.part_type == "scope_pack":
                    state["scope"] = part.status
                elif part.part_type == "verification_plan":
                    state["verification_plan"] = part.status
                elif part.part_type == "change_document":
                    state["change_document"] = part.status
        return state


__all__ = ["QualityLoopContextQueryApplicationService"]
