from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from .context_extraction import ContextExtractionService
from .models import (
    AssetLane,
    BaselineRecord,
    ContextObjectOverlay,
    ContextRelationship,
    KnowledgeObject,
    QualityMetricSnapshot,
    RawAssetRecord,
    SystemImageResponse,
    USItem,
)
from .source_ingestion import SourceIngestionService, SourceSpec

if TYPE_CHECKING:
    from .store import ApplicationStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


class SystemImageService:
    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store
        self.source_ingestion = SourceIngestionService()
        self.context_extraction = ContextExtractionService()

    def ensure_state(self, project_id: str, *, ready: bool, version_id: Optional[str] = None) -> None:
        project = self.store.projects[project_id]
        now = _now_iso()
        baseline_id = f"base_{project_id}_official"
        status = "ready" if ready else "draft"
        source_status = "indexed" if ready else "pending"
        object_count = len(self.store.knowledge_objects.get(project_id, []))
        relationship_count = len(self.store.context_relationships.get(project_id, [])) if ready else 0
        metric_count = len(self.store.quality_metric_snapshots.get(project_id, [])) if ready else 0

        if not self.store.raw_assets.get(project_id):
            self.store.raw_assets[project_id] = [
                RawAssetRecord(
                    id=f"raw_{project_id}_code",
                    project_id=project_id,
                    version_id=version_id,
                    source_type="code",
                    source_uri=self.default_source_uri(project_id, "code"),
                    ingestion_status=source_status,
                    content_hash=f"hash:{project_id}:code" if ready else "",
                    content_ref=f"minio://nasus/raw/{project_id}/code" if ready else None,
                    evidence_refs=["source:git", "parser:tree-sitter", "index:opengrok"] if ready else [],
                    last_ingested_at=now if ready else None,
                ),
                RawAssetRecord(
                    id=f"raw_{project_id}_us",
                    project_id=project_id,
                    version_id=version_id,
                    source_type="us_doc",
                    source_uri=self.default_source_uri(project_id, "us_doc"),
                    ingestion_status=source_status,
                    content_hash=f"hash:{project_id}:us" if ready else "",
                    content_ref=f"minio://nasus/raw/{project_id}/us-docs" if ready else None,
                    evidence_refs=["source:historical-us", "parser:document-chunker"] if ready else [],
                    last_ingested_at=now if ready else None,
                ),
                RawAssetRecord(
                    id=f"raw_{project_id}_tests",
                    project_id=project_id,
                    version_id=version_id,
                    source_type="test_asset",
                    source_uri=self.default_source_uri(project_id, "test_asset"),
                    ingestion_status=source_status,
                    content_hash=f"hash:{project_id}:tests" if ready else "",
                    content_ref=f"minio://nasus/raw/{project_id}/test-assets" if ready else None,
                    evidence_refs=["source:test-cases", "source:automation-scripts"] if ready else [],
                    last_ingested_at=now if ready else None,
                ),
            ]
        elif ready:
            for source in self.store.raw_assets[project_id]:
                source.ingestion_status = "indexed"
                source.last_ingested_at = source.last_ingested_at or now
                if not source.evidence_refs:
                    if source.source_type == "code":
                        source.evidence_refs = ["source:git", "parser:tree-sitter", "index:opengrok"]
                    elif source.source_type == "us_doc":
                        source.evidence_refs = ["source:historical-us", "parser:document-chunker"]
                    else:
                        source.evidence_refs = ["source:test-cases", "source:automation-scripts"]

        self.store.baselines[project_id] = [
            BaselineRecord(
                id=baseline_id,
                project_id=project_id,
                kind="official",
                status=status,
                fork_strategy="copy_on_write",
                object_count=object_count,
                relationship_count=relationship_count or (4 if ready and object_count else 0),
                metric_snapshot_count=metric_count or (4 if ready and object_count else 0),
                updated_at=now,
            )
        ]

        if ready and self.store.knowledge_objects.get(project_id) and not self.store.context_relationships.get(project_id):
            objects = self.store.knowledge_objects[project_id]
            checkout = next((item for item in objects if "CHECKOUT" in item.id), objects[0])
            asset = next((item for item in objects if item.type == "QualityAssetPack"), objects[-1])
            self.store.context_relationships[project_id] = [
                ContextRelationship(
                    id=f"rel_{project_id}_code_feature",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id=checkout.id,
                    relationship_type="implements",
                    to_object_id="raw:code",
                    confidence=0.89,
                    source_refs=[f"raw:{project_id}:code"],
                ),
                ContextRelationship(
                    id=f"rel_{project_id}_us_feature",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id="US-123",
                    relationship_type="impacts",
                    to_object_id=checkout.id,
                    confidence=0.84,
                    source_refs=[f"raw:{project_id}:us_doc"],
                ),
                ContextRelationship(
                    id=f"rel_{project_id}_tests_feature",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id=asset.id,
                    relationship_type="covers",
                    to_object_id=checkout.id,
                    confidence=0.88,
                    source_refs=[f"raw:{project_id}:test_asset"],
                ),
                ContextRelationship(
                    id=f"rel_{project_id}_evidence_metric",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id=checkout.id,
                    relationship_type="evidenced_by",
                    to_object_id="metric:test_quality",
                    confidence=0.91,
                    source_refs=["run:run_9021", "scenario-pack:r3"],
                ),
            ]
        elif not ready:
            self.store.context_relationships[project_id] = []

        overlay_object_id = (
            self.store.knowledge_objects[project_id][0].id
            if self.store.knowledge_objects.get(project_id)
            else "context:pending"
        )
        self.store.context_object_overlays[project_id] = [
            ContextObjectOverlay(
                id=f"overlay_{project_id}_version_risk",
                project_id=project_id,
                baseline_id=baseline_id,
                object_id=overlay_object_id,
                field_path="risk_patterns.checkout_redirect",
                operation="add",
                value_ref="candidate:risk-pattern:checkout-redirect",
                source_refs=["run:run_9021", "approval:approval_442"],
                status="candidate",
            )
        ] if ready else []

        if ready and not self.store.quality_metric_snapshots.get(project_id):
            self.store.quality_metric_snapshots[project_id] = [
                QualityMetricSnapshot(
                    id=f"metric_{project_id}_code",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id=version_id,
                    metric_group="code_quality",
                    metrics={"changed_modules": 3, "critical_paths": 2, "code_risk_score": 67},
                    evidence_refs=[f"raw:{project_id}:code"],
                    captured_at=now,
                ),
                QualityMetricSnapshot(
                    id=f"metric_{project_id}_us",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id=version_id,
                    us_id="us_123",
                    metric_group="us_completion_quality",
                    metrics={"requirements_clarity": 0.82, "acceptance_criteria_coverage": 0.76},
                    evidence_refs=[f"raw:{project_id}:us_doc"],
                    captured_at=now,
                ),
                QualityMetricSnapshot(
                    id=f"metric_{project_id}_tests",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id=version_id,
                    metric_group="test_quality",
                    metrics={"scenario_coverage": 0.78, "automation_coverage": 0.52, "failed_runs": 1},
                    evidence_refs=[f"raw:{project_id}:test_asset"],
                    captured_at=now,
                ),
                QualityMetricSnapshot(
                    id=f"metric_{project_id}_release",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id=version_id,
                    metric_group="release_readiness",
                    metrics={"release_score": project.progress, "open_blockers": project.blocked_items},
                    evidence_refs=["approval:approval_442"],
                    captured_at=now,
                ),
            ]
        elif not ready:
            self.store.quality_metric_snapshots[project_id] = []

        self._persist_system_image(project_id)

    def default_source_uri(self, project_id: str, source_type: str) -> str:
        project = self.store.projects[project_id]
        slug = _slugify(project.name)
        if source_type == "code":
            return f"git://{slug}"
        if source_type == "us_doc":
            return f"docs://{slug}/historical-us"
        return f"tests://{slug}/regression"

    def source_binding_incomplete(self, project_id: str) -> bool:
        sources_by_type = {source.source_type: source for source in self.store.raw_assets.get(project_id, [])}
        for source_type in ("code", "us_doc", "test_asset"):
            source = sources_by_type.get(source_type)
            if source is None:
                return True
            if (
                source.source_uri == self.default_source_uri(project_id, source_type)
                and not source.content_hash
                and not source.evidence_refs
            ):
                return True
        return False

    def missing_source_types(self, project_id: str) -> list[str]:
        sources_by_type = {source.source_type: source for source in self.store.raw_assets.get(project_id, [])}
        missing: list[str] = []
        for source_type in ("code", "us_doc", "test_asset"):
            source = sources_by_type.get(source_type)
            if source is None or (
                source.source_uri == self.default_source_uri(project_id, source_type)
                and not source.content_hash
                and not source.evidence_refs
            ):
                missing.append(source_type)
        return missing

    def register_sources(self, project_id: str, source_specs: list[SourceSpec] | None = None) -> SystemImageResponse:
        self.ensure_state(project_id, ready=False)
        if source_specs:
            existing_by_type = {source.source_type: source for source in self.store.raw_assets[project_id]}
            for spec in source_specs:
                current = existing_by_type.get(spec.source_type)
                if current is None:
                    self.store.raw_assets[project_id].append(
                        RawAssetRecord(
                            id=f"raw_{project_id}_{spec.source_type}",
                            project_id=project_id,
                            source_type=spec.source_type,
                            source_uri=spec.source_uri,
                        )
                    )
                else:
                    current.source_uri = spec.source_uri
                    current.ingestion_status = "pending"
                    current.content_hash = ""
                    current.content_ref = None
                    current.evidence_refs = []
                    current.last_ingested_at = None

        project = self.store.projects[project_id]
        project.system_image_status = "draft"
        project.progress = max(project.progress, 16)
        self.store.projects[project_id] = project
        self.store.project_repository.upsert_project(project)
        self._persist_system_image(project_id)
        self.store._refresh_project_read_models(project_id)
        return self.get(project_id)

    def ingest_sources(self, project_id: str) -> SystemImageResponse:
        self.register_sources(project_id)
        now = _now_iso()
        for source in self.store.raw_assets[project_id]:
            try:
                ingested = self.source_ingestion.ingest(source)
            except OSError as exc:
                source.ingestion_status = "failed"
                source.evidence_refs = [f"ingest_error:{exc}"]
                source.last_ingested_at = now
                continue
            source.ingestion_status = "indexed"
            source.content_hash = ingested.content_hash
            source.content_ref = ingested.content_ref
            source.evidence_refs = ingested.evidence_refs
            source.last_ingested_at = now

        project = self.store.projects[project_id]
        project.progress = max(project.progress, 20)
        self.store.projects[project_id] = project
        self.store.project_repository.upsert_project(project)
        self._persist_system_image(project_id)
        self.store._refresh_project_read_models(project_id)
        return self.get(project_id)

    def ensure_context_objects(self, project_id: str) -> None:
        project = self.store.projects[project_id]
        if self.store.knowledge_objects.get(project_id):
            return

        object_prefix = f"OBJ-{project_id.upper().replace('-', '_')}"
        self.store.knowledge_objects[project_id] = [
            KnowledgeObject(
                id=f"{object_prefix}-CORE",
                name=f"{project.name} Core",
                type="System",
                branch="Official",
                confidence="0.72",
                relations=["Imported Code", "Historical US", "Regression Tests"],
                evidence=["Source import placeholders"],
                freshness="just now",
            ),
            KnowledgeObject(
                id=f"{object_prefix}-US",
                name="Historical US Baseline",
                type="Feature",
                branch="Official",
                confidence="0.68",
                relations=[f"{project.name} Core", "Quality Loop"],
                evidence=["US document import"],
                freshness="just now",
            ),
            KnowledgeObject(
                id=f"{object_prefix}-TESTS",
                name="Regression Quality Pack",
                type="QualityAssetPack",
                branch="Official",
                confidence="0.66",
                relations=[f"{project.name} Core", "Release Gate"],
                evidence=["Historical cases", "Automation scripts"],
                freshness="just now",
            ),
        ]
        self.store.project_repository.replace_knowledge_objects(project_id, self.store.knowledge_objects[project_id])

    def _materialize_fallback_context(
        self,
        project_id: str,
        *,
        baseline_id: str,
        version_id: str | None,
        captured_at: str,
    ) -> None:
        objects = self.store.knowledge_objects[project_id]
        core = next((item for item in objects if item.type == "System"), objects[0])
        feature = next((item for item in objects if item.type == "Feature"), objects[0])
        asset = next((item for item in objects if item.type == "QualityAssetPack"), objects[-1])
        self.store.context_relationships[project_id] = [
            ContextRelationship(
                id=f"rel_{project_id}_code_feature",
                project_id=project_id,
                baseline_id=baseline_id,
                from_object_id=feature.id,
                relationship_type="implements",
                to_object_id=core.id,
                confidence=0.89,
                source_refs=[f"raw:{project_id}:code"],
            ),
            ContextRelationship(
                id=f"rel_{project_id}_us_feature",
                project_id=project_id,
                baseline_id=baseline_id,
                from_object_id="US-123",
                relationship_type="impacts",
                to_object_id=feature.id,
                confidence=0.84,
                source_refs=[f"raw:{project_id}:us_doc"],
            ),
            ContextRelationship(
                id=f"rel_{project_id}_tests_feature",
                project_id=project_id,
                baseline_id=baseline_id,
                from_object_id=asset.id,
                relationship_type="covers",
                to_object_id=feature.id,
                confidence=0.88,
                source_refs=[f"raw:{project_id}:test_asset"],
            ),
            ContextRelationship(
                id=f"rel_{project_id}_evidence_metric",
                project_id=project_id,
                baseline_id=baseline_id,
                from_object_id=feature.id,
                relationship_type="evidenced_by",
                to_object_id="metric:test_quality",
                confidence=0.91,
                source_refs=["system-image:fallback"],
            ),
        ]
        self.store.quality_metric_snapshots[project_id] = [
            QualityMetricSnapshot(
                id=f"metric_{project_id}_code",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="code_quality",
                metrics={"changed_modules": 3, "critical_paths": 2, "code_risk_score": 67},
                evidence_refs=[f"raw:{project_id}:code"],
                captured_at=captured_at,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_us",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                us_id="us_123",
                metric_group="us_completion_quality",
                metrics={"requirements_clarity": 0.82, "acceptance_criteria_coverage": 0.76},
                evidence_refs=[f"raw:{project_id}:us_doc"],
                captured_at=captured_at,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_tests",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="test_quality",
                metrics={"scenario_coverage": 0.78, "automation_coverage": 0.52, "failed_runs": 1},
                evidence_refs=[f"raw:{project_id}:test_asset"],
                captured_at=captured_at,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_release",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="release_readiness",
                metrics={
                    "release_score": self.store.projects[project_id].progress,
                    "open_blockers": self.store.projects[project_id].blocked_items,
                },
                evidence_refs=["system-image:fallback"],
                captured_at=captured_at,
            ),
        ]

    def materialize_context(self, project_id: str) -> SystemImageResponse:
        self.ingest_sources(project_id)
        self._ensure_sources_ready(project_id, stage="materialize system context")
        version_id = self.store.versions[project_id][0].id if self.store.versions.get(project_id) else None
        baseline_id = (
            self.store.baselines[project_id][0].id
            if self.store.baselines.get(project_id)
            else f"base_{project_id}_official"
        )
        now = _now_iso()
        extracted = self.context_extraction.extract(
            project_id=project_id,
            project_name=self.store.projects[project_id].name,
            baseline_id=baseline_id,
            sources=self.store.raw_assets[project_id],
            version_id=version_id,
            captured_at=now,
        )
        if len(extracted.objects) > 1:
            self.store.knowledge_objects[project_id] = extracted.objects
            self.store.context_relationships[project_id] = extracted.relationships
            self.store.quality_metric_snapshots[project_id] = extracted.metrics
        else:
            self.ensure_context_objects(project_id)
            self._materialize_fallback_context(project_id, baseline_id=baseline_id, version_id=version_id, captured_at=now)

        self._sync_us_work_items_from_context(project_id, version_id=version_id)

        if self.store.baselines.get(project_id):
            self.store.baselines[project_id][0].object_count = len(self.store.knowledge_objects[project_id])
            self.store.baselines[project_id][0].relationship_count = len(self.store.context_relationships[project_id])
            self.store.baselines[project_id][0].metric_snapshot_count = len(
                self.store.quality_metric_snapshots[project_id]
            )
            self.store.baselines[project_id][0].updated_at = now

        project = self.store.projects[project_id]
        project.progress = max(project.progress, 24)
        self.store.projects[project_id] = project
        self.store.project_repository.upsert_project(project)
        self.store.project_repository.replace_knowledge_objects(project_id, self.store.knowledge_objects[project_id])
        self._persist_system_image(project_id)
        self.store._refresh_project_read_models(project_id)
        return self.get(project_id)

    def _sync_us_work_items_from_context(self, project_id: str, *, version_id: str | None) -> None:
        if self.store.us_items.get(project_id):
            return

        us_objects = [
            item for item in self.store.knowledge_objects.get(project_id, [])
            if item.type == "USWorkItem"
        ]
        if not us_objects:
            us_objects = [
                item for item in self.store.knowledge_objects.get(project_id, [])
                if item.type in {"Feature", "RequirementSection", "RequirementDocument"}
            ]
        if not us_objects:
            return

        us_items: list[USItem] = []
        for index, item in enumerate(us_objects[:8], start=1):
            us_id_match = re.search(r"\bUS[-_ ]?(\d+)\b", item.name, re.IGNORECASE)
            us_code = f"US-{us_id_match.group(1)}" if us_id_match else f"US-{index:03d}"
            us_items.append(
                USItem(
                    id=f"us_{_slugify(us_code)}_{project_id[-6:]}",
                    title=item.name[:96],
                    owner="Nasus Agent",
                    status="analysis",
                    risk="medium",
                    progress=18,
                    next_action="Generate scenarios",
                )
            )

        self.store.us_items[project_id] = us_items
        self.store.project_repository.replace_us_items(project_id, version_id, us_items)
        for us_item in us_items:
            lanes = [
                AssetLane(
                    id=f"{us_item.id}_lane_scenarios",
                    label="Scenarios",
                    status="not_started",
                    summary="Waiting for scenario generation from system image, US, and test evidence.",
                    updated_at=_now_iso(),
                ),
                AssetLane(
                    id=f"{us_item.id}_lane_cases",
                    label="Cases",
                    status="not_started",
                    summary="Waiting for approved scenario structure.",
                    updated_at=_now_iso(),
                ),
                AssetLane(
                    id=f"{us_item.id}_lane_automation",
                    label="Automation",
                    status="not_started",
                    summary="Waiting for reviewed cases before script generation.",
                    updated_at=_now_iso(),
                ),
                AssetLane(
                    id=f"{us_item.id}_lane_release",
                    label="Release Assessment",
                    status="not_started",
                    summary="Waiting for execution evidence and quality scoring.",
                    updated_at=_now_iso(),
                ),
            ]
            self.store.asset_lanes[us_item.id] = lanes
            self.store.project_repository.replace_asset_lanes(project_id, us_item.id, lanes)

    def initialize_baseline(self, project_id: str) -> SystemImageResponse:
        self.materialize_context(project_id)
        self._ensure_sources_ready(project_id, stage="initialize Official System Image")
        self.ensure_context_objects(project_id)
        project = self.store.projects[project_id]
        project.system_image_status = "ready"
        project.progress = max(project.progress, 28)
        self.store.projects[project_id] = project
        self.store.project_repository.upsert_project(project)
        version_id = self.store.versions[project_id][0].id if self.store.versions.get(project_id) else None
        self.ensure_state(project_id, ready=True, version_id=version_id)
        self.store._refresh_project_read_models(project_id)
        return self.get(project_id)

    def get(self, project_id: str) -> SystemImageResponse:
        self.store._refresh_project_read_models(project_id)
        project = self.store.projects[project_id]
        baseline = self.store.baselines[project_id][0] if self.store.baselines.get(project_id) else None
        source_counts = {
            source_type: sum(1 for source in self.store.raw_assets[project_id] if source.source_type == source_type)
            for source_type in ["code", "us_doc", "test_asset"]
        }
        summary = (
            f"{project.name} system image is {project.system_image_status}. "
            f"Sources: code={source_counts['code']}, us_doc={source_counts['us_doc']}, "
            f"test_asset={source_counts['test_asset']}. "
            f"Baseline {baseline.id if baseline else 'not initialized'} has "
            f"{baseline.object_count if baseline else 0} objects and "
            f"{baseline.relationship_count if baseline else 0} relationships."
        )
        return SystemImageResponse(
            project=project,
            summary=summary,
            baselines=self.store.baselines[project_id],
            sources=self.store.raw_assets[project_id],
            objects=self.store.knowledge_objects[project_id],
            relationships=self.store.context_relationships[project_id],
            overlays=self.store.context_object_overlays[project_id],
            metric_snapshots=self.store.quality_metric_snapshots[project_id],
        )

    def _persist_system_image(self, project_id: str) -> None:
        self.store.project_repository.replace_system_image(
            project_id,
            sources=self.store.raw_assets[project_id],
            baselines=self.store.baselines[project_id],
            relationships=self.store.context_relationships[project_id],
            overlays=self.store.context_object_overlays[project_id],
            metric_snapshots=self.store.quality_metric_snapshots[project_id],
        )

    def _ensure_sources_ready(self, project_id: str, *, stage: str) -> None:
        failed_sources = [
            source
            for source in self.store.raw_assets[project_id]
            if source.ingestion_status == "failed"
        ]
        if failed_sources:
            failed = ", ".join(f"{source.source_type}:{source.source_uri}" for source in failed_sources)
            raise RuntimeError(f"Cannot {stage}; source ingestion failed for {failed}.")
