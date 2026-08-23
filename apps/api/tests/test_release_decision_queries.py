from __future__ import annotations

from dataclasses import dataclass, field

from apps.api.app.application.quality_loop.quality_models import ReleaseDecision
from apps.api.app.application.quality_loop.release_decision_queries import (
    QualityLoopReleaseDecisionQueryApplicationService,
)


@dataclass
class InMemoryReleaseDecisionReader:
    decisions: dict[tuple[str, str | None, str | None], ReleaseDecision] = (
        field(default_factory=dict)
    )
    calls: list[tuple[str, str | None, str | None]] = field(
        default_factory=list
    )

    def find_release_decision(
        self,
        project_id: str,
        us_id: str | None = None,
        version_id: str | None = None,
    ) -> ReleaseDecision | None:
        key = (project_id, us_id, version_id)
        self.calls.append(key)
        return self.decisions.get(key)


def decision() -> ReleaseDecision:
    return ReleaseDecision(
        id="release_decision_proj_a_ver_a_US-A1",
        project_id="proj_a",
        version_id="ver_a",
        us_id="US-A1",
        status="ready",
        score=92,
        rationale="Quality evidence satisfies the release policy.",
        evidence_refs=["evidence:run_a"],
        created_at="2026-07-30T00:00:00+00:00",
    )


def test_release_decision_query_delegates_to_durable_read_port() -> None:
    expected = decision()
    reader = InMemoryReleaseDecisionReader(
        decisions={
            ("proj_a", "US-A1", "ver_a"): expected,
        }
    )
    service = QualityLoopReleaseDecisionQueryApplicationService(reader)

    actual = service.current_release_decision(
        "proj_a",
        us_id="US-A1",
        version_id="ver_a",
    )

    assert actual == expected
    assert reader.calls == [("proj_a", "US-A1", "ver_a")]


def test_release_decision_query_returns_none_when_no_durable_fact_exists() -> None:
    reader = InMemoryReleaseDecisionReader()
    service = QualityLoopReleaseDecisionQueryApplicationService(reader)

    assert service.current_release_decision("proj_missing") is None
    assert reader.calls == [("proj_missing", None, None)]
