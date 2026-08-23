from __future__ import annotations

from dataclasses import replace

from .agent_models import AgentGoal, AgentGoalCreateRequest
from .graph import AgentGraphRuntime
from .ports import AgentLoopStatePort
from ...domain.agent.runtime_models import AgentGoalProposal
from ...domain.agent.state_machine import AgentGoalRuntimeCheckpoint, AgentGoalStateMachine


class AgentLoopRuntime:
    """Owns AgentGoal lifecycle and delegates graph execution to an AgentGraphRuntime."""

    def __init__(
        self,
        state: AgentLoopStatePort,
        graph_runtime: AgentGraphRuntime,
        state_machine: AgentGoalStateMachine | None = None,
    ) -> None:
        self._state = state
        self.state_machine = state_machine or AgentGoalStateMachine()
        self.graph_runtime = graph_runtime

    @property
    def graph_kind(self) -> str:
        return self.graph_runtime.graph_kind

    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        conversation = self._state.get_conversation(conversation_id)
        bound_proposal = self._bind_conversation_context(conversation, proposal)
        goal = self._state.create_goal(
            AgentGoalCreateRequest(
                conversation_id=conversation_id,
                title=bound_proposal.title,
                summary=bound_proposal.summary,
                autonomy_level=bound_proposal.suggested_autonomy_level,
                max_steps=bound_proposal.max_steps,
                max_model_calls=bound_proposal.max_model_calls,
                max_thinking_tokens=bound_proposal.max_thinking_tokens,
                max_runtime_seconds=bound_proposal.max_runtime_seconds,
                max_no_progress_observations=(
                    bound_proposal.max_no_progress_observations
                ),
                project_id=conversation.project_id,
                us_id=self._goal_us_id(conversation, bound_proposal),
                goal_template=bound_proposal.goal_template,
                goal_description=bound_proposal.goal_description,
                target_refs=bound_proposal.target_refs,
                query_keys=bound_proposal.query_keys,
                planner_kind=bound_proposal.planner_kind,
                planning_summary=self._planning_summary(bound_proposal),
                model_calls_used=bound_proposal.planning_usage.model_calls,
                thinking_input_tokens_used=bound_proposal.planning_usage.input_tokens,
                thinking_output_tokens_used=bound_proposal.planning_usage.output_tokens,
                steps=self.graph_runtime.steps_for_proposal(bound_proposal),
            )
        )
        self._state.record_goal_audit(
            goal,
            action="agent.goal.proposed",
            status=goal.status,
            summary=f"Agent goal proposed from conversation: {goal.title}",
            metadata={
                "goal_template": bound_proposal.goal_template,
                "target_refs": bound_proposal.target_refs,
                "planned_tool_ids": [step.selected_tool_id for step in goal.steps if step.selected_tool_id],
                "graph_kind": self.graph_kind,
            },
        )

        await self._state.publish_goal_proposed(
            goal,
            graph_kind=self.graph_kind,
        )
        if bound_proposal.kickoff_message:
            await self._state.append_assistant_message(
                conversation_id,
                bound_proposal.kickoff_message,
                metadata={
                    "agent_runtime": "goal_kickoff",
                    "goal_template": bound_proposal.goal_template,
                    "graph_kind": self.graph_kind,
                },
            )

        await self.graph_runtime.start(goal.id, bound_proposal)
        # Graph execution may run in another process or persistence session.
        # Reload the committed aggregate instead of relying on shared object
        # identity with an in-memory adapter.
        return self._state.get_goal(goal.id)

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        return await self.graph_runtime.resume(goal_id)

    def checkpoint(self, goal_id: str) -> AgentGoalRuntimeCheckpoint:
        return self.state_machine.checkpoint(self._state.get_goal(goal_id))

    @staticmethod
    def _bind_conversation_context(conversation, proposal: AgentGoalProposal) -> AgentGoalProposal:
        if not conversation.project_id:
            return proposal
        project_ref = f"project:{conversation.project_id}"
        if project_ref in proposal.target_refs:
            return proposal
        return replace(proposal, target_refs=[*proposal.target_refs, project_ref])

    @staticmethod
    def _goal_us_id(conversation, proposal: AgentGoalProposal) -> str | None:
        if conversation.us_id:
            return conversation.us_id
        proposed_us_id = proposal.initial_tool_input.get("us_id")
        if isinstance(proposed_us_id, str) and proposed_us_id:
            return proposed_us_id
        return None

    @staticmethod
    def _planning_summary(proposal: AgentGoalProposal) -> str:
        tool_ids = [step.tool_id for step in proposal.planned_tools]
        if not tool_ids and proposal.initial_tool_id:
            tool_ids = [proposal.initial_tool_id]
        tool_summary = ", ".join(tool_ids) if tool_ids else "state-aware compiler"
        return (
            f"template={proposal.goal_template}; autonomy={proposal.suggested_autonomy_level}; "
            f"estimated_steps={proposal.estimated_steps}; tools={tool_summary}"
        )


__all__ = ["AgentLoopRuntime"]
