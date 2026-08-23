from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ....application.agent.agent_models import (
    ConversationArchiveRequest,
    ConversationCreateRequest,
    ConversationMergeRequest,
    ConversationMessageRequest,
)
from ..dependencies import AgentApp
from ..errors import error_response
from ...sse import SSE_RESPONSE_HEADERS, encode_event, encode_heartbeat

router = APIRouter()


@router.post("/v1/conversations")
def ensure_conversation(payload: ConversationCreateRequest, agent: AgentApp) -> Any:
    return agent.ensure_conversation(payload)


@router.get("/v1/conversations")
def list_conversations(
    agent: AgentApp,
    project_id: Optional[str] = None,
    version_id: Optional[str] = None,
    space_type: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
) -> Any:
    return agent.list_conversations(
        project_id=project_id,
        version_id=version_id,
        space_type=space_type,
        status=status,
        q=q,
    )


@router.get("/v1/conversations/search")
def search_conversations(q: str, agent: AgentApp) -> Any:
    return agent.search_conversations(q)


@router.get("/v1/conversations/{conversation_id}")
def get_conversation(conversation_id: str, agent: AgentApp) -> Any:
    try:
        return agent.get_conversation(conversation_id)
    except KeyError as exc:
        raise error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc


@router.get("/v1/conversations/{conversation_id}/messages")
def list_conversation_messages(
    conversation_id: str,
    agent: AgentApp,
    before_message_id: Optional[str] = None,
) -> Any:
    try:
        return agent.list_conversation_messages(conversation_id, before_message_id)
    except KeyError as exc:
        raise error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc


@router.patch("/v1/conversations/{conversation_id}/archive")
def archive_conversation(conversation_id: str, payload: ConversationArchiveRequest, agent: AgentApp) -> Any:
    try:
        return agent.archive_conversation(conversation_id, payload)
    except KeyError as exc:
        raise error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc


@router.post("/v1/conversations/{conversation_id}/merge")
def merge_conversation(conversation_id: str, payload: ConversationMergeRequest, agent: AgentApp) -> Any:
    try:
        return agent.merge_conversation(conversation_id, payload)
    except KeyError as exc:
        raise error_response("not_found", "conversation merge target was not found", 404) from exc


@router.post("/v1/conversations/{conversation_id}/messages")
async def post_message(conversation_id: str, payload: ConversationMessageRequest, agent: AgentApp) -> Any:
    try:
        return await agent.post_message(conversation_id, payload)
    except KeyError as exc:
        raise error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc


@router.get("/v1/conversations/{conversation_id}/events")
async def conversation_events(conversation_id: str, request: Request, agent: AgentApp) -> StreamingResponse:
    try:
        agent.get_conversation(conversation_id)
    except KeyError as exc:
        raise error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc

    async def event_generator():
        last_event_id = request.headers.get("last-event-id")
        async for event in agent.stream_conversation_events(conversation_id, last_event_id):
            yield encode_event(event) if event is not None else encode_heartbeat()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )
