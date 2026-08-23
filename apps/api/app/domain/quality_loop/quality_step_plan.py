from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Union


MetricValue = Union[str, int, float, bool, None]
SUPPORTED_DETERMINISTIC_QUALITY_STEPS = (
    "scope",
    "scenarios",
    "verification_plan",
    "cases",
    "automation",
    "change_document",
)


class AutomationRunLike(Protocol):
    id: str
    status: str
    task_context_id: Optional[str]
    runner_job_id: Optional[str]
    evidence: list[str]


class ReleaseReadinessLike(Protocol):
    version_id: str
    score: int
    blockers: int
    approvals_open: int
    pending_merge: int
    execution_health: str
    summary: str


@dataclass(frozen=True)
class QualityStepLaneUpdate:
    lane_key: str
    status: str
    summary: str


@dataclass(frozen=True)
class QualityStepUSUpdate:
    progress: int
    status: str
    next_action: str


@dataclass(frozen=True)
class QualityStepMetricUpdate:
    step: str
    metrics: tuple[tuple[str, MetricValue], ...]
    evidence_refs: tuple[str, ...]

    def metric_dict(self) -> dict[str, MetricValue]:
        return dict(self.metrics)


@dataclass(frozen=True)
class QualityStepAssetPartUpdate:
    part_type: str
    status: str
    title: str
    summary: str
    object_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class QualityStepPlan:
    step: str
    summary: str
    object_refs: tuple[str, ...]
    lane_updates: tuple[QualityStepLaneUpdate, ...]
    us_update: QualityStepUSUpdate
    metric_update: QualityStepMetricUpdate
    asset_part_update: QualityStepAssetPartUpdate
    next_tools: tuple[str, ...]
    requires_failure_report: bool = False


def deterministic_quality_step_plan(step: str, *, us_id: str) -> QualityStepPlan | None:
    if step == "scope":
        return scope_quality_step_plan(us_id=us_id)
    if step == "scenarios":
        return scenario_quality_step_plan(us_id=us_id)
    if step == "verification_plan":
        return verification_plan_quality_step_plan(us_id=us_id)
    if step == "cases":
        return case_quality_step_plan(us_id=us_id)
    if step == "automation":
        return automation_generation_quality_step_plan(us_id=us_id)
    if step == "change_document":
        return change_document_quality_step_plan(us_id=us_id)
    return None


def scope_quality_step_plan(*, us_id: str) -> QualityStepPlan:
    return QualityStepPlan(
        step="scope",
        summary="Generated test scope",
        object_refs=("scope_pack:current",),
        lane_updates=(
            QualityStepLaneUpdate(
                lane_key="scenarios",
                status="ready_for_review",
                summary=(
                    "Test scope is ready: core path, regression, integration, failure, and observability "
                    "coverage are identified."
                ),
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=32,
            status="scope_ready",
            next_action="Generate scenarios",
        ),
        metric_update=QualityStepMetricUpdate(
            step="scope",
            metrics=(
                ("scope_items", 5),
                ("regression_focus", 0.76),
                ("quality_context_required", True),
                ("asset_lane_status", "ready_for_review"),
            ),
            evidence_refs=("scope_pack:current", f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="scope_pack",
            status="ready_for_review",
            title="Test scope pack",
            summary=(
                "Core path, regression, integration, failure, and observability coverage are identified "
                "from system image context."
            ),
            object_refs=("scope_pack:current",),
            evidence_refs=("scope_pack:current", f"us:{us_id}"),
        ),
        next_tools=("quality.scenario.generate",),
    )


def scenario_quality_step_plan(*, us_id: str) -> QualityStepPlan:
    return QualityStepPlan(
        step="scenarios",
        summary="Generated scenario pack",
        object_refs=("scenario_set:current",),
        lane_updates=(
            QualityStepLaneUpdate(
                lane_key="scenarios",
                status="approved",
                summary=(
                    "8 scenario groups cover happy path, fallback, risk edge, data validation, "
                    "and observability checks."
                ),
            ),
            QualityStepLaneUpdate(
                lane_key="verification",
                status="ready_for_review",
                summary="Verification planning is ready from the approved scenario structure.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=42,
            status="scenario_ready",
            next_action="Generate verification plan",
        ),
        metric_update=QualityStepMetricUpdate(
            step="scenarios",
            metrics=(
                ("scenario_groups", 8),
                ("scenario_coverage", 0.82),
                ("risk_edge_groups", 2),
                ("asset_lane_status", "approved"),
            ),
            evidence_refs=("scenario_set:current", f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="scenario_set",
            status="approved",
            title="Scenario coverage pack",
            summary="8 scenario groups cover happy path, fallback, risk edge, data validation, and observability checks.",
            object_refs=("scenario_set:current",),
            evidence_refs=("scenario_set:current", f"us:{us_id}"),
        ),
        next_tools=("quality.plan.generate",),
    )


def verification_plan_quality_step_plan(*, us_id: str) -> QualityStepPlan:
    return QualityStepPlan(
        step="verification_plan",
        summary="Generated verification plan",
        object_refs=("verification_plan:current",),
        lane_updates=(
            QualityStepLaneUpdate(
                lane_key="verification",
                status="approved",
                summary=(
                    "Verification priorities, environment and data requirements, execution allocation, "
                    "performance checks, and approval points are defined."
                ),
            ),
            QualityStepLaneUpdate(
                lane_key="cases",
                status="ready_for_review",
                summary="Case generation is ready from the approved verification plan.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=50,
            status="verification_plan_ready",
            next_action="Generate test cases",
        ),
        metric_update=QualityStepMetricUpdate(
            step="verification_plan",
            metrics=(
                ("verification_priorities", 2),
                ("execution_allocations", 2),
                ("approval_points", 1),
                ("asset_lane_status", "approved"),
            ),
            evidence_refs=("verification_plan:current", "scenario_set:current", f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="verification_plan",
            status="approved",
            title="Verification plan",
            summary=(
                "Priorities, environments, data, manual/automation allocation, performance, and approval "
                "requirements are traceable to approved scenarios."
            ),
            object_refs=("verification_plan:current", "scenario_set:current"),
            evidence_refs=("verification_plan:current", "scenario_set:current", f"us:{us_id}"),
        ),
        next_tools=("quality.case.generate",),
    )


def case_quality_step_plan(*, us_id: str) -> QualityStepPlan:
    return QualityStepPlan(
        step="cases",
        summary="Generated test case pack",
        object_refs=("case_set:current",),
        lane_updates=(
            QualityStepLaneUpdate(
                lane_key="cases",
                status="approved",
                summary="14 structured cases with preconditions, assertions, data hints, and regression tags are approved.",
            ),
            QualityStepLaneUpdate(
                lane_key="automation",
                status="ready_for_review",
                summary="Automation script generation is ready from the approved cases.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=62,
            status="cases_ready",
            next_action="Generate automation",
        ),
        metric_update=QualityStepMetricUpdate(
            step="cases",
            metrics=(
                ("test_cases", 14),
                ("assertion_coverage", 0.8),
                ("regression_tags", 5),
                ("asset_lane_status", "approved"),
            ),
            evidence_refs=(
                "case_set:current",
                "verification_plan:current",
                "scenario_set:current",
                f"us:{us_id}",
            ),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="case_set",
            status="approved",
            title="Structured test case pack",
            summary="14 structured cases include preconditions, assertions, test data hints, and regression tags.",
            object_refs=("case_set:current", "verification_plan:current", "scenario_set:current"),
            evidence_refs=(
                "case_set:current",
                "verification_plan:current",
                "scenario_set:current",
                f"us:{us_id}",
            ),
        ),
        next_tools=("automation.generate",),
    )


def automation_generation_quality_step_plan(*, us_id: str) -> QualityStepPlan:
    return QualityStepPlan(
        step="automation",
        summary="Generated reviewable Playwright automation blueprint",
        object_refs=("automation_asset:current",),
        lane_updates=(
            QualityStepLaneUpdate(
                lane_key="automation",
                status="ready_for_review",
                summary=(
                    "Versioned Playwright scripts were generated from approved cases and are ready "
                    "for target configuration and execution."
                ),
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=70,
            status="automation_ready",
            next_action="Start automation run",
        ),
        metric_update=QualityStepMetricUpdate(
            step="automation",
            metrics=(
                ("automation_scripts", 1),
                ("asset_lane_status", "ready_for_review"),
                ("execution_started", False),
            ),
            evidence_refs=("automation_asset:current", "case_set:current", f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="automation_blueprint",
            status="ready_for_review",
            title="Playwright automation blueprint",
            summary=(
                "Reviewable Playwright scripts include linked case identifiers, selector strategy, "
                "fixture hints, and validated runner steps."
            ),
            object_refs=("automation_asset:current", "case_set:current"),
            evidence_refs=("case_set:current", f"us:{us_id}"),
        ),
        next_tools=("run.start",),
    )


def change_document_quality_step_plan(*, us_id: str) -> QualityStepPlan:
    return QualityStepPlan(
        step="change_document",
        summary="Generated quality change document",
        object_refs=("change_document:current",),
        lane_updates=(
            QualityStepLaneUpdate(
                lane_key="change_document",
                status="completed",
                summary=(
                    "The requirement, code, system-image, quality-asset, risk, and evidence deltas are "
                    "consolidated in a traceable change document."
                ),
            ),
            QualityStepLaneUpdate(
                lane_key="release",
                status="ready_for_review",
                summary="The change record and execution evidence are ready for release readiness scoring.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=88,
            status="change_document_ready",
            next_action="Assess release quality",
        ),
        metric_update=QualityStepMetricUpdate(
            step="change_document",
            metrics=(
                ("change_deltas", 2),
                ("change_risks", 1),
                ("asset_lane_status", "completed"),
            ),
            evidence_refs=("change_document:current", "quality_asset_pack:current", f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="change_document",
            status="completed",
            title="Quality change document",
            summary=(
                "A release-facing change record links requirement, system-image, generated quality assets, "
                "risks, and execution evidence."
            ),
            object_refs=("change_document:current", "quality_asset_pack:current"),
            evidence_refs=("change_document:current", "quality_asset_pack:current", f"us:{us_id}"),
        ),
        next_tools=("release.assess",),
    )


def automation_quality_step_plan(
    *,
    run: AutomationRunLike,
    failed: bool,
    runner_mode: str,
    execution_evidence_refs: tuple[str, ...],
    automation_asset_ref: str = "automation_asset:current",
) -> QualityStepPlan:
    if failed:
        lane_updates = (
            QualityStepLaneUpdate(
                lane_key="automation",
                status="blocked",
                summary="Executed the generated automation and captured failed runner evidence for analysis.",
            ),
            QualityStepLaneUpdate(
                lane_key="release",
                status="blocked",
                summary="Release assessment is blocked until the failed run is reviewed or healed.",
            ),
        )
        us_update = QualityStepUSUpdate(
            progress=72,
            status="execution_failed",
            next_action="Analyze failed run",
        )
        summary = "Automation execution produced failed runner evidence"
        next_tools = ("healing.propose", "query.run.status")
        part_status = "blocked"
        part_summary = "The versioned automation asset produced failed evidence and opened a FailureReport."
    else:
        lane_updates = (
            QualityStepLaneUpdate(
                lane_key="automation",
                status="completed",
                summary="Executed the versioned Playwright automation asset and captured passing runner evidence.",
            ),
            QualityStepLaneUpdate(
                lane_key="change_document",
                status="ready_for_review",
                summary="Execution evidence is ready for the quality change document.",
            ),
        )
        us_update = QualityStepUSUpdate(
            progress=76,
            status="execution_ready",
            next_action="Generate quality change document",
        )
        summary = "Executed automation and captured passing evidence"
        next_tools = ("quality.change-doc.generate",)
        part_status = "completed"
        part_summary = "The versioned automation asset completed and has append-only execution evidence."

    run_ref = f"run:{run.id}"
    return QualityStepPlan(
        step="automation",
        summary=summary,
        object_refs=(automation_asset_ref, run_ref),
        lane_updates=lane_updates,
        us_update=us_update,
        metric_update=QualityStepMetricUpdate(
            step="automation",
            metrics=(
                ("automation_coverage", 0.74),
                ("latest_run_status", run.status),
                ("runner_mode", runner_mode),
                ("runner_job_id", run.runner_job_id),
                ("task_context_id", run.task_context_id),
                ("evidence_count", len(run.evidence)),
                ("healing_required", failed),
            ),
            evidence_refs=(run_ref, *execution_evidence_refs),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="automation_blueprint",
            status=part_status,
            title="Automation blueprint and smoke run",
            summary=part_summary,
            object_refs=(automation_asset_ref, run_ref),
            evidence_refs=execution_evidence_refs,
        ),
        next_tools=next_tools,
        requires_failure_report=failed,
    )


def release_quality_step_plan(
    *,
    us_id: str,
    release: ReleaseReadinessLike,
    release_evidence_refs: tuple[str, ...],
) -> QualityStepPlan:
    readiness_ref = f"release_readiness:{release.version_id}"
    return QualityStepPlan(
        step="release",
        summary="Assessed release readiness",
        object_refs=(readiness_ref,),
        lane_updates=(
            QualityStepLaneUpdate(
                lane_key="release",
                status="completed" if not release.blockers else "blocked",
                summary="Release readiness score is complete. Formal ReleaseDecision still requires approval.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=92,
            status="release_ready",
            next_action="Request release approval",
        ),
        metric_update=QualityStepMetricUpdate(
            step="release",
            metrics=(
                ("release_score", release.score),
                ("blockers", release.blockers),
                ("approvals_open", release.approvals_open),
                ("pending_merge", release.pending_merge),
                ("execution_health", release.execution_health),
            ),
            evidence_refs=(readiness_ref, *release_evidence_refs, f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="release_assessment",
            status="completed",
            title="Release readiness assessment",
            summary=release.summary,
            object_refs=(readiness_ref,),
            evidence_refs=release_evidence_refs,
        ),
        next_tools=("approval.request", "query.version.status", "query.governance.status"),
    )
