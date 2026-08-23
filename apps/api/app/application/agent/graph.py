from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from .plans import AgentGoalPlanCompiler
from .agent_models import AgentGoal, AgentStep
from .ports import AgentGraphStatePort
from .replanning import AgentReplanDecision, AgentReplanRequest, AgentReplanner
from ...domain.agent.budget_policy import (
    AgentBudgetDecision,
    evaluate_agent_budget,
    observation_progress_fingerprint,
    record_model_usage,
    record_observation_progress,
)
from ...domain.agent.memory import AgentMemoryContext, memory_context_hash, memory_context_summary
from ...domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep
from ...domain.agent.state_machine import AgentGoalStateMachine
from ..platform.tool_models import ToolInvocation, ToolInvocationRequest


class AgentGraphRuntime(Protocol):
    graph_kind: str

    async def start(self, goal_id: str, proposal: AgentGoalProposal) -> None:
        ...

    async def resume(self, goal_id: str) -> AgentGoal:
        ...

    def steps_for_proposal(self, proposal: AgentGoalProposal) -> list[AgentStep]:
        ...


class LangGraphGateway(Protocol):
    """Boundary for a LangGraph-backed Agent Goal graph implementation."""

    async def start(self, goal_id: str, proposal: AgentGoalProposal) -> None:
        ...

    async def resume(self, goal_id: str) -> AgentGoal:
        ...

    def steps_for_proposal(self, proposal: AgentGoalProposal) -> list[AgentStep]:
        ...


AgentGraphNodeRoute = Literal["think", "act", "observe", "decide", "end"]


@dataclass(frozen=True)
class AgentGraphNodeOutcome:
    route: AgentGraphNodeRoute
    step_index: int | None = None
    invocation_id: str | None = None
    observation_summary: str = ""


class LangGraphAgentGraphRuntime:
    """Adapter for LangGraph-backed Think/Act/Observe/Decide execution."""

    graph_kind = "langgraph"

    def __init__(self, gateway: LangGraphGateway) -> None:
        self.gateway = gateway

    async def start(self, goal_id: str, proposal: AgentGoalProposal) -> None:
        await self.gateway.start(goal_id, proposal)

    async def resume(self, goal_id: str) -> AgentGoal:
        return await self.gateway.resume(goal_id)

    def steps_for_proposal(self, proposal: AgentGoalProposal) -> list[AgentStep]:
        return self.gateway.steps_for_proposal(proposal)


class LocalAgentGraphRuntime:
    """Local Think/Act/Observe/Decide graph adapter.

    This is intentionally shaped like a graph runtime boundary so it can be
    replaced by a LangGraph-backed implementation without changing AgentService
    or ToolInvocationRuntime.
    """

    graph_kind = "local"

    def __init__(
        self,
        state: AgentGraphStatePort,
        state_machine: AgentGoalStateMachine,
        plan_compiler: AgentGoalPlanCompiler,
        replanner: AgentReplanner | None = None,
    ) -> None:
        self._state = state
        self.state_machine = state_machine
        self.plan_compiler = plan_compiler
        self.replanner = replanner

    async def start(self, goal_id: str, proposal: AgentGoalProposal) -> None:
        outcome = await self.prepare_start(goal_id)
        await self._drive(goal_id, outcome, proposal=proposal)

    async def resume(self, goal_id: str) -> AgentGoal:
        outcome = await self.prepare_resume(goal_id)
        await self._drive(goal_id, outcome, proposal=None)
        return self._state.get_goal(goal_id)

    async def prepare_start(self, goal_id: str) -> AgentGraphNodeOutcome:
        goal = self._state.get_goal(goal_id)
        if goal.status in self.state_machine.terminal_statuses or goal.status in {"paused", "blocked"}:
            return AgentGraphNodeOutcome("end")
        if goal.status in {"draft", "pending"}:
            await self._update_goal(goal, patch=self.state_machine.start_goal(goal))
        return self.route_for_goal(goal_id)

    async def prepare_resume(self, goal_id: str) -> AgentGraphNodeOutcome:
        goal = self._state.get_goal(goal_id)
        if goal.status in self.state_machine.terminal_statuses:
            return AgentGraphNodeOutcome("end")

        checkpoint = self.state_machine.checkpoint(goal)
        blocked_index = checkpoint.resume_step_index
        if blocked_index is None:
            if goal.status in {"paused", "blocked"}:
                pause_reason = goal.pause_reason
                await self._update_goal(goal, patch=self.state_machine.start_goal(goal))
                if pause_reason == "user_interrupt" and goal.planner_kind == "manual":
                    return AgentGraphNodeOutcome("end")
            return self.route_for_goal(goal_id)

        act_step = goal.steps[blocked_index]
        if not act_step.tool_invocation_id:
            if goal.pause_reason == "budget_exhausted":
                act_step.status = "pending"
                act_step.decision = None
                act_step.decision_rationale = None
                await self._update_goal(
                    goal,
                    patch={
                        **self.state_machine.start_goal(goal),
                        "current_step": act_step.title,
                        "resume_mode": "budget_released",
                    },
                )
                return self.route_for_goal(goal_id)
            await self._update_goal(
                goal,
                patch=self.state_machine.fail_on_step(
                    goal,
                    blocked_index,
                    "Cannot resume because the blocked step has no tool invocation reference.",
                ),
            )
            return AgentGraphNodeOutcome("end")

        pause_reason = goal.pause_reason
        await self._update_goal(goal, patch={**self.state_machine.start_goal(goal), "current_step": act_step.title})
        if pause_reason == "missing_source_binding":
            act_step.tool_invocation_id = None
            act_step.status = "pending"
            act_step.decision = None
            act_step.tool_input_payload["agent_loop_attempt"] = (
                int(act_step.tool_input_payload.get("agent_loop_attempt") or 0) + 1
            )
            await self._update_goal(
                goal,
                patch={"current_step": act_step.title, "resume_mode": "source_binding_supplied"},
            )
            return AgentGraphNodeOutcome("act", blocked_index)

        invocation = await self._state.confirm_tool_invocation(
            act_step.tool_invocation_id
        )
        act_step.status = "pending"
        act_step.decision = None
        await self._update_goal(
            goal,
            patch={
                "current_step": act_step.title,
                "tool_invocation_id": invocation.id,
                "resume_mode": "governance_gate_released",
            },
        )
        return AgentGraphNodeOutcome("act", blocked_index, invocation.id)

    def route_for_goal(self, goal_id: str) -> AgentGraphNodeOutcome:
        goal = self._state.get_goal(goal_id)
        if goal.status in self.state_machine.terminal_statuses or goal.status in {"paused", "blocked"}:
            return AgentGraphNodeOutcome("end")

        for index, step in enumerate(goal.steps):
            if step.status not in {"pending", "running"}:
                continue
            if index == 0:
                return AgentGraphNodeOutcome("think", index)
            if index == len(goal.steps) - 1:
                return AgentGraphNodeOutcome(
                    "decide",
                    index,
                    observation_summary=self._latest_observation(goal),
                )
            if step.phase == "acting":
                return AgentGraphNodeOutcome("act", index, step.tool_invocation_id)
            if self._is_observe_step(goal, index):
                invocation_id = step.tool_invocation_id or goal.steps[index - 1].tool_invocation_id
                return AgentGraphNodeOutcome("observe", index, invocation_id)

        return AgentGraphNodeOutcome("end")

    async def run_think_node(
        self,
        goal_id: str,
        proposal: AgentGoalProposal,
    ) -> AgentGraphNodeOutcome:
        goal = self._state.get_goal(goal_id)
        think_step = goal.steps[0]
        if think_step.status == "completed":
            return self.route_for_goal(goal_id)

        self.state_machine.start_step(goal, 0, "thinking")
        memory_context = await self._memory_context_for_goal(goal)
        self._bind_memory_context_to_step(think_step, memory_context)
        think_step.reasoning = self._reasoning_for_proposal(proposal, memory_context)
        planned_tools = self._planned_tool_steps(proposal)
        think_step.next_plan_hint = planned_tools[0].tool_id if planned_tools else "direct_answer"
        await self._update_goal(goal, patch={"current_step": think_step.title, "phase": think_step.phase})
        await self._emit_thinking_delta(goal, think_step, planned_tools)
        await asyncio.sleep(0)
        await self._update_goal(
            goal,
            patch=self.state_machine.complete_step(
                goal,
                0,
                decision="continue",
                decision_rationale="The current context is sufficient to execute the next tool.",
            ),
        )
        if not planned_tools:
            await self._complete_without_tools(goal)
            return AgentGraphNodeOutcome("end")
        return self.route_for_goal(goal_id)

    async def run_act_node(
        self,
        goal_id: str,
        step_index: int | None,
        invocation_id: str | None = None,
    ) -> AgentGraphNodeOutcome:
        goal = self._state.get_goal(goal_id)
        if step_index is None or not (0 <= step_index < len(goal.steps) - 1):
            return self.route_for_goal(goal_id)
        act_step = goal.steps[step_index]
        if act_step.status == "completed":
            return self.route_for_goal(goal_id)
        budget = evaluate_agent_budget(goal)
        if budget.exhausted:
            await self._pause_on_budget(goal, step_index, budget)
            return AgentGraphNodeOutcome("end")

        self.state_machine.start_step(goal, step_index, "acting")
        tool_id = act_step.selected_tool_id
        if not tool_id:
            await self._update_goal(
                goal,
                patch=self.state_machine.fail_on_step(
                    goal,
                    step_index,
                    "Cannot execute an acting step without selected_tool_id.",
                ),
            )
            return AgentGraphNodeOutcome("end")

        await self._update_goal(goal, patch={"current_step": act_step.title, "selected_tool_id": tool_id})
        invocation = self._tool_invocation_or_none(invocation_id or act_step.tool_invocation_id or "")
        if invocation is None:
            attempt = int(act_step.tool_input_payload.get("agent_loop_attempt") or 0)
            invocation = await self._state.create_tool_invocation(
                ToolInvocationRequest(
                    conversation_id=goal.conversation_id,
                    tool_id=tool_id,
                    input={
                        **act_step.tool_input_payload,
                        "agent_goal_id": goal.id,
                        "agent_loop_iteration_id": f"{goal.id}:{act_step.id}:{attempt}",
                    },
                    initiator_surface="agent_loop",
                    initiator_actor="agent",
                    target_scope=act_step.tool_target_scope,
                    idempotency_key=f"agent-goal:{goal.id}:step:{act_step.id}:attempt:{attempt}",
                )
            )

        act_step.tool_invocation_id = invocation.id
        await self._update_goal(
            goal,
            patch={
                "current_step": act_step.title,
                "selected_tool_id": tool_id,
                "tool_invocation_id": invocation.id,
            },
        )

        if invocation.status in {"waiting_confirmation", "waiting_approval"}:
            await self._update_goal(
                goal,
                patch=self.state_machine.pause_on_gate(goal, step_index, invocation.status),
            )
            return AgentGraphNodeOutcome("end", step_index, invocation.id)
        if invocation.status == "failed":
            await self._update_goal(
                goal,
                patch=self.state_machine.fail_on_step(goal, step_index, invocation.summary),
            )
            return AgentGraphNodeOutcome("end", step_index, invocation.id)
        if invocation.result and invocation.result.requires_followup:
            await self._update_goal(
                goal,
                patch=self.state_machine.pause_on_followup(
                    goal,
                    step_index,
                    invocation.result.followup_reason or "requires_followup",
                    invocation.result.summary,
                ),
            )
            return AgentGraphNodeOutcome("end", step_index, invocation.id)

        await self._update_goal(
            goal,
            patch=self.state_machine.complete_step(goal, step_index, decision=None),
        )
        return AgentGraphNodeOutcome("observe", step_index + 1, invocation.id)

    async def run_observe_node(
        self,
        goal_id: str,
        step_index: int | None,
        invocation_id: str | None,
    ) -> AgentGraphNodeOutcome:
        goal = self._state.get_goal(goal_id)
        if step_index is None or not (0 < step_index < len(goal.steps) - 1):
            return self.route_for_goal(goal_id)
        observe_step = goal.steps[step_index]
        if observe_step.status == "completed":
            return self.route_for_goal(goal_id)

        act_step = goal.steps[step_index - 1]
        invocation = self._tool_invocation_or_none(
            invocation_id or observe_step.tool_invocation_id or act_step.tool_invocation_id or ""
        )
        if invocation is None:
            await self._update_goal(
                goal,
                patch=self.state_machine.fail_on_step(
                    goal,
                    step_index - 1,
                    "Cannot observe a tool action without its persisted ToolInvocation.",
                ),
            )
            return AgentGraphNodeOutcome("end")

        self.state_machine.start_step(goal, step_index, "observing")
        observe_step.tool_invocation_id = invocation.id
        observation_summary = invocation.result.summary if invocation.result else invocation.summary
        await self._update_goal(
            goal,
            patch={"current_step": observe_step.title, "tool_invocation_id": invocation.id},
        )
        await self._emit_observation_delta(goal, observe_step, invocation, observation_summary)
        await asyncio.sleep(0)
        await self._update_goal(
            goal,
            patch=self.state_machine.complete_step(
                goal,
                step_index,
                decision="continue",
                decision_rationale="The tool returned a usable result that can drive the next step.",
                observation_summary=observation_summary,
            ),
        )
        self._record_observation_progress(goal, invocation, observation_summary)
        await self._update_goal(
            goal,
            patch={
                **self._budget_usage_patch(goal),
                "observation_progress": (
                    "progressed"
                    if goal.no_progress_observations == 0
                    else "no_progress"
                ),
            },
        )
        budget = evaluate_agent_budget(goal)
        if budget.exhausted:
            await self._pause_on_budget(
                goal,
                self._next_budget_pause_step_index(goal, step_index),
                budget,
            )
            return AgentGraphNodeOutcome("end")
        await self._extend_goal_plan_after_tool_success(goal, step_index - 1)
        await self._replan_after_observation(goal, step_index, observation_summary)
        next_outcome = self.route_for_goal(goal_id)
        return AgentGraphNodeOutcome(
            next_outcome.route,
            next_outcome.step_index,
            next_outcome.invocation_id,
            observation_summary,
        )

    async def run_decide_node(
        self,
        goal_id: str,
        observation_summary: str = "",
    ) -> AgentGraphNodeOutcome:
        goal = self._state.get_goal(goal_id)
        if goal.status in self.state_machine.terminal_statuses:
            return AgentGraphNodeOutcome("end")
        budget = evaluate_agent_budget(goal)
        if budget.exhausted:
            await self._pause_on_budget(goal, len(goal.steps) - 1, budget)
            return AgentGraphNodeOutcome("end")

        decide_index = len(goal.steps) - 1
        decide_step = goal.steps[decide_index]
        last_observation = observation_summary or self._latest_observation(goal)
        if decide_step.status != "completed":
            self.state_machine.start_step(goal, decide_index, "deciding")
            await self._update_goal(goal, patch={"current_step": decide_step.title, "status": "running"})
            await asyncio.sleep(0)
            decision_rationale = self._decision_summary_from_goal(goal)
            next_plan_hint = self._next_plan_hint_from_goal(goal)
            self.state_machine.complete_step(
                goal,
                decide_index,
                decision="complete",
                decision_rationale=decision_rationale,
                observation_summary=last_observation,
                next_plan_hint=next_plan_hint,
            )
            await self._emit_decision_delta(
                goal,
                decide_step,
                decision_rationale,
                last_observation,
                next_plan_hint,
            )
        await self._update_goal(
            goal,
            patch=self.state_machine.complete_goal(goal, decide_index),
        )
        await self._persist_goal_memory_checkpoint(goal, last_observation)
        return AgentGraphNodeOutcome("end")

    async def _drive(
        self,
        goal_id: str,
        outcome: AgentGraphNodeOutcome,
        *,
        proposal: AgentGoalProposal | None,
    ) -> None:
        node_budget = max(12, self._state.get_goal(goal_id).max_steps * 3 + 4)
        current = outcome
        for _ in range(node_budget):
            if current.route == "end":
                return
            if current.route == "think":
                current = await self.run_think_node(
                    goal_id,
                    proposal or self.proposal_from_goal(self._state.get_goal(goal_id)),
                )
            elif current.route == "act":
                current = await self.run_act_node(goal_id, current.step_index, current.invocation_id)
            elif current.route == "observe":
                current = await self.run_observe_node(goal_id, current.step_index, current.invocation_id)
            else:
                current = await self.run_decide_node(goal_id, current.observation_summary)
        raise RuntimeError(f"Agent graph exceeded its node execution budget for goal {goal_id}.")

    @staticmethod
    def _is_observe_step(goal: AgentGoal, step_index: int) -> bool:
        return step_index > 0 and goal.steps[step_index - 1].phase == "acting"

    @staticmethod
    def _latest_observation(goal: AgentGoal) -> str:
        return next(
            (
                step.observation_summary
                for step in reversed(goal.steps)
                if step.phase == "observing" and step.observation_summary
            ),
            "",
        )

    @staticmethod
    def proposal_from_goal(goal: AgentGoal) -> AgentGoalProposal:
        planned_tools = [
            ToolPlanStep(
                tool_id=step.selected_tool_id,
                input_payload=dict(step.tool_input_payload),
                target_scope=step.tool_target_scope,
                reason=step.reasoning or "",
            )
            for step in goal.steps
            if step.phase == "acting" and step.selected_tool_id
        ]
        return AgentGoalProposal(
            goal_template=goal.goal_template or "autonomous_goal",
            title=goal.title,
            summary=goal.summary,
            goal_description=goal.goal_description or goal.summary,
            planner_kind=goal.planner_kind or "deterministic",
            suggested_autonomy_level=goal.autonomy_level,
            estimated_steps=max(1, len(planned_tools)),
            target_refs=list(goal.target_refs),
            planned_tools=planned_tools,
            query_keys=list(goal.query_keys),
        )

    async def _emit_thinking_delta(
        self,
        goal: AgentGoal,
        step: AgentStep,
        planned_tools: list[ToolPlanStep],
    ) -> None:
        delta = step.reasoning or "Agent is planning the next action from memory and available tools."
        patch = {
            "agent_goal_id": goal.id,
            "agent_step_id": step.id,
            "agent_step_phase": "thinking",
            "current_step": step.title,
            "stream_id": f"{goal.id}:{step.id}:thinking",
            "sequence": 1,
            "chunk_index": 0,
            "delta": delta,
            "full_text": delta,
            "is_final": True,
            "thinking_delta": delta,
            "thinking_full_text": delta,
            "memory_context_hash": step.memory_context_hash,
            "memory_context_summary": step.memory_context_summary,
            "memory_retrieval_query": step.memory_retrieval_query,
            "memory_retrieval_run_refs": step.memory_retrieval_run_refs,
            "retrieved_context_refs": step.retrieved_context_refs,
            "retrieved_context_summary": step.retrieved_context_summary,
            "planned_tool_ids": [tool_step.tool_id for tool_step in planned_tools],
            "agent_step": step.model_dump(),
        }
        await self._state.publish_goal_event(
            goal,
            "agent.step.thinking.delta",
            patch,
        )

    async def _emit_observation_delta(
        self,
        goal: AgentGoal,
        step: AgentStep,
        invocation: ToolInvocation,
        observation_summary: str,
    ) -> None:
        patch = {
            "agent_goal_id": goal.id,
            "agent_step_id": step.id,
            "agent_step_phase": "observing",
            "current_step": step.title,
            "tool_invocation_id": invocation.id,
            "observed_tool_id": invocation.tool_id,
            "observation_delta": observation_summary,
            "observation_summary": observation_summary,
            "object_refs": invocation.result.object_refs if invocation.result else [],
            "evidence_refs": invocation.result.evidence_refs if invocation.result else [],
            "next_recommended_tools": invocation.result.next_recommended_tools if invocation.result else [],
            "agent_step": step.model_dump(),
        }
        await self._state.publish_goal_event(
            goal,
            "agent.step.observation.delta",
            patch,
        )

    async def _emit_decision_delta(
        self,
        goal: AgentGoal,
        step: AgentStep,
        decision_rationale: str,
        observation_summary: str,
        next_plan_hint: str,
    ) -> None:
        patch = {
            "agent_goal_id": goal.id,
            "agent_step_id": step.id,
            "agent_step_phase": "deciding",
            "current_step": step.title,
            "decision": "complete",
            "decision_delta": decision_rationale,
            "decision_rationale": decision_rationale,
            "observation_summary": observation_summary,
            "next_plan_hint": next_plan_hint,
            "agent_step": step.model_dump(),
        }
        await self._state.publish_goal_event(
            goal,
            "agent.step.decision.delta",
            patch,
        )

    async def _complete_without_tools(self, goal: AgentGoal) -> None:
        if len(goal.steps) > 1:
            goal.steps[1].phase = "deciding"
            self.state_machine.complete_step(
                goal,
                1,
                decision="complete",
                observation_summary="The goal could be completed without a tool action.",
            )
        await self._update_goal(goal, patch=self.state_machine.complete_goal(goal, 1 if len(goal.steps) > 1 else None))
        await self._persist_goal_memory_checkpoint(goal, "The goal completed without tool execution.")

    def steps_for_proposal(self, proposal: AgentGoalProposal) -> list[AgentStep]:
        planned_tools = self._planned_tool_steps(proposal)
        if not planned_tools:
            return [
                AgentStep(id="step_think", title="Plan next action", status="pending"),
                AgentStep(id="step_decide", title="Decide next frontier", status="pending"),
            ]

        steps = [
            AgentStep(id="step_think", title="Plan next action", status="pending"),
        ]
        steps.extend(
            self._agent_steps_for_tool_plan(
                planned_tools,
                goal_template=proposal.goal_template,
                goal_description=proposal.goal_description,
                start_index=1,
            )
        )
        steps.append(AgentStep(id="step_decide", title="Decide next frontier", status="pending"))
        return steps

    def _planned_tool_steps(self, proposal: AgentGoalProposal) -> list[ToolPlanStep]:
        return self.plan_compiler.compile_tool_plan(proposal)

    async def _extend_goal_plan_after_tool_success(self, goal: AgentGoal, completed_act_step_index: int) -> None:
        completed_step = goal.steps[completed_act_step_index]
        if not self._is_replannable_system_image_step(completed_step):
            return
        if not (completed_step.selected_tool_id or "").startswith("system_image."):
            return
        if goal.steps[-1].status != "pending":
            return

        existing_tool_ids = {
            step.selected_tool_id
            for step in goal.steps
            if step.phase == "acting" and step.selected_tool_id
        }
        remaining_plan = [
            tool_step
            for tool_step in self.plan_compiler.compile_followup_tool_plan(goal)
            if tool_step.tool_id not in existing_tool_ids
        ]
        if not remaining_plan:
            return

        new_steps = self._agent_steps_for_tool_plan(
            remaining_plan,
            goal_template=str(completed_step.tool_input_payload.get("goal_template") or "system_image_build"),
            goal_description=str(completed_step.tool_input_payload.get("goal_description") or goal.summary),
            start_index=self._next_tool_plan_index(goal),
        )
        goal.steps[-1:-1] = new_steps
        await self._update_goal(
            goal,
            patch={
                "current_step": completed_step.title,
                "status": goal.status,
                "plan_extended": "system_image_state_replan",
                "replan_after_tool_id": completed_step.selected_tool_id,
                "added_tool_ids": ",".join(tool_step.tool_id for tool_step in remaining_plan),
            },
        )

    async def _replan_after_observation(
        self,
        goal: AgentGoal,
        observation_step_index: int,
        observation_summary: str,
    ) -> None:
        if self.replanner is None or goal.status != "running":
            return
        remaining_steps = self._pending_tool_plan_steps(goal)
        if not remaining_steps:
            return
        request = AgentReplanRequest(
            conversation=self._state.get_conversation(goal.conversation_id),
            goal=goal,
            observation_summary=observation_summary,
            completed_steps=self._completed_tool_plan_steps(goal),
            remaining_steps=remaining_steps,
        )
        try:
            decision = await self.replanner.replan(request)
        except Exception:
            decision = AgentReplanDecision.keep(
                "The replanner failed unexpectedly, so the validated pending plan was retained.",
                planner_kind="replanner_error",
            )

        record_model_usage(goal, decision.model_usage)
        await self._update_goal(
            goal,
            patch={
                **self._budget_usage_patch(goal),
                "model_usage_source": decision.model_usage.usage_source,
                "replan_model_calls": decision.model_usage.model_calls,
                "replan_input_tokens": decision.model_usage.input_tokens,
                "replan_output_tokens": decision.model_usage.output_tokens,
            },
        )
        budget = evaluate_agent_budget(goal)
        if budget.exhausted:
            await self._pause_on_budget(
                goal,
                self._next_budget_pause_step_index(goal, observation_step_index),
                budget,
            )
            return

        removed_tool_ids: list[str] = []
        added_tool_ids: list[str] = []
        if decision.action in {"replace_remaining", "complete"}:
            removed_tool_ids = [
                step.selected_tool_id
                for step in goal.steps[observation_step_index + 1:-1]
                if step.phase == "acting" and step.status == "pending" and step.selected_tool_id
            ]
            goal.steps[observation_step_index + 1:-1] = []

        if decision.action == "replace_remaining":
            new_steps = self._agent_steps_for_tool_plan(
                decision.planned_tools,
                goal_template=goal.goal_template or "autonomous_goal",
                goal_description=goal.goal_description or goal.summary,
                start_index=self._next_tool_plan_index(goal),
            )
            goal.steps[-1:-1] = new_steps
            added_tool_ids = [step.tool_id for step in decision.planned_tools]

        next_tools = self._pending_tool_plan_steps(goal)
        observed_step = goal.steps[observation_step_index]
        observed_step.next_plan_hint = next_tools[0].tool_id if next_tools else "complete"
        self._state.record_goal_audit(
            goal,
            action="agent.goal.replanned",
            status=goal.status,
            summary=f"Agent goal plan decision: {decision.action}",
            metadata={
                "planner_kind": decision.planner_kind,
                "confidence": decision.confidence,
                "rationale": decision.rationale,
                "removed_tool_ids": removed_tool_ids,
                "added_tool_ids": added_tool_ids,
                "observation_step_id": observed_step.id,
            },
        )
        await self._update_goal(
            goal,
            patch={
                "current_step": observed_step.title,
                "plan_replanned": decision.planner_kind,
                "replan_action": decision.action,
                "replan_rationale": decision.rationale,
                "removed_tool_ids": ",".join(removed_tool_ids),
                "added_tool_ids": ",".join(added_tool_ids),
                "next_plan_hint": observed_step.next_plan_hint,
            },
        )

    @staticmethod
    def _completed_tool_plan_steps(goal: AgentGoal) -> list[ToolPlanStep]:
        return [
            ToolPlanStep(
                tool_id=step.selected_tool_id,
                input_payload=dict(step.tool_input_payload),
                target_scope=step.tool_target_scope,
                reason=step.reasoning or "",
            )
            for step in goal.steps
            if step.phase == "acting"
            and step.status == "completed"
            and step.selected_tool_id
        ]

    @staticmethod
    def _pending_tool_plan_steps(goal: AgentGoal) -> list[ToolPlanStep]:
        return [
            ToolPlanStep(
                tool_id=step.selected_tool_id,
                input_payload=dict(step.tool_input_payload),
                target_scope=step.tool_target_scope,
                reason=step.reasoning or "",
            )
            for step in goal.steps
            if step.phase == "acting"
            and step.status == "pending"
            and step.selected_tool_id
        ]

    @staticmethod
    def _is_replannable_system_image_step(step: AgentStep) -> bool:
        goal_template = step.tool_input_payload.get("goal_template")
        if goal_template == "system_image_build":
            return True
        goal_description = str(step.tool_input_payload.get("goal_description") or "").lower()
        return "system image" in goal_description

    @staticmethod
    def _next_tool_plan_index(goal: AgentGoal) -> int:
        existing_indexes = [
            int(step.tool_input_payload["tool_plan_index"])
            for step in goal.steps
            if step.phase == "acting"
            and isinstance(step.tool_input_payload.get("tool_plan_index"), int)
        ]
        if existing_indexes:
            return max(existing_indexes) + 1
        return len([step for step in goal.steps if step.phase == "acting"]) + 1

    @staticmethod
    def _agent_steps_for_tool_plan(
        planned_tools: list[ToolPlanStep],
        *,
        goal_template: str,
        goal_description: str,
        start_index: int,
    ) -> list[AgentStep]:
        steps: list[AgentStep] = []
        for index, tool_step in enumerate(planned_tools, start=start_index):
            safe_tool_id = tool_step.tool_id.replace(".", "_")
            steps.extend(
                [
                    AgentStep(
                        id=f"step_act_{index}_{safe_tool_id}",
                        title=f"Execute {tool_step.tool_id}",
                        status="pending",
                        phase="acting",
                        reasoning=tool_step.reason,
                        selected_tool_id=tool_step.tool_id,
                        tool_input_payload={
                            **tool_step.input_payload,
                            "goal_template": goal_template,
                            "goal_description": goal_description,
                            "tool_plan_index": index,
                            "tool_plan_reason": tool_step.reason,
                        },
                        tool_target_scope=tool_step.target_scope,
                    ),
                    AgentStep(
                        id=f"step_observe_{index}_{safe_tool_id}",
                        title=f"Observe {tool_step.tool_id}",
                        status="pending",
                    ),
                ]
            )
        return steps

    async def _persist_goal_memory_checkpoint(self, goal: AgentGoal, observation_summary: str) -> None:
        conversation = self._state.get_conversation(goal.conversation_id)
        if any(
            message.metadata.get("agent_runtime") == "goal_completion"
            and message.metadata.get("agent_goal_id") == goal.id
            for message in conversation.messages
        ):
            return

        executed_tool_ids: list[str] = []
        tool_refs: list[str] = []
        object_refs: list[str] = []
        evidence_refs: list[str] = []
        for step in goal.steps:
            if step.phase != "acting" or not step.selected_tool_id:
                continue
            executed_tool_ids.append(step.selected_tool_id)
            if not step.tool_invocation_id:
                continue
            tool_refs.append(f"tool_invocation:{step.tool_invocation_id}")
            invocation = self._tool_invocation_or_none(step.tool_invocation_id)
            if invocation and invocation.result:
                object_refs.extend(invocation.result.object_refs)
                evidence_refs.extend(invocation.result.evidence_refs)

        compact_object_refs = list(dict.fromkeys(object_refs))[:12]
        compact_evidence_refs = list(dict.fromkeys(evidence_refs))[:12]
        summary_lines = [
            f"Completed AgentGoal: {goal.title}",
            f"Decision: {self._decision_summary_from_goal(goal)}",
            f"Executed tools: {', '.join(executed_tool_ids) if executed_tool_ids else 'none'}",
            f"Latest observation: {observation_summary or 'No tool observation was produced.'}",
        ]
        if compact_object_refs:
            summary_lines.append(f"Objects: {', '.join(compact_object_refs)}")
        if compact_evidence_refs:
            summary_lines.append(f"Evidence: {', '.join(compact_evidence_refs)}")

        completion_message = await self._state.append_assistant_message(
            goal.conversation_id,
            "\n".join(summary_lines),
            metadata={
                "agent_runtime": "goal_completion",
                "agent_goal_id": goal.id,
                "goal_template": goal.goal_template or "autonomous_goal",
                "executed_tool_ids": executed_tool_ids,
                "memory_checkpoint_reason": "agent_goal_completed",
            },
            tool_refs=tool_refs,
            object_refs=compact_object_refs,
        )
        await self._state.create_memory_checkpoint(
            conversation_id=goal.conversation_id,
            agent_goal_id=goal.id,
        )
        project_id = goal.project_id or conversation.project_id
        if project_id:
            link_refs = [
                (target_ref, "supports", 0.9)
                for target_ref in goal.target_refs
                if target_ref.startswith(("project:", "version:", "us:", "system_image:"))
            ]
            if self._is_system_image_goal(goal):
                link_refs.append((f"system_image:{project_id}", "supports", 0.9))
            self._state.record_memory_item(
                memory_scope="project_long_term",
                owner_ref=f"project:{project_id}",
                summary="\n".join(summary_lines),
                source_refs=[
                    f"agent_goal:{goal.id}",
                    f"conversation:{goal.conversation_id}",
                    f"conversation_message:{completion_message.id}",
                    *tool_refs,
                ],
                object_refs=compact_object_refs,
                evidence_refs=compact_evidence_refs,
                link_refs=link_refs,
            )

    def _tool_invocation_or_none(self, invocation_id: str) -> ToolInvocation | None:
        return self._state.get_tool_invocation_or_none(invocation_id)

    @staticmethod
    def _is_system_image_goal(goal: AgentGoal) -> bool:
        if any(step.tool_input_payload.get("goal_template") == "system_image_build" for step in goal.steps):
            return True
        return "system image" in goal.title.lower() or "system image" in goal.summary.lower()

    async def _update_goal(self, goal: AgentGoal, *, patch: dict[str, Any]) -> None:
        self._state.persist_goal(goal)
        event_patch = self._event_patch_for_goal(goal, patch)
        self._audit_goal_patch(goal, event_patch)
        await self._state.publish_goal_event(
            goal,
            "agent.goal.updated",
            event_patch,
        )
        current_step = self._current_step_for_patch(goal, event_patch)
        if current_step is not None:
            await self._state.publish_goal_event(
                goal,
                "agent.step.updated",
                {
                    **event_patch,
                    "agent_goal_id": goal.id,
                    "agent_step_id": current_step.id,
                    "agent_step_phase": current_step.phase,
                    "agent_step_status": current_step.status,
                    "agent_step": current_step.model_dump(),
                },
            )

    @staticmethod
    def _current_step_for_patch(goal: AgentGoal, patch: dict[str, Any]) -> AgentStep | None:
        step_id = patch.get("agent_step_id")
        if isinstance(step_id, str):
            return next((step for step in goal.steps if step.id == step_id), None)
        return None

    def _event_patch_for_goal(self, goal: AgentGoal, patch: dict[str, Any]) -> dict[str, Any]:
        event_patch = dict(patch)
        current_step_index = self.state_machine.current_step_index(goal)
        if current_step_index is not None and 0 <= current_step_index < len(goal.steps):
            current_step = goal.steps[current_step_index]
            event_patch.setdefault("agent_step_id", current_step.id)
            if current_step.tool_invocation_id:
                event_patch.setdefault("tool_invocation_id", current_step.tool_invocation_id)
            if current_step.phase:
                event_patch.setdefault("agent_step_phase", current_step.phase)
        return event_patch

    def _audit_goal_patch(self, goal: AgentGoal, patch: dict[str, Any]) -> None:
        lifecycle_transition = patch.get("lifecycle_transition")
        if not lifecycle_transition:
            return
        status = patch.get("status", goal.status)
        if lifecycle_transition == "started":
            action = "agent.goal.started"
            summary = f"Agent goal started: {goal.title}"
        elif lifecycle_transition == "resumed":
            action = "agent.goal.resumed"
            summary = f"Agent goal resumed: {goal.title}"
        elif lifecycle_transition == "budget_exhausted":
            action = "agent.goal.budget_exhausted"
            reason = goal.budget_exhausted_reason or "runtime_budget"
            summary = f"Agent goal paused because {reason} was exhausted: {goal.title}"
        elif lifecycle_transition == "paused":
            action = "agent.goal.paused"
            summary = f"Agent goal paused: {goal.title}"
        elif lifecycle_transition == "completed":
            action = "agent.goal.completed"
            summary = f"Agent goal completed: {goal.title}"
        elif lifecycle_transition == "failed":
            action = "agent.goal.failed"
            summary = f"Agent goal failed: {goal.title}"
        elif lifecycle_transition == "cancelled":
            action = "agent.goal.cancelled"
            summary = f"Agent goal cancelled: {goal.title}"
        else:
            action = "agent.goal.updated"
            summary = f"Agent goal updated: {goal.title}"
        self._state.record_goal_audit(
            goal,
            action=action,
            status=status,
            summary=summary,
            metadata={"patch": patch},
        )

    async def _pause_on_budget(
        self,
        goal: AgentGoal,
        step_index: int,
        decision: AgentBudgetDecision,
    ) -> None:
        await self._update_goal(
            goal,
            patch={
                **self.state_machine.pause_on_budget(
                    goal,
                    step_index,
                    reason=decision.reason or "runtime_budget",
                    summary=decision.summary or "The AgentGoal runtime budget was exhausted.",
                ),
                **self._budget_usage_patch(goal),
            },
        )

    @staticmethod
    def _budget_usage_patch(goal: AgentGoal) -> dict[str, Any]:
        return {
            "max_steps": goal.max_steps,
            "max_model_calls": goal.max_model_calls,
            "max_thinking_tokens": goal.max_thinking_tokens,
            "max_runtime_seconds": goal.max_runtime_seconds,
            "max_no_progress_observations": goal.max_no_progress_observations,
            "steps_completed": goal.steps_completed,
            "model_calls_used": goal.model_calls_used,
            "thinking_input_tokens_used": goal.thinking_input_tokens_used,
            "thinking_output_tokens_used": goal.thinking_output_tokens_used,
            "thinking_tokens_used": goal.thinking_tokens_used,
            "no_progress_observations": goal.no_progress_observations,
            "last_progress_at": goal.last_progress_at,
            "budget_exhausted_reason": goal.budget_exhausted_reason,
        }

    @staticmethod
    def _record_observation_progress(
        goal: AgentGoal,
        invocation: ToolInvocation,
        observation_summary: str,
    ) -> None:
        result = invocation.result
        fingerprint = observation_progress_fingerprint(
            tool_id=invocation.tool_id,
            status=invocation.status,
            summary=observation_summary,
            object_refs=result.object_refs if result else (),
            evidence_refs=result.evidence_refs if result else (),
            next_recommended_tools=result.next_recommended_tools if result else (),
            requires_followup=result.requires_followup if result else False,
        )
        record_observation_progress(
            goal,
            fingerprint=fingerprint,
            occurred_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _next_budget_pause_step_index(goal: AgentGoal, after_index: int) -> int:
        return next(
            (
                index
                for index in range(after_index + 1, len(goal.steps))
                if goal.steps[index].status in {"pending", "running"}
            ),
            min(max(after_index, 0), len(goal.steps) - 1),
        )

    async def _memory_context_for_goal(self, goal: AgentGoal) -> AgentMemoryContext:
        return await self._state.build_memory_context(goal)

    def _bind_memory_context_to_step(self, step: AgentStep, memory_context: AgentMemoryContext) -> None:
        step.memory_context_hash = memory_context_hash(memory_context)
        step.memory_context_summary = memory_context_summary(memory_context)
        step.memory_recent_turn_count = memory_context.recent_turn_count
        step.memory_checkpoint_count = memory_context.checkpoint_count
        step.memory_retrieval_query = memory_context.retrieval_query
        step.memory_retrieval_run_refs = memory_context.retrieval_run_refs
        step.retrieved_context_refs = memory_context.retrieved_context_refs
        step.retrieved_context_summary = memory_context.retrieved_context_summary
        step.available_tool_ids = list(self._state.available_tool_ids())

    @staticmethod
    def _reasoning_for_proposal(proposal: AgentGoalProposal, memory_context: AgentMemoryContext | None = None) -> str:
        memory_summary = ""
        if memory_context is not None:
            memory_summary = (
                " Memory context includes "
                f"{memory_context.recent_turn_count} recent turns and "
                f"{memory_context.checkpoint_count} checkpoints."
            )
        if proposal.goal_template == "project_setup":
            return (
                "Create the project shell first, then guide the user through source import and system image initialization."
                + memory_summary
            )
        if proposal.goal_template == "system_image_build":
            return (
                "Build the system image as a durable tool chain: register sources, ingest evidence, "
                "materialize context, then initialize the baseline."
                + memory_summary
            )
        if proposal.goal_template == "quality_loop":
            return (
                "Start from the next unblocked quality asset step, materialize that asset, and then recommend "
                "the most efficient follow-up action."
                + memory_summary
            )
        return "Use the proposal context to execute the next best step." + memory_summary

    @staticmethod
    def _decision_summary_from_goal(goal: AgentGoal) -> str:
        if "System Image" in goal.title:
            return "The Official System Image is ready enough to guide version planning, US analysis, test generation, and release scoring."
        if "quality loop" in goal.title.lower():
            return "The next quality frontier is ready; continue into cases, automation, or execution based on the updated asset lanes."
        if "Create project" in goal.title:
            return "The draft project is ready, so the next frontier is source connection and system image initialization."
        return "The immediate goal step is complete."

    @staticmethod
    def _next_plan_hint_from_goal(goal: AgentGoal) -> str:
        if "System Image" in goal.title:
            return "query.system_image.status"
        if "quality loop" in goal.title.lower():
            return "quality.case.generate"
        if "Create project" in goal.title:
            return "project.import_sources"
        return "direct_answer"


AgentGraphRuntimeKind = Literal["local", "langgraph"]


__all__ = [
    "AgentGraphNodeOutcome",
    "AgentGraphNodeRoute",
    "AgentGraphRuntime",
    "AgentGraphRuntimeKind",
    "LangGraphAgentGraphRuntime",
    "LangGraphGateway",
    "LocalAgentGraphRuntime",
]
