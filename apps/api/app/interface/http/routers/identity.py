from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query

from ....application.platform.identity_administration_models import (
    ProjectMemberUpsertRequest,
    UserAdministrationPatch,
)
from ..dependencies import IdentityAdministrationApp
from ..errors import error_response


router = APIRouter(tags=["identity-administration"])


@router.get("/v1/admin/users")
def list_users(
    identities: IdentityAdministrationApp,
    q: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    return identities.list_users(query=q, limit=limit, offset=offset)


@router.patch("/v1/admin/users/{user_id}")
def update_user(
    user_id: str,
    payload: UserAdministrationPatch,
    identities: IdentityAdministrationApp,
) -> Any:
    return identities.update_user(user_id, payload)


@router.get("/v1/auth/sessions")
def list_my_sessions(identities: IdentityAdministrationApp) -> Any:
    return identities.list_my_sessions()


@router.delete("/v1/auth/sessions/{session_id}")
def revoke_my_session(session_id: str, identities: IdentityAdministrationApp) -> Any:
    return identities.revoke_session(session_id)


@router.get("/v1/admin/users/{user_id}/sessions")
def list_user_sessions(user_id: str, identities: IdentityAdministrationApp) -> Any:
    return identities.list_user_sessions(user_id)


@router.delete("/v1/admin/users/{user_id}/sessions/{session_id}")
def revoke_user_session(
    user_id: str,
    session_id: str,
    identities: IdentityAdministrationApp,
) -> Any:
    return identities.revoke_session(session_id, target_user_id=user_id)


@router.get("/v1/projects/{project_id}/members")
def list_project_members(project_id: str, identities: IdentityAdministrationApp) -> Any:
    try:
        return identities.list_project_members(project_id)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc


@router.get("/v1/projects/{project_id}/member-candidates")
def search_project_member_candidates(
    project_id: str,
    identities: IdentityAdministrationApp,
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
) -> Any:
    try:
        return identities.search_project_member_candidates(
            project_id,
            query=q,
            limit=limit,
        )
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc


@router.put("/v1/projects/{project_id}/members/{user_id}")
def upsert_project_member(
    project_id: str,
    user_id: str,
    payload: ProjectMemberUpsertRequest,
    identities: IdentityAdministrationApp,
) -> Any:
    try:
        return identities.upsert_project_member(project_id, user_id, payload)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc


@router.delete("/v1/projects/{project_id}/members/{user_id}")
def revoke_project_member(
    project_id: str,
    user_id: str,
    identities: IdentityAdministrationApp,
) -> Any:
    try:
        return identities.revoke_project_member(project_id, user_id)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc


__all__ = ["router"]
