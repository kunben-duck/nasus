from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request, Response

from ....application.platform.account_models import AuthLoginRequest, AuthRegisterRequest, UserAvatarUpdateRequest
from ....application.platform.errors import PlatformApplicationError
from ....application.platform.model_settings import (
    ModelConfigCreateRequest,
    ModelConfigTestRequest,
    ModelConfigUpdateRequest,
    ModelRoute,
    StudioSettingsConnectionTestRequest,
    StudioSettingsPatch,
)
from ....application.platform.tool_models import ToolInvocationRequest
from ..dependencies import PlatformApp
from ..errors import error_response

router = APIRouter()


@router.get("/v1/auth/me")
def auth_me(request: Request, platform: PlatformApp) -> Any:
    return getattr(request.state, "user", platform.current_user())


@router.post("/v1/auth/register")
def auth_register(payload: AuthRegisterRequest, request: Request, platform: PlatformApp) -> Any:
    try:
        return platform.register_user(payload, user_agent=request.headers.get("user-agent"))
    except PlatformApplicationError as exc:
        raise error_response(exc.code, exc.message, exc.status_code) from exc


@router.post("/v1/auth/login")
def auth_login(payload: AuthLoginRequest, request: Request, platform: PlatformApp) -> Any:
    try:
        return platform.login_user(payload, user_agent=request.headers.get("user-agent"))
    except PlatformApplicationError as exc:
        raise error_response(exc.code, exc.message, exc.status_code) from exc


@router.post("/v1/auth/logout")
def auth_logout(request: Request, platform: PlatformApp) -> Any:
    header = request.headers.get("authorization", "")
    scheme, _, header_token = header.partition(" ")
    token = header_token if scheme.lower() == "bearer" else request.query_params.get("access_token", "")
    return platform.logout_user(token)


@router.patch("/v1/auth/me/avatar")
def update_auth_avatar(payload: UserAvatarUpdateRequest, request: Request, platform: PlatformApp) -> Any:
    user = getattr(request.state, "user", None)
    try:
        return platform.update_user_avatar(user=user, payload=payload)
    except PlatformApplicationError as exc:
        raise error_response(exc.code, exc.message, exc.status_code) from exc


@router.get("/v1/auth/me/avatar/content")
def get_auth_avatar_content(request: Request, platform: PlatformApp) -> Response:
    user = getattr(request.state, "user", None)
    try:
        content = platform.get_user_avatar_content(user=user)
    except PlatformApplicationError as exc:
        raise error_response(exc.code, exc.message, exc.status_code) from exc
    return Response(
        content=content.body,
        media_type=content.mime_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/v1/welcome")
def get_welcome(platform: PlatformApp) -> Any:
    return platform.get_welcome()


@router.get("/v1/build")
def get_build(platform: PlatformApp) -> Any:
    return platform.get_build()


@router.get("/v1/dashboard")
def get_dashboard(platform: PlatformApp) -> Any:
    return platform.get_dashboard()


@router.get("/v1/documentation")
def get_documentation(platform: PlatformApp) -> Any:
    return platform.list_documentation()


@router.get("/v1/settings")
def get_settings(platform: PlatformApp) -> Any:
    return platform.get_settings()


@router.patch("/v1/settings")
def patch_settings(payload: StudioSettingsPatch, platform: PlatformApp) -> Any:
    return platform.update_settings(payload)


@router.get("/v1/settings/test-connection")
def get_test_settings_connection_help(platform: PlatformApp) -> Any:
    settings = platform.get_settings()
    return {
        "message": "Use POST /v1/settings/test-connection with a JSON body to test the active or custom model route.",
        "method": "POST",
        "current_model_preset": settings.model_preset,
        "current_provider": settings.model_provider,
        "current_model_name": settings.model_name,
        "runtime_mode": settings.runtime_mode,
    }


@router.post("/v1/settings/test-connection")
async def test_settings_connection(
    platform: PlatformApp,
    payload: Optional[StudioSettingsConnectionTestRequest] = None,
) -> Any:
    return await platform.test_settings_connection(payload)


@router.post("/v1/settings/model-configs/test")
async def test_model_config_connection(payload: ModelConfigTestRequest, platform: PlatformApp) -> Any:
    return await platform.test_model_config_connection(payload)


@router.post("/v1/settings/model-configs")
def create_model_config(payload: ModelConfigCreateRequest, platform: PlatformApp) -> Any:
    try:
        return platform.create_model_config(payload)
    except ValueError as exc:
        raise error_response("model_config_not_tested", str(exc), 400) from exc


@router.patch("/v1/settings/model-configs/{config_id}")
def update_model_config(config_id: str, payload: ModelConfigUpdateRequest, platform: PlatformApp) -> Any:
    try:
        return platform.update_model_config(config_id, payload)
    except KeyError as exc:
        raise error_response("not_found", f"model config {config_id} was not found", 404) from exc
    except ValueError as exc:
        raise error_response("model_config_not_tested", str(exc), 400) from exc


@router.get("/v1/settings/model-configs")
def list_model_configs(platform: PlatformApp, route: Optional[ModelRoute] = None) -> Any:
    return platform.list_model_configurations(route)


@router.post("/v1/settings/model-configs/{route}/use-system-default")
def use_system_default_model_config(route: ModelRoute, platform: PlatformApp) -> Any:
    return platform.use_system_default_model_config(route)


@router.post("/v1/settings/model-configs/{config_id}/activate")
def activate_model_config(config_id: str, platform: PlatformApp) -> Any:
    try:
        return platform.activate_model_config(config_id)
    except KeyError as exc:
        raise error_response("not_found", f"model config {config_id} was not found", 404) from exc


@router.get("/v1/tools/catalog")
def get_tools(platform: PlatformApp) -> Any:
    return platform.list_tools()


@router.get("/v1/audit-events")
def list_audit_events(
    platform: PlatformApp,
    conversation_id: Optional[str] = None,
    tool_invocation_id: Optional[str] = None,
    agent_goal_id: Optional[str] = None,
) -> Any:
    return platform.list_audit_events(
        conversation_id=conversation_id,
        tool_invocation_id=tool_invocation_id,
        agent_goal_id=agent_goal_id,
    )


@router.get("/v1/llm-calls")
def list_llm_calls(
    platform: PlatformApp,
    route: Optional[ModelRoute] = None,
    project_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    agent_goal_id: Optional[str] = None,
    tool_invocation_id: Optional[str] = None,
    limit: int = 100,
) -> Any:
    return platform.list_llm_calls(
        route=route,
        project_id=project_id,
        conversation_id=conversation_id,
        agent_goal_id=agent_goal_id,
        tool_invocation_id=tool_invocation_id,
        limit=limit,
    )


@router.post("/v1/tool-invocations")
async def create_tool_invocation(payload: ToolInvocationRequest, platform: PlatformApp) -> Any:
    return await platform.create_tool_invocation(payload)


@router.get("/v1/tool-invocations")
def list_tool_invocations(
    platform: PlatformApp,
    conversation_id: Optional[str] = None,
    agent_goal_id: Optional[str] = None,
    tool_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Any:
    return platform.list_tool_invocations(
        conversation_id=conversation_id,
        agent_goal_id=agent_goal_id,
        tool_id=tool_id,
        status=status,
    )


@router.get("/v1/tool-invocations/{invocation_id}")
def get_tool_invocation(invocation_id: str, platform: PlatformApp) -> Any:
    try:
        return platform.get_tool_invocation(invocation_id)
    except KeyError as exc:
        raise error_response("not_found", f"tool invocation {invocation_id} was not found", 404) from exc


@router.post("/v1/tool-invocations/{invocation_id}/confirm")
async def confirm_tool_invocation(invocation_id: str, platform: PlatformApp) -> Any:
    try:
        return await platform.confirm_tool_invocation(invocation_id)
    except KeyError as exc:
        raise error_response("not_found", f"tool invocation {invocation_id} was not found", 404) from exc
