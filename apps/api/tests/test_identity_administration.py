from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from apps.api.app.infrastructure.persistence.database import SessionLocal
from apps.api.app.infrastructure.persistence.db_models import (
    AccessSessionRecord,
    ProjectRoleBindingRecord,
    UserIdentityRecord,
)
from apps.api.app.main import app


client = TestClient(app)


def _reset_identity_tables() -> None:
    with SessionLocal() as session:
        session.execute(delete(AccessSessionRecord))
        session.execute(delete(ProjectRoleBindingRecord))
        session.execute(delete(UserIdentityRecord))
        session.commit()


def _register(email: str, name: str) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "strong-password-123", "name": name},
    )
    assert response.status_code == 200
    body = response.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


def test_platform_user_administration_is_persistent_and_revokes_suspended_sessions() -> None:
    _reset_identity_tables()
    registered, headers = _register("managed-user@example.com", "Managed User")
    user_id = registered["user"]["id"]

    denied = client.get("/v1/admin/users", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "platform_admin_required"

    page = client.get("/v1/admin/users", params={"q": "managed-user"})
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["active_session_count"] == 1

    updated = client.patch(
        f"/v1/admin/users/{user_id}",
        json={"display_name": "Managed Tester", "role": "tester"},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Managed Tester"
    assert updated.json()["role"] == "tester"

    suspended = client.patch(
        f"/v1/admin/users/{user_id}",
        json={"status": "suspended"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["active_session_count"] == 0

    rejected = client.get("/v1/auth/me", headers=headers)
    assert rejected.status_code == 401
    with SessionLocal() as session:
        access_session = session.scalar(
            select(AccessSessionRecord).where(AccessSessionRecord.user_id == user_id)
        )
        assert access_session is not None
        assert access_session.status == "revoked"


def test_user_can_inspect_and_revoke_only_own_access_session() -> None:
    _reset_identity_tables()
    first, first_headers = _register("first-session@example.com", "First Session")
    second, second_headers = _register("second-session@example.com", "Second Session")

    first_sessions = client.get("/v1/auth/sessions", headers=first_headers)
    assert first_sessions.status_code == 200
    first_session_id = first_sessions.json()[0]["session_id"]

    second_sessions = client.get("/v1/auth/sessions", headers=second_headers)
    second_session_id = second_sessions.json()[0]["session_id"]
    cross_account = client.delete(
        f"/v1/auth/sessions/{second_session_id}",
        headers=first_headers,
    )
    assert cross_account.status_code == 404

    revoked = client.delete(
        f"/v1/auth/sessions/{first_session_id}",
        headers=first_headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert client.get("/v1/auth/me", headers=first_headers).status_code == 401
    assert client.get("/v1/auth/me", headers=second_headers).status_code == 200


def test_project_administrator_manages_members_and_access_changes_immediately() -> None:
    _reset_identity_tables()
    owner, owner_headers = _register("member-owner@example.com", "Member Owner")
    member, member_headers = _register("project-member@example.com", "Project Member")

    created = client.post(
        "/v1/projects",
        headers=owner_headers,
        json={"name": "Identity Administration Project"},
    )
    assert created.status_code == 200
    project_id = created.json()["id"]

    assigned = client.put(
        f"/v1/projects/{project_id}/members/{member['user']['id']}",
        headers=owner_headers,
        json={"role": "tester"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["binding"]["role"] == "tester"

    candidate = _register("candidate-member@example.com", "Candidate Member")[0]
    candidates = client.get(
        f"/v1/projects/{project_id}/member-candidates",
        headers=owner_headers,
        params={"q": "candidate-member"},
    )
    assert candidates.status_code == 200
    assert candidates.json() == [
        {
            "id": candidate["user"]["id"],
            "email": "candidate-member@example.com",
            "display_name": "Candidate Member",
            "avatar_preset": None,
            "avatar_image": False,
        }
    ]

    listed = client.get(f"/v1/projects/{project_id}/members", headers=owner_headers)
    assert listed.status_code == 200
    assert {item["user"]["id"] for item in listed.json()} == {
        owner["user"]["id"],
        member["user"]["id"],
    }
    assert client.get(f"/v1/projects/{project_id}", headers=member_headers).status_code == 200

    denied = client.get(f"/v1/projects/{project_id}/members", headers=member_headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "project_admin_required"

    revoked = client.delete(
        f"/v1/projects/{project_id}/members/{member['user']['id']}",
        headers=owner_headers,
    )
    assert revoked.status_code == 200
    assert revoked.json() == {"ok": True}
    denied_project = client.get(f"/v1/projects/{project_id}", headers=member_headers)
    assert denied_project.status_code == 403


def test_platform_admin_cannot_demote_or_suspend_its_own_active_account() -> None:
    _reset_identity_tables()
    registered, _headers = _register("self-admin@example.com", "Self Admin")
    user_id = registered["user"]["id"]
    with SessionLocal() as session:
        session.execute(
            update(UserIdentityRecord)
            .where(UserIdentityRecord.user_id == user_id)
            .values(role="platform_admin")
        )
        session.commit()
    login = client.post(
        "/v1/auth/login",
        json={"email": "self-admin@example.com", "password": "strong-password-123"},
    )
    admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    rejected = client.patch(
        f"/v1/admin/users/{user_id}",
        headers=admin_headers,
        json={"role": "qa_lead"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "cannot_remove_own_platform_access"
