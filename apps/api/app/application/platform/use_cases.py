from __future__ import annotations

from typing import Any, Optional

from .account_models import (
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthSessionResponse,
    UserAvatarUpdateRequest,
)
from .tool_models import ToolInvocationRequest
from .model_settings import (
    ModelConfigCreateRequest,
    ModelConfigTestRequest,
    ModelConfigUpdateRequest,
    StudioSettingsConnectionTestRequest,
    StudioSettingsPatch,
)
from .accounts import AccountApplicationService
from .errors import PlatformApplicationError
from .model_configurations import ModelConfigurationApplicationService
from .audit_events import PlatformAuditApplicationService
from .llm_calls import LLMCallAuditApplicationService
from .top_level_content import TopLevelContentApplicationService
from .tool_invocations import ToolInvocationApplicationService


class PlatformApplicationService:
    """Platform support use cases.

    This HTTP-facing facade composes dedicated platform application services
    so routers do not gain direct compatibility-store coupling.
    """

    def __init__(
        self,
        *,
        accounts: AccountApplicationService,
        audit_events: PlatformAuditApplicationService,
        llm_calls: LLMCallAuditApplicationService,
        model_configurations: ModelConfigurationApplicationService,
        top_level_content: TopLevelContentApplicationService,
        tool_invocations: ToolInvocationApplicationService,
    ) -> None:
        self._accounts = accounts
        self._audit_events = audit_events
        self._llm_calls = llm_calls
        self._model_configurations = model_configurations
        self._top_level_content = top_level_content
        self._tool_invocations = tool_invocations

    def current_user(self) -> Any:
        return self._accounts.current_user()

    def authenticate_token(self, token: str) -> Any:
        return self._accounts.authenticate_token(token)

    def register_user(self, payload: AuthRegisterRequest, *, user_agent: Optional[str] = None) -> AuthSessionResponse:
        return self._accounts.register_user(payload, user_agent=user_agent)

    def login_user(self, payload: AuthLoginRequest, *, user_agent: Optional[str] = None) -> AuthSessionResponse:
        return self._accounts.login_user(payload, user_agent=user_agent)

    def logout_user(self, token: str) -> dict[str, bool]:
        return self._accounts.logout_user(token)

    def update_user_avatar(self, *, user: Any, payload: UserAvatarUpdateRequest) -> Any:
        return self._accounts.update_user_avatar(user=user, payload=payload)

    def get_user_avatar_content(self, *, user: Any) -> Any:
        return self._accounts.get_user_avatar_content(user=user)

    def get_welcome(self) -> Any:
        return self._top_level_content.get_welcome()

    def get_build(self) -> Any:
        return self._top_level_content.get_build()

    def get_dashboard(self) -> Any:
        return self._top_level_content.get_dashboard()

    def list_documentation(self) -> Any:
        return self._top_level_content.list_documentation()

    def get_settings(self) -> Any:
        return self._model_configurations.get_settings()

    def update_settings(self, payload: StudioSettingsPatch) -> Any:
        return self._model_configurations.update_settings(payload)

    async def test_settings_connection(self, payload: Optional[StudioSettingsConnectionTestRequest]) -> Any:
        return await self._model_configurations.test_settings_connection(payload)

    async def test_model_config_connection(self, payload: ModelConfigTestRequest) -> Any:
        return await self._model_configurations.test_model_config_connection(payload)

    def create_model_config(self, payload: ModelConfigCreateRequest) -> Any:
        return self._model_configurations.create_model_config(payload)

    def update_model_config(self, config_id: str, payload: ModelConfigUpdateRequest) -> Any:
        return self._model_configurations.update_model_config(config_id, payload)

    def list_model_configurations(self, route: Optional[str] = None) -> Any:
        return self._model_configurations.list_model_configurations(route)

    def activate_model_config(self, config_id: str) -> Any:
        return self._model_configurations.activate_model_config(config_id)

    def use_system_default_model_config(self, route: str) -> Any:
        return self._model_configurations.use_system_default_model_config(route)

    def list_tools(self) -> Any:
        return self._tool_invocations.list_tools()

    def list_audit_events(
        self,
        *,
        conversation_id: Optional[str] = None,
        tool_invocation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
    ) -> Any:
        return self._tool_invocations.list_audit_events(
            conversation_id=conversation_id,
            tool_invocation_id=tool_invocation_id,
            agent_goal_id=agent_goal_id,
        )

    def list_llm_calls(
        self,
        *,
        route: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        agent_goal_id: str | None = None,
        tool_invocation_id: str | None = None,
        limit: int = 100,
    ) -> Any:
        if self.current_user().role != "platform_admin":
            raise PlatformApplicationError(
                "forbidden",
                "LLM call audit is restricted to platform administrators.",
                403,
            )
        return self._llm_calls.list_calls(
            route=route,
            project_id=project_id,
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            tool_invocation_id=tool_invocation_id,
            limit=limit,
        )

    def record_audit_event(self, event: Any) -> None:
        self._audit_events.record_audit_event(event)

    def record_agent_goal_audit_event(
        self,
        goal: Any,
        *,
        action: str,
        status: str | None = None,
        summary: str,
        actor: str = "agent",
        actor_kind: str = "agent",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._audit_events.record_agent_goal_audit_event(
            goal,
            action=action,
            status=status,
            summary=summary,
            actor=actor,
            actor_kind=actor_kind,
            metadata=metadata,
        )

    async def create_tool_invocation(self, payload: ToolInvocationRequest) -> Any:
        return await self._tool_invocations.create_tool_invocation(payload)

    def list_tool_invocations(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        tool_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Any:
        return self._tool_invocations.list_tool_invocations(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            tool_id=tool_id,
            status=status,
        )

    def get_tool_invocation(self, invocation_id: str) -> Any:
        return self._tool_invocations.get_tool_invocation(invocation_id)

    async def confirm_tool_invocation(self, invocation_id: str) -> Any:
        return await self._tool_invocations.confirm_tool_invocation(invocation_id)
