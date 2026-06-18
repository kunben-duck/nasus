from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .agent_goal_state_machine import AgentGoalRuntimeCheckpoint, AgentGoalStateMachine
from .agent_graph_runtime import AgentGraphRuntime, LangGraphGateway, build_agent_graph_runtime
from .agent_runtime_models import AgentGoalProposal
from .models import AgentGoal, AgentGoalCreateRequest

if TYPE_CHECKING:
    from .store import ApplicationStore


class AgentLoopRuntime:
    """Owns AgentGoal lifecycle and delegates graph execution to an AgentGraphRuntime."""

    def __init__(
        self,
        store: "ApplicationStore",
        graph_runtime: AgentGraphRuntime | None = None,
        langgraph_gateway: LangGraphGateway | None = None,
    ) -> None:
        self.store = store
        self.state_machine = AgentGoalStateMachine()
        self.graph_runtime: AgentGraphRuntime = graph_runtime or build_agent_graph_runtime(
            store,
            self.state_machine,
            langgraph_gateway=langgraph_gateway,
        )

    @property
    def graph_kind(self) -> str:
        return self.graph_runtime.graph_kind

    async def start_goal(self, conversation_id: str, proposal: AgentGoalProposal) -> AgentGoal:
        conversation = self.store.get_conversation(conversation_id)
        bound_proposal = self._bind_conversation_context(conversation, proposal)
        goal = self.store.create_agent_goal(
            AgentGoalCreateRequest(
                conversation_id=conversation_id,
                title=bound_proposal.title,
                summary=bound_proposal.summary,
                autonomy_level=bound_proposal.suggested_autonomy_level,
                project_id=conversation.project_id,
                us_id=self._goal_us_id(conversation, bound_proposal),
                steps=self.graph_runtime.steps_for_proposal(bound_proposal),
            )
        )
        self.store.record_agent_goal_audit_event(
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

        await self.store._push_event(
            conversation_id,
            "conversation.agent_goal.proposed",
            "agent_goal",
            goal.id,
            "append",
            {
                "goal_id": goal.id,
                "status": goal.status,
                "title": goal.title,
                "graph_kind": self.graph_kind,
            },
            [["conversation", conversation_id]],
        )
        if bound_proposal.kickoff_message:
            await self.store.append_message(
                conversation_id,
                "assistant",
                bound_proposal.kickoff_message,
                metadata={
                    "agent_runtime": "goal_kickoff",
                    "goal_template": bound_proposal.goal_template,
                    "graph_kind": self.graph_kind,
                },
            )

        await self.graph_runtime.start(goal.id, bound_proposal)
        return goal

    async def resume_goal(self, goal_id: str) -> AgentGoal:
        return await self.graph_runtime.resume(goal_id)

    def checkpoint(self, goal_id: str) -> AgentGoalRuntimeCheckpoint:
        return self.state_machine.checkpoint(self.store.get_agent_goal(goal_id))

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
