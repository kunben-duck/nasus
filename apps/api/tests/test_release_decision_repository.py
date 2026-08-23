from __future__ import annotations

from uuid import uuid4

from apps.api.app.application.quality_loop.quality_models import ReleaseDecision
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.quality_loop_repository import (
    QualityLoopRepository,
)


def release_decision(
    *,
    decision_id: str,
    project_id: str,
    version_id: str,
    us_id: str,
    created_at: str,
    score: int,
) -> ReleaseDecision:
    return ReleaseDecision(
        id=decision_id,
        project_id=project_id,
        version_id=version_id,
        us_id=us_id,
        status="ready",
        score=score,
        rationale=f"Release score {score}.",
        evidence_refs=[f"evidence:{decision_id}"],
        created_at=created_at,
    )


def test_release_decision_repository_prefers_exact_scope_then_latest_project_fact() -> None:
    init_database()
    repository = QualityLoopRepository()
    suffix = uuid4().hex[:10]
    project_id = f"proj_release_query_{suffix}"
    exact = release_decision(
        decision_id=f"decision_exact_{suffix}",
        project_id=project_id,
        version_id="ver_1",
        us_id="US-1",
        created_at="2026-07-30T00:00:00+00:00",
        score=82,
    )
    latest = release_decision(
        decision_id=f"decision_latest_{suffix}",
        project_id=project_id,
        version_id="ver_2",
        us_id="US-2",
        created_at="2026-07-30T01:00:00+00:00",
        score=94,
    )
    repository.upsert_release_decision(exact)
    repository.upsert_release_decision(latest)

    assert repository.find_release_decision(
        project_id,
        us_id="US-1",
        version_id="ver_1",
    ) == exact
    assert repository.find_release_decision(project_id) == latest
