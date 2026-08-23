from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .generation import AutomationStep
from .ports import QualityAssetPackReadPort, QualityExecutionEvidenceReadPort
from .quality_models import ExecutionEvidence, QualityAssetPart, RunDetail
from .results import QualityLoopApplicationError
from .runner_port import QualityAutomationExecutionPort


@dataclass(frozen=True)
class QualityRunExecutionResult:
    run: RunDetail
    evidence: list[ExecutionEvidence]
    evidence_refs: list[str]
    failed: bool
    runner_mode: str
    automation_part: QualityAssetPart | None
    automation_asset_ref: str
    script_id: str


class QualityRunExecutionApplicationService:
    """Application boundary for quality-loop automation execution.

    The infrastructure runner owns how automation is executed and persisted.
    Quality-loop use cases only need the resulting run and evidence refs for
    state transitions, asset updates, and follow-up tool planning.
    """

    def __init__(
        self,
        executor: QualityAutomationExecutionPort,
        asset_packs: QualityAssetPackReadPort,
        evidence: QualityExecutionEvidenceReadPort,
    ) -> None:
        self._executor = executor
        self._asset_packs = asset_packs
        self._evidence = evidence

    def execute_automation(
        self,
        project_id: str,
        us_id: str,
        *,
        invocation_input: dict[str, Any],
    ) -> QualityRunExecutionResult:
        automation_part, script = self._active_automation_script(
            project_id,
            us_id,
            requested_script_id=str(invocation_input.get("automation_script_id") or ""),
        )
        automation_asset_ref = (
            f"quality_asset_part:{automation_part.id}:revision:{automation_part.revision}"
        )
        runner_input = self._runner_input(
            invocation_input,
            automation_asset_ref=automation_asset_ref,
            script=script,
            default_base_url=str(
                automation_part.structured_content.get("default_base_url") or ""
            ),
        )
        outcome = self._executor.execute_automation(
            project_id,
            us_id,
            invocation_input=runner_input,
        )
        evidence = list(outcome.evidence)
        return QualityRunExecutionResult(
            run=outcome.run,
            evidence=evidence,
            evidence_refs=[f"execution_evidence:{item.id}" for item in evidence],
            failed=outcome.failed,
            runner_mode=outcome.runner_mode,
            automation_part=automation_part,
            automation_asset_ref=automation_asset_ref,
            script_id=str(script["script_id"]),
        )

    def retry_automation(
        self,
        project_id: str,
        us_id: str,
        *,
        source_run: RunDetail,
    ) -> QualityRunExecutionResult:
        if source_run.us_id and source_run.us_id != us_id:
            raise QualityLoopApplicationError(
                "The source Run belongs to a different US",
                next_tools=["run.progress.get", "us.status.get"],
            )
        if not source_run.target_base_url:
            raise QualityLoopApplicationError(
                "The source Run predates persisted execution targets and cannot be retried safely",
                next_tools=["run.start"],
            )
        if not source_run.automation_asset_ref or not source_run.automation_script_id:
            raise QualityLoopApplicationError(
                "The source Run has no persisted automation revision or script identity",
                next_tools=["automation.generate", "run.start"],
            )
        steps = self._runner_steps(source_run.execution_plan)
        timeout_ms = min(max(int(source_run.execution_timeout_ms), 1_000), 120_000)
        runner_input = {
            "project_id": project_id,
            "us_id": us_id,
            "run_id": source_run.id,
            "runner_request": {
                "base_url": source_run.target_base_url,
                "steps": steps,
                "timeout_ms": timeout_ms,
                "automation_asset_ref": source_run.automation_asset_ref,
                "automation_script_id": source_run.automation_script_id,
                "retry_of_run_id": source_run.id,
                "attempt": max(source_run.attempt, 1) + 1,
            },
        }
        outcome = self._executor.execute_automation(
            project_id,
            us_id,
            invocation_input=runner_input,
        )
        evidence = list(outcome.evidence)
        return QualityRunExecutionResult(
            run=outcome.run,
            evidence=evidence,
            evidence_refs=[f"execution_evidence:{item.id}" for item in evidence],
            failed=outcome.failed,
            runner_mode=outcome.runner_mode,
            automation_part=None,
            automation_asset_ref=source_run.automation_asset_ref,
            script_id=source_run.automation_script_id,
        )

    def _active_automation_script(
        self,
        project_id: str,
        us_id: str,
        *,
        requested_script_id: str,
    ) -> tuple[QualityAssetPart, dict[str, Any]]:
        pack = self._asset_packs.get_quality_asset_pack(project_id, us_id)
        part = next(
            (
                item
                for item in (pack.parts if pack is not None else [])
                if item.part_type == "automation_blueprint"
            ),
            None,
        )
        if part is None or part.status not in {
            "ready_for_review",
            "approved",
            "completed",
        }:
            raise QualityLoopApplicationError(
                "run.start requires a generated automation blueprint for the selected US",
                next_tools=["automation.generate"],
            )
        scripts = part.structured_content.get("scripts")
        if not isinstance(scripts, list) or not scripts:
            raise QualityLoopApplicationError(
                "The current automation blueprint has no executable structured scripts",
                next_tools=["automation.generate"],
            )
        selected = next(
            (
                script
                for script in scripts
                if isinstance(script, dict)
                and (
                    not requested_script_id
                    or str(script.get("script_id") or "") == requested_script_id
                )
            ),
            None,
        )
        if selected is None:
            raise QualityLoopApplicationError(
                f"Automation script {requested_script_id!r} does not exist in the current blueprint",
                next_tools=["automation.generate", "query.us.status"],
            )
        steps = selected.get("steps")
        if not isinstance(steps, list) or not steps:
            raise QualityLoopApplicationError(
                "The selected automation script has no executable steps",
                next_tools=["automation.generate"],
            )
        return part, selected

    @staticmethod
    def _runner_input(
        invocation_input: dict[str, Any],
        *,
        automation_asset_ref: str,
        script: dict[str, Any],
        default_base_url: str,
    ) -> dict[str, Any]:
        existing_request = invocation_input.get("runner_request")
        request = dict(existing_request) if isinstance(existing_request, dict) else {}
        base_url = str(
            invocation_input.get("base_url")
            or request.get("base_url")
            or default_base_url
            or ""
        ).strip()
        if not base_url:
            raise QualityLoopApplicationError(
                "run.start requires base_url for the target environment",
                next_tools=["run.start"],
            )
        request.update(
            {
                "base_url": base_url,
                "steps": QualityRunExecutionApplicationService._runner_steps(
                    script["steps"]
                ),
                "timeout_ms": script.get(
                    "timeout_ms",
                    request.get("timeout_ms", invocation_input.get("timeout_ms", 60_000)),
                ),
                "automation_asset_ref": automation_asset_ref,
                "automation_script_id": str(script["script_id"]),
                "attempt": 1,
            }
        )
        return {
            **invocation_input,
            "runner_request": request,
        }

    @staticmethod
    def _runner_steps(raw_steps: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_steps, list) or not raw_steps:
            raise QualityLoopApplicationError(
                "The selected automation script has no executable steps",
                next_tools=["automation.generate"],
            )
        try:
            return [
                AutomationStep.model_validate(step).model_dump(
                    mode="json",
                    exclude_none=True,
                )
                for step in raw_steps
            ]
        except ValidationError as exc:
            raise QualityLoopApplicationError(
                f"The selected automation script is invalid: {exc.errors()[0]['msg']}",
                next_tools=["automation.generate"],
            ) from exc

    def evidence_refs_for_us(
        self,
        project_id: str,
        us_id: str,
        *,
        fallback_refs: list[str] | tuple[str, ...] = (),
    ) -> list[str]:
        refs = [
            f"execution_evidence:{item.id}"
            for item in self._evidence.list_execution_evidence(project_id)
            if item.us_id == us_id
        ]
        return refs or list(fallback_refs)


__all__ = ["QualityRunExecutionApplicationService", "QualityRunExecutionResult"]
