from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .project_models import ProjectRoleBinding


GlobalRole = Literal["viewer", "tester", "qa_lead", "platform_admin"]
ProjectRole = Literal["viewer", "tester", "qa_lead", "project_admin"]
AccountStatus = Literal["active", "suspended"]


class UserAdministrationRecord(BaseModel):
    id: str
    email: str
    display_name: str
    role: GlobalRole
    status: AccountStatus
    avatar_preset: Optional[str] = None
    avatar_image: bool = False
    created_at: str
    updated_at: str
    last_login_at: Optional[str] = None
    active_session_count: int = 0


class UserAdministrationPage(BaseModel):
    items: list[UserAdministrationRecord]
    total: int
    limit: int
    offset: int


class UserAdministrationPatch(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    role: Optional[GlobalRole] = None
    status: Optional[AccountStatus] = None

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name cannot be blank.")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> "UserAdministrationPatch":
        if self.display_name is None and self.role is None and self.status is None:
            raise ValueError("At least one user field must be supplied.")
        return self


class AccessSessionView(BaseModel):
    session_id: str
    user_id: str
    status: Literal["active", "revoked", "expired"]
    created_at: str
    expires_at: str
    revoked_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    user_agent: Optional[str] = None


class ProjectMemberUpsertRequest(BaseModel):
    role: ProjectRole


class ProjectMemberView(BaseModel):
    user: UserAdministrationRecord
    binding: ProjectRoleBinding


class ProjectMemberCandidate(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_preset: Optional[str] = None
    avatar_image: bool = False


__all__ = [
    "AccessSessionView",
    "AccountStatus",
    "GlobalRole",
    "ProjectMemberUpsertRequest",
    "ProjectMemberCandidate",
    "ProjectMemberView",
    "ProjectRole",
    "UserAdministrationPage",
    "UserAdministrationPatch",
    "UserAdministrationRecord",
]
