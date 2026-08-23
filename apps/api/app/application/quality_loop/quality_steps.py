from __future__ import annotations

from typing import Any

from .asset_packs import QualityAssetPackApplicationService
from .asset_progress import QualityAssetProgressApplicationService
from .context_queries import QualityLoopContextQueryApplicationService
from .generation import (
    QualityGenerationError,
    QualityGenerationPort,
    QualityGenerationRequest,
    QualityGenerationResult,
)
from .quality_image_updates import QualityImageUpdateApplicationService
from .release_readiness import QualityReleaseReadinessApplicationService
from .results import QualityLoopApplicationError, QualityLoopUseCaseResult
from .run_execution import QualityRunExecutionApplicationService
from .scope_queries import QualityLoopScopeQueryApplicationService
from ..platform.read_model_refresh import ProjectReadModelRefreshApplicationService
from ..platform.tool_models import ToolInvocation
from ...domain.quality_loop.quality_step_plan import (
    deterministic_quality_step_plan,
    release_quality_step_plan,
)
from ...domain.quality_loop.step_guidance import (
    quality_step_assistant_followup,
    quality_step_running_summary,
)


class QualityStepCompletionApplicationService:
    """Application boundary for quality-step state transitions."""

    def __init__(
        self,
        *,
        read_model_refresh: ProjectReadModelRefreshApplicationService,
        context_queries: QualityLoopContextQueryApplicationService,
        scope_queries: QualityLoopScopeQueryApplicationService,
        asset_progress: QualityAssetProgressApplicationService,
        asset_packs: QualityAssetPackApplicationService,
        release_readiness: QualityReleaseReadinessApplicationService,
        quality_image_updates: QualityImageUpdateApplicationService,
        run_execution: QualityRunExecutionApplicationService,
        quality_generator: QualityGenerationPort,
    ) -> None:
        self.read_model_refresh = read_model_refresh
        self.context_queries = context_queries
        self.scope_queries = scope_queries
        self.asset_progress = asset_progress
        self.asset_packs = asset_packs
        self.release_readiness = release_readiness
        self.quality_image_updates = quality_image_updates
        self.run_execution = run_execution
        self.quality_generator = quality_generator

    async def complete_quality_step(self, invocation: ToolInvocation, *, step: str) -> QualityLoopUseCaseResult | None:
        scope = self.scope_queries.resolve_scope(invocation)
        if scope is None:
            return None
        project_id, us_id = scope
        query_keys = self.scope_queries.query_keys_for(invocation, project_id, us_id)

        deterministic_plan = deterministic_quality_step_plan(step, us_id=us_id)
        generation: QualityGenerationResult | None = None
        if deterministic_plan is not None:
            try:
                generation = await self.quality_generator.generate(
                    self._generation_request(invocation, project_id=project_id, us_id=us_id, step=step)
                )
            except QualityGenerationError as exc:
                raise QualityLoopApplicationError(
                    str(exc),
                    next_tools=["query.system-image.status", "system_image.context.materialize"],
                ) from exc

        # Generation is validated before this first mutation, keeping failures atomic.
        self.asset_progress.ensure_asset_lanes(project_id, us_id)
        summary = ""
        object_refs = [f"project:{project_id}", f"us:{us_id}"]
        evidence_refs: list[str] = []
        next_tools: list[str] = []
        metric_refs: list[str] = []
        pack_refs: list[str] = []

        if deterministic_plan is not None:
            assert generation is not None
            for lane_update in deterministic_plan.lane_updates:
                self.asset_progress.update_lane(
                    project_id,
                    us_id,
                    lane_update.lane_key,
                    status=lane_update.status,
                    summary=(
                        generation.summary
                        if lane_update.lane_key
                        == {
                            "scope": "scenarios",
                            "scenarios": "scenarios",
                            "verification_plan": "verification",
                            "cases": "cases",
                            "automation": "automation",
                            "change_document": "change_document",
                        }[step]
                        else lane_update.summary
                    ),
                )
            self.asset_progress.touch_us(
                project_id,
                us_id,
                progress=deterministic_plan.us_update.progress,
                status=deterministic_plan.us_update.status,
                next_action=deterministic_plan.us_update.next_action,
            )
            summary = generation.summary
            object_refs.extend(deterministic_plan.object_refs)
            metrics = deterministic_plan.metric_update.metric_dict()
            metrics.update(self._generation_metric_overrides(step, generation.structured_output))
            metrics.update(
                {
                    "generation_mode": generation.generation.mode,
                    "generation_provider": generation.generation.provider,
                    "generation_model": generation.generation.model_name,
                    "prompt_id": generation.generation.prompt_id,
                    "prompt_version": generation.generation.prompt_version,
                }
            )
            metric_refs.extend(
                self.quality_image_updates.record_quality_image_update(
                    project_id,
                    us_id,
                    step=deterministic_plan.metric_update.step,
                    metrics=metrics,
                    evidence_refs=list(deterministic_plan.metric_update.evidence_refs),
                )
            )
            pack_refs.extend(
                self.asset_packs.upsert_part(
                    project_id,
                    us_id,
                    part_type=deterministic_plan.asset_part_update.part_type,
                    status=deterministic_plan.asset_part_update.status,
                    title=generation.title,
                    summary=generation.summary,
                    object_refs=list(deterministic_plan.asset_part_update.object_refs),
                    evidence_refs=list(deterministic_plan.asset_part_update.evidence_refs),
                    structured_content=generation.structured_output,
                    generation=generation.generation,
                )
            )
            next_tools = list(deterministic_plan.next_tools)

        elif step == "release":
            release = self.release_readiness.upsert_release_readiness(project_id, us_id)
            release_evidence_refs = self.run_execution.evidence_refs_for_us(
                project_id,
                us_id,
                fallback_refs=[f"release_readiness:{release.version_id}"],
            )
            release_plan = release_quality_step_plan(
                us_id=us_id,
                release=release,
                release_evidence_refs=tuple(release_evidence_refs),
            )
            for lane_update in release_plan.lane_updates:
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
                progress=release_plan.us_update.progress,
                status=release_plan.us_update.status,
                next_action=release_plan.us_update.next_action,
            )
            summary = release_plan.summary
            object_refs.extend(release_plan.object_refs)
            evidence_refs.extend(release_evidence_refs)
            metric_refs.extend(
                self.quality_image_updates.record_quality_image_update(
                    project_id,
                    us_id,
                    step=release_plan.metric_update.step,
                    metrics=release_plan.metric_update.metric_dict(),
                    evidence_refs=list(release_plan.metric_update.evidence_refs),
                )
            )
            pack_refs.extend(
                self.asset_packs.upsert_part(
                    project_id,
                    us_id,
                    part_type=release_plan.asset_part_update.part_type,
                    status=release_plan.asset_part_update.status,
                    title=release_plan.asset_part_update.title,
                    summary=release_plan.asset_part_update.summary,
                    object_refs=list(release_plan.asset_part_update.object_refs),
                    evidence_refs=list(release_plan.asset_part_update.evidence_refs),
                )
            )
            next_tools = list(release_plan.next_tools)

        else:
            raise QualityLoopApplicationError(f"Unsupported quality step: {step}")

        self.read_model_refresh.refresh_project(project_id)
        object_refs.extend(metric_refs)
        object_refs.extend(pack_refs)
        return QualityLoopUseCaseResult(
            summary=summary,
            project_id=project_id,
            us_id=us_id,
            object_refs=object_refs,
            evidence_refs=evidence_refs,
            next_tools=next_tools,
            query_keys=query_keys,
            assistant_message=f"{summary}. {quality_step_assistant_followup(step)}",
            assistant_metadata={
                "planner_kind": "quality_loop_progress",
                "quality_step": step,
                **(
                    {
                        "generation_mode": generation.generation.mode,
                        "generation_provider": generation.generation.provider,
                        "generation_model": generation.generation.model_name,
                        "prompt_id": generation.generation.prompt_id,
                        "prompt_version": generation.generation.prompt_version,
                        "input_context_hash": generation.generation.input_context_hash,
                    }
                    if generation is not None
                    else {}
                ),
            },
        )

    def _generation_request(
        self,
        invocation: ToolInvocation,
        *,
        project_id: str,
        us_id: str,
        step: str,
    ) -> QualityGenerationRequest:
        task_context = self.context_queries.current_task_context(project_id, us_id)
        quality_profile = self.context_queries.current_quality_profile(project_id, us_id)
        if task_context is None or quality_profile is None:
            raise QualityLoopApplicationError(
                (
                    f"Quality generation for US {us_id} requires its own materialized "
                    "TaskContext and QualityProfile."
                ),
                next_tools=["system_image.context.materialize", "query.system-image.status"],
            )
        if task_context.readiness != "ready":
            raise QualityLoopApplicationError(
                (
                    f"TaskContext {task_context.id} for US {us_id} is "
                    f"{task_context.readiness}; quality generation requires readiness=ready."
                ),
                next_tools=["system_image.context.materialize", "query.system-image.status"],
            )
        pack = self.asset_packs.current_pack(project_id, us_id)
        prior_assets = [part.model_dump(mode="json") for part in pack.parts] if pack is not None else []
        return QualityGenerationRequest(
            stage=step,  # type: ignore[arg-type]
            project_id=project_id,
            us_id=us_id,
            task_context=task_context.model_dump(mode="json"),
            quality_profile=quality_profile.model_dump(mode="json"),
            prior_assets=prior_assets,
            tool_input=dict(invocation.input_payload),
            conversation_id=invocation.conversation_id,
            tool_invocation_id=invocation.id,
        )

    @staticmethod
    def _generation_metric_overrides(step: str, payload: dict[str, Any]) -> dict[str, Any]:
        if step == "scope":
            return {
                "scope_items": sum(
                    len(payload.get(key, []))
                    for key in ("in_scope", "out_of_scope", "regression_targets", "risk_targets")
                ),
                "risk_targets": len(payload.get("risk_targets", [])),
                "regression_targets": len(payload.get("regression_targets", [])),
            }
        if step == "scenarios":
            scenarios = payload.get("scenarios", [])
            return {
                "scenario_groups": len(scenarios),
                "risk_edge_groups": sum(
                    1
                    for scenario in scenarios
                    if scenario.get("category") in {"error_path", "permission", "boundary_data"}
                ),
            }
        if step == "cases":
            cases = payload.get("cases", [])
            return {
                "test_cases": len(cases),
                "regression_tags": len(
                    {
                        tag
                        for case in cases
                        for tag in case.get("regression_tags", [])
                    }
                ),
            }
        if step == "verification_plan":
            return {
                "verification_priorities": len(payload.get("priorities", [])),
                "execution_allocations": len(payload.get("execution_allocations", [])),
                "approval_points": len(payload.get("approval_points", [])),
                "performance_requirements": len(payload.get("performance_requirements", [])),
            }
        if step == "automation":
            scripts = payload.get("scripts", [])
            return {
                "automation_scripts": len(scripts),
                "automation_steps": sum(
                    len(script.get("steps", []))
                    for script in scripts
                    if isinstance(script, dict)
                ),
                "linked_cases": len(
                    {
                        case_id
                        for script in scripts
                        if isinstance(script, dict)
                        for case_id in script.get("linked_case_ids", [])
                    }
                ),
            }
        return {
            "change_deltas": len(payload.get("deltas", [])),
            "change_risks": len(payload.get("risks", [])),
            "unresolved_questions": len(payload.get("unresolved_questions", [])),
            "change_evidence_refs": len(payload.get("evidence_refs", [])),
        }

    @staticmethod
    def running_summary(step: str) -> str:
        return quality_step_running_summary(step)

    @staticmethod
    def assistant_followup(step: str) -> str:
        return quality_step_assistant_followup(step)


__all__ = ["QualityStepCompletionApplicationService"]
