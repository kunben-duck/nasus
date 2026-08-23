from __future__ import annotations

import asyncio
from collections import defaultdict
from threading import RLock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from apps.api.app.application.platform.project_models import ProjectCard
from apps.api.app.infrastructure.system_image import (
    CompatibilitySystemImageIngestionProjection,
    DefaultSystemImageRetriever,
    DurableSystemImageWorkspaceAdapters,
    LegacySystemImageWorkspace,
    SQLAlchemySystemImageWorkspace,
    SystemImageProjectionState,
    SystemImageRetrievalState,
    SystemImageWorkspaceAdapters,
)


def _projection_state() -> SystemImageProjectionState:
    return SystemImageProjectionState(
        projects={},
        versions=defaultdict(list),
        us_items=defaultdict(list),
        asset_lanes=defaultdict(list),
        knowledge_objects=defaultdict(list),
        raw_assets=defaultdict(list),
        raw_asset_chunks=defaultdict(list),
        baselines=defaultdict(list),
        context_relationships=defaultdict(list),
        context_object_overlays=defaultdict(list),
        quality_metric_snapshots=defaultdict(list),
        embedding_records=defaultdict(list),
        retrieval_runs=defaultdict(list),
        rerank_records=defaultdict(list),
        task_contexts=defaultdict(list),
        quality_profiles=defaultdict(list),
    )


def test_system_image_workspace_operates_without_application_store() -> None:
    state = _projection_state()
    project_repository = Mock()
    system_image_repository = Mock()
    read_model_refresh = Mock()
    project_access = Mock()
    object_storage = Mock()
    object_storage.put_json.return_value = SimpleNamespace(storage_ref="s3://bucket/source.json")
    object_storage.get_json.return_value = {"source": "code"}
    model_gateway = SimpleNamespace(
        embed_texts=AsyncMock(return_value=SimpleNamespace(mode="live")),
        rerank_candidates=AsyncMock(return_value=SimpleNamespace(mode="live")),
    )
    settings = object()
    api_keys = {"embedding": "embedding-secret", "rerank": "rerank-secret"}
    workspace = LegacySystemImageWorkspace(
        state,
        SystemImageWorkspaceAdapters(
            project_repository=project_repository,
            system_image_repository=system_image_repository,
            project_read_model_refresh=read_model_refresh,
            project_access=project_access,
            object_storage=object_storage,
            model_gateway=model_gateway,
            settings_provider=lambda: settings,  # type: ignore[arg-type]
            custom_api_key_provider=api_keys.__getitem__,
        ),
        require_live_model_routes=True,
    )
    project = ProjectCard(
        id="project_001",
        name="Payments",
        code="PAY",
        summary="Payment quality",
        status="active",
        risk="medium",
        progress=0,
        active_version="",
        blocked_items=0,
        pending_approvals=0,
        system_image_status="not_started",
    )

    workspace.save_project(project)
    workspace.require_project_access(project.id)
    workspace.refresh_project_read_model(project.id)
    storage_ref = workspace.put_json("sources/project_001.json", {"source": "code"})
    embedding_result, rerank_result = asyncio.run(
        _exercise_model_routes(workspace)
    )

    assert workspace.get_project(project.id) == project
    assert storage_ref == "s3://bucket/source.json"
    assert workspace.get_json(storage_ref) == {"source": "code"}
    assert embedding_result.mode == "live"
    assert rerank_result.mode == "live"
    project_repository.upsert_project.assert_called_once_with(project)
    project_access.require_project_access.assert_called_once_with(project.id)
    read_model_refresh.refresh_system_image.assert_called_once_with(project.id)
    model_gateway.embed_texts.assert_awaited_once_with(
        settings=settings,
        texts=["checkout"],
        custom_api_key="embedding-secret",
    )
    model_gateway.rerank_candidates.assert_awaited_once_with(
        settings=settings,
        query="payment retry",
        documents=["checkout", "refund"],
        custom_api_key="rerank-secret",
    )


def test_sqlalchemy_workspace_commits_and_reloads_repository_snapshot() -> None:
    project = ProjectCard(
        id="project_001",
        name="Payments",
        code="PAY",
        summary="Payment quality",
        status="active",
        risk="medium",
        progress=0,
        active_version="",
        blocked_items=0,
        pending_approvals=0,
        system_image_status="draft",
    )
    project_repository = Mock()
    project_repository.get_project.return_value = project
    project_repository.list_versions.return_value = []
    quality_loop_repository = Mock()
    quality_loop_repository.list_us_items.return_value = []
    quality_loop_repository.list_asset_lanes.return_value = {}
    quality_loop_repository.list_asset_lanes_for_us.return_value = []
    persisted_source = SimpleNamespace(id="source_001")
    reloaded_source = SimpleNamespace(id="source_002")

    def system_image_snapshot(sources):
        return SimpleNamespace(
            knowledge_objects=[],
            raw_assets=sources,
            raw_asset_chunks=[],
            baselines=[],
            relationships=[],
            overlays=[],
            metric_snapshots=[],
            embedding_records=[],
            retrieval_runs=[],
            rerank_records=[],
            task_contexts=[],
            quality_profiles=[],
        )

    system_image_repository = Mock()
    system_image_repository.load_project_snapshot.side_effect = [
        system_image_snapshot([]),
        system_image_snapshot([reloaded_source]),
    ]
    read_model_refresh = Mock()
    workspace = SQLAlchemySystemImageWorkspace(
        DurableSystemImageWorkspaceAdapters(
            project_repository=project_repository,
            quality_loop_repository=quality_loop_repository,
            system_image_repository=system_image_repository,
            project_read_model_refresh=read_model_refresh,
            project_access=Mock(),
            object_storage=Mock(),
            model_gateway=Mock(),
            settings_provider=Mock(),
            custom_api_key_provider=Mock(),
        )
    )

    workspace.replace_raw_assets("project_001", [persisted_source])
    workspace.persist_system_image("project_001")

    assert workspace.list_raw_assets("project_001") == [reloaded_source]
    assert system_image_repository.load_project_snapshot.call_count == 2
    system_image_repository.replace_system_image.assert_called_once_with(
        "project_001",
        sources=[persisted_source],
        chunks=[],
        baselines=[],
        relationships=[],
        overlays=[],
        metric_snapshots=[],
        embedding_records=[],
        retrieval_runs=[],
        rerank_records=[],
        task_contexts=[],
        quality_profiles=[],
        knowledge_objects=[],
    )


async def _exercise_model_routes(
    workspace: LegacySystemImageWorkspace,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    embedding_result = await workspace.embed_texts(["checkout"])
    rerank_result = await workspace.rerank_candidates(
        query="payment retry",
        candidates=["checkout", "refund"],
    )
    return embedding_result, rerank_result


def test_system_image_retriever_uses_explicit_read_projections() -> None:
    state = _projection_state()
    state.knowledge_objects["project_001"] = [
        SimpleNamespace(
            id="object_checkout",
            name="Checkout payment",
            type="feature",
            branch="official",
            relations=[],
            evidence=["code:checkout.py"],
        )
    ]
    state.raw_asset_chunks["project_001"] = [
        SimpleNamespace(
            id="chunk_checkout",
            source_type="code",
            chunk_kind="code_symbol",
            section_path="checkout.py",
            content_hash="sha256:checkout",
        )
    ]
    agent_memory_items = {
        "memory_001": SimpleNamespace(
            id="memory_001",
            owner_ref="project:project_001",
            memory_scope="project_long_term",
            status="active",
            summary="Checkout payment recovery",
            source_refs=[],
            object_refs=["context_object:object_checkout"],
            evidence_refs=[],
        )
    }
    retriever = DefaultSystemImageRetriever(
        SystemImageRetrievalState(
            system_image=state,
            agent_memory_items=agent_memory_items,  # type: ignore[arg-type]
        ),
        lambda _chunk: "checkout payment orchestration",
    )

    result = asyncio.run(
        retriever.search_project_memory(
            SimpleNamespace(project_id="project_001"),  # type: ignore[arg-type]
            "checkout payment",
        )
    )

    assert {hit.ref for hit in result.hits} >= {
        "context_object:object_checkout",
        "raw_asset_chunk:chunk_checkout",
        "agent_memory:memory_001",
    }


def test_ingestion_projection_receives_lock_factory_instead_of_store() -> None:
    lock = RLock()
    workspace = Mock()
    read_model_refresh = Mock()
    projection = CompatibilitySystemImageIngestionProjection(
        lambda project_id: lock,
        workspace,
        read_model_refresh,
    )

    with projection.mutation_guard("project_001"):
        projection.clear_chunks("project_001")
        projection.refresh("project_001")

    workspace.replace_raw_asset_chunks.assert_called_once_with("project_001", [])
    read_model_refresh.refresh_system_image.assert_called_once_with("project_001")
