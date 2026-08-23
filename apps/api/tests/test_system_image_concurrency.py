from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from threading import Event, RLock, Thread
from types import SimpleNamespace

from apps.api.app.application.platform.project_models import ProjectCard
from apps.api.app.application.system_image.source_ingestion import (
    SystemImageSourceIngestionApplicationService,
)
from apps.api.app.application.system_image.source_ports import IngestedSource
from apps.api.app.application.system_image.system_image_models import RawAssetRecord


class _BlockingSourceIngestion:
    def __init__(self, started: Event, release: Event) -> None:
        self._started = started
        self._release = release
        self._calls = 0

    def ingest(self, source: RawAssetRecord) -> IngestedSource:
        self._calls += 1
        if self._calls == 1:
            self._started.set()
            if not self._release.wait(timeout=5):
                raise TimeoutError("test did not release source ingestion")
        return IngestedSource(
            content_hash=f"sha256:{source.source_type}",
            content_ref=f"local-object://test/{source.source_type}",
            evidence_refs=[f"source:{source.source_type}"],
            file_count=1,
            byte_count=10,
        )


class _SnapshotPersistence:
    def __init__(self, store: SimpleNamespace) -> None:
        self._store = store
        self.sources: list[RawAssetRecord] = []

    def persist(self, project_id: str) -> None:
        self.sources = deepcopy(self._store.raw_assets[project_id])


class _Projection:
    def __init__(self, store: SimpleNamespace, persistence: _SnapshotPersistence) -> None:
        self._store = store
        self._persistence = persistence

    def mutation_guard(self, project_id: str) -> RLock:
        del project_id
        return self._store.runtime_projection_lock

    def get_project(self, project_id: str) -> ProjectCard:
        return self._store.projects[project_id]

    def list_sources(self, project_id: str) -> list[RawAssetRecord]:
        return self._store.raw_assets[project_id]

    def replace_sources(self, project_id: str, sources: list[RawAssetRecord]) -> None:
        self._store.raw_assets[project_id] = sources

    def save_project(self, project: ProjectCard) -> None:
        self._store.projects[project.id] = project

    def clear_derived_context(self, project_id: str) -> None:
        self._store.raw_asset_chunks[project_id] = []
        self._store.embedding_records[project_id] = []
        self._store.retrieval_runs[project_id] = []
        self._store.rerank_records[project_id] = []
        self._store.task_contexts[project_id] = []
        self._store.quality_profiles[project_id] = []

    def clear_chunks(self, project_id: str) -> None:
        self._store.raw_asset_chunks[project_id] = []

    def persist(self, project_id: str) -> None:
        self._persistence.persist(project_id)

    def refresh(self, project_id: str) -> None:
        with self._store.runtime_projection_lock:
            self._store.raw_assets[project_id] = deepcopy(self._persistence.sources)


class _ProjectRepository:
    def upsert_project(self, project: ProjectCard) -> None:
        del project


class _RawAssetChunks:
    def materialize(self, project_id: str, *, captured_at: str) -> list[object]:
        del project_id, captured_at
        return []


def _store() -> SimpleNamespace:
    project_id = "project-concurrency"
    project = ProjectCard(
        id=project_id,
        name="Concurrency Project",
        code="CON",
        summary="Projection concurrency regression",
        status="active",
        risk="low",
        progress=0,
        active_version="",
        blocked_items=0,
        pending_approvals=0,
        system_image_status="draft",
    )
    sources = [
        RawAssetRecord(
            id=f"raw-{source_type}",
            project_id=project_id,
            source_type=source_type,
            source_uri=f"/fixtures/{source_type}",
        )
        for source_type in ("code", "us_doc", "test_asset")
    ]
    return SimpleNamespace(
        runtime_projection_lock=RLock(),
        projects={project_id: project},
        raw_assets=defaultdict(list, {project_id: sources}),
        raw_asset_chunks=defaultdict(list),
        embedding_records=defaultdict(list),
        retrieval_runs=defaultdict(list),
        rerank_records=defaultdict(list),
        task_contexts=defaultdict(list),
        quality_profiles=defaultdict(list),
        project_repository=_ProjectRepository(),
    )


def test_ingestion_prevents_concurrent_refresh_from_replacing_write_projection() -> None:
    store = _store()
    project_id = "project-concurrency"
    ingestion_started = Event()
    release_ingestion = Event()
    persistence = _SnapshotPersistence(store)
    projection = _Projection(store, persistence)
    service = SystemImageSourceIngestionApplicationService(
        projection,
        _BlockingSourceIngestion(ingestion_started, release_ingestion),
        _RawAssetChunks(),
    )

    writer = Thread(
        target=service.ingest_sources,
        kwargs={
            "project_id": project_id,
            "ensure_draft_state": lambda: None,
            "source_binding_incomplete": lambda: False,
            "missing_source_types": lambda: [],
        },
    )
    writer.start()
    assert ingestion_started.wait(timeout=2)

    refresh_finished = Event()

    def refresh() -> None:
        projection.refresh(project_id)
        refresh_finished.set()

    reader = Thread(target=refresh)
    reader.start()
    assert not refresh_finished.wait(timeout=0.05)

    release_ingestion.set()
    writer.join(timeout=2)
    reader.join(timeout=2)

    assert not writer.is_alive()
    assert not reader.is_alive()
    assert refresh_finished.is_set()
    assert {source.ingestion_status for source in persistence.sources} == {"indexed"}
    assert {source.ingestion_status for source in store.raw_assets[project_id]} == {"indexed"}
    assert store.projects[project_id].system_image_status == "indexed"
