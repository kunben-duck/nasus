from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Union

from .release_readiness import meets_release_review_threshold


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
    status: str
    score: int
    blockers: int
    approvals_open: int
    pending_merge: int
    execution_health: str
    summary: str
    evidence_summary: dict[str, int]


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


def _generation_inventory_metrics(*fields: tuple[str, MetricValue]) -> tuple[tuple[str, MetricValue], ...]:
    # Actual counts are supplied by the validated generation output, not a template.
    return (
        ("measurement_basis", "generated_draft_inventory_not_quality_assessment"),
        ("coverage_status", "unknown"),
        ("asset_lane_status", "ready_for_review"),
        *fields,
    )


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
                    "Draft scope proposes core path, regression, integration, failure, and observability "
                    "targets for independent review. Coverage has not been measured."
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
            metrics=_generation_inventory_metrics(("quality_context_required", True)),
            evidence_refs=("scope_pack:current", f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="scope_pack",
            status="ready_for_review",
            title="Test scope pack",
            summary=(
                "Draft scope targets are proposed from system image context and require independent review."
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
                status="ready_for_review",
                summary=(
                    "Generated scenario groups propose happy path, fallback, risk edge, data validation, "
                    "and observability checks; independent review and coverage assessment remain required."
                ),
            ),
            QualityStepLaneUpdate(
                lane_key="verification",
                status="ready_for_review",
                summary="A verification plan can be drafted from the generated scenarios; they are not yet approved.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=42,
            status="scenario_ready",
            next_action="Generate verification plan",
        ),
        metric_update=QualityStepMetricUpdate(
            step="scenarios",
            metrics=_generation_inventory_metrics(),
            evidence_refs=("scenario_set:current", f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="scenario_set",
            status="ready_for_review",
            title="Scenario coverage pack",
            summary="Generated scenario groups remain drafts; independent review does not follow from generation.",
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
                status="ready_for_review",
                summary=(
                    "Verification priorities, environment and data requirements, execution allocation, "
                    "performance checks, and approval points are proposed for independent review."
                ),
            ),
            QualityStepLaneUpdate(
                lane_key="cases",
                status="ready_for_review",
                summary="Cases can be drafted from the generated verification plan; the plan is not yet approved.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=50,
            status="verification_plan_ready",
            next_action="Generate test cases",
        ),
        metric_update=QualityStepMetricUpdate(
            step="verification_plan",
            metrics=_generation_inventory_metrics(),
            evidence_refs=("verification_plan:current", "scenario_set:current", f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="verification_plan",
            status="ready_for_review",
            title="Verification plan",
            summary=(
                "Priorities, environments, data, manual/automation allocation, performance, and approval "
                "requirements are draft proposals, not independently approved verification authority."
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
                status="ready_for_review",
                summary="Generated cases include proposed steps and expectations; independent oracle and assertion review remain required.",
            ),
            QualityStepLaneUpdate(
                lane_key="automation",
                status="ready_for_review",
                summary="Automation blueprints can be drafted from generated cases; the cases are not yet approved.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=62,
            status="cases_ready",
            next_action="Generate automation",
        ),
        metric_update=QualityStepMetricUpdate(
            step="cases",
            metrics=_generation_inventory_metrics(),
            evidence_refs=(
                "case_set:current",
                "verification_plan:current",
                "scenario_set:current",
                f"us:{us_id}",
            ),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="case_set",
            status="ready_for_review",
            title="Structured test case pack",
            summary="Generated case drafts include preconditions, proposed assertions, test data hints, and regression tags.",
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
                    "Versioned Playwright blueprint drafts require independent review, fixed target "
                    "configuration and separate execution authorization."
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
            metrics=_generation_inventory_metrics(("execution_started", False)),
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
                status="ready_for_review",
                summary=(
                    "The requirement, code, system-image, quality-asset, risk, and evidence deltas are "
                    "proposed in a draft change document for independent review."
                ),
            ),
            QualityStepLaneUpdate(
                lane_key="release",
                status="ready_for_review",
                summary="Release assessment must verify independent quality and execution evidence; a generated document is not sufficient.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=88,
            status="change_document_ready",
            next_action="Assess release quality",
        ),
        metric_update=QualityStepMetricUpdate(
            step="change_document",
            metrics=_generation_inventory_metrics(),
            evidence_refs=("change_document:current", "quality_asset_pack:current", f"us:{us_id}"),
        ),
        asset_part_update=QualityStepAssetPartUpdate(
            part_type="change_document",
            status="ready_for_review",
            title="Quality change document",
            summary=(
                "A draft change record proposes links between requirement, system-image, generated quality "
                "assets, risks, and available evidence; independent review remains required."
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
                ("measurement_basis", "runner_observation_not_quality_assessment"),
                ("coverage_status", "unknown"),
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
    blocked = not meets_release_review_threshold(release)
    return QualityStepPlan(
        step="release",
        summary="Assessed release readiness",
        object_refs=(readiness_ref,),
        lane_updates=(
            QualityStepLaneUpdate(
                lane_key="release",
                status="blocked" if blocked else "completed",
                summary=release.summary if blocked else "Release readiness score is complete. Formal ReleaseDecision still requires approval.",
            ),
        ),
        us_update=QualityStepUSUpdate(
            progress=70 if blocked else 92,
            status="blocked" if blocked else "release_ready",
            next_action="Resolve release evidence gaps" if blocked else "Request release approval",
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
            status="blocked" if blocked else "completed",
            title="Release readiness assessment",
            summary=release.summary,
            object_refs=(readiness_ref,),
            evidence_refs=release_evidence_refs,
        ),
        next_tools=(("query.version.status", "query.governance.status") if blocked else
            ("approval.request", "query.version.status", "query.governance.status")),
    )
