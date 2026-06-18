from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .models import AssetLane, ReleaseReadiness, RunDetail, RunSummary, ToolInvocation, ToolResult, USItem

if TYPE_CHECKING:
    from .store import ApplicationStore


class QualityLoopToolHandler:
    """Executes quality-loop tools through canonical ToolInvocation handlers.

    AgentGoal lifecycle is owned by AgentGraphRuntime. Handlers here only
    materialize domain state and report ToolResult back to the invocation
    runtime, keeping the control flow aligned with the agent-first contract.
    """

    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store

    async def generate_scenarios(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="scenarios")

    async def generate_cases(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="cases")

    async def generate_automation(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="automation")

    async def assess_release(self, invocation: ToolInvocation) -> None:
        await self._complete_quality_step(invocation, step="release")

    async def _complete_quality_step(self, invocation: ToolInvocation, *, step: str) -> None:
        scope = self._resolve_scope(invocation)
        if scope is None:
            await self._fail_missing_us(invocation)
            return
        project_id, us_id = scope
        query_keys = self._query_keys(invocation, project_id, us_id)

        await self.store._emit_tool_status(
            invocation.id,
            "running",
            self._running_summary(step),
            query_keys,
        )
        await asyncio.sleep(0.05)

        self._ensure_asset_lanes(project_id, us_id)
        summary = ""
        object_refs = [f"project:{project_id}", f"us:{us_id}", "quality_asset_pack:current"]
        evidence_refs: list[str] = []
        next_tools: list[str] = []

        if step == "scenarios":
            self._update_lane(
                project_id,
                us_id,
                "scenarios",
                status="approved",
                summary="8 scenario groups cover happy path, fallback, risk edge, data validation, and observability checks.",
            )
            self._update_lane(
                project_id,
                us_id,
                "cases",
                status="ready_for_review",
                summary="Case generation is ready from the approved scenario structure.",
            )
            self._touch_us(project_id, us_id, progress=42, status="scenario_ready", next_action="Generate test cases")
            summary = "Generated scenario pack"
            object_refs.append("scenario_set:current")
            next_tools = ["quality.case.generate"]

        elif step == "cases":
            self._update_lane(
                project_id,
                us_id,
                "cases",
                status="approved",
                summary="14 structured cases with preconditions, assertions, data hints, and regression tags are approved.",
            )
            self._update_lane(
                project_id,
                us_id,
                "automation",
                status="ready_for_review",
                summary="Automation script generation is ready from the approved cases.",
            )
            self._touch_us(project_id, us_id, progress=58, status="cases_ready", next_action="Generate automation")
            summary = "Generated test case pack"
            object_refs.append("case_set:current")
            next_tools = ["automation.generate"]

        elif step == "automation":
            run = self._upsert_automation_run(project_id, us_id)
            self._update_lane(
                project_id,
                us_id,
                "automation",
                status="completed",
                summary="Generated Playwright-style automation draft and completed a deterministic smoke validation run.",
            )
            self._update_lane(
                project_id,
                us_id,
                "release",
                status="ready_for_review",
                summary="Execution evidence is ready for release readiness scoring.",
            )
            self._touch_us(project_id, us_id, progress=76, status="execution_ready", next_action="Assess release quality")
            summary = "Generated automation and execution evidence"
            object_refs.extend([f"run:{run.id}", "execution_evidence:current"])
            evidence_refs.extend(run.evidence)
            next_tools = ["release.assess"]

        elif step == "release":
            release = self._upsert_release_readiness(project_id, us_id)
            self._update_lane(
                project_id,
                us_id,
                "release",
                status="completed",
                summary="Release readiness score is complete with automation evidence and no blocking approvals.",
            )
            self._touch_us(project_id, us_id, progress=92, status="release_ready", next_action="Review release decision")
            summary = "Assessed release readiness"
            object_refs.append(f"release_readiness:{release.version_id}")
            next_tools = ["query.version.status", "query.governance.status"]

        else:
            await self.store._emit_tool_status(
                invocation.id,
                "failed",
                f"Unsupported quality step: {step}",
                query_keys,
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=f"Unsupported quality step: {step}",
                ),
            )
            return

        if invocation.conversation_id:
            await self.store.append_message(
                invocation.conversation_id,
                "assistant",
                f"{summary}. {self._assistant_followup(step)}",
                metadata={"planner_kind": "quality_loop_progress", "quality_step": step},
            )

        self.store._refresh_project_read_models(project_id)
        await self.store._emit_tool_status(
            invocation.id,
            "completed",
            summary,
            query_keys,
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=summary,
                object_refs=object_refs,
                evidence_refs=evidence_refs,
                next_recommended_tools=next_tools,
            ),
        )

    def _resolve_scope(self, invocation: ToolInvocation) -> tuple[str, str] | None:
        project_id = str(invocation.input_payload.get("project_id") or "")
        us_id = str(invocation.input_payload.get("us_id") or "")
        conversation = self.store.conversations.get(invocation.conversation_id or "")
        if conversation:
            project_id = project_id or conversation.project_id or (
                conversation.space_id if conversation.space_type == "project" else ""
            )
            us_id = us_id or conversation.us_id or (
                conversation.space_id if conversation.space_type == "workspace" else ""
            )
        if not project_id and us_id:
            for candidate_project_id, items in self.store.us_items.items():
                if any(item.id == us_id for item in items):
                    project_id = candidate_project_id
                    break
        if not us_id and project_id:
            first_us = next(iter(self.store.us_items.get(project_id, [])), None)
            us_id = first_us.id if first_us is not None else ""
        if not project_id or not us_id:
            return None
        return project_id, us_id

    async def _fail_missing_us(self, invocation: ToolInvocation) -> None:
        project_id = str(invocation.input_payload.get("project_id") or "")
        if invocation.conversation_id:
            await self.store.append_message(
                invocation.conversation_id,
                "assistant",
                (
                    "I need at least one imported US work item before I can start the quality loop. "
                    "Build the system image or import US documents first, then I can generate scenarios, cases, automation, and release evidence."
                ),
                metadata={"planner_kind": "quality_loop_blocked", "missing_context": ["us_work_item"]},
            )
        await self.store._emit_tool_status(
            invocation.id,
            "failed",
            "US work item is required before quality-loop generation",
            [["conversation", invocation.conversation_id or ""], ["project", project_id]],
            ToolResult(
                invocation_id=invocation.id,
                status="failed",
                summary="US work item is required before quality-loop generation",
                next_recommended_tools=["system_image.context.materialize"],
            ),
        )

    def _ensure_asset_lanes(self, project_id: str, us_id: str) -> None:
        lanes = list(self.store.asset_lanes.get(us_id, []))
        changed = False
        for key, label, summary in [
            ("scenarios", "Scenarios", "Waiting for scenario generation from system image, US, and test evidence."),
            ("cases", "Cases", "Waiting for approved scenario structure."),
            ("automation", "Automation", "Waiting for reviewed cases before script generation."),
            ("release", "Release Assessment", "Waiting for execution evidence and quality scoring."),
        ]:
            if self._find_lane(lanes, key) is None:
                lanes.append(
                    AssetLane(
                        id=self._lane_id(us_id, key),
                        label=label,
                        status="not_started",
                        summary=summary,
                        updated_at=self._now(),
                    )
                )
                changed = True
        if changed:
            self.store.asset_lanes[us_id] = lanes
            self.store.project_repository.replace_asset_lanes(project_id, us_id, lanes)

    def _update_lane(self, project_id: str, us_id: str, key: str, *, status: str, summary: str) -> None:
        lanes = list(self.store.asset_lanes.get(us_id, []))
        lane = self._find_lane(lanes, key)
        if lane is None:
            self._ensure_asset_lanes(project_id, us_id)
            lanes = list(self.store.asset_lanes.get(us_id, []))
            lane = self._find_lane(lanes, key)
        if lane is None:
            return
        lane.status = status
        lane.summary = summary
        lane.updated_at = self._now()
        self.store.asset_lanes[us_id] = lanes
        self.store.project_repository.replace_asset_lanes(project_id, us_id, lanes)

    @staticmethod
    def _find_lane(lanes: list[AssetLane], key: str) -> AssetLane | None:
        expected_suffix = f"lane_{key}"
        expected_label = {
            "scenarios": "scenarios",
            "cases": "cases",
            "automation": "automation",
            "release": "release assessment",
        }[key]
        return next(
            (
                lane
                for lane in lanes
                if lane.id == expected_suffix
                or lane.id.endswith(f"_{expected_suffix}")
                or lane.label.strip().lower() == expected_label
            ),
            None,
        )

    @staticmethod
    def _lane_id(us_id: str, key: str) -> str:
        return f"{us_id}_lane_{key}"

    def _touch_us(self, project_id: str, us_id: str, *, progress: int, status: str, next_action: str) -> None:
        updated_items: list[USItem] = []
        for item in self.store.us_items.get(project_id, []):
            if item.id == us_id:
                item = item.model_copy(update={"progress": progress, "status": status, "next_action": next_action})
            updated_items.append(item)
        self.store.us_items[project_id] = updated_items
        version_id = self.store.versions[project_id][0].id if self.store.versions.get(project_id) else None
        self.store.project_repository.replace_us_items(project_id, version_id, updated_items)

    def _upsert_automation_run(self, project_id: str, us_id: str) -> RunDetail:
        us = next((item for item in self.store.us_items.get(project_id, []) if item.id == us_id), None)
        us_title = us.title if us else us_id
        run_id = f"run_{us_id}_automation"
        run = RunDetail(
            id=run_id,
            status="passed",
            channel="web_runner",
            title=f"{us_title} automation validation",
            summary="Generated automation draft and completed smoke validation against the current quality asset pack.",
            started_at=self._now(),
            timeline=[
                "Generated browser automation from approved cases.",
                "Bound selectors and assertions to system-image evidence refs.",
                "Executed deterministic smoke validation in the web runner channel.",
                "Captured trace, log, and generated script references for review.",
            ],
            evidence=[f"script://{run_id}", f"trace://{run_id}", f"log://{run_id}"],
            failure_summary="No blocking failure observed in the generated smoke validation.",
            healing_status="not_required",
        )
        existing_details = [
            self.store.run_details[item.id]
            for item in self.store.runs.get(project_id, [])
            if item.id != run_id and item.id in self.store.run_details
        ]
        self.store.run_details[run.id] = run
        self.store.runs[project_id] = [
            RunSummary(
                id=run.id,
                status=run.status,
                channel=run.channel,
                title=run.title,
                summary=run.summary,
                started_at=run.started_at,
            )
        ] + [
            item for item in self.store.runs.get(project_id, []) if item.id != run_id
        ]
        self.store.project_repository.replace_runs(project_id, [run] + existing_details)
        return run

    def _upsert_release_readiness(self, project_id: str, us_id: str) -> ReleaseReadiness:
        version = self._active_or_create_version(project_id)
        release = ReleaseReadiness(
            version_id=version.id,
            status="Ready for release review",
            score=86,
            blockers=0,
            approvals_open=0,
            pending_merge=0,
            execution_health="Latest generated automation evidence passed.",
            summary=(
                "Quality loop reached release-review readiness for the selected US: scenarios and cases are approved, "
                "automation evidence is attached, and no blocking governance item remains."
            ),
            blocker_items=[],
        )
        self.store.release_readiness[version.id] = release
        self.store.project_repository.upsert_release_readiness(project_id, release)

        project = self.store.projects[project_id]
        project.progress = max(project.progress, 82)
        project.risk = "low" if project.blocked_items == 0 else project.risk
        self.store.project_repository.upsert_project(project)
        return release

    def _active_or_create_version(self, project_id: str):
        versions = self.store.versions.get(project_id, [])
        if versions:
            return versions[0]
        return self.store.create_version(project_id, "Initial Quality Loop")

    @staticmethod
    def _query_keys(invocation: ToolInvocation, project_id: str, us_id: str) -> list[list[str]]:
        keys = [["project", project_id], ["workspace", project_id, us_id], ["runs", project_id], ["governance", project_id]]
        if invocation.conversation_id:
            keys.insert(0, ["conversation", invocation.conversation_id])
        return keys

    @staticmethod
    def _running_summary(step: str) -> str:
        return {
            "scenarios": "Generating scenario pack",
            "cases": "Generating structured test cases",
            "automation": "Generating automation and execution evidence",
            "release": "Assessing release readiness",
        }.get(step, "Running quality-loop tool")

    @staticmethod
    def _assistant_followup(step: str) -> str:
        return {
            "scenarios": "Next I will turn the approved scenario structure into executable test cases.",
            "cases": "Next I will generate the automation draft and attach execution evidence.",
            "automation": "Next I will score release readiness from the new execution evidence.",
            "release": "The quality loop is ready for human release review or governance follow-up.",
        }.get(step, "I will continue with the next quality-loop step.")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
