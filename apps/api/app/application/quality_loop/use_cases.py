from __future__ import annotations

from dataclasses import replace

from .asset_packs import QualityAssetPackApplicationService
from .asset_progress import QualityAssetProgressApplicationService
from .context_queries import QualityLoopContextQueryApplicationService
from .failure_reports import QualityFailureReportApplicationService
from .quality_models import RunDetail
from .quality_image_updates import QualityImageUpdateApplicationService
from .quality_steps import QualityStepCompletionApplicationService
from .release_readiness import QualityReleaseReadinessApplicationService
from .results import QualityLoopApplicationError, QualityLoopUseCaseResult
from .run_execution import (
    QualityRunExecutionApplicationService,
    QualityRunExecutionResult,
)
from .scope_queries import QualityLoopScopeQueryApplicationService
from .version_context import QualityLoopVersionContextApplicationService
from ..platform.read_model_refresh import ProjectReadModelRefreshApplicationService
from ..platform.tool_models import ToolInvocation
from ...domain.quality_loop.failure_loop_progress import decide_failure_loop_progress
from ...domain.quality_loop.quality_step_plan import automation_quality_step_plan


class QualityLoopApplicationService:
    """Quality-loop write-side use cases.

    This service owns state transitions for run execution, failure analysis,
    release advice, and quality asset pack refresh. Tool handlers should only
    translate ToolInvocation runtime events around these use cases.
    """

    def __init__(
        self,
        *,
        read_model_refresh: ProjectReadModelRefreshApplicationService,
        context_queries: QualityLoopContextQueryApplicationService,
        scope_queries: QualityLoopScopeQueryApplicationService,
        version_context: QualityLoopVersionContextApplicationService,
        asset_progress: QualityAssetProgressApplicationService,
        asset_packs: QualityAssetPackApplicationService,
        run_execution: QualityRunExecutionApplicationService,
        failure_reports: QualityFailureReportApplicationService,
        release_readiness: QualityReleaseReadinessApplicationService,
        quality_image_updates: QualityImageUpdateApplicationService,
        quality_steps: QualityStepCompletionApplicationService,
        max_healing_depth: int = 2,
    ) -> None:
        self.read_model_refresh = read_model_refresh
        self.context_queries = context_queries
        self.scope_queries = scope_queries
        self.version_context = version_context
        self.asset_progress = asset_progress
        self.asset_packs = asset_packs
        self.max_healing_depth = max_healing_depth
        self.failure_reports = failure_reports
        self.release_readiness = release_readiness
        self.quality_image_updates = quality_image_updates
        self.run_execution = run_execution
        self.quality_steps = quality_steps

    def refresh_asset_pack(self, invocation: ToolInvocation) -> QualityLoopUseCaseResult | None:
        scope = self.resolve_scope(invocation)
        if scope is None:
            return None
        project_id, us_id = scope
        self.asset_progress.ensure_asset_lanes(project_id, us_id)
        pack, pack_refs = self.asset_packs.refresh_pack(project_id, us_id)
        summary = f"Refreshed QualityAssetPack {pack.id if pack else 'current'}."
        return QualityLoopUseCaseResult(
            summary=summary,
            project_id=project_id,
            us_id=us_id,
            object_refs=[f"project:{project_id}", f"us:{us_id}", *pack_refs],
            evidence_refs=pack.evidence_refs if pack else [],
            next_tools=["quality.scenario.generate", "quality.case.generate", "automation.generate"],
            query_keys=self.query_keys_for(invocation, project_id, us_id),
        )

    def start_run(self, invocation: ToolInvocation) -> QualityLoopUseCaseResult | None:
        scope = self.resolve_scope(invocation)
        if scope is None:
            return None
        project_id, us_id = scope
        query_keys = self.query_keys_for(invocation, project_id, us_id)
        outcome = self.run_execution.execute_automation(
            project_id,
            us_id,
            invocation_input=invocation.input_payload,
        )
        return self._complete_execution_outcome(
            invocation,
            project_id=project_id,
            us_id=us_id,
            outcome=outcome,
            query_keys=query_keys,
        )

    def retry_run(self, invocation: ToolInvocation) -> QualityLoopUseCaseResult:
        if not str(invocation.input_payload.get("run_id") or "").strip():
            raise QualityLoopApplicationError(
                "run.retry requires an explicit source run_id",
                next_tools=["run.progress.get"],
            )
        scope = self.resolve_failure_scope(invocation)
        if scope is None:
            raise QualityLoopApplicationError(
                "The source Run could not be resolved in the requested project scope",
                next_tools=["run.progress.get", "us.status.get"],
            )
        project_id, us_id, source_run = scope
        query_keys = self.query_keys_for(invocation, project_id, us_id)
        query_keys.append(["run", project_id, source_run.id])
        outcome = self.run_execution.retry_automation(
            project_id,
            us_id,
            source_run=source_run,
        )
        result = self._complete_execution_outcome(
            invocation,
            project_id=project_id,
            us_id=us_id,
            outcome=outcome,
            query_keys=query_keys,
        )
        return replace(
            result,
            summary=(
                f"Retried Run {source_run.id} as {outcome.run.id}. {result.summary}"
            ),
        )

    def _complete_execution_outcome(
        self,
        invocation: ToolInvocation,
        *,
        project_id: str,
        us_id: str,
        outcome: QualityRunExecutionResult,
        query_keys: list[list[str]],
    ) -> QualityLoopUseCaseResult:
        run = outcome.run
        evidence_refs = list(outcome.evidence_refs)
        plan = automation_quality_step_plan(
            run=run,
            failed=outcome.failed,
            runner_mode=outcome.runner_mode,
            execution_evidence_refs=tuple(evidence_refs),
            automation_asset_ref=outcome.automation_asset_ref,
        )
        object_refs = [
            f"project:{project_id}",
            f"us:{us_id}",
            *plan.object_refs,
        ]
        if plan.requires_failure_report:
            report = self.failure_reports.upsert_failure_report(
                project_id,
                us_id,
                run,
                increment_healing_attempt=False,
            )
            object_refs.append(f"failure_report:{report.id}")
        self.asset_progress.ensure_asset_lanes(project_id, us_id)
        for lane_update in plan.lane_updates:
            self.asset_progress.update_lane(
                project_id,
                us_id,
                lane_update.lane_key,
                status=lane_update.status,
                summary=lane_update.summary,
            )
        self.asset_progress.touch_us(
            project_id,
            us_id,
            progress=plan.us_update.progress,
            status=plan.us_update.status,
            next_action=plan.us_update.next_action,
        )
        metric_refs = self.quality_image_updates.record_quality_image_update(
            project_id,
            us_id,
            step=plan.metric_update.step,
            metrics={
                **plan.metric_update.metric_dict(),
                "automation_script_id": outcome.script_id,
                "automation_asset_ref": outcome.automation_asset_ref,
            },
            evidence_refs=list(plan.metric_update.evidence_refs),
        )
        part = outcome.automation_part
        pack_refs = (
            self.asset_packs.upsert_part(
                project_id,
                us_id,
                part_type=plan.asset_part_update.part_type,
                status=plan.asset_part_update.status,
                title=part.title,
                summary=plan.asset_part_update.summary,
                object_refs=list(plan.asset_part_update.object_refs),
                evidence_refs=list(plan.asset_part_update.evidence_refs),
                structured_content=part.structured_content,
                generation=part.generation,
            )
            if part is not None
            else []
        )
        object_refs.extend(metric_refs)
        object_refs.extend(pack_refs)
        self.read_model_refresh.refresh_project(project_id)
        return QualityLoopUseCaseResult(
            summary=plan.summary,
            project_id=project_id,
            us_id=us_id,
            object_refs=object_refs,
            evidence_refs=evidence_refs,
            next_tools=list(plan.next_tools),
            query_keys=[*query_keys, ["run", project_id, run.id]],
        )

    def get_release_advice(self, invocation: ToolInvocation) -> QualityLoopUseCaseResult | None:
        scope = self.resolve_scope(invocation)
        if scope is None:
            return None
        project_id, us_id = scope
        release = self.release_readiness.upsert_release_readiness(project_id, us_id)
        self.read_model_refresh.refresh_project(project_id)
        summary = (
            f"Release advice for {release.version_id}: score={release.score}, "
            f"blockers={release.blockers}, status={release.status}."
        )
        return QualityLoopUseCaseResult(
            summary=summary,
            project_id=project_id,
            us_id=us_id,
            object_refs=[f"project:{project_id}", f"us:{us_id}", f"release_readiness:{release.version_id}"],
            evidence_refs=[f"release_readiness:{release.version_id}"],
            next_tools=["release.assess", "approval.request"],
            query_keys=self.query_keys_for(invocation, project_id, us_id),
            assistant_message=f"{summary} {release.summary}",
            assistant_metadata={"planner_kind": "release_advice", "tool_id": invocation.tool_id},
        )

    def complete_failure_step(
        self,
        invocation: ToolInvocation,
        *,
        propose_healing: bool,
    ) -> QualityLoopUseCaseResult:
        scope = self.resolve_failure_scope(invocation)
        if scope is None:
            raise QualityLoopApplicationError(
                "A failed run is required before failure analysis or healing can continue",
                next_tools=["query.run.status", "automation.generate"],
            )

        project_id, us_id, run = scope
        query_keys = self.query_keys_for(invocation, project_id, us_id)
        query_keys.append(["run", project_id, run.id])
        report = self.failure_reports.upsert_failure_report(
            project_id,
            us_id,
            run,
            increment_healing_attempt=propose_healing,
        )
        decision = decide_failure_loop_progress(
            report,
            propose_healing=propose_healing,
            max_healing_depth=self.max_healing_depth,
        )

        return QualityLoopUseCaseResult(
            summary=decision.summary,
            project_id=project_id,
            us_id=us_id,
            object_refs=[f"project:{project_id}", f"us:{us_id}", f"run:{run.id}", f"failure_report:{report.id}"],
            evidence_refs=report.evidence_refs,
            next_tools=decision.next_tools,
            query_keys=query_keys,
            assistant_message=decision.assistant_message,
            assistant_metadata={
                "planner_kind": decision.planner_kind,
                "tool_id": invocation.tool_id,
                "failure_report_id": report.id,
                "fallback_to_human": decision.fallback_to_human,
            },
        )

    async def complete_quality_step(self, invocation: ToolInvocation, *, step: str) -> QualityLoopUseCaseResult | None:
        return await self.quality_steps.complete_quality_step(invocation, step=step)

    @staticmethod
    def running_summary(step: str) -> str:
        return QualityStepCompletionApplicationService.running_summary(step)

    @staticmethod
    def assistant_followup(step: str) -> str:
        return QualityStepCompletionApplicationService.assistant_followup(step)

    def resolve_scope(self, invocation: ToolInvocation) -> tuple[str, str] | None:
        return self.scope_queries.resolve_scope(invocation)

    def resolve_failure_scope(self, invocation: ToolInvocation) -> tuple[str, str, RunDetail] | None:
        return self.scope_queries.resolve_failure_scope(invocation)

    def query_keys_for(self, invocation: ToolInvocation, project_id: str, us_id: str) -> list[list[str]]:
        return self.scope_queries.query_keys_for(invocation, project_id, us_id)
