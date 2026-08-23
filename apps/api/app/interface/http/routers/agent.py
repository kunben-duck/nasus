from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ....application.agent.agent_models import (
    AgentGoalCreateRequest,
    AgentGoalBudgetUpdateRequest,
    AgentGoalFeedbackRequest,
    AgentMemoryCheckpointRequest,
)
from ..dependencies import AgentApp
from ..errors import error_response
from ...sse import SSE_RESPONSE_HEADERS, encode_event, encode_heartbeat

router = APIRouter()


@router.post("/v1/agent-goals")
async def create_agent_goal(payload: AgentGoalCreateRequest, agent: AgentApp) -> Any:
    try:
        return await agent.create_manual_goal(payload)
    except KeyError as exc:
        raise error_response("not_found", "conversation was not found", 404) from exc


@router.get("/v1/agent-goals/{goal_id}")
def get_agent_goal(goal_id: str, agent: AgentApp) -> Any:
    try:
        return agent.get_agent_goal(goal_id)
    except KeyError as exc:
        raise error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc


@router.get("/v1/agent-goals/{goal_id}/checkpoint")
def get_agent_goal_checkpoint(goal_id: str, agent: AgentApp) -> Any:
    try:
        return agent.get_agent_goal_checkpoint(goal_id)
    except KeyError as exc:
        raise error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc


@router.get("/v1/agent-goals/{goal_id}/explanation")
def get_agent_goal_explanation(goal_id: str, agent: AgentApp) -> Any:
    try:
        return agent.get_agent_goal_explanation(goal_id)
    except KeyError as exc:
        raise error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc


@router.patch("/v1/agent-goals/{goal_id}/budget")
def update_agent_goal_budget(
    goal_id: str,
    payload: AgentGoalBudgetUpdateRequest,
    agent: AgentApp,
) -> Any:
    try:
        return agent.update_agent_goal_budget(goal_id, payload)
    except KeyError as exc:
        raise error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc
    except ValueError as exc:
        raise error_response("validation_error", str(exc), 400) from exc


@router.get("/v1/agent-memory/context")
async def get_agent_memory_context(
    agent: AgentApp,
    conversation_id: Optional[str] = None,
    agent_goal_id: Optional[str] = None,
    space_ref: Optional[str] = None,
) -> Any:
    try:
        return await agent.get_agent_memory_context(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            space_ref=space_ref,
        )
    except KeyError as exc:
        raise error_response("not_found", "agent memory context target was not found", 404) from exc


@router.post("/v1/agent-memory/checkpoints")
async def create_agent_memory_checkpoint(payload: AgentMemoryCheckpointRequest, agent: AgentApp) -> Any:
    try:
        return await agent.create_agent_memory_checkpoint(payload)
    except KeyError as exc:
        raise error_response("not_found", "agent memory checkpoint target was not found", 404) from exc
    except ValueError as exc:
        raise error_response("validation_error", str(exc), 400) from exc


@router.get("/v1/agent-goals/{goal_id}/events")
async def agent_goal_events(goal_id: str, request: Request, agent: AgentApp) -> StreamingResponse:
    try:
        agent.get_agent_goal(goal_id)
    except KeyError as exc:
        raise error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc

    async def event_generator():
        last_event_id = request.headers.get("last-event-id")
        async for event in agent.stream_goal_events(goal_id, last_event_id):
            yield encode_event(event) if event is not None else encode_heartbeat()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )


@router.get("/v1/agent-swarms/{swarm_id}")
def get_agent_swarm(swarm_id: str, agent: AgentApp) -> Any:
    try:
        return agent.get_agent_swarm(swarm_id)
    except KeyError as exc:
        raise error_response("not_found", f"agent swarm {swarm_id} was not found", 404) from exc


@router.get("/v1/agent-swarms")
def list_agent_swarms(
    agent: AgentApp,
    conversation_id: Optional[str] = None,
    parent_goal_id: Optional[str] = None,
) -> Any:
    try:
        return agent.list_agent_swarms(
            conversation_id=conversation_id,
            parent_goal_id=parent_goal_id,
        )
    except KeyError as exc:
        raise error_response("not_found", "agent swarm scope was not found", 404) from exc
    except ValueError as exc:
        raise error_response("validation_error", str(exc), 400) from exc


@router.get("/v1/agent-swarms/{swarm_id}/events")
async def agent_swarm_events(swarm_id: str, request: Request, agent: AgentApp) -> StreamingResponse:
    try:
        agent.get_agent_swarm(swarm_id)
    except KeyError as exc:
        raise error_response("not_found", f"agent swarm {swarm_id} was not found", 404) from exc

    async def event_generator():
        last_event_id = request.headers.get("last-event-id")
        async for event in agent.stream_swarm_events(swarm_id, last_event_id):
            yield encode_event(event) if event is not None else encode_heartbeat()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )


@router.post("/v1/agent-goals/{goal_id}/interrupt")
async def interrupt_agent_goal(goal_id: str, agent: AgentApp) -> Any:
    try:
        return await agent.interrupt_goal(goal_id)
    except KeyError as exc:
        raise error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc


@router.post("/v1/agent-goals/{goal_id}/resume")
async def resume_agent_goal(goal_id: str, agent: AgentApp) -> Any:
    try:
        return await agent.resume_goal(goal_id)
    except KeyError as exc:
        raise error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc


@router.post("/v1/agent-goals/{goal_id}/feedback")
async def feedback_agent_goal(goal_id: str, payload: AgentGoalFeedbackRequest, agent: AgentApp) -> Any:
    try:
        return await agent.add_goal_feedback(goal_id, payload)
    except KeyError as exc:
        raise error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc
