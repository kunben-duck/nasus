from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Optional, TypedDict

from ...application.agent.agent_models import AgentGoal, AgentStep
from ...application.agent.graph import AgentGraphNodeOutcome, AgentGraphNodeRoute
from ...application.agent.plans import AgentGoalPlanCompiler
from ...application.agent.ports import AgentGraphStatePort
from ...domain.agent.runtime_models import AgentGoalProposal, agent_goal_proposal_from_payload
from ...domain.agent.state_machine import AgentGoalStateMachine
from ..config.agent_runtime_config import LangGraphGatewayConfig, langgraph_gateway_config_from_env

if TYPE_CHECKING:
    from ...application.agent.graph import LocalAgentGraphRuntime
    from ...application.agent.replanning import AgentReplanner


class _AgentLoopGraphState(TypedDict, total=False):
    operation: str
    goal_id: str
    proposal_payload: dict[str, Any]
    route: AgentGraphNodeRoute
    step_index: Optional[int]
    invocation_id: Optional[str]
    observation_summary: str


class LangGraphAgentLoopGateway:
    """Durable LangGraph orchestration for Think/Act/Observe/Decide.

    LangGraph persists only graph cursor state. AgentGoal, AgentStep, and
    ToolInvocation remain the authoritative business facts so Temporal retries
    and process restarts can safely reconstruct the next node.
    """

    def __init__(
        self,
        state: AgentGraphStatePort,
        state_machine: AgentGoalStateMachine,
        plan_compiler: AgentGoalPlanCompiler,
        *,
        config: LangGraphGatewayConfig | None = None,
        delegate_runtime: "LocalAgentGraphRuntime | None" = None,
        replanner: "AgentReplanner | None" = None,
        compiled_graph: Any | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        from ...application.agent.graph import LocalAgentGraphRuntime

        self._state = state
        self.config = config or langgraph_gateway_config_from_env()
        self.delegate_runtime = delegate_runtime or LocalAgentGraphRuntime(
            state,
            state_machine,
            plan_compiler,
            replanner=replanner,
        )
        self._compiled_graph = compiled_graph
        self._checkpointer = checkpointer

    async def start(self, goal_id: str, proposal: AgentGoalProposal) -> None:
        await self._invoke(
            {
                "operation": "start",
                "goal_id": goal_id,
                "proposal_payload": asdict(proposal),
            },
            goal_id,
        )

    async def resume(self, goal_id: str) -> AgentGoal:
        await self._invoke({"operation": "resume", "goal_id": goal_id}, goal_id)
        return self._state.get_goal(goal_id)

    def steps_for_proposal(self, proposal: AgentGoalProposal) -> list[AgentStep]:
        return self.delegate_runtime.steps_for_proposal(proposal)

    async def _invoke(self, state: _AgentLoopGraphState, goal_id: str) -> dict[str, Any]:
        invocation_config = {
            "configurable": {
                "thread_id": f"{self.config.graph_name}:{goal_id}",
            }
        }
        if self._compiled_graph is not None:
            return await self._compiled_graph.ainvoke(state, config=invocation_config)
        if self.config.checkpoint_backend == "postgres":
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL LangGraph checkpointing is selected, but "
                    "langgraph-checkpoint-postgres is not installed."
                ) from exc
            async with AsyncPostgresSaver.from_conn_string(self.config.psycopg_connection_string) as saver:
                graph = self._compile_graph(saver)
                return await graph.ainvoke(state, config=invocation_config)
        return await self._graph().ainvoke(state, config=invocation_config)

    def _graph(self) -> Any:
        if self._compiled_graph is None:
            checkpointer = self._checkpointer
            if checkpointer is None:
                from langgraph.checkpoint.memory import MemorySaver

                checkpointer = MemorySaver()
            self._compiled_graph = self._compile_graph(checkpointer)
        return self._compiled_graph

    def _compile_graph(self, checkpointer: Any) -> Any:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError(
                "LangGraph graph runtime is selected, but the langgraph package is not installed. "
                "Install apps/api/requirements.txt or set NASUS_AGENT_GRAPH_RUNTIME=local."
            ) from exc

        graph = StateGraph(_AgentLoopGraphState)
        graph.add_node("prepare", self._prepare)
        graph.add_node("think", self._think)
        graph.add_node("act", self._act)
        graph.add_node("observe", self._observe)
        graph.add_node("decide", self._decide)
        graph.add_edge(START, "prepare")
        route_map = {
            "think": "think",
            "act": "act",
            "observe": "observe",
            "decide": "decide",
            "end": END,
        }
        for node_name in ("prepare", "think", "act", "observe"):
            graph.add_conditional_edges(node_name, self._route, route_map)
        graph.add_edge("decide", END)
        return graph.compile(checkpointer=checkpointer)

    async def _prepare(self, state: _AgentLoopGraphState) -> _AgentLoopGraphState:
        operation = state.get("operation")
        goal_id = state["goal_id"]
        if operation == "start":
            outcome = await self.delegate_runtime.prepare_start(goal_id)
        elif operation == "resume":
            outcome = await self.delegate_runtime.prepare_resume(goal_id)
        else:
            raise RuntimeError(f"Unsupported LangGraph Agent Loop operation: {operation!r}.")
        return self._outcome_state(outcome)

    async def _think(self, state: _AgentLoopGraphState) -> _AgentLoopGraphState:
        proposal_payload = state.get("proposal_payload")
        if not proposal_payload:
            proposal = self.delegate_runtime.proposal_from_goal(
                self._state.get_goal(state["goal_id"])
            )
        else:
            proposal = agent_goal_proposal_from_payload(proposal_payload)
        outcome = await self.delegate_runtime.run_think_node(state["goal_id"], proposal)
        return self._outcome_state(outcome)

    async def _act(self, state: _AgentLoopGraphState) -> _AgentLoopGraphState:
        outcome = await self.delegate_runtime.run_act_node(
            state["goal_id"],
            state.get("step_index"),
            state.get("invocation_id"),
        )
        return self._outcome_state(outcome)

    async def _observe(self, state: _AgentLoopGraphState) -> _AgentLoopGraphState:
        outcome = await self.delegate_runtime.run_observe_node(
            state["goal_id"],
            state.get("step_index"),
            state.get("invocation_id"),
        )
        return self._outcome_state(outcome)

    async def _decide(self, state: _AgentLoopGraphState) -> _AgentLoopGraphState:
        outcome = await self.delegate_runtime.run_decide_node(
            state["goal_id"],
            state.get("observation_summary", ""),
        )
        return self._outcome_state(outcome)

    @staticmethod
    def _route(state: _AgentLoopGraphState) -> AgentGraphNodeRoute:
        return state.get("route", "end")

    @staticmethod
    def _outcome_state(outcome: AgentGraphNodeOutcome) -> _AgentLoopGraphState:
        return {
            "route": outcome.route,
            "step_index": outcome.step_index,
            "invocation_id": outcome.invocation_id,
            "observation_summary": outcome.observation_summary,
        }


__all__ = ["LangGraphAgentLoopGateway"]
