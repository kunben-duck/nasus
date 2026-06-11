from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .models import (
    AgentGoalCreateRequest,
    AgentGoalFeedbackRequest,
    ConversationArchiveRequest,
    ConversationCreateRequest,
    ConversationMergeRequest,
    ConversationMessageRequest,
    StudioSettingsConnectionTestRequest,
    StudioSettingsPatch,
    ToolInvocationRequest,
    VersionSummary,
)
from .store import store


app = FastAPI(title="Nasus API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "request_id": "req_local",
            "timestamp": "2026-03-27T00:00:00Z",
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "retry_after": None,
            },
        },
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/auth/me")
def auth_me() -> Any:
    return store.user


@app.get("/v1/welcome")
def get_welcome() -> Any:
    return store.get_welcome()


@app.get("/v1/build")
def get_build() -> Any:
    return store.get_build()


@app.get("/v1/dashboard")
def get_dashboard() -> Any:
    return store.get_dashboard()


@app.get("/v1/documentation")
def get_documentation() -> Any:
    return store.list_documentation()


@app.get("/v1/settings")
def get_settings() -> Any:
    return store.get_settings()


@app.patch("/v1/settings")
def patch_settings(payload: StudioSettingsPatch) -> Any:
    return store.update_settings(payload)


@app.get("/v1/settings/test-connection")
def get_test_settings_connection_help() -> Any:
    settings = store.get_settings()
    return {
        "message": "Use POST /v1/settings/test-connection with a JSON body to test the active or custom model route.",
        "method": "POST",
        "current_model_preset": settings.model_preset,
        "current_provider": settings.model_provider,
        "current_model_name": settings.model_name,
        "runtime_mode": settings.runtime_mode,
    }


@app.post("/v1/settings/test-connection")
async def test_settings_connection(payload: Optional[StudioSettingsConnectionTestRequest] = None) -> Any:
    return await store.test_settings_connection(payload)


@app.get("/v1/tools/catalog")
def get_tools() -> Any:
    return store.tools


@app.post("/v1/tool-invocations")
async def create_tool_invocation(payload: ToolInvocationRequest) -> Any:
    return await store.create_tool_invocation(payload)


@app.get("/v1/tool-invocations/{invocation_id}")
def get_tool_invocation(invocation_id: str) -> Any:
    try:
        return store.get_tool_invocation(invocation_id)
    except KeyError as exc:
        raise _error_response("not_found", f"tool invocation {invocation_id} was not found", 404) from exc


@app.get("/v1/projects")
def list_projects() -> Any:
    return store.list_projects()


@app.post("/v1/projects")
def create_project(payload: dict[str, str]) -> Any:
    name = payload.get("name")
    if not name:
        raise _error_response("validation_error", "name is required")
    return store.create_project(name)


@app.get("/v1/projects/{project_id}")
def get_project(project_id: str) -> Any:
    try:
        return store.get_project_workspace(project_id)
    except KeyError as exc:
        raise _error_response("not_found", f"project {project_id} was not found", 404) from exc


@app.get("/v1/projects/{project_id}/versions")
def get_versions(project_id: str) -> Any:
    try:
        return store.versions[project_id]
    except KeyError as exc:
        raise _error_response("not_found", f"project {project_id} was not found", 404) from exc


@app.post("/v1/projects/{project_id}/versions")
def create_version(project_id: str, payload: dict[str, str]) -> VersionSummary:
    name = payload.get("name")
    if not name:
        raise _error_response("validation_error", "name is required")
    try:
        return store.create_version(project_id, name)
    except KeyError as exc:
        raise _error_response("not_found", f"project {project_id} was not found", 404) from exc


@app.get("/v1/projects/{project_id}/workspaces/{us_id}")
def get_workspace(project_id: str, us_id: str) -> Any:
    try:
        return store.get_workspace_data(project_id, us_id)
    except KeyError as exc:
        raise _error_response("not_found", "workspace was not found", 404) from exc


@app.get("/v1/projects/{project_id}/knowledge")
def get_project_knowledge(project_id: str) -> Any:
    try:
        return store.list_knowledge_objects(project_id)
    except KeyError as exc:
        raise _error_response("not_found", f"project {project_id} was not found", 404) from exc


@app.get("/v1/projects/{project_id}/knowledge/{object_id}")
def get_knowledge_detail(project_id: str, object_id: str) -> Any:
    try:
        return store.get_knowledge_object(project_id, object_id)
    except (KeyError, StopIteration) as exc:
        raise _error_response("not_found", f"knowledge object {object_id} was not found", 404) from exc


@app.get("/v1/projects/{project_id}/runs")
def get_project_runs(project_id: str) -> Any:
    return store.runs.get(project_id, [])


@app.get("/v1/projects/{project_id}/runs/{run_id}")
def get_run_detail(project_id: str, run_id: str) -> Any:
    try:
        return store.get_run_detail(project_id, run_id)
    except KeyError as exc:
        raise _error_response("not_found", f"run {run_id} was not found", 404) from exc


@app.get("/v1/projects/{project_id}/approvals")
def get_project_approvals(project_id: str) -> Any:
    return store.approvals.get(project_id, [])


@app.get("/v1/projects/{project_id}/approvals/{approval_id}")
def get_approval_detail(project_id: str, approval_id: str) -> Any:
    try:
        return store.get_approval_detail(project_id, approval_id)
    except KeyError as exc:
        raise _error_response("not_found", f"approval {approval_id} was not found", 404) from exc


@app.get("/v1/projects/{project_id}/release-readiness")
def get_release_readiness(project_id: str) -> Any:
    try:
        return store.get_release_readiness(project_id)
    except (KeyError, IndexError) as exc:
        raise _error_response("not_found", f"release readiness for project {project_id} was not found", 404) from exc


@app.post("/v1/conversations")
def ensure_conversation(payload: ConversationCreateRequest) -> Any:
    return store.get_or_create_conversation(payload.space_type, payload.space_id, payload.title or payload.space_id)


@app.get("/v1/conversations")
def list_conversations(
    project_id: Optional[str] = None,
    version_id: Optional[str] = None,
    space_type: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
) -> Any:
    return store.list_conversations(project_id=project_id, version_id=version_id, space_type=space_type, status=status, q=q)


@app.get("/v1/conversations/search")
def search_conversations(q: str) -> Any:
    return store.search_conversations(q)


@app.get("/v1/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> Any:
    try:
        return store.get_conversation(conversation_id)
    except KeyError as exc:
        raise _error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc


@app.get("/v1/conversations/{conversation_id}/messages")
def list_conversation_messages(conversation_id: str, before_message_id: Optional[str] = None) -> Any:
    try:
        return store.list_conversation_messages(conversation_id, before_message_id)
    except KeyError as exc:
        raise _error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc


@app.patch("/v1/conversations/{conversation_id}/archive")
def archive_conversation(conversation_id: str, payload: ConversationArchiveRequest) -> Any:
    try:
        return store.archive_conversation(conversation_id, payload)
    except KeyError as exc:
        raise _error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc


@app.post("/v1/conversations/{conversation_id}/merge")
def merge_conversation(conversation_id: str, payload: ConversationMergeRequest) -> Any:
    try:
        return store.merge_conversations(conversation_id, payload)
    except KeyError as exc:
        raise _error_response("not_found", "conversation merge target was not found", 404) from exc


@app.post("/v1/conversations/{conversation_id}/messages")
async def post_message(conversation_id: str, payload: ConversationMessageRequest) -> Any:
    try:
        return await store.handle_message(conversation_id, payload.content)
    except KeyError as exc:
        raise _error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc


@app.get("/v1/conversations/{conversation_id}/events")
async def conversation_events(conversation_id: str) -> StreamingResponse:
    try:
        store.get_conversation(conversation_id)
    except KeyError as exc:
        raise _error_response("not_found", f"conversation {conversation_id} was not found", 404) from exc

    async def event_generator():
        async for event in store.stream_events(conversation_id):
            yield f"event: {event.event_type}\n"
            yield f"data: {json.dumps(event.model_dump())}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/v1/agent-goals")
def create_agent_goal(payload: AgentGoalCreateRequest) -> Any:
    try:
        return store.create_agent_goal(payload)
    except KeyError as exc:
        raise _error_response("not_found", "conversation was not found", 404) from exc


@app.get("/v1/agent-goals/{goal_id}")
def get_agent_goal(goal_id: str) -> Any:
    try:
        return store.get_agent_goal(goal_id)
    except KeyError as exc:
        raise _error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc


@app.get("/v1/agent-goals/{goal_id}/events")
async def agent_goal_events(goal_id: str) -> StreamingResponse:
    try:
        store.get_agent_goal(goal_id)
    except KeyError as exc:
        raise _error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc

    async def event_generator():
        async for event in store.stream_goal_events(goal_id):
            yield f"event: {event.event_type}\n"
            yield f"data: {json.dumps(event.model_dump())}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/v1/agent-goals/{goal_id}/interrupt")
async def interrupt_agent_goal(goal_id: str) -> Any:
    try:
        return await store.interrupt_agent_goal(goal_id)
    except KeyError as exc:
        raise _error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc


@app.post("/v1/agent-goals/{goal_id}/resume")
async def resume_agent_goal(goal_id: str) -> Any:
    try:
        return await store.resume_agent_goal(goal_id)
    except KeyError as exc:
        raise _error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc


@app.post("/v1/agent-goals/{goal_id}/feedback")
async def feedback_agent_goal(goal_id: str, payload: AgentGoalFeedbackRequest) -> Any:
    try:
        return await store.add_goal_feedback(goal_id, payload.feedback)
    except KeyError as exc:
        raise _error_response("not_found", f"agent goal {goal_id} was not found", 404) from exc
