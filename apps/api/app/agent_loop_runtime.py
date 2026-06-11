from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

from .agent_runtime_models import AgentGoalProposal
from .models import AgentGoal, AgentGoalCreateRequest, AgentStep, ToolInvocationRequest

if TYPE_CHECKING:
    from .store import ApplicationStore


class AgentLoopRuntime:
    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store

    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        conversation = self.store.get_conversation(conversation_id)
        goal = self.store.create_agent_goal(
            AgentGoalCreateRequest(
                conversation_id=conversation_id,
                title=proposal.title,
                summary=proposal.summary,
                autonomy_level=proposal.suggested_autonomy_level,
                project_id=conversation.project_id,
                us_id=self._goal_us_id(conversation, proposal),
                steps=self._steps_for_proposal(proposal),
            )
        )

        await self.store._push_event(
            conversation_id,
            "conversation.agent_goal.proposed",
            "agent_goal",
            goal.id,
            "append",
            {"goal_id": goal.id, "status": goal.status, "title": goal.title},
            [["conversation", conversation_id]],
        )
        if proposal.kickoff_message:
            await self.store.append_message(
                conversation_id,
                "assistant",
                proposal.kickoff_message,
                metadata={"agent_runtime": "goal_kickoff", "goal_template": proposal.goal_template},
            )

        await self._run_goal(goal.id, proposal)
        return goal

    async def _run_goal(self, goal_id: str, proposal: AgentGoalProposal) -> None:
        goal = self.store.get_agent_goal(goal_id)
        conversation = self.store.get_conversation(goal.conversation_id)
        goal.status = "running"
        await self._update_goal(goal, patch={"status": "running"})

        think_step = goal.steps[0]
        think_step.status = "running"
        think_step.phase = "thinking"
        think_step.reasoning = self._reasoning_for_proposal(proposal)
        think_step.next_plan_hint = proposal.initial_tool_id or "direct_answer"
        await self._update_goal(goal, patch={"current_step": think_step.title, "phase": think_step.phase})
        await asyncio.sleep(0.05)
        think_step.status = "completed"
        think_step.decision = "continue"
        think_step.decision_rationale = "The current context is sufficient to execute the next tool."
        goal.steps_completed = 1
        await self._update_goal(goal, patch={"current_step": think_step.title, "status": goal.status})

        if proposal.initial_tool_id is None:
            goal.status = "completed"
            if len(goal.steps) > 1:
                goal.steps[1].status = "completed"
                goal.steps[1].phase = "deciding"
                goal.steps[1].decision = "complete"
                goal.steps[1].observation_summary = "The goal could be completed without a tool action."
            await self._update_goal(goal, patch={"status": "completed"})
            return

        act_step = goal.steps[1]
        act_step.status = "running"
        act_step.phase = "acting"
        act_step.selected_tool_id = proposal.initial_tool_id
        await self._update_goal(goal, patch={"current_step": act_step.title, "selected_tool_id": proposal.initial_tool_id})

        invocation_request = ToolInvocationRequest(
            conversation_id=goal.conversation_id,
            tool_id=proposal.initial_tool_id,
            input={
                **proposal.initial_tool_input,
                "agent_goal_id": goal.id,
                "goal_template": proposal.goal_template,
                "goal_description": proposal.goal_description,
                "agent_loop_iteration_id": f"iter_{uuid4().hex[:8]}",
            },
            initiator_surface="agent_loop",
            initiator_actor="agent",
            target_scope="central",
        )
        invocation = await self.store.create_tool_invocation(invocation_request)
        act_step.tool_invocation_id = invocation.id

        if invocation.status in {"waiting_confirmation", "waiting_approval"}:
            goal.status = "paused"
            goal.pause_reason = invocation.status
            act_step.status = "blocked"
            act_step.decision = "pause"
            act_step.decision_rationale = "The selected tool reached a governance gate and needs an external resume signal."
            await self._update_goal(goal, patch={"status": "paused", "pause_reason": goal.pause_reason})
            return

        act_step.status = "completed"
        goal.steps_completed = max(goal.steps_completed, 2)

        observe_step = goal.steps[2]
        observe_step.status = "running"
        observe_step.phase = "observing"
        observe_step.tool_invocation_id = invocation.id
        observe_step.observation_summary = invocation.result.summary if invocation.result else invocation.summary
        await self._update_goal(goal, patch={"current_step": observe_step.title, "tool_invocation_id": invocation.id})
        await asyncio.sleep(0.05)
        observe_step.status = "completed"
        observe_step.decision = "continue"
        observe_step.decision_rationale = "The tool returned a usable result that can be summarized for the user."
        goal.steps_completed = max(goal.steps_completed, 3)

        decide_step = goal.steps[3]
        decide_step.status = "running"
        decide_step.phase = "deciding"
        decide_step.observation_summary = observe_step.observation_summary
        decide_step.decision = "complete"
        decide_step.decision_rationale = self._decision_summary(proposal)
        decide_step.next_plan_hint = self._next_plan_hint(proposal)
        await self._update_goal(goal, patch={"current_step": decide_step.title, "status": "running"})
        await asyncio.sleep(0.05)
        decide_step.status = "completed"
        goal.status = "completed"
        goal.steps_completed = len(goal.steps)
        await self._update_goal(goal, patch={"status": "completed", "current_step": decide_step.title})

    def _steps_for_proposal(self, proposal: AgentGoalProposal) -> list[AgentStep]:
        return [
            AgentStep(id="step_think", title="Plan next action", status="pending"),
            AgentStep(id="step_act", title="Execute tool", status="pending"),
            AgentStep(id="step_observe", title="Observe result", status="pending"),
            AgentStep(id="step_decide", title="Decide next frontier", status="pending"),
        ]

    @staticmethod
    def _goal_us_id(conversation, proposal: AgentGoalProposal) -> str | None:
        if conversation.us_id:
            return conversation.us_id
        proposed_us_id = proposal.initial_tool_input.get("us_id")
        if isinstance(proposed_us_id, str) and proposed_us_id:
            return proposed_us_id
        return None

    async def _update_goal(self, goal: AgentGoal, *, patch: dict[str, str]) -> None:
        self.store.conversation_repository.upsert_goal(goal)
        self.store._upsert_goal_in_conversation(goal)
        await self.store._push_goal_event(
            goal.id,
            "agent.goal.updated",
            "patch",
            patch,
            [["agent-goal", goal.id]],
        )
        await self.store._push_event(
            goal.conversation_id,
            "agent.goal.updated",
            "agent_goal",
            goal.id,
            "patch",
            patch,
            [["conversation", goal.conversation_id]],
        )

    @staticmethod
    def _reasoning_for_proposal(proposal: AgentGoalProposal) -> str:
        if proposal.goal_template == "project_setup":
            return "Create the project shell first, then guide the user through source import and system image initialization."
        if proposal.goal_template == "quality_loop":
            return "Start from the next unblocked quality asset step, materialize that asset, and then recommend the most efficient follow-up action."
        return "Use the proposal context to execute the next best step."

    @staticmethod
    def _decision_summary(proposal: AgentGoalProposal) -> str:
        if proposal.goal_template == "project_setup":
            return "The draft project is ready, so the next frontier is source connection and system image initialization."
        if proposal.goal_template == "quality_loop":
            return "The next quality frontier is ready; continue into cases, automation, or execution based on the updated asset lanes."
        return "The immediate goal step is complete."

    @staticmethod
    def _next_plan_hint(proposal: AgentGoalProposal) -> str:
        if proposal.goal_template == "quality_loop":
            return "quality.case.generate"
        if proposal.goal_template == "project_setup":
            return "project.import_sources"
        return "direct_answer"
