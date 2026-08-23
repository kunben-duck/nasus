from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ...application.agent import AgentApplicationService
from ...application.platform.project_workspace import ProjectWorkspaceApplicationService
from ...application.platform.governance import GovernanceApplicationService
from ...application.platform.identity_administration import (
    IdentityAdministrationApplicationService,
)
from ...application.platform.readiness import ReadinessApplicationService
from ...application.platform.operational_metrics import OperationalMetricsExportPort
from ...application.platform.use_cases import PlatformApplicationService
from ...application.system_image import SystemImageApplicationService
from ...application.system_image.source_uploads import SourceUploadApplicationService


def get_agent_application(request: Request) -> AgentApplicationService:
    return request.app.state.container.agent


def get_platform_application(request: Request) -> PlatformApplicationService:
    return request.app.state.container.platform


def get_project_workspace_application(request: Request) -> ProjectWorkspaceApplicationService:
    return request.app.state.container.project_workspace


def get_system_image_application(request: Request) -> SystemImageApplicationService:
    return request.app.state.container.system_image


def get_source_upload_application(request: Request) -> SourceUploadApplicationService:
    return request.app.state.container.source_uploads


def get_readiness_application(request: Request) -> ReadinessApplicationService:
    return request.app.state.readiness


def get_governance_application(request: Request) -> GovernanceApplicationService:
    return request.app.state.container.governance


def get_identity_administration_application(
    request: Request,
) -> IdentityAdministrationApplicationService:
    return request.app.state.container.identity_administration


def get_operational_metrics(request: Request) -> OperationalMetricsExportPort:
    return request.app.state.http_metrics


AgentApp = Annotated[AgentApplicationService, Depends(get_agent_application)]
PlatformApp = Annotated[PlatformApplicationService, Depends(get_platform_application)]
ProjectWorkspaceApp = Annotated[
    ProjectWorkspaceApplicationService,
    Depends(get_project_workspace_application),
]
SystemImageApp = Annotated[SystemImageApplicationService, Depends(get_system_image_application)]
SourceUploadApp = Annotated[
    SourceUploadApplicationService,
    Depends(get_source_upload_application),
]
ReadinessApp = Annotated[ReadinessApplicationService, Depends(get_readiness_application)]
GovernanceApp = Annotated[GovernanceApplicationService, Depends(get_governance_application)]
IdentityAdministrationApp = Annotated[
    IdentityAdministrationApplicationService,
    Depends(get_identity_administration_application),
]
OperationalMetricsApp = Annotated[
    OperationalMetricsExportPort,
    Depends(get_operational_metrics),
]


__all__ = [
    "AgentApp",
    "GovernanceApp",
    "IdentityAdministrationApp",
    "OperationalMetricsApp",
    "PlatformApp",
    "ProjectWorkspaceApp",
    "ReadinessApp",
    "SourceUploadApp",
    "SystemImageApp",
    "get_agent_application",
    "get_governance_application",
    "get_identity_administration_application",
    "get_operational_metrics",
    "get_platform_application",
    "get_project_workspace_application",
    "get_readiness_application",
    "get_source_upload_application",
    "get_system_image_application",
]
