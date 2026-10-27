from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from ...domain.system_image.source_access import SourceAccessScope
from .system_image_models import BaselineRecord, ContextRelationship, KnowledgeObject, QualityMetricSnapshot, RawAssetRecord
from .publication_read_models import ImageReadState
from ...domain.system_image.publication import PublicationChanged


@dataclass(frozen=True)
class SystemImageContextFacts:
    scope: SourceAccessScope
    sources: tuple[RawAssetRecord, ...] = ()
    objects: tuple[KnowledgeObject, ...] = ()
    baselines: tuple[BaselineRecord, ...] = ()
    relationships: tuple[ContextRelationship, ...] = ()
    metrics: tuple[QualityMetricSnapshot, ...] = ()
    system_image_status: Optional[str] = None
    read_state: ImageReadState = field(default_factory=ImageReadState)
    verify_publication: Optional[Callable[[], None]] = None


class SystemImageContextReadPort(Protocol):
    def read(self, project_id: str, *, version_id: Optional[str] = None) -> SystemImageContextFacts: ...

    def scope(self, project_id: str) -> SourceAccessScope: ...

    def require_current(self, scope: SourceAccessScope) -> None: ...


class SystemImageMemoryContextApplicationService:
    """Build Agent-readable system-image memory facts.

    This is an application-layer query boundary for the Agent module. Agent
    memory may consume these strings and references, but it should not know
    which transitional store-backed collections currently hold system-image
    facts.
    """

    def __init__(self, reader: SystemImageContextReadPort) -> None:
        self._reader = reader

    def scope(self, project_id: str) -> SourceAccessScope:
        return self._reader.scope(project_id)

    def require_current(self, scope: SourceAccessScope | None) -> None:
        if scope is not None:
            self._reader.require_current(scope)

    def context_sections(self, project_id: str | None, *, version_id=None, expected_state=None) -> list[str]:
        if not project_id:
            return []

        facts = self._reader.read(project_id, version_id=version_id) if version_id else self._reader.read(project_id)
        if expected_state is not None and facts.read_state != expected_state:
            raise PublicationChanged("Image head changed between retrieval and context assembly")
        sections = ["[system_image]"]
        if facts.read_state.mode != "legacy_draft":
            sections.append("image_read_state=" + facts.read_state.model_dump_json())
            sections.append("Knowledge snapshot only; not business acceptance, test coverage or release authority.")
        for baseline in facts.baselines[:2]:
            sections.append(
                f"baseline={baseline.id}; kind={baseline.kind}; status={baseline.status}; "
                f"objects={baseline.object_count}; relationships={baseline.relationship_count}; "
                f"metrics={baseline.metric_snapshot_count}"
            )
        for source in facts.sources[:6]:
            sections.append(
                f"source={source.source_type}; status={source.ingestion_status}; uri={source.source_uri}; "
                f"hash={source.content_hash or 'pending'}"
            )
        for item in facts.objects[:6]:
            sections.append(
                f"context_object={item.id}; name={item.name}; type={item.type}; branch={item.branch}; "
                f"confidence={item.confidence}; freshness={item.freshness}"
            )
            reference = getattr(item, "code_reference", None)
            if reference is not None:
                sections.append("code_evidence_query=" + json.dumps({
                    "project_id": project_id, "object_id": item.id,
                    "source_revision_id": reference.source_revision_id,
                    "entity_revision_id": reference.entity_revision_id,
                }, ensure_ascii=False, sort_keys=True))
        for relationship in facts.relationships[:6]:
            sections.append(
                f"relationship={relationship.relationship_type}; from={relationship.from_object_id}; "
                f"to={relationship.to_object_id}; confidence={relationship.confidence}"
            )
        for metric in facts.metrics[:4]:
            sections.append(f"metric={metric.metric_group}; values={json.dumps(metric.metrics, ensure_ascii=False)}")
        self.require_current(facts.scope)
        if facts.verify_publication:
            facts.verify_publication()
        return sections if len(sections) > 1 else []

    def long_term_project_refs(self, project_id: str | None, *, version_id=None) -> dict[str, Any]:
        if not project_id:
            return {
                "project_id": project_id,
                "system_image_status": None,
                "baseline_refs": [],
                "source_refs": [],
                "context_object_refs": [],
                "metric_groups": [],
            }

        facts = self._reader.read(project_id, version_id=version_id) if version_id else self._reader.read(project_id)
        result = {
            "image_read_state": facts.read_state.model_dump(mode="json"),
            "project_id": project_id,
            "system_image_status": facts.system_image_status,
            "baseline_refs": [
                f"baseline:{baseline.id}:{baseline.status}"
                for baseline in facts.baselines
            ],
            "source_refs": [
                f"raw_asset:{source.id}:{source.source_type}:{source.ingestion_status}"
                for source in facts.sources
            ],
            "context_object_refs": [
                f"context_object:{item.id}:{item.type}"
                for item in facts.objects[:12]
            ],
            "metric_groups": sorted(
                {
                    metric.metric_group
                    for metric in facts.metrics
                }
            ),
        }
        self.require_current(facts.scope)
        if facts.verify_publication:
            facts.verify_publication()
        return result
