"""Startup-only registration using the isolated real PostgreSQL test database."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import make_url

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import UserIdentityRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.platform.account_identity import SQLAlchemyAccountIdentityService
from apps.api.app.infrastructure.platform.operator_identity import (
    OPERATOR_PASSWORD_MARKER, SQLAlchemyOperatorIdentityBootstrap,
)
from apps.api.app.main import app
from apps.api.app.interface.http.auth import AuthConfig


@pytest.fixture
def operator():
    url = make_url(engine.url)
    assert url.get_backend_name() == "postgresql" and url.database.startswith("nasus_test_")
    ident = uuid4().hex
    return UserProfile(id="operator_" + ident, name="Configured operator", email=f"operator-{ident}@example.test",
        role="platform_admin")


def persisted(profile):
    with session_scope() as session:
        row = session.get(UserIdentityRecord, profile.id)
        return {column.name: getattr(row, column.name) for column in row.__table__.columns} if row else None


def test_concurrent_startup_records_one_non_password_operator(operator):
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: SQLAlchemyOperatorIdentityBootstrap().ensure(operator), range(2)))
    row = persisted(operator)
    assert row["status"] == "active" and row["role"] == operator.role
    assert row["password_hash"] == OPERATOR_PASSWORD_MARKER
    for password in ("", "password123", OPERATOR_PASSWORD_MARKER):
        assert not SQLAlchemyAccountIdentityService._verify_password(password, row["password_hash"])
    SQLAlchemyOperatorIdentityBootstrap().ensure(operator)
    assert persisted(operator) == row


def test_restart_preserves_suspended_downgraded_operator_and_profile_edits(operator):
    SQLAlchemyOperatorIdentityBootstrap().ensure(operator)
    with session_scope() as session:
        row = session.get(UserIdentityRecord, operator.id)
        row.status, row.role, row.display_name = "suspended", "viewer", "Edited by administrator"
    before = persisted(operator)
    SQLAlchemyOperatorIdentityBootstrap().ensure(operator)
    assert persisted(operator) == before


@pytest.mark.parametrize("collision", ["same_id", "same_email", "case_variant_email"])
def test_operator_registration_never_takes_over_an_existing_user(operator, collision):
    user = UserIdentityRecord(user_id=operator.id if collision == "same_id" else "user_" + uuid4().hex,
        display_name="Existing person", email=operator.email.upper() if collision == "case_variant_email" else operator.email,
        role="viewer", password_hash=SQLAlchemyAccountIdentityService._hash_password("ExistingPassword123!"),
        status="active", created_at="2026-10-09T00:00:00Z", updated_at="2026-10-09T00:00:00Z")
    with session_scope() as session:
        session.add(user)
        identity = user.user_id
    with pytest.raises(ValueError, match="conflict|another account"):
        SQLAlchemyOperatorIdentityBootstrap().ensure(operator)
    with session_scope() as session:
        original = session.get(UserIdentityRecord, identity)
        assert original.role == "viewer" and original.password_hash != OPERATOR_PASSWORD_MARKER
        assert SQLAlchemyAccountIdentityService._verify_password("ExistingPassword123!", original.password_hash)
        assert session.scalar(select(UserIdentityRecord.user_id).where(UserIdentityRecord.user_id == operator.id)) == (
            operator.id if collision == "same_id" else None)


@pytest.mark.parametrize("mode,token,expected", [("dev", "", True), ("required", "", False),
    ("production", "", False), ("required", "explicit-operator-token", True)])
def test_composition_only_provisions_a_configured_local_or_static_principal(operator, monkeypatch, mode, token, expected):
    import apps.api.app.bootstrap as bootstrap
    from apps.api.app.composition import create_app
    configuration = AuthConfig(mode=mode, bearer_token=token, user_id=operator.id, user_name=operator.name,
        user_email=operator.email, user_role=operator.role)
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: replace(app.state.container, auth_config=configuration))
    created = create_app()
    assert created.state.auth_config == configuration
    assert (persisted(operator) is not None) == expected


def configured_application(operator, monkeypatch, mode):
    import apps.api.app.bootstrap as bootstrap
    from apps.api.app.composition import create_app
    configuration = AuthConfig(mode=mode, bearer_token="static-operator-token" if mode == "required" else "",
        user_id=operator.id, user_name=operator.name, user_email=operator.email, user_role=operator.role)
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: replace(app.state.container, auth_config=configuration))
    application = create_app()
    headers = {"Authorization": "Bearer static-operator-token"} if mode == "required" else {}
    return application, TestClient(application), headers


@pytest.mark.parametrize("mode", ["dev", "required"])
def test_http_operator_uses_current_profile_and_governed_role_changes(operator, monkeypatch, mode):
    application, client, headers = configured_application(operator, monkeypatch, mode)
    assert client.get("/v1/auth/me", headers=headers).json()["role"] == "platform_admin"
    registered = client.post("/v1/auth/register", json={"email": f"admin-{uuid4().hex}@example.test",
        "password": "AdminPassword123!", "name": "Independent administrator"})
    assert registered.status_code == 200, registered.text
    administrator = registered.json()
    with session_scope() as session:
        session.get(UserIdentityRecord, administrator["user"]["id"]).role = "platform_admin"
    admin_headers = {"Authorization": "Bearer " + administrator["access_token"]}
    changed = client.patch(f"/v1/admin/users/{operator.id}", headers=admin_headers,
        json={"role": "viewer", "display_name": "Current operator profile"})
    assert changed.status_code == 200, changed.text
    current = client.get("/v1/auth/me", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["role"] == "viewer" and current.json()["name"] == "Current operator profile"
    assert client.get("/v1/admin/users", headers=headers).status_code == 403
    denied = client.post("/v1/tool-invocations", headers=headers, json={"tool_id": "project.create",
        "input": {"name": "Operator downgrade must reject creation"}, "initiator_actor": "user", "initiator_surface": "api"})
    assert denied.status_code == 200, denied.text
    assert denied.json()["result"]["followup_reason"] == "authorization_denied"
    assert denied.json()["input_payload"]["authorization_user_role"] == "viewer"
    assert application.state.auth_config.user_role == "platform_admin"


@pytest.mark.parametrize("mode", ["dev", "required"])
def test_http_operator_suspension_revokes_access_without_recreating_identity(operator, monkeypatch, mode):
    _, client, headers = configured_application(operator, monkeypatch, mode)
    with session_scope() as session:
        session.get(UserIdentityRecord, operator.id).status = "suspended"
    original = persisted(operator)
    for path in ("/v1/auth/me", "/v1/projects", "/v1/settings"):
        denied = client.get(path, headers=headers)
        assert denied.status_code == 401, denied.text
        assert denied.json()["error"]["code"] == "configured_identity_unavailable"
    assert client.post("/v1/tool-invocations", headers=headers,
        json={"tool_id": "project.create", "input": {"name": "Suspended operator"}}).status_code == 401
    assert client.get("/healthz", headers=headers).status_code == 200
    assert client.get("/healthz").status_code == 200
    SQLAlchemyOperatorIdentityBootstrap().ensure(operator)
    assert persisted(operator) == original
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
    with session_scope() as session:
        session.get(UserIdentityRecord, operator.id).status = "active"
    assert client.get("/v1/auth/me", headers=headers).status_code == 200


@pytest.mark.parametrize("damage", ["missing", "email", "password_identity"])
def test_http_operator_rejects_missing_or_replaced_identity_without_repair(operator, monkeypatch, damage):
    _, client, headers = configured_application(operator, monkeypatch, "required")
    with session_scope() as session:
        row = session.get(UserIdentityRecord, operator.id)
        if damage == "missing":
            session.delete(row)
        elif damage == "email":
            row.email = "replaced-" + operator.email
        else:
            row.password_hash = SQLAlchemyAccountIdentityService._hash_password("ReplacementPassword123!")
    original = persisted(operator)
    denied = client.get("/v1/auth/me", headers=headers)
    assert denied.status_code == 401, denied.text
    assert denied.json()["error"]["code"] == "configured_identity_unavailable"
    assert persisted(operator) == original


def test_http_static_query_token_observes_current_account_status(operator, monkeypatch):
    _, client, _ = configured_application(operator, monkeypatch, "required")
    params = {"access_token": "static-operator-token"}
    assert client.get("/v1/auth/me", params=params).status_code == 200
    with session_scope() as session:
        session.get(UserIdentityRecord, operator.id).status = "suspended"
    assert client.get("/v1/auth/me", params=params).status_code == 401
