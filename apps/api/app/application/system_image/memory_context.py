from __future__ import annotations

import json
from typing import Any

from .ports import SystemImageWorkspacePort


class SystemImageMemoryContextApplicationService:
    """Build Agent-readable system-image memory facts.

    This is an application-layer query boundary for the Agent module. Agent
    memory may consume these strings and references, but it should not know
    which transitional store-backed collections currently hold system-image
    facts.
    """

    def __init__(self, workspace: SystemImageWorkspacePort) -> None:
        self._workspace = workspace

    def context_sections(self, project_id: str | None) -> list[str]:
        if not project_id:
            return []

        sections = ["[system_image]"]
        for baseline in self._workspace.list_baselines(project_id)[:2]:
            sections.append(
                f"baseline={baseline.id}; kind={baseline.kind}; status={baseline.status}; "
                f"objects={baseline.object_count}; relationships={baseline.relationship_count}; "
                f"metrics={baseline.metric_snapshot_count}"
            )
        for source in self._workspace.list_raw_assets(project_id)[:6]:
            sections.append(
                f"source={source.source_type}; status={source.ingestion_status}; uri={source.source_uri}; "
                f"hash={source.content_hash or 'pending'}"
            )
        for item in self._workspace.list_knowledge_objects(project_id)[:6]:
            sections.append(
                f"context_object={item.id}; name={item.name}; type={item.type}; branch={item.branch}; "
                f"confidence={item.confidence}; freshness={item.freshness}"
            )
        for relationship in self._workspace.list_context_relationships(project_id)[:6]:
            sections.append(
                f"relationship={relationship.relationship_type}; from={relationship.from_object_id}; "
                f"to={relationship.to_object_id}; confidence={relationship.confidence}"
            )
        for metric in self._workspace.list_quality_metric_snapshots(project_id)[:4]:
            sections.append(f"metric={metric.metric_group}; values={json.dumps(metric.metrics, ensure_ascii=False)}")
        return sections if len(sections) > 1 else []

    def long_term_project_refs(self, project_id: str | None) -> dict[str, Any]:
        if not project_id or not self._workspace.has_project(project_id):
            return {
                "project_id": project_id,
                "system_image_status": None,
                "baseline_refs": [],
                "source_refs": [],
                "context_object_refs": [],
                "metric_groups": [],
            }

        project = self._workspace.get_project(project_id)
        return {
            "project_id": project_id,
            "system_image_status": project.system_image_status,
            "baseline_refs": [
                f"baseline:{baseline.id}:{baseline.status}"
                for baseline in self._workspace.list_baselines(project_id)
            ],
            "source_refs": [
                f"raw_asset:{source.id}:{source.source_type}:{source.ingestion_status}"
                for source in self._workspace.list_raw_assets(project_id)
            ],
            "context_object_refs": [
                f"context_object:{item.id}:{item.type}"
                for item in self._workspace.list_knowledge_objects(project_id)[:12]
            ],
            "metric_groups": sorted(
                {
                    metric.metric_group
                    for metric in self._workspace.list_quality_metric_snapshots(project_id)
                }
            ),
        }
