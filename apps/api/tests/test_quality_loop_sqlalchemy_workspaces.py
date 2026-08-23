from __future__ import annotations

from uuid import uuid4

from apps.api.app.application.agent.agent_models import ConversationSession
from apps.api.app.application.platform.project_models import ProjectCard, VersionSummary
from apps.api.app.application.quality_loop.quality_models import (
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    RunDetail,
    USItem,
)
from apps.api.app.application.quality_loop.asset_progress import (
    QualityAssetProgressApplicationService,
)
from apps.api.app.application.system_image.system_image_models import (
    QualityProfile,
    TaskContext,
)
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.quality_loop_repository import (
    QualityLoopRepository,
)
from apps.api.app.infrastructure.persistence.project_repository import ProjectRepository
from apps.api.app.infrastructure.persistence.system_image_repository import (
    SystemImageRepository,
)
from apps.api.app.infrastructure.quality_loop import (
    SQLAlchemyProjectVersionWorkspace,
    SQLAlchemyQualityAssetPackWorkspace,
    SQLAlchemyQualityAssetProgressWorkspace,
    SQLAlchemyQualityFailureWorkspace,
    SQLAlchemyQualityLoopContextWorkspace,
    SQLAlchemyQualityLoopScopeWorkspace,
    SQLAlchemyQualityRunWorkspace,
)


def _run(run_id: str, *, status: str = "passed") -> RunDetail:
    return RunDetail(
        id=run_id,
        status=status,
        channel="web_runner",
        title=f"Run {run_id}",
        summary=f"{status} summary",
        started_at="2026-08-09T00:00:00+00:00",
        failure_summary="assertion failed" if status == "failed" else "",
        healing_status="not_started" if status == "failed" else "not_required",
    )


def _evidence(
    evidence_id: str,
    *,
    project_id: str,
    run_id: str,
    us_id: str,
) -> ExecutionEvidence:
    return ExecutionEvidence(
        id=evidence_id,
        project_id=project_id,
        run_id=run_id,
        us_id=us_id,
        evidence_type="report",
        storage_ref=f"s3://nasus-artifacts/{evidence_id}.json",
        content_hash=f"sha256:{evidence_id}",
        producer="web_runner",
        captured_at="2026-08-09T00:01:00+00:00",
    )


def _failure(
    report_id: str,
    *,
    project_id: str,
    run_id: str,
    us_id: str,
) -> FailureReport:
    return FailureReport(
        id=report_id,
        project_id=project_id,
        run_id=run_id,
        us_id=us_id,
        failure_kind="assertion",
        failure_fingerprint=f"fingerprint:{report_id}",
        summary="Assertion failed.",
        root_cause="Expected output did not match.",
        status="under_review",
        created_at="2026-08-09T00:02:00+00:00",
    )


def test_run_workspace_persists_only_target_run_and_evidence() -> None:
    init_database()
    suffix = uuid4().hex
    project_id = f"project_run_workspace_{suffix}"
    us_id = f"us_run_workspace_{suffix}"
    repository = QualityLoopRepository()
    repository.replace_us_items(
        project_id,
        None,
        [
            USItem(
                id=us_id,
                title="Checkout reliability",
                owner="QA",
                status="in_progress",
                risk="high",
                progress=50,
                next_action="Run automation",
            )
        ],
    )
    workspace = SQLAlchemyQualityRunWorkspace(repository)
    peer_run = _run(f"run_peer_{suffix}")
    target_run = _run(f"run_target_{suffix}")
    repository.upsert_run_detail(project_id, peer_run)

    assert workspace.us_title(project_id, us_id) == "Checkout reliability"
    workspace.save_run_detail(project_id, target_run)
    peer_evidence = _evidence(
        f"evidence_peer_{suffix}",
        project_id=project_id,
        run_id=peer_run.id,
        us_id=us_id,
    )
    target_evidence = _evidence(
        f"evidence_target_{suffix}",
        project_id=project_id,
        run_id=target_run.id,
        us_id=us_id,
    )
    repository.replace_execution_evidence_for_run(
        project_id,
        peer_run.id,
        [peer_evidence],
    )
    workspace.replace_run_evidence(project_id, target_run.id, [target_evidence])

    assert {item.id for item in repository.list_run_details(project_id)} == {
        peer_run.id,
        target_run.id,
    }
    assert {
        item.id for item in repository.list_execution_evidence(project_id)
    } == {peer_evidence.id, target_evidence.id}

    replacement = target_evidence.model_copy(
        update={
            "id": f"evidence_target_replacement_{suffix}",
            "content_hash": "sha256:replacement",
        }
    )
    workspace.replace_run_evidence(project_id, target_run.id, [replacement])
    assert {
        item.id for item in repository.list_execution_evidence(project_id)
    } == {peer_evidence.id, replacement.id}


def test_failure_workspace_upserts_without_deleting_peer_facts() -> None:
    init_database()
    suffix = uuid4().hex
    project_id = f"project_failure_workspace_{suffix}"
    us_id = f"us_failure_workspace_{suffix}"
    repository = QualityLoopRepository()
    workspace = SQLAlchemyQualityFailureWorkspace(repository)
    peer_run = _run(f"run_failure_peer_{suffix}", status="failed")
    peer_report = _failure(
        f"failure_peer_{suffix}",
        project_id=project_id,
        run_id=peer_run.id,
        us_id=us_id,
    )
    repository.upsert_failure_analysis(
        project_id,
        peer_run,
        [peer_report],
    )

    target_run = _run(f"run_failure_target_{suffix}", status="failed")
    target_report = _failure(
        f"failure_target_{suffix}",
        project_id=project_id,
        run_id=target_run.id,
        us_id=us_id,
    )
    workspace.save_failure_analysis(project_id, target_run, [target_report])

    assert {item.id for item in repository.list_run_details(project_id)} == {
        peer_run.id,
        target_run.id,
    }
    assert {item.id for item in workspace.list_failure_reports(project_id)} == {
        peer_report.id,
        target_report.id,
    }


def test_scope_workspace_resolves_durable_conversation_run_and_evidence() -> None:
    init_database()
    suffix = uuid4().hex
    project_id = f"project_scope_workspace_{suffix}"
    us_id = f"us_scope_workspace_{suffix}"
    run_id = f"run_scope_workspace_{suffix}"
    conversation_id = f"conversation_scope_workspace_{suffix}"
    quality_loop = QualityLoopRepository()
    conversations = ConversationRepository()
    quality_loop.replace_us_items(
        project_id,
        None,
        [
            USItem(
                id=us_id,
                title="Durable scope",
                owner="QA",
                status="in_progress",
                risk="medium",
                progress=40,
                next_action="Inspect run",
            )
        ],
    )
    quality_loop.upsert_run_detail(project_id, _run(run_id, status="failed"))
    quality_loop.replace_execution_evidence_for_run(
        project_id,
        run_id,
        [
            _evidence(
                f"evidence_scope_workspace_{suffix}",
                project_id=project_id,
                run_id=run_id,
                us_id=us_id,
            )
        ],
    )
    conversations.upsert_conversation(
        ConversationSession(
            id=conversation_id,
            session_id=f"session_{suffix}",
            title="Quality workspace",
            space_type="workspace",
            space_id=us_id,
            project_id=project_id,
            us_id=us_id,
            status="active",
        )
    )
    workspace = SQLAlchemyQualityLoopScopeWorkspace(
        quality_loop,
        conversations,
    )

    scope = workspace.conversation_scope(conversation_id)
    assert scope is not None
    assert scope.project_id == project_id
    assert scope.us_id == us_id
    assert workspace.project_id_for_us(us_id) == project_id
    assert workspace.first_us_id(project_id) == us_id
    assert workspace.project_id_for_run(run_id) == project_id
    assert workspace.list_run_details(project_id)[0].id == run_id
    assert workspace.us_id_for_run_evidence(project_id, run_id) == us_id


def test_asset_progress_workspace_updates_only_target_entities() -> None:
    init_database()
    suffix = uuid4().hex
    project_id = f"project_asset_progress_{suffix}"
    version_id = f"version_asset_progress_{suffix}"
    target_us_id = f"us_asset_progress_target_{suffix}"
    peer_us_id = f"us_asset_progress_peer_{suffix}"
    repository = QualityLoopRepository()
    repository.replace_us_items(
        project_id,
        version_id,
        [
            USItem(
                id=target_us_id,
                title="Target story",
                owner="QA",
                status="analysis",
                risk="high",
                progress=10,
                next_action="Generate scope",
            ),
            USItem(
                id=peer_us_id,
                title="Peer story",
                owner="QA",
                status="approved",
                risk="low",
                progress=90,
                next_action="Release",
            ),
        ],
    )
    peer_lane = AssetLane(
        id=f"lane_peer_{suffix}",
        label="Peer Lane",
        status="approved",
        summary="Peer facts must survive.",
        updated_at="2026-08-09T00:00:00+00:00",
    )
    repository.ensure_asset_lanes(
        project_id,
        peer_us_id,
        [peer_lane],
    )
    workspace = SQLAlchemyQualityAssetProgressWorkspace(repository)
    service = QualityAssetProgressApplicationService(workspace)

    service.ensure_asset_lanes(project_id, target_us_id)
    service.update_lane(
        project_id,
        target_us_id,
        "scenarios",
        status="ready_for_review",
        summary="Target scenarios generated.",
    )
    service.touch_us(
        project_id,
        target_us_id,
        progress=55,
        status="scenario_generation",
        next_action="Review scenarios",
    )

    target = repository.get_us_item_for_project(project_id, target_us_id)
    peer = repository.get_us_item_for_project(project_id, peer_us_id)
    assert target is not None and target.progress == 55
    assert target.status == "scenario_generation"
    assert peer is not None and peer.progress == 90
    assert repository.version_id_for_us(project_id, target_us_id) == version_id
    assert repository.list_asset_lanes_for_us(peer_us_id) == [peer_lane]
    assert any(
        lane.status == "ready_for_review"
        for lane in repository.list_asset_lanes_for_us(target_us_id)
    )


def test_asset_pack_and_context_workspaces_read_canonical_repositories() -> None:
    init_database()
    suffix = uuid4().hex
    project_id = f"project_quality_context_{suffix}"
    us_id = f"us_quality_context_{suffix}"
    quality_loop = QualityLoopRepository()
    system_image = SystemImageRepository()
    quality_loop.replace_us_items(
        project_id,
        None,
        [
            USItem(
                id=us_id,
                title="Canonical quality context",
                owner="QA",
                status="analysis",
                risk="medium",
                progress=20,
                next_action="Build context",
            )
        ],
    )
    task_context = TaskContext(
        id=f"task_context_{suffix}",
        project_id=project_id,
        baseline_id=f"baseline_{suffix}",
        us_id=us_id,
        retrieval_run_id=f"retrieval_{suffix}",
        summary="Durable task context.",
        readiness="ready",
        freshness_at="2026-08-09T00:00:00+00:00",
        context_hash=f"hash_{suffix}",
    )
    quality_profile = QualityProfile(
        id=f"quality_profile_{suffix}",
        project_id=project_id,
        baseline_id=f"baseline_{suffix}",
        us_id=us_id,
        task_context_id=task_context.id,
        risk_score=70,
        coverage_score=60,
        release_score=50,
        automation_feasibility=80,
        freshness_at="2026-08-09T00:00:00+00:00",
    )
    system_image.replace_system_image(
        project_id,
        sources=[],
        chunks=[],
        baselines=[],
        relationships=[],
        overlays=[],
        metric_snapshots=[],
        embedding_records=[],
        retrieval_runs=[],
        rerank_records=[],
        task_contexts=[task_context],
        quality_profiles=[quality_profile],
    )
    pack = QualityAssetPack(
        id=f"qap_{project_id}_{us_id}",
        project_id=project_id,
        us_id=us_id,
        updated_at="2026-08-09T00:01:00+00:00",
    )
    pack_workspace = SQLAlchemyQualityAssetPackWorkspace(quality_loop)
    pack_workspace.save_quality_asset_pack(pack)
    context_workspace = SQLAlchemyQualityLoopContextWorkspace(
        system_image,
        quality_loop,
    )

    assert pack_workspace.get_quality_asset_pack(project_id, us_id) == pack
    assert context_workspace.list_task_contexts(project_id) == [task_context]
    assert context_workspace.list_quality_profiles(project_id) == [quality_profile]
    assert context_workspace.get_quality_asset_pack(project_id, us_id) == pack
    assert context_workspace.project_id_for_us(us_id) == project_id


def test_project_version_workspace_uses_durable_entity_grained_writes() -> None:
    init_database()
    suffix = uuid4().hex
    project_id = f"project_version_workspace_{suffix}"
    quality_loop = QualityLoopRepository()
    projects = ProjectRepository(quality_loop_repository=quality_loop)
    system_image = SystemImageRepository()
    conversations = ConversationRepository()
    system_image_calls: list[tuple[str, bool]] = []
    creator_grants: list[str] = []

    def get_or_create_conversation(
        space_type: str,
        space_id: str,
        title: str,
    ) -> ConversationSession:
        conversation = ConversationSession(
            id=f"conversation_{space_id}",
            session_id=f"session_{space_id}",
            title=title,
            space_type=space_type,
            space_id=space_id,
            project_id=space_id,
            status="active",
        )
        conversations.upsert_conversation(conversation)
        return conversation

    workspace = SQLAlchemyProjectVersionWorkspace(
        projects,
        quality_loop,
        system_image,
        conversations,
        lambda value, *, ready: system_image_calls.append((value, ready)),
        creator_grants.append,
        get_or_create_conversation,
    )
    project = ProjectCard(
        id=project_id,
        name="Durable project",
        code="DUR",
        summary="Durable project/version workspace.",
        status="draft",
        risk="low",
        progress=12,
        active_version="Not started",
        blocked_items=0,
        pending_approvals=0,
        system_image_status="draft",
    )
    workspace.initialize_project(project)
    first = VersionSummary(
        id=f"version_first_{suffix}",
        name="2026.08",
        status="draft",
        branch_name="release/2026.08",
        us_total=0,
        us_closed=0,
        pending_runs=0,
        pending_approvals=0,
    )
    second = first.model_copy(
        update={
            "id": f"version_second_{suffix}",
            "name": "2026.09",
            "branch_name": "release/2026.09",
        }
    )
    workspace.prepend_version(project_id, first)
    workspace.prepend_version(project_id, second)
    workspace.save_version(
        project_id,
        first.model_copy(update={"status": "active"}),
    )
    target_us = USItem(
        id=f"us_target_{suffix}",
        title="Target story",
        owner="QA",
        status="analysis",
        risk="medium",
        progress=20,
        next_action="Review",
    )
    peer_us = target_us.model_copy(
        update={"id": f"us_peer_{suffix}", "title": "Peer story"}
    )
    workspace.save_us_items(project_id, second.id, [target_us, peer_us])
    workspace.save_us_item(
        project_id,
        second.id,
        target_us.model_copy(update={"progress": 60}),
    )

    assert workspace.has_project(project_id)
    assert workspace.get_project(project_id) == project
    assert [item.id for item in workspace.list_versions(project_id)] == [
        second.id,
        first.id,
    ]
    assert workspace.list_versions(project_id)[1].status == "active"
    assert {
        item.id: item.progress
        for item in workspace.list_us_items(project_id, second.id)
    } == {target_us.id: 60, peer_us.id: 20}
    assert workspace.conversation_project_id(f"conversation_{project_id}") == project_id
    assert system_image_calls == [(project_id, False)]
    assert creator_grants == [project_id]
