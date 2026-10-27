from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import StreamingResponse

from ....application.agent.agent_models import (
    ConversationArchiveRequest,
    ConversationCreateRequest,
    ConversationMergeRequest,
    ConversationMessageRequest,
)
from ....application.agent.turns import ConversationTurnConflict
from ....application.platform.actor_context import current_actor
from ..dependencies import AgentApp
from ..errors import error_response
from ..request_context import resolve_request_id
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


@router.post(
    "/v1/conversations/{conversation_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_message(
    conversation_id: str,
    payload: ConversationMessageRequest,
    request: Request,
    agent: AgentApp,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    try:
        actor = current_actor()
        return await agent.accept_message(
            conversation_id,
            payload,
            idempotency_key=idempotency_key or f"server-{uuid4().hex}",
            events_url=f"/v1/conversations/{conversation_id}/events",
            actor=actor.user if actor is not None else None,
            request_id=resolve_request_id(request),
        )
    except KeyError as exc:
        raise error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc
    except ConversationTurnConflict as exc:
        raise error_response("conversation_turn_active", str(exc), 409) from exc


@router.get("/v1/conversations/{conversation_id}/turns/{turn_id}")
def get_conversation_turn(conversation_id: str, turn_id: str, agent: AgentApp) -> Any:
    try:
        return agent.get_conversation_turn(conversation_id, turn_id)
    except KeyError as exc:
        raise error_response("not_found", f"conversation turn {turn_id} was not found", 404) from exc


@router.post("/v1/conversations/{conversation_id}/turns/{turn_id}/cancel")
async def cancel_conversation_turn(conversation_id: str, turn_id: str, agent: AgentApp) -> Any:
    try:
        return await agent.cancel_conversation_turn(conversation_id, turn_id)
    except KeyError as exc:
        raise error_response("not_found", f"conversation turn {turn_id} was not found", 404) from exc


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
