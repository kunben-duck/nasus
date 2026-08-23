from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from ..application.agent import AgentApplicationService
from ..application.agent.activities import AgentWorkflowActivityApplicationService
from ..application.platform.accounts import AccountApplicationService
from ..application.platform.governance import GovernanceApplicationService
from ..application.platform.identity_administration import (
    IdentityAdministrationApplicationService,
)
from ..application.platform.project_workspace import ProjectWorkspaceApplicationService
from ..application.platform.readiness import ReadinessApplicationService
from ..application.platform.use_cases import PlatformApplicationService
from ..application.system_image import SystemImageApplicationService
from ..application.system_image.source_uploads import SourceUploadApplicationService
from ..infrastructure.config.runtime_config import current_runtime_profile
from ..infrastructure.llm import ModelRoutesReadinessProbe, PromptRegistryReadinessProbe
from ..infrastructure.persistence import DatabaseReadinessProbe, engine
from ..infrastructure.platform import (
    CallableCurrentUserProvider,
    SQLAlchemyAccountIdentityService,
    SQLAlchemyIdentityAdministrationAdapter,
    SQLAlchemyProjectWorkspaceReadModel,
)
from ..infrastructure.runner import AutomationRunnerReadinessProbe
from ..infrastructure.storage import ObjectStorage, ObjectStorageReadinessProbe
from ..infrastructure.system_image import (
    CodeIntelligenceReadinessProbe,
    GitSourceConnectorReadinessProbe,
)
from ..infrastructure.workflow import (
    LangGraphCheckpointReadinessProbe,
    TemporalWorkflowReadinessProbe,
)
from ..interface.http.auth import AuthConfig


@dataclass(frozen=True)
class ApplicationContainer:
    """Explicit services exposed to delivery adapters.

    The legacy projection runtime is intentionally not exposed. HTTP and
    Temporal adapters can only resolve application services from this object.
    """

    auth_config: AuthConfig
    platform: PlatformApplicationService
    agent: AgentApplicationService
    project_workspace: ProjectWorkspaceApplicationService
    system_image: SystemImageApplicationService
    source_uploads: SourceUploadApplicationService
    governance: GovernanceApplicationService
    identity_administration: IdentityAdministrationApplicationService
    readiness: ReadinessApplicationService
    agent_workflow_activities: AgentWorkflowActivityApplicationService


_container: ApplicationContainer | None = None
_container_lock = RLock()


def get_application_container() -> ApplicationContainer:
    global _container
    if _container is None:
        with _container_lock:
            if _container is None:
                _container = _build_application_container()
    return _container


def _build_application_container() -> ApplicationContainer:
    # Delayed import preserves production fail-fast validation before database
    # initialization and compatibility projection hydration.
    from ..store import get_runtime_assembly

    runtime = get_runtime_assembly()
    platform = PlatformApplicationService(
        accounts=AccountApplicationService(
            current_user=CallableCurrentUserProvider(lambda: runtime.user),
            identities=SQLAlchemyAccountIdentityService(),
        ),
        audit_events=runtime.platform_audit,
        llm_calls=runtime.llm_call_audit,
        model_configurations=runtime.model_configuration,
        top_level_content=runtime.top_level_content,
        tool_invocations=runtime.tool_invocations_app,
    )
    agent_workflow_activities = AgentWorkflowActivityApplicationService(
        loop_runtime=runtime.agent_loop_runtime,
        goal_projector=runtime.agent_goal_projection,
    )
    project_workspace = ProjectWorkspaceApplicationService(
        read_model=SQLAlchemyProjectWorkspaceReadModel(
            runtime.project_repository,
            runtime.quality_loop_repository,
            runtime.system_image_repository,
        ),
        authorization=runtime.project_access,
        tool_invocations=runtime.tool_invocations_app,
        conversations=runtime.conversation_management,
    )
    identity_administration = IdentityAdministrationApplicationService(
        current_user=CallableCurrentUserProvider(lambda: runtime.user),
        identities=SQLAlchemyIdentityAdministrationAdapter(),
        project_access=runtime.project_access,
        audit=runtime.platform_audit,
    )
    readiness = ReadinessApplicationService(
        (
            DatabaseReadinessProbe(engine),
            ObjectStorageReadinessProbe(ObjectStorage()),
            GitSourceConnectorReadinessProbe(),
            CodeIntelligenceReadinessProbe(runtime.code_intelligence),
            AutomationRunnerReadinessProbe(),
            ModelRoutesReadinessProbe(
                runtime.model_configuration.get_settings,
                require_live=current_runtime_profile().production_like,
            ),
            PromptRegistryReadinessProbe(runtime.prompt_registry),
            TemporalWorkflowReadinessProbe(),
            LangGraphCheckpointReadinessProbe(engine),
        )
    )
    return ApplicationContainer(
        auth_config=AuthConfig.from_env(),
        platform=platform,
        agent=runtime.agent_app,
        project_workspace=project_workspace,
        system_image=runtime.system_image_app,
        source_uploads=runtime.source_uploads,
        governance=runtime.governance,
        identity_administration=identity_administration,
        readiness=readiness,
        agent_workflow_activities=agent_workflow_activities,
    )
