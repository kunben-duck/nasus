from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ProjectCreateRequest(BaseModel):
    name: str


class ProjectCard(BaseModel):
    id: str
    name: str
    code: str
    summary: str
    status: str
    risk: str
    progress: int
    active_version: str
    blocked_items: int
    pending_approvals: int
    system_image_status: str


class VersionSummary(BaseModel):
    id: str
    name: str
    status: str
    branch_name: str
    us_total: int
    us_closed: int
    pending_runs: int
    pending_approvals: int


class VersionCreateRequest(BaseModel):
    name: str


class ProjectRoleBinding(BaseModel):
    binding_id: str
    project_id: str
    version_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: str
    role: Literal["viewer", "tester", "qa_lead", "project_admin", "platform_admin"]
    scope_ref: str
    effective_policy_ref: Optional[str] = None
    status: Literal["active", "revoked"] = "active"
    created_at: str
    updated_at: str
    created_by: str


__all__ = [
    "ProjectCreateRequest",
    "ProjectCard",
    "ProjectRoleBinding",
    "VersionCreateRequest",
    "VersionSummary",
]
