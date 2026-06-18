from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import uuid4

from .agent_memory import AgentMemoryContext, memory_context_hash, memory_context_summary
from .agent_goal_plan_compiler import AgentGoalPlanCompiler
from .agent_goal_state_machine import AgentGoalStateMachine
from .agent_runtime_models import AgentGoalProposal, ToolPlanStep
from .models import AgentGoal, AgentStep, ToolInvocation, ToolInvocationRequest

if TYPE_CHECKING:
    from .store import ApplicationStore


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

    def __init__(self, store: "ApplicationStore", state_machine: AgentGoalStateMachine) -> None:
        self.store = store
        self.state_machine = state_machine
        self.plan_compiler = AgentGoalPlanCompiler(store)

    async def start(self, goal_id: str, proposal: AgentGoalProposal) -> None:
        goal = self.store.get_agent_goal(goal_id)
        await self._update_goal(goal, patch=self.state_machine.start_goal(goal))

        think_step = goal.steps[0]
        self.state_machine.start_step(goal, 0, "thinking")
        memory_context = self._memory_context_for_goal(goal)
        self._bind_memory_context_to_step(think_step, memory_context)
        think_step.reasoning = self._reasoning_for_proposal(proposal, memory_context)
        planned_tools = self._planned_tool_steps(proposal)
        think_step.next_plan_hint = planned_tools[0].tool_id if planned_tools else "direct_answer"
        await self._update_goal(goal, patch={"current_step": think_step.title, "phase": think_step.phase})
        await asyncio.sleep(0.05)
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
            return

        await self._run_tool_steps(goal, start_step_index=1)

    async def resume(self, goal_id: str) -> AgentGoal:
        goal = self.store.get_agent_goal(goal_id)
        checkpoint = self.state_machine.checkpoint(goal)
        blocked_index = checkpoint.resume_step_index
        if blocked_index is None:
            await self._update_goal(goal, patch=self.state_machine.start_goal(goal))
            return goal

        act_step = goal.steps[blocked_index]
        if not act_step.tool_invocation_id:
            await self._update_goal(
                goal,
                patch=self.state_machine.fail_on_step(
                    goal,
                    blocked_index,
                    "Cannot resume because the blocked step has no tool invocation reference.",
                ),
            )
            return goal

        pause_reason = goal.pause_reason
        await self._update_goal(goal, patch={**self.state_machine.start_goal(goal), "current_step": act_step.title})
        if pause_reason == "missing_source_binding":
            act_step.tool_invocation_id = None
            await self._run_tool_steps(goal, start_step_index=blocked_index)
            return goal
        invocation = await self.store.confirm_tool_invocation(act_step.tool_invocation_id)
        await self._run_tool_steps(goal, start_step_index=blocked_index, first_invocation=invocation)
        return goal

    async def _run_tool_steps(
        self,
        goal: AgentGoal,
        *,
        start_step_index: int,
        first_invocation: ToolInvocation | None = None,
    ) -> None:
        last_observation = ""
        step_index = start_step_index
        while step_index < len(goal.steps) - 1:
            act_step = goal.steps[step_index]
            if act_step.phase not in {None, "acting"}:
                break
            if self._budget_exhausted(goal):
                await self._update_goal(goal, patch=self.state_machine.pause_on_budget(goal, step_index))
                return

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
                return

            await self._update_goal(goal, patch={"current_step": act_step.title, "selected_tool_id": tool_id})
            if first_invocation is not None:
                invocation = first_invocation
                first_invocation = None
            else:
                invocation = await self.store.create_tool_invocation(
                    ToolInvocationRequest(
                        conversation_id=goal.conversation_id,
                        tool_id=tool_id,
                        input={
                            **act_step.tool_input_payload,
                            "agent_goal_id": goal.id,
                            "agent_loop_iteration_id": f"iter_{uuid4().hex[:8]}",
                        },
                        initiator_surface="agent_loop",
                        initiator_actor="agent",
                        target_scope=act_step.tool_target_scope,
                    )
                )
            act_step.tool_invocation_id = invocation.id

            if invocation.status in {"waiting_confirmation", "waiting_approval"}:
                await self._update_goal(
                    goal,
                    patch=self.state_machine.pause_on_gate(goal, step_index, invocation.status),
                )
                return

            if invocation.status == "failed":
                await self._update_goal(
                    goal,
                    patch=self.state_machine.fail_on_step(goal, step_index, invocation.summary),
                )
                return

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
                return

            self.state_machine.complete_step(goal, step_index, decision=None)
            observe_step = goal.steps[step_index + 1]
            self.state_machine.start_step(goal, step_index + 1, "observing")
            observe_step.tool_invocation_id = invocation.id
            last_observation = invocation.result.summary if invocation.result else invocation.summary
            await self._update_goal(goal, patch={"current_step": observe_step.title, "tool_invocation_id": invocation.id})
            await asyncio.sleep(0.05)
            await self._update_goal(
                goal,
                patch=self.state_machine.complete_step(
                    goal,
                    step_index + 1,
                    decision="continue",
                    decision_rationale="The tool returned a usable result that can drive the next step.",
                    observation_summary=last_observation,
                ),
            )
            await self._extend_goal_plan_after_tool_success(goal, step_index)
            step_index += 2

        if self._budget_exhausted(goal):
            await self._update_goal(
                goal,
                patch=self.state_machine.pause_on_budget(goal, min(step_index, len(goal.steps) - 1)),
            )
            return

        decide_step = goal.steps[-1]
        self.state_machine.start_step(goal, len(goal.steps) - 1, "deciding")
        await self._update_goal(goal, patch={"current_step": decide_step.title, "status": "running"})
        await asyncio.sleep(0.05)
        self.state_machine.complete_step(
            goal,
            len(goal.steps) - 1,
            decision="complete",
            decision_rationale=self._decision_summary_from_goal(goal),
            observation_summary=last_observation,
            next_plan_hint=self._next_plan_hint_from_goal(goal),
        )
        await self._update_goal(
            goal,
            patch=self.state_machine.complete_goal(goal, len(goal.steps) - 1),
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
        if completed_step.selected_tool_id != "system_image.sources.register":
            return
        if not self._is_replannable_system_image_step(completed_step):
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
                "plan_extended": "system_image_followup",
                "added_tool_ids": ",".join(tool_step.tool_id for tool_step in remaining_plan),
            },
        )

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

    async def _update_goal(self, goal: AgentGoal, *, patch: dict[str, str]) -> None:
        self.store.conversation_repository.upsert_goal(goal)
        self.store._upsert_goal_in_conversation(goal)
        event_patch = self._event_patch_for_goal(goal, patch)
        self._audit_goal_patch(goal, event_patch)
        await self.store._push_goal_event(
            goal.id,
            "agent.goal.updated",
            "patch",
            event_patch,
            [["agent-goal", goal.id]],
        )
        await self.store._push_event(
            goal.conversation_id,
            "agent.goal.updated",
            "agent_goal",
            goal.id,
            "patch",
            event_patch,
            [["conversation", goal.conversation_id]],
        )

    def _event_patch_for_goal(self, goal: AgentGoal, patch: dict[str, str]) -> dict[str, str]:
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

    def _audit_goal_patch(self, goal: AgentGoal, patch: dict[str, str]) -> None:
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
            summary = f"Agent goal paused because max_steps={goal.max_steps} was reached: {goal.title}"
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
        self.store.record_agent_goal_audit_event(
            goal,
            action=action,
            status=status,
            summary=summary,
            metadata={"patch": patch},
        )

    @staticmethod
    def _budget_exhausted(goal: AgentGoal) -> bool:
        return goal.steps_completed >= goal.max_steps

    def _memory_context_for_goal(self, goal: AgentGoal) -> AgentMemoryContext:
        conversation = self.store.get_conversation(goal.conversation_id)
        if hasattr(self.store, "agent_memory"):
            return self.store.agent_memory.build_context(conversation, tools=self.store.tools)
        return AgentMemoryContext(
            system_prompt=f"Nasus Agent scoped to {conversation.space_type}:{conversation.space_id}.",
            context_snapshot=f"[space]\nspace_type={conversation.space_type}\nspace_id={conversation.space_id}",
            history_snapshot="No prior conversation memory.",
            recent_turn_count=0,
            checkpoint_count=0,
        )

    def _bind_memory_context_to_step(self, step: AgentStep, memory_context: AgentMemoryContext) -> None:
        step.memory_context_hash = memory_context_hash(memory_context)
        step.memory_context_summary = memory_context_summary(memory_context)
        step.memory_recent_turn_count = memory_context.recent_turn_count
        step.memory_checkpoint_count = memory_context.checkpoint_count
        step.available_tool_ids = [tool.tool_id for tool in self.store.tools]

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


def selected_agent_graph_runtime_kind() -> AgentGraphRuntimeKind:
    raw_value = os.getenv("NASUS_AGENT_GRAPH_RUNTIME", "local").strip().lower()
    if raw_value in {"", "local"}:
        return "local"
    if raw_value == "langgraph":
        return "langgraph"
    raise RuntimeError(
        "NASUS_AGENT_GRAPH_RUNTIME must be either 'local' or 'langgraph'. "
        f"Received: {raw_value!r}."
    )


def build_agent_graph_runtime(
    store: "ApplicationStore",
    state_machine: AgentGoalStateMachine,
    *,
    graph_kind: AgentGraphRuntimeKind | None = None,
    langgraph_gateway: LangGraphGateway | None = None,
) -> AgentGraphRuntime:
    selected_kind = graph_kind or selected_agent_graph_runtime_kind()
    if selected_kind == "local":
        return LocalAgentGraphRuntime(store, state_machine)
    if langgraph_gateway is None:
        from .langgraph_agent_gateway import LangGraphAgentLoopGateway

        langgraph_gateway = LangGraphAgentLoopGateway(store, state_machine)
    return LangGraphAgentGraphRuntime(langgraph_gateway)
