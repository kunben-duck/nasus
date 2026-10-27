from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from apps.api.app.application.quality_loop.quality_models import ReleaseReadiness
from apps.api.app.application.quality_loop.release_readiness import (
    QualityReleaseReadinessApplicationService,
)
from apps.api.app.application.quality_loop.release_readiness_port import (
    ReleaseReadinessSnapshot,
)
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import (
    ApprovalRecord,
    ExecutionEvidenceRecord,
    ProjectRecord,
    QualityAssetPackRecord,
    QualityProfileRecord,
    ReleaseReadinessRecord,
    RunRecord,
    TaskContextRecord,
    USWorkItemRecord,
)
from apps.api.app.infrastructure.persistence.release_readiness_repository import (
    SQLAlchemyReleaseReadinessRepository,
)


class FakeReleaseReadinessRepository:
    def __init__(self, snapshot: ReleaseReadinessSnapshot) -> None:
        self.snapshot = snapshot
        self.loaded_with: dict[str, str] | None = None
        self.saved_with: dict[str, object] | None = None

    def load_snapshot(
        self,
        *,
        project_id: str,
        us_id: str,
        version_id: str,
    ) -> ReleaseReadinessSnapshot:
        self.loaded_with = {
            "project_id": project_id,
            "us_id": us_id,
            "version_id": version_id,
        }
        return self.snapshot

    def save_assessment(
        self,
        *,
        project_id: str,
        readiness: ReleaseReadiness,
        progress_floor: int,
        blockers: int,
    ) -> None:
        self.saved_with = {
            "project_id": project_id,
            "readiness": readiness,
            "progress_floor": progress_floor,
            "blockers": blockers,
        }


@pytest.fixture
def isolated_session_factory():
    assert engine.dialect.name == "postgresql", "run persistence tests with scripts/test-api-postgres.py"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield sessionmaker(bind=connection, autoflush=False, autocommit=False,
                expire_on_commit=False, join_transaction_mode="create_savepoint")
        finally:
            transaction.rollback()


def test_release_readiness_application_uses_repository_snapshot_and_save_port() -> None:
    repository = FakeReleaseReadinessRepository(
        ReleaseReadinessSnapshot(
            version_id="ver_1",
            run_statuses=("passed",),
            evidence_types=("report", "trace"),
            asset_part_statuses=(
                ("scenario_set", "approved"),
                ("case_set", "approved"),
                ("automation_blueprint", "completed"),
            ),
            task_context_readiness="ready",
            task_context_confidence=0.95,
            quality_profile_coverage=90,
            quality_profile_confidence=0.9,
        )
    )
    service = QualityReleaseReadinessApplicationService(
        repository,
        lambda _project_id: SimpleNamespace(id="ver_1"),
    )

    result = service.upsert_release_readiness("proj_1", "us_1")

    assert repository.loaded_with == {
        "project_id": "proj_1",
        "us_id": "us_1",
        "version_id": "ver_1",
    }
    assert result.status == "Ready for release review"
    assert repository.saved_with is not None
    assert repository.saved_with["readiness"] == result
    assert repository.saved_with["progress_floor"] == 82
    assert repository.saved_with["blockers"] == 0


def test_inventory_context_cannot_supply_release_quality_evidence() -> None:
    repository = FakeReleaseReadinessRepository(ReleaseReadinessSnapshot(
        version_id="ver_1", run_statuses=("passed",), evidence_types=("report", "trace"),
        asset_part_statuses=(("scenario_set", "approved"), ("case_set", "approved"),
            ("automation_blueprint", "completed")), task_context_readiness="ready",
        task_context_confidence=None, quality_profile_coverage=None, quality_profile_confidence=None))
    service = QualityReleaseReadinessApplicationService(repository,
        lambda _: SimpleNamespace(id="ver_1"))
    result = service.upsert_release_readiness("proj_1", "us_1")
    assert result.status == "Needs additional release evidence"
    assert result.score <= 59 and result.blockers == 1
    assert result.blocker_items == [
        "System image quality assessment is unknown; retrieval inventory is not release evidence."]
    assert result.score_breakdown["system_context"] == 0
    assert result.evidence_summary["quality_assessment_unknown"] == 1
    assert repository.saved_with["readiness"] == result


def test_sqlalchemy_preserves_unknown_profile_and_context_values(isolated_session_factory) -> None:
    session_factory = isolated_session_factory
    with session_factory() as session:
        session.add(TaskContextRecord(id="unknown_ctx", project_id="unknown_project",
            baseline_id="base", us_id="unknown_us", retrieval_run_id="retrieval", summary="Inventory",
            readiness="ready", confidence=None, freshness_at="2026-10-10", context_hash="original"))
        session.add(QualityProfileRecord(id="unknown_profile", project_id="unknown_project",
            baseline_id="base", us_id="unknown_us", task_context_id="unknown_ctx", risk_score=None,
            coverage_score=None, release_score=None, automation_feasibility=None,
            confidence=None, freshness_at="2026-10-10"))
        session.commit()
    with session_factory() as session:
        profile = session.get(QualityProfileRecord, "unknown_profile")
        assert all(getattr(profile, name) is None for name in
            ("risk_score", "coverage_score", "release_score", "automation_feasibility", "confidence"))
        assert session.get(TaskContextRecord, "unknown_ctx").confidence is None
    snapshot = SQLAlchemyReleaseReadinessRepository(session_factory).load_snapshot(
        project_id="unknown_project", us_id="unknown_us", version_id="unknown_version")
    assert snapshot.task_context_readiness == "ready"
    assert snapshot.task_context_confidence is None
    assert snapshot.quality_profile_coverage is None and snapshot.quality_profile_confidence is None


def test_sqlalchemy_release_readiness_repository_loads_cross_context_snapshot(isolated_session_factory) -> None:
    session_factory = isolated_session_factory
    with session_factory() as session:
        session.add(
            ProjectRecord(
                id="proj_1",
                name="Payments",
                code="PAY",
                summary="Payment quality project",
                progress=10,
            )
        )
        session.add(
            USWorkItemRecord(
                id="us_1",
                project_id="proj_1",
                version_id="ver_1",
                title="Checkout",
                owner="QA",
                next_action="Review",
            )
        )
        session.add(
            RunRecord(
                id="run_1",
                project_id="proj_1",
                status="passed",
                channel="web_runner",
                title="Checkout run",
                summary="Passed",
                started_at="2026-07-30T00:00:00Z",
                failure_summary="",
                healing_status="not_started",
            )
        )
        session.add(
            ExecutionEvidenceRecord(
                id="evidence_1",
                project_id="proj_1",
                run_id="run_1",
                us_id="us_1",
                evidence_type="report",
                storage_ref="s3://evidence/report.json",
                content_hash="sha256:evidence",
                producer="web_runner",
                captured_at="2026-07-30T00:01:00Z",
            )
        )
        session.add(
            QualityAssetPackRecord(
                id="qap_proj_1_us_1",
                project_id="proj_1",
                version_id="ver_1",
                us_id="us_1",
                status="pending_merge",
                current_revision=3,
                parts=[
                    {
                        "part_type": "scenario_set",
                        "status": "approved",
                        "generation": {"mode": "live"},
                    },
                    {
                        "part_type": "case_set",
                        "status": "approved",
                        "generation": {"mode": "fallback"},
                    },
                ],
                updated_at="2026-07-30T00:02:00Z",
            )
        )
        session.add(
            TaskContextRecord(
                id="ctx_1",
                project_id="proj_1",
                baseline_id="baseline_1",
                version_id="ver_1",
                us_id="us_1",
                retrieval_run_id="retrieval_1",
                summary="Checkout context",
                readiness="ready",
                missing_context=["historical defect"],
                confidence=0.8,
                freshness_at="2026-07-30T00:03:00Z",
                context_hash="sha256:context",
            )
        )
        session.add(
            QualityProfileRecord(
                id="profile_1",
                project_id="proj_1",
                baseline_id="baseline_1",
                version_id="ver_1",
                us_id="us_1",
                task_context_id="ctx_1",
                risk_score=70,
                coverage_score=75,
                release_score=60,
                automation_feasibility=80,
                confidence=0.7,
                freshness_at="2026-07-30T00:04:00Z",
            )
        )
        session.add(
            ApprovalRecord(
                id="approval_1",
                project_id="proj_1",
                title="Release approval",
                status="waiting_approval",
                summary="Awaiting QA lead",
            )
        )
        session.add(
            ReleaseReadinessRecord(
                version_id="ver_1",
                project_id="proj_1",
                status="Draft",
                score=0,
                blockers=0,
                approvals_open=0,
                pending_merge=2,
                execution_health="No runs",
                summary="Draft",
            )
        )
        session.commit()

    repository = SQLAlchemyReleaseReadinessRepository(session_factory)
    snapshot = repository.load_snapshot(
        project_id="proj_1",
        us_id="us_1",
        version_id="ver_1",
    )

    assert snapshot.run_statuses == ("passed",)
    assert snapshot.evidence_types == ("report",)
    assert snapshot.task_context_readiness == "ready"
    assert snapshot.missing_context_count == 1
    assert snapshot.quality_profile_coverage == 75
    assert snapshot.fallback_generated_parts == 1
    assert snapshot.approvals_open == 1
    assert snapshot.pending_merge == 2


def test_sqlalchemy_release_readiness_repository_saves_assessment_atomically(isolated_session_factory) -> None:
    session_factory = isolated_session_factory
    with session_factory() as session:
        session.add(
            ProjectRecord(
                id="proj_1",
                name="Payments",
                code="PAY",
                summary="Payment quality project",
                progress=10,
            )
        )
        session.commit()

    repository = SQLAlchemyReleaseReadinessRepository(session_factory)
    readiness = ReleaseReadiness(
        version_id="ver_1",
        status="Needs additional release evidence",
        score=52,
        blockers=2,
        approvals_open=0,
        pending_merge=0,
        execution_health="No automation run has been recorded.",
        summary="More evidence is required.",
        blocker_items=["Missing run", "Missing assets"],
        score_breakdown={"execution": 0},
        evidence_summary={"runs": 0},
    )
    repository.save_assessment(
        project_id="proj_1",
        readiness=readiness,
        progress_floor=70,
        blockers=2,
    )

    with session_factory() as session:
        release_row = session.get(ReleaseReadinessRecord, "ver_1")
        project_row = session.get(ProjectRecord, "proj_1")
        assert release_row is not None
        assert release_row.score == 52
        assert release_row.blocker_items == ["Missing run", "Missing assets"]
        assert project_row is not None
        assert project_row.progress == 70
        assert project_row.blocked_items == 2
        assert project_row.risk == "high"

    failed_readiness = readiness.model_copy(update={"version_id": "ver_missing_project"})
    try:
        repository.save_assessment(
            project_id="missing_project",
            readiness=failed_readiness,
            progress_floor=70,
            blockers=2,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Missing projects must reject release-readiness writes")

    with session_factory() as session:
        assert session.scalar(
            select(ReleaseReadinessRecord).where(
                ReleaseReadinessRecord.version_id == "ver_missing_project"
            )
        ) is None
