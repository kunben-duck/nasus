from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from .agent_goal_state_machine import AgentGoalStateMachine
from .agent_runtime_config import LangGraphGatewayConfig, langgraph_gateway_config_from_env
from .agent_runtime_models import AgentGoalProposal
from .models import AgentGoal, AgentStep

if TYPE_CHECKING:
    from .agent_graph_runtime import AgentGraphRuntime
    from .store import ApplicationStore


class _AgentLoopGraphState(TypedDict, total=False):
    operation: str
    goal_id: str
    proposal: AgentGoalProposal
    goal: AgentGoal


class LangGraphAgentLoopGateway:
    """LangGraph-backed Agent Loop gateway.

    LangGraph owns the graph execution boundary. The node implementation
    delegates domain-safe work to the existing AgentGraphRuntime so every
    action still passes through ToolInvocationRuntime, policy gates, and audit.
    """

    def __init__(
        self,
        store: "ApplicationStore",
        state_machine: AgentGoalStateMachine,
        *,
        config: LangGraphGatewayConfig | None = None,
        delegate_runtime: "AgentGraphRuntime | None" = None,
        compiled_graph: Any | None = None,
    ) -> None:
        from .agent_graph_runtime import LocalAgentGraphRuntime

        self.store = store
        self.config = config or langgraph_gateway_config_from_env()
        self.delegate_runtime: "AgentGraphRuntime" = delegate_runtime or LocalAgentGraphRuntime(store, state_machine)
        self._compiled_graph = compiled_graph

    async def start(self, goal_id: str, proposal: AgentGoalProposal) -> None:
        graph = self._graph()
        await graph.ainvoke({"operation": "start", "goal_id": goal_id, "proposal": proposal})

    async def resume(self, goal_id: str) -> AgentGoal:
        graph = self._graph()
        state = await graph.ainvoke({"operation": "resume", "goal_id": goal_id})
        goal = state.get("goal") if isinstance(state, dict) else None
        if isinstance(goal, AgentGoal):
            return goal
        return self.store.get_agent_goal(goal_id)

    def steps_for_proposal(self, proposal: AgentGoalProposal) -> list[AgentStep]:
        return self.delegate_runtime.steps_for_proposal(proposal)

    def _graph(self) -> Any:
        if self._compiled_graph is None:
            self._compiled_graph = self._compile_graph()
        return self._compiled_graph

    def _compile_graph(self) -> Any:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError(
                "LangGraph graph runtime is selected, but the langgraph package is not installed. "
                "Install apps/api/requirements.txt or set NASUS_AGENT_GRAPH_RUNTIME=local."
            ) from exc

        graph = StateGraph(_AgentLoopGraphState)
        graph.add_node("dispatch_agent_loop", self._dispatch)
        graph.add_edge(START, "dispatch_agent_loop")
        graph.add_edge("dispatch_agent_loop", END)
        return graph.compile()

    async def _dispatch(self, state: _AgentLoopGraphState) -> dict[str, AgentGoal]:
        operation = state.get("operation")
        goal_id = state["goal_id"]
        if operation == "start":
            proposal = state.get("proposal")
            if proposal is None:
                raise RuntimeError("LangGraph start operation requires an AgentGoalProposal.")
            await self.delegate_runtime.start(goal_id, proposal)
            return {"goal": self.store.get_agent_goal(goal_id)}
        if operation == "resume":
            goal = await self.delegate_runtime.resume(goal_id)
            return {"goal": goal}
        raise RuntimeError(f"Unsupported LangGraph Agent Loop operation: {operation!r}.")
