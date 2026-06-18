from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .models import AgentGoalCreateRequest, ToolInvocation, ToolResult

if TYPE_CHECKING:
    from .store import ApplicationStore


class QualityLoopToolHandler:
    """Executes quality-loop tools through canonical ToolInvocation handlers."""

    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store

    async def generate_scenarios(self, invocation: ToolInvocation) -> None:
        if not invocation.conversation_id:
            return

        project_id = str(invocation.input_payload.get("project_id") or "")
        us_id = str(invocation.input_payload.get("us_id") or "")
        conversation = self.store.conversations.get(invocation.conversation_id)
        if not project_id and conversation:
            project_id = conversation.project_id or ""
        if not us_id and project_id:
            first_us = next(iter(self.store.us_items.get(project_id, [])), None)
            us_id = first_us.id if first_us is not None else ""
        if not project_id or not us_id:
            await self.store.append_message(
                invocation.conversation_id,
                "assistant",
                (
                    "I need at least one imported US work item before I can start the quality loop. "
                    "Import US documents first, then I can generate scenarios, cases, automation, and release evidence."
                ),
                metadata={"planner_kind": "quality_loop_blocked", "missing_context": ["us_work_item"]},
            )
            await self.store._emit_tool_status(
                invocation.id,
                "failed",
                "US work item is required before scenario generation",
                [["conversation", invocation.conversation_id], ["project", project_id]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary="US work item is required before scenario generation",
                    next_recommended_tools=["project.import_us_docs"],
                ),
            )
            return

        goal = self._goal_for_invocation(invocation, project_id, us_id)
        goal.steps[0].status = "running"
        goal.steps[0].phase = "thinking"
        goal.steps[0].selected_tool_id = invocation.tool_id
        goal.steps[0].tool_invocation_id = invocation.id
        goal.status = "running"
        self._persist_goal(goal)

        await self.store._emit_tool_status(
            invocation.id,
            "running",
            "Generating test scenarios",
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id], ["project", project_id]],
        )
        await self._emit_goal_update(
            goal.id,
            invocation.conversation_id,
            "replace",
            {"status": "running"},
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id]],
        )

        await asyncio.sleep(0.2)
        goal.steps[0].status = "completed"
        goal.steps[0].decision = "continue"
        goal.steps[1].status = "running"
        goal.steps[1].phase = "observing"
        goal.steps[1].tool_invocation_id = invocation.id
        goal.steps_completed = 1
        self._persist_goal(goal)
        await self._emit_goal_update(
            goal.id,
            invocation.conversation_id,
            "patch",
            {"current_step": "Review impact"},
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id]],
        )

        await asyncio.sleep(0.2)
        goal.steps[1].status = "completed"
        goal.steps[1].decision = "continue"
        goal.steps[2].status = "running"
        goal.steps[2].phase = "deciding"
        goal.steps[2].tool_invocation_id = invocation.id
        goal.steps_completed = 2
        self._persist_goal(goal)
        planning_update = await self.store._generate_llm_content(
            conversation=self.store.conversations[invocation.conversation_id],
            user_message="Summarize the current scenario planning progress for this US.",
            fallback_text=(
                "I narrowed the scope to checkout fallback, saved-card recovery, and post-redirect assertion coverage. "
                "I am now drafting the scenario pack with explicit recovery and fraud-edge branches."
            ),
            system_prompt=(
                "You are Nasus Agent. Summarize scenario planning progress in one concise paragraph "
                "and keep it grounded in the provided workspace context."
            ),
        )
        await self.store.append_message(
            invocation.conversation_id,
            "assistant",
            planning_update["content"],
            metadata=planning_update["metadata"],
        )

        await asyncio.sleep(0.2)
        goal.steps[2].status = "completed"
        goal.steps_completed = 3
        goal.status = "completed"
        self._persist_goal(goal)
        for lane in self.store.asset_lanes.get(us_id, []):
            if lane.id == "lane_scenarios":
                lane.status = "approved"
                lane.summary = "8 scenarios grouped into happy path, redirect recovery, risk edges, and observability checks."
                lane.updated_at = "2026-03-27 19:10"
            if lane.id == "lane_cases":
                lane.status = "ready_for_review"
                lane.summary = "12 cases suggested from the approved scenario structure."
                lane.updated_at = "2026-03-27 19:10"
        self.store.project_repository.replace_asset_lanes(project_id, us_id, self.store.asset_lanes.get(us_id, []))
        completion_update = await self.store._generate_llm_content(
            conversation=self.store.conversations[invocation.conversation_id],
            user_message="Summarize the completed scenario generation result and the best next action.",
            fallback_text=(
                "Scenario generation is complete. The scenario lane is now approved and the case lane is ready for review, "
                "so we can continue into case generation or move directly toward automation drafting."
            ),
            system_prompt="You are Nasus Agent. Summarize completed scenario generation with a short next-step recommendation.",
        )
        await self.store.append_message(
            invocation.conversation_id,
            "assistant",
            completion_update["content"],
            metadata=completion_update["metadata"],
        )
        await self._emit_goal_update(
            goal.id,
            invocation.conversation_id,
            "replace",
            {"status": "completed"},
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id]],
        )
        await self.store._emit_tool_status(
            invocation.id,
            "completed",
            "Generated scenario pack",
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id], ["project", project_id]],
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary="Generated scenario pack",
                object_refs=[f"us:{us_id}", "quality_asset_pack:scenario"],
                next_recommended_tools=["quality.case.generate", "automation.generate"],
            ),
        )

    def _goal_for_invocation(self, invocation: ToolInvocation, project_id: str, us_id: str):
        existing_goal_id = invocation.input_payload.get("agent_goal_id")
        if isinstance(existing_goal_id, str) and existing_goal_id in self.store.agent_goals:
            return self.store.agent_goals[existing_goal_id]
        return self.store.create_agent_goal(
            AgentGoalCreateRequest(
                conversation_id=invocation.conversation_id or "",
                title="Generate scenario pack",
                summary="Building a structured scenario set from system image, US context, and recent change evidence.",
                project_id=project_id,
                us_id=us_id,
            )
        )

    def _persist_goal(self, goal) -> None:
        self.store.conversation_repository.upsert_goal(goal)
        self.store._upsert_goal_in_conversation(goal)

    async def _emit_goal_update(
        self,
        goal_id: str,
        conversation_id: str,
        mutation_kind: str,
        patch: dict,
        query_keys: list[list[str]],
    ) -> None:
        await self.store._push_event(
            conversation_id,
            "agent.goal.updated",
            "agent_goal",
            goal_id,
            mutation_kind,
            patch,
            query_keys,
        )
        await self.store._push_goal_event(
            goal_id,
            "agent.goal.updated",
            mutation_kind,
            patch,
            [["agent-goal", goal_id]],
        )
