from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from .context_queries import QualityLoopContextQueryApplicationService
from .ports import QualityAssetPackWorkspacePort
from .quality_models import QualityAssetGenerationMetadata, QualityAssetPack, QualityAssetPart
from ...domain.quality_loop.quality_assets import (
    next_quality_asset_part_revision,
    quality_asset_pack_current_revision,
    quality_asset_pack_evidence_refs,
    quality_asset_pack_status,
)


class ActiveVersionProvider(Protocol):
    def __call__(self, project_id: str) -> Any:
        """Return the active version or create the default quality-loop version."""


class QualityAssetPackApplicationService:
    """Write-side boundary for QualityAssetPack facts.

    The quality-loop coordinator decides which part should change. This service
    owns part revisioning, pack status/current revision/evidence aggregation,
    source reference resolution, and repository persistence.
    """

    def __init__(
        self,
        workspace: QualityAssetPackWorkspacePort,
        context_queries: QualityLoopContextQueryApplicationService,
        active_version_provider: ActiveVersionProvider,
    ) -> None:
        self._workspace = workspace
        self._context_queries = context_queries
        self._active_version_provider = active_version_provider

    def refresh_pack(self, project_id: str, us_id: str) -> tuple[QualityAssetPack | None, list[str]]:
        pack = self._workspace.get_quality_asset_pack(project_id, us_id)
        if pack is None:
            pack_refs = self.upsert_part(
                project_id,
                us_id,
                part_type="scope_pack",
                status="draft",
                title="Quality asset pack initialized",
                summary=(
                    "Quality asset pack is initialized and waiting for scope, scenario, case, "
                    "automation, and release evidence."
                ),
                object_refs=[f"us:{us_id}"],
                evidence_refs=[f"us:{us_id}"],
            )
            pack = self._workspace.get_quality_asset_pack(project_id, us_id)
        else:
            pack.current_revision += 1
            pack.updated_at = self._now()
            self._workspace.save_quality_asset_pack(pack)
            pack_refs = [f"quality_asset_pack:{pack.id}"]
        return pack, pack_refs

    def current_pack(
        self,
        project_id: str,
        us_id: str,
    ) -> QualityAssetPack | None:
        return self._workspace.get_quality_asset_pack(project_id, us_id)

    def upsert_part(
        self,
        project_id: str,
        us_id: str,
        *,
        part_type: str,
        status: str,
        title: str,
        summary: str,
        object_refs: list[str],
        evidence_refs: list[str],
        structured_content: dict[str, Any] | None = None,
        generation: QualityAssetGenerationMetadata | None = None,
    ) -> list[str]:
        version = self._active_version_provider(project_id)
        pack_id = f"qap_{project_id}_{us_id}"
        now = self._now()
        existing = self._workspace.get_quality_asset_pack(project_id, us_id)
        parts = list(existing.parts if existing else [])
        revision = next_quality_asset_part_revision(parts, part_type)
        part = QualityAssetPart(
            id=f"{pack_id}_{part_type}",
            part_type=part_type,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            title=title,
            summary=summary,
            revision=revision,
            object_refs=object_refs,
            evidence_refs=evidence_refs,
            structured_content=structured_content or {},
            generation=generation,
            updated_at=now,
        )
        parts = [part, *[item for item in parts if item.part_type != part_type]]
        source_refs = []
        context = self._context_queries.current_task_context(project_id, us_id)
        if context is not None:
            source_refs = context.source_refs
        pack = QualityAssetPack(
            id=pack_id,
            project_id=project_id,
            version_id=version.id,
            us_id=us_id,
            status=quality_asset_pack_status(parts),  # type: ignore[arg-type]
            current_revision=quality_asset_pack_current_revision(parts),
            parts=parts,
            source_refs=source_refs,
            evidence_refs=quality_asset_pack_evidence_refs(parts),
            updated_at=now,
        )
        self._workspace.save_quality_asset_pack(pack)
        return [f"quality_asset_pack:{pack.id}", f"quality_asset_part:{part.id}"]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = ["ActiveVersionProvider", "QualityAssetPackApplicationService"]
