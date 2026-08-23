from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .persistence import SystemImagePersistenceApplicationService
from .ports import SystemImageWorkspacePort
from .system_image_models import RetrievalRun


class SystemImageRetrievalTraceApplicationService:
    """Persist retrieval traces owned by the system-image module."""

    def __init__(self, workspace: SystemImageWorkspacePort) -> None:
        self._workspace = workspace
        self._persistence = SystemImagePersistenceApplicationService(workspace)

    def record_agent_memory_retrieval(
        self,
        *,
        project_id: str | None,
        version_id: str | None,
        us_id: str | None,
        query: str,
        result_refs: list[str],
    ) -> list[str]:
        if not project_id or not query.strip():
            return []

        retrieval_run = RetrievalRun(
            id=f"retrieval_agent_memory_{uuid4().hex[:12]}",
            project_id=project_id,
            baseline_id=self._retrieval_baseline_id(project_id),
            version_id=version_id,
            us_id=us_id,
            query=query,
            strategy=self._retrieval_strategy(project_id),
            candidate_count=len(result_refs),
            result_refs=result_refs,
            embedding_record_ids=self._ready_embedding_record_ids(project_id),
            rerank_record_id=self._latest_rerank_record_id(project_id),
            fallback_used=self._retrieval_fallback_used(project_id),
            created_at=_now_iso(),
        )
        self._workspace.append_retrieval_run(project_id, retrieval_run)
        self._persistence.persist(project_id)
        self._workspace.refresh_project_read_model(project_id)
        return [f"retrieval_run:{retrieval_run.id}"]

    def _retrieval_baseline_id(self, project_id: str) -> str:
        baselines = self._workspace.list_baselines(project_id)
        ready_official = next(
            (
                baseline
                for baseline in baselines
                if baseline.kind == "official" and baseline.status in {"ready", "promoted"}
            ),
            None,
        )
        if ready_official is not None:
            return ready_official.id
        if baselines:
            return baselines[0].id
        return f"baseline_pending_{project_id}"

    def _retrieval_strategy(self, project_id: str) -> str:
        if any(
            record.status == "ready"
            for record in self._workspace.list_embedding_records(project_id)
        ):
            return "hybrid_graph_vector"
        return "rule_based_fusion"

    def _ready_embedding_record_ids(self, project_id: str) -> list[str]:
        return [
            record.id
            for record in self._workspace.list_embedding_records(project_id)
            if record.status == "ready"
        ][:24]

    def _latest_rerank_record_id(self, project_id: str) -> str | None:
        records = self._workspace.list_rerank_records(project_id)
        if not records:
            return None
        return records[-1].id

    def _retrieval_fallback_used(self, project_id: str) -> bool:
        return not any(
            record.status == "ready"
            for record in self._workspace.list_embedding_records(project_id)
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
