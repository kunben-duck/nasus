import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import delete, select, update

STATE_DIR = os.environ.get("NASUS_STATE_DIR") or tempfile.mkdtemp(prefix="nasus-api-tests-")
os.environ["NASUS_STATE_DIR"] = STATE_DIR
os.environ.setdefault("NASUS_RUNNER_MODE", "protocol_stub")

from fastapi.testclient import TestClient

from starlette.requests import Request

from apps.api.app.auth import AuthConfig, authenticate_request
from apps.api.app.database import SessionLocal
from apps.api.app.db_models import (
    AccessSessionRecord,
    ModelConfigTestGrantRecord,
    ModelProviderConfigRecord,
    ModelRouteSelectionRecord,
    ProjectRoleBindingRecord,
    UserIdentityRecord,
)
from apps.api.app.main import app
from apps.api.app.conversation_orchestrator import ConversationOrchestrator
from apps.api.app.llm import EmbeddingBatchResult, RerankBatchResult
from apps.api.app.application.quality_loop.generation import QualityGenerationError
from apps.api.app.application.platform.model_settings import StudioSettings
from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.domain.platform.llm_call import LLMCallContext
from apps.api.app.application.system_image.source_ports import IngestedSource, SourceSpec
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.conversation_repository import (
    ConversationRepository,
)
from apps.api.app.infrastructure.persistence.model_config_test_grant_repository import (
    SQLAlchemyModelConfigTestGrantRepository,
)
from apps.api.app.interface.sse.encoding import encode_event, encode_heartbeat
from apps.api.app.models import ApprovalDetail, USItem
from apps.api.app.store import InMemoryStore, store


client = TestClient(app)
TEST_TARGET_BASE_URL = "http://example.test"


def test_platform_admin_can_query_redacted_llm_call_audit() -> None:
    result = asyncio.run(
        store.llm.generate_reply(
            settings=StudioSettings(),
            system_prompt="sensitive system text",
            user_message="sensitive user text",
            context_snapshot="sensitive context text",
            history_snapshot="sensitive history text",
            fallback_text="sensitive fallback text",
            call_context=LLMCallContext(
                purpose="test.api.audit",
                project_id="project_llm_audit_api",
            ),
        )
    )

    response = client.get(
        "/v1/llm-calls",
        params={"project_id": "project_llm_audit_api", "limit": 10},
    )

    assert response.status_code == 200
    record = next(item for item in response.json() if item["id"] == result.llm_call_id)
    assert record["purpose"] == "test.api.audit"
    assert record["route"] == "chat"
    assert record["request_hash"].startswith("sha256:")
    assert "sensitive" not in str(record)


def reset_model_configuration_tables():
    with SessionLocal() as session:
        session.execute(delete(ModelConfigTestGrantRecord))
        session.execute(delete(ModelRouteSelectionRecord))
        session.execute(delete(ModelProviderConfigRecord))
        session.commit()
    store.get_settings()


def reset_auth_tables():
    with SessionLocal() as session:
        session.execute(delete(AccessSessionRecord))
        session.execute(delete(ProjectRoleBindingRecord))
        session.execute(delete(UserIdentityRecord))
        session.commit()


def restore_model_route(original_settings: dict, route: str = "chat"):
    route_state = original_settings.get("model_configurations", {}).get(route, {})
    active_source = route_state.get("active_source", "system_default")
    active_config_id = route_state.get("active_config_id")
    if active_source == "custom" and active_config_id:
        client.post(f"/v1/settings/model-configs/{active_config_id}/activate")
    else:
        client.post(f"/v1/settings/model-configs/{route}/use-system-default")


def save_tested_model_config(
    *,
    route: str = "chat",
    display_name: str = "Test custom model",
    provider_kind: str = "openai_compatible",
    base_url: Optional[str] = "https://api.example.com/v1",
    model_name: str,
    api_key: str,
    activate: bool = True,
):
    payload = {
        "model_route": route,
        "display_name": display_name,
        "custom_provider_kind": provider_kind,
        "custom_base_url": base_url,
        "custom_model_name": model_name,
        "custom_api_key": api_key,
    }

    async def fake_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
        assert custom_model.model_name == model_name
        assert custom_api_key == api_key
        return "READY"

    async def fake_probe_embedding_provider(**kwargs):
        assert kwargs["model_name"] == model_name

    async def fake_rerank_candidates(*, settings, query, documents, custom_api_key=None, call_context=None):
        del call_context
        assert custom_api_key == api_key
        return RerankBatchResult(
            ranked_indices=list(range(len(documents))),
            provider="openai_compatible",
            model_name=model_name,
            mode="live",
            reason="test_probe",
            latency_ms=1,
        )

    if route == "embedding":
        patcher = patch.object(store.llm, "_probe_embedding_provider", new=fake_probe_embedding_provider)
    elif route == "rerank":
        patcher = patch.object(store.llm, "rerank_candidates", new=fake_rerank_candidates)
    else:
        patcher = patch.object(store.llm, "_call_custom", new=fake_call_custom)

    with patcher:
        test_response = client.post("/v1/settings/model-configs/test", json=payload)

    assert test_response.status_code == 200
    test_body = test_response.json()
    assert test_body["ok"] is True
    assert test_body["test_token"]

    save_response = client.post(
        "/v1/settings/model-configs",
        json={**payload, "test_token": test_body["test_token"]},
    )
    assert save_response.status_code == 200
    route_configs = save_response.json()["model_configurations"][route]["configurations"]
    config = next(item for item in route_configs if item["model_name"] == model_name)

    if activate:
        activate_response = client.post(f"/v1/settings/model-configs/{config['config_id']}/activate")
        assert activate_response.status_code == 200
        return activate_response.json(), config

    return save_response.json(), config


def test_auth_required_mode_rejects_missing_or_invalid_tokens_and_allows_valid_tokens():
    previous = app.state.auth_config
    app.state.auth_config = AuthConfig(
        mode="required",
        bearer_token="test-token",
        user_id="user_prod",
        user_name="Production User",
        user_email="prod@example.com",
        user_role="qa_lead",
    )
    protected_client = TestClient(app)
    try:
        assert protected_client.get("/healthz").status_code == 200

        missing = protected_client.get("/v1/auth/me", headers={"X-Request-ID": "req_auth_test"})
        assert missing.status_code == 401
        missing_body = missing.json()
        assert missing_body["error"]["code"] == "missing_token"
        assert missing_body["request_id"] == "req_auth_test"
        assert missing_body["timestamp"] != "2026-03-27T00:00:00Z"

        invalid = protected_client.get("/v1/auth/me", headers={"Authorization": "Bearer wrong"})
        assert invalid.status_code == 401
        assert invalid.json()["error"]["code"] == "invalid_token"

        valid = protected_client.get("/v1/auth/me", headers={"Authorization": "Bearer test-token"})
        assert valid.status_code == 200
        assert valid.json()["id"] == "user_prod"
        assert valid.json()["role"] == "qa_lead"
    finally:
        app.state.auth_config = previous


def test_auth_required_mode_allows_sse_query_token_for_eventsource():
    config = AuthConfig(
        mode="required",
        bearer_token="sse-token",
        user_id="user_sse",
        user_name="SSE User",
        user_email="sse@example.com",
        user_role="qa_lead",
    )
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/v1/conversations/conv_test/events",
        "headers": [],
        "query_string": b"access_token=sse-token",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "scheme": "http",
    })

    result = authenticate_request(request, config)
    assert not hasattr(result, "status_code")
    assert result.id == "user_sse"


def test_email_registration_login_and_logout_session_flow():
    reset_auth_tables()
    email = "qa-admin@example.com"
    password = "strong-password-123"

    registered = client.post(
        "/v1/auth/register",
        json={"email": email, "password": password, "name": "QA Admin"},
    )
    assert registered.status_code == 200
    registered_body = registered.json()
    assert registered_body["access_token"]
    assert registered_body["token_type"] == "Bearer"
    assert registered_body["user"]["email"] == email
    assert registered_body["user"]["role"] == "qa_lead"

    duplicate = client.post("/v1/auth/register", json={"email": email, "password": password})
    assert duplicate.status_code == 409

    token = registered_body["access_token"]
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert me.json()["avatar_url"] is None

    avatar_data_url = "data:image/png;base64,iVBORw0KGgo="
    avatar = client.patch(
        "/v1/auth/me/avatar",
        headers={"Authorization": f"Bearer {token}"},
        json={"avatar_url": avatar_data_url},
    )
    assert avatar.status_code == 200
    assert avatar.json()["avatar_url"] is None
    assert avatar.json()["avatar_preset"] is None
    assert avatar.json()["avatar_image"] is True

    me_with_avatar = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_with_avatar.status_code == 200
    assert me_with_avatar.json()["avatar_url"] is None
    assert me_with_avatar.json()["avatar_image"] is True
    avatar_content = client.get("/v1/auth/me/avatar/content", headers={"Authorization": f"Bearer {token}"})
    assert avatar_content.status_code == 200
    assert avatar_content.headers["content-type"] == "image/png"
    assert avatar_content.content == b"\x89PNG\r\n\x1a\n"
    with SessionLocal() as session:
        avatar_user = session.get(UserIdentityRecord, registered_body["user"]["id"])
        assert avatar_user is not None
        assert avatar_user.avatar_object_ref
        assert avatar_user.avatar_url is None
        assert avatar_user.avatar_mime_type == "image/png"

    preset_avatar = client.patch(
        "/v1/auth/me/avatar",
        headers={"Authorization": f"Bearer {token}"},
        json={"avatar_preset": "yellow_duck"},
    )
    assert preset_avatar.status_code == 200
    assert preset_avatar.json()["avatar_url"] is None
    assert preset_avatar.json()["avatar_preset"] == "yellow_duck"
    assert preset_avatar.json()["avatar_image"] is False
    preset_content = client.get("/v1/auth/me/avatar/content", headers={"Authorization": f"Bearer {token}"})
    assert preset_content.status_code == 404

    invalid_avatar = client.patch(
        "/v1/auth/me/avatar",
        headers={"Authorization": f"Bearer {token}"},
        json={"avatar_url": "https://example.com/avatar.png"},
    )
    assert invalid_avatar.status_code == 422

    invalid_preset = client.patch(
        "/v1/auth/me/avatar",
        headers={"Authorization": f"Bearer {token}"},
        json={"avatar_preset": "psyduck"},
    )
    assert invalid_preset.status_code == 422

    logout = client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200
    assert logout.json()["ok"] is True

    revoked = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "invalid_token"

    login = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    assert login.json()["access_token"]
    assert login.json()["user"]["role"] == "qa_lead"

    bad_login = client.post("/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert bad_login.status_code == 401


def test_request_actor_and_project_membership_isolate_users_end_to_end():
    reset_auth_tables()

    def register(email: str, name: str) -> tuple[dict, dict[str, str]]:
        response = client.post(
            "/v1/auth/register",
            json={"email": email, "password": "strong-password-123", "name": name},
        )
        assert response.status_code == 200
        body = response.json()
        return body["user"], {"Authorization": f"Bearer {body['access_token']}"}

    owner, owner_headers = register("owner@example.com", "Project Owner")
    outsider, outsider_headers = register("outsider@example.com", "Project Outsider")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                client.get,
                "/v1/auth/me",
                headers=owner_headers if index % 2 == 0 else outsider_headers,
            )
            for index in range(24)
        ]
    identities = [future.result().json()["id"] for future in futures]
    assert identities[::2] == [owner["id"]] * 12
    assert identities[1::2] == [outsider["id"]] * 12

    created = client.post(
        "/v1/projects",
        headers=owner_headers,
        json={"name": "Private Release Project"},
    )
    assert created.status_code == 200
    project = created.json()
    with SessionLocal() as session:
        binding = session.scalar(
            select(ProjectRoleBindingRecord).where(
                ProjectRoleBindingRecord.project_id == project["id"],
                ProjectRoleBindingRecord.user_id == owner["id"],
            )
        )
        assert binding is not None
        assert binding.role == "project_admin"

    owner_project = client.get(f"/v1/projects/{project['id']}", headers=owner_headers)
    assert owner_project.status_code == 200
    outsider_projects = client.get("/v1/projects", headers=outsider_headers)
    assert outsider_projects.status_code == 200
    assert project["id"] not in {item["id"] for item in outsider_projects.json()}
    outsider_project = client.get(f"/v1/projects/{project['id']}", headers=outsider_headers)
    assert outsider_project.status_code == 403
    assert outsider_project.json()["error"]["code"] == "project_access_denied"

    owner_conversation = client.post(
        "/v1/conversations",
        headers=owner_headers,
        json={"space_type": "build", "space_id": "private-owner-build", "title": "Owner build"},
    )
    assert owner_conversation.status_code == 200
    outsider_conversation = client.get(
        f"/v1/conversations/{owner_conversation.json()['id']}",
        headers=outsider_headers,
    )
    assert outsider_conversation.status_code == 403
    assert outsider_conversation.json()["error"]["code"] == "conversation_access_denied"

    denied_invocation = client.post(
        "/v1/tool-invocations",
        headers=outsider_headers,
        json={
            "tool_id": "query.project.status",
            "input": {"project_id": project["id"]},
            "initiator_surface": "api",
            "initiator_actor": "user",
        },
    )
    assert denied_invocation.status_code == 200
    denied_body = denied_invocation.json()
    assert denied_body["status"] == "failed"
    assert denied_body["result"]["followup_reason"] == "authorization_denied"

    owner_critical = client.post(
        "/v1/tool-invocations",
        headers=owner_headers,
        json={
            "tool_id": "baseline.promote",
            "input": {"project_id": project["id"], "approval_id": "approval_required"},
            "initiator_surface": "api",
            "initiator_actor": "user",
        },
    )
    assert owner_critical.status_code == 200
    assert owner_critical.json()["status"] in {"waiting_approval", "waiting_confirmation"}
    assert owner_critical.json()["input_payload"].get("authorization_denied") is not True


def test_tool_runtime_enforces_role_based_authorization_and_audits_denial():
    previous_config = app.state.auth_config
    app.state.auth_config = AuthConfig(
        mode="required",
        bearer_token="viewer-token",
        user_id="user_viewer",
        user_name="Viewer User",
        user_email="viewer@example.com",
        user_role="viewer",
    )
    protected_client = TestClient(app)
    headers = {"Authorization": "Bearer viewer-token"}
    try:
        allowed_query = protected_client.post(
            "/v1/tool-invocations",
            headers=headers,
            json={
                "tool_id": "query.dashboard.progress",
                "input": {},
                "initiator_surface": "api",
                "initiator_actor": "user",
            },
        )
        assert allowed_query.status_code == 200
        assert allowed_query.json()["status"] == "completed"

        denied_analysis = protected_client.post(
            "/v1/tool-invocations",
            headers=headers,
            json={
                "tool_id": "quality.scope.generate",
                "input": {"project_id": "project_missing", "us_id": "us_missing"},
                "initiator_surface": "api",
                "initiator_actor": "user",
            },
        )
        assert denied_analysis.status_code == 200
        assert denied_analysis.json()["status"] == "failed"
        assert denied_analysis.json()["result"]["followup_reason"] == "authorization_denied"

        denied_project = protected_client.post(
            "/v1/tool-invocations",
            headers=headers,
            json={
                "tool_id": "project.create",
                "input": {"name": "Unauthorized Viewer Project"},
                "initiator_surface": "api",
                "initiator_actor": "user",
            },
        )
        assert denied_project.status_code == 200
        denied_body = denied_project.json()
        assert denied_body["status"] == "failed"
        assert denied_body["result"]["followup_reason"] == "authorization_denied"
        assert denied_body["input_payload"]["authorization_denied"] is True
        assert denied_body["input_payload"]["authorization_user_role"] == "viewer"
        assert "qa_lead" in denied_body["input_payload"]["authorization_required_roles"]
        assert all(
            project.name != "Unauthorized Viewer Project"
            for project in store.project_repository.list_projects()
        )

        audit = protected_client.get(
            f"/v1/audit-events?tool_invocation_id={denied_body['id']}",
            headers=headers,
        ).json()
        actions = {event["action"] for event in audit}
        assert "tool.invocation.authorization_denied" in actions
        assert "tool.invocation.executing" not in actions
        denied_event = next(event for event in audit if event["action"] == "tool.invocation.authorization_denied")
        assert denied_event["metadata"]["authorization_user_role"] == "viewer"
        assert "qa_lead" in denied_event["metadata"]["authorization_required_roles"]
    finally:
        app.state.auth_config = previous_config


def test_critical_tool_requires_project_admin_role_before_governance_gates():
    previous_config = app.state.auth_config
    app.state.auth_config = AuthConfig(
        mode="required",
        bearer_token="qa-token",
        user_id="user_qa",
        user_name="QA Lead",
        user_email="qa@example.com",
        user_role="qa_lead",
    )
    protected_client = TestClient(app)
    try:
        denied = protected_client.post(
            "/v1/tool-invocations",
            headers={"Authorization": "Bearer qa-token"},
            json={
                "tool_id": "baseline.promote",
                "input": {"project_id": "project_missing", "approval_id": "approval_missing"},
                "initiator_surface": "api",
                "initiator_actor": "user",
            },
        )
        assert denied.status_code == 200
        body = denied.json()
        assert body["status"] == "failed"
        assert body["result"]["followup_reason"] == "authorization_denied"
        assert body["input_payload"]["authorization_user_role"] == "qa_lead"
        assert "project_admin" in body["input_payload"]["authorization_required_roles"]
        audit = protected_client.get(
            f"/v1/audit-events?tool_invocation_id={body['id']}",
            headers={"Authorization": "Bearer qa-token"},
        ).json()
        assert "tool.invocation.gated" not in {event["action"] for event in audit}
        assert "tool.invocation.authorization_denied" in {event["action"] for event in audit}
    finally:
        app.state.auth_config = previous_config


def wait_until(predicate, timeout: float = 1.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition was not met before timeout")


def create_system_image_source_dirs(prefix: str):
    source_root = Path(tempfile.mkdtemp(prefix=prefix))
    code_dir = source_root / "code"
    us_dir = source_root / "us"
    tests_dir = source_root / "tests"
    code_dir.mkdir()
    us_dir.mkdir()
    tests_dir.mkdir()
    (code_dir / "checkout.py").write_text("def checkout(cart):\n    return cart.total\n", encoding="utf-8")
    (us_dir / "US-001.md").write_text("# US-001\nAs a buyer, I can complete checkout.\n", encoding="utf-8")
    (tests_dir / "test_checkout.py").write_text("def test_checkout():\n    assert True\n", encoding="utf-8")
    return code_dir, us_dir, tests_dir


def system_image_source_prompt(code_dir: Path, us_dir: Path, tests_dir: Path) -> str:
    return f"code path {code_dir}, US docs path {us_dir}, tests path {tests_dir}"


def create_project_with_materialized_system_image(name: str):
    project = client.post("/v1/projects", json={"name": name}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs(f"nasus-{name.lower().replace(' ', '-')}-")
    source_specs = [
        {"source_type": "code", "source_uri": str(code_dir)},
        {"source_type": "us_doc", "source_uri": str(us_dir)},
        {"source_type": "test_asset", "source_uri": str(tests_dir)},
    ]
    registered = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {"project_id": project["id"], "source_specs": source_specs},
        },
    )
    assert registered.status_code == 200
    assert registered.json()["status"] == "completed"
    for tool_id in ["system_image.sources.ingest", "system_image.context.materialize"]:
        invoked = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": {"project_id": project["id"]},
            },
        )
        assert invoked.status_code == 200
        assert invoked.json()["status"] == "completed"
    workspace = client.get(f"/v1/projects/{project['id']}").json()
    assert workspace["us_items"]
    return project, conversation, workspace


def test_system_image_source_prompt_parser_does_not_match_us_inside_absolute_path():
    prompt = (
        "code path /Users/uben/project/project/Nasus/tests/fixtures/system-image/code, "
        "US docs path /Users/uben/project/project/Nasus/tests/fixtures/system-image/us, "
        "tests path /Users/uben/project/project/Nasus/tests/fixtures/system-image/tests"
    )

    specs = ConversationOrchestrator._extract_system_image_source_specs(prompt)

    assert specs == [
        {
            "source_type": "code",
            "source_uri": "/Users/uben/project/project/Nasus/tests/fixtures/system-image/code",
        },
        {
            "source_type": "us_doc",
            "source_uri": "/Users/uben/project/project/Nasus/tests/fixtures/system-image/us",
        },
        {
            "source_type": "test_asset",
            "source_uri": "/Users/uben/project/project/Nasus/tests/fixtures/system-image/tests",
        },
    ]


def test_system_image_source_prompt_parser_accepts_managed_object_uris():
    specs = ConversationOrchestrator._extract_system_image_source_specs(
        "code path /srv/repository, "
        "US docs URI s3://nasus-artifacts/source-uploads/proj/us.zip, "
        "test assets URI local-object://nasus-artifacts/source-uploads/proj/tests.zip"
    )

    assert specs == [
        {"source_type": "code", "source_uri": "/srv/repository"},
        {
            "source_type": "us_doc",
            "source_uri": "s3://nasus-artifacts/source-uploads/proj/us.zip",
        },
        {
            "source_type": "test_asset",
            "source_uri": "local-object://nasus-artifacts/source-uploads/proj/tests.zip",
        },
    ]


def test_welcome_payload_has_recent_projects():
    response = client.get("/v1/welcome")
    assert response.status_code == 200
    body = response.json()
    assert len(body["recent_projects"]) >= 1


def test_settings_can_be_read_and_updated():
    original = client.get("/v1/settings").json()

    try:
        response = client.patch(
            "/v1/settings",
            json={
                "language": "en",
                "theme": "system",
                "model_preset": "system_default",
                "notification_mode": "all",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["language"] == "en"
        assert body["theme"] == "system"
        assert body["model_preset"] == "system_default"
        assert body["notification_mode"] == "all"
        assert body["model_provider"] == body["active_provider_status"]["provider"]
        assert body["runtime_mode"] == body["active_provider_status"]["mode"]
        assert body["fallback_provider"] == "mock"
    finally:
        client.patch(
            "/v1/settings",
            json={
                "language": original["language"],
                "theme": original["theme"],
                "model_preset": original["model_preset"],
                "notification_mode": original["notification_mode"],
            },
        )


def test_custom_model_config_can_be_saved():
    original = client.get("/v1/settings").json()
    reset_model_configuration_tables()

    try:
        body, config = save_tested_model_config(
            display_name="Example live model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="example-model",
            api_key="sk-custom-1234",
        )
        assert body["model_preset"] == "custom"
        assert body["model_provider"] == "openai_compatible"
        assert body["custom_model"]["provider_kind"] == "openai_compatible"
        assert body["custom_model"]["base_url"] == "https://api.example.com/v1"
        assert body["custom_model"]["model_name"] == "example-model"
        assert body["custom_model"]["has_api_key"] is True
        assert body["custom_model"]["api_key_masked"] == "••••1234"
        assert body["runtime_mode"] == "live"
        assert body["active_provider_status"]["provider"] == "openai_compatible"
        route_state = body["model_configurations"]["chat"]
        assert route_state["active_source"] == "custom"
        assert route_state["active_config_id"] == config["config_id"]
        assert route_state["configurations"][0]["active"] is True
    finally:
        restore_model_route(original, "chat")


def test_model_routes_can_be_configured_independently():
    original = client.get("/v1/settings").json()
    reset_model_configuration_tables()

    try:
        embedding_body, embedding_config = save_tested_model_config(
            route="embedding",
            display_name="Embedding live model",
            provider_kind="openai_compatible",
            base_url="https://vectors.example.com/v1",
            model_name="embed-large",
            api_key="sk-embedding-1111",
        )
        assert embedding_body["model_preset"] == original["model_preset"]
        assert embedding_body["model_profiles"]["chat"]["model_preset"] == original["model_preset"]
        assert embedding_body["model_profiles"]["embedding"]["model_preset"] == "custom"
        assert embedding_body["model_profiles"]["embedding"]["model_provider"] == "openai_compatible"
        assert embedding_body["model_profiles"]["embedding"]["custom_model"]["base_url"] == "https://vectors.example.com/v1"
        assert embedding_body["model_profiles"]["embedding"]["custom_model"]["model_name"] == "embed-large"
        assert embedding_body["model_profiles"]["embedding"]["custom_model"]["api_key_masked"] == "••••1111"
        assert embedding_body["model_configurations"]["embedding"]["active_config_id"] == embedding_config["config_id"]

        rerank_body, rerank_config = save_tested_model_config(
            route="rerank",
            display_name="Rerank live model",
            provider_kind="openai_compatible",
            base_url="https://rank.example.com/v1",
            model_name="rerank-v1",
            api_key="sk-rerank-2222",
        )
        assert rerank_body["model_profiles"]["embedding"]["custom_model"]["model_name"] == "embed-large"
        assert rerank_body["model_profiles"]["rerank"]["model_preset"] == "custom"
        assert rerank_body["model_profiles"]["rerank"]["custom_model"]["api_key_masked"] == "••••2222"
        assert rerank_body["model_configurations"]["rerank"]["active_config_id"] == rerank_config["config_id"]

        persisted_db = Path(STATE_DIR) / "nasus.db"
        assert b"sk-embedding-1111" not in persisted_db.read_bytes()
        assert b"sk-rerank-2222" not in persisted_db.read_bytes()
    finally:
        restore_model_route(original, "embedding")
        restore_model_route(original, "rerank")


def test_model_config_requires_successful_fresh_test_before_save():
    reset_model_configuration_tables()
    payload = {
        "model_route": "chat",
        "display_name": "Untested model",
        "custom_provider_kind": "openai_compatible",
        "custom_base_url": "https://api.example.com/v1",
        "custom_model_name": "untested-model",
        "custom_api_key": "sk-untested",
    }

    untested = client.post("/v1/settings/model-configs", json={**payload, "test_token": "missing-token"})
    assert untested.status_code == 400
    assert untested.json()["detail"]["error"]["code"] == "model_config_not_tested"

    async def fake_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
        return "READY"

    with patch.object(store.llm, "_call_custom", new=fake_call_custom):
        tested = client.post("/v1/settings/model-configs/test", json=payload)
    assert tested.status_code == 200
    token = tested.json()["test_token"]
    with SessionLocal() as session:
        grant = session.scalar(select(ModelConfigTestGrantRecord))
        assert grant is not None
        assert grant.token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert token not in grant.token_hash

    # A newly constructed adapter can consume the grant after a process restart.
    store.model_config_test_grant_repository = SQLAlchemyModelConfigTestGrantRepository()

    changed = client.post(
        "/v1/settings/model-configs",
        json={**payload, "custom_model_name": "changed-model", "test_token": token},
    )
    assert changed.status_code == 400
    assert changed.json()["detail"]["error"]["code"] == "model_config_not_tested"

    saved = client.post("/v1/settings/model-configs", json={**payload, "test_token": token})
    assert saved.status_code == 200
    assert saved.json()["model_configurations"]["chat"]["active_source"] == "custom"

    replayed = client.post("/v1/settings/model-configs", json={**payload, "test_token": token})
    assert replayed.status_code == 400
    assert replayed.json()["detail"]["error"]["code"] == "model_config_not_tested"


def test_expired_model_config_test_grant_cannot_be_used_to_save():
    reset_model_configuration_tables()
    payload = {
        "model_route": "chat",
        "display_name": "Expired grant model",
        "custom_provider_kind": "openai_compatible",
        "custom_base_url": "https://api.example.com/v1",
        "custom_model_name": "expired-grant-model",
        "custom_api_key": "sk-expired",
    }

    async def fake_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
        return "READY"

    with patch.object(store.llm, "_call_custom", new=fake_call_custom):
        tested = client.post("/v1/settings/model-configs/test", json=payload)
    assert tested.status_code == 200

    with SessionLocal() as session:
        session.execute(
            update(ModelConfigTestGrantRecord).values(
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
        session.commit()

    expired = client.post(
        "/v1/settings/model-configs",
        json={**payload, "test_token": tested.json()["test_token"]},
    )
    assert expired.status_code == 400
    assert expired.json()["detail"]["error"]["code"] == "model_config_not_tested"


def test_second_model_does_not_override_active_until_explicitly_selected():
    reset_model_configuration_tables()
    first_body, first_config = save_tested_model_config(
        display_name="First custom model",
        model_name="first-model",
        api_key="sk-first-0001",
        activate=False,
    )
    assert first_body["model_configurations"]["chat"]["active_config_id"] == first_config["config_id"]

    second_body, second_config = save_tested_model_config(
        display_name="Second custom model",
        model_name="second-model",
        api_key="sk-second-0002",
        activate=False,
    )
    assert second_body["model_configurations"]["chat"]["active_config_id"] == first_config["config_id"]
    assert second_body["custom_model"]["model_name"] == "first-model"

    activated = client.post(f"/v1/settings/model-configs/{second_config['config_id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["model_configurations"]["chat"]["active_config_id"] == second_config["config_id"]
    assert activated.json()["custom_model"]["model_name"] == "second-model"

    system_default = client.post("/v1/settings/model-configs/chat/use-system-default")
    assert system_default.status_code == 200
    assert system_default.json()["model_configurations"]["chat"]["active_source"] == "system_default"
    assert system_default.json()["model_preset"] == "system_default"


def test_saved_model_config_can_be_edited_after_successful_test():
    reset_model_configuration_tables()
    body, config = save_tested_model_config(
        display_name="Editable custom model",
        model_name="editable-model",
        api_key="sk-edit-0001",
        activate=False,
    )
    config_id = config["config_id"]
    assert body["model_configurations"]["chat"]["active_config_id"] == config_id

    update_payload = {
        "config_id": config_id,
        "model_route": "chat",
        "display_name": "Edited custom model",
        "custom_provider_kind": "openai_compatible",
        "custom_base_url": "https://api.example.com/v2",
        "custom_model_name": "edited-model",
        "custom_api_key": "",
    }

    untested = client.patch(
        f"/v1/settings/model-configs/{config_id}",
        json={**update_payload, "test_token": "missing-token"},
    )
    assert untested.status_code == 400
    assert untested.json()["detail"]["error"]["code"] == "model_config_not_tested"

    async def fake_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
        assert custom_model.model_name == "edited-model"
        assert custom_model.base_url == "https://api.example.com/v2"
        assert custom_api_key == "sk-edit-0001"
        return "READY"

    with patch.object(store.llm, "_call_custom", new=fake_call_custom):
        tested = client.post("/v1/settings/model-configs/test", json=update_payload)

    assert tested.status_code == 200
    token = tested.json()["test_token"]
    changed_after_test = client.patch(
        f"/v1/settings/model-configs/{config_id}",
        json={**update_payload, "custom_model_name": "changed-after-test", "test_token": token},
    )
    assert changed_after_test.status_code == 400
    assert changed_after_test.json()["detail"]["error"]["code"] == "model_config_not_tested"

    updated = client.patch(f"/v1/settings/model-configs/{config_id}", json={**update_payload, "test_token": token})
    assert updated.status_code == 200
    updated_body = updated.json()
    assert updated_body["model_configurations"]["chat"]["active_config_id"] == config_id
    assert updated_body["custom_model"]["model_name"] == "edited-model"
    edited_config = next(
        item for item in updated_body["model_configurations"]["chat"]["configurations"] if item["config_id"] == config_id
    )
    assert edited_config["display_name"] == "Edited custom model"
    assert edited_config["base_url"] == "https://api.example.com/v2"
    assert edited_config["api_key_masked"] == "••••0001"


def test_saved_model_display_name_can_be_edited_without_retesting_connection():
    reset_model_configuration_tables()
    _, config = save_tested_model_config(
        display_name="Original display name",
        model_name="display-name-model",
        api_key="sk-display-0001",
        activate=False,
    )
    config_id = config["config_id"]
    update_payload = {
        "config_id": config_id,
        "model_route": "chat",
        "display_name": "Renamed display name",
        "custom_provider_kind": "openai_compatible",
        "custom_base_url": "https://api.example.com/v1",
        "custom_model_name": "display-name-model",
        "custom_api_key": "",
        "test_token": "",
    }

    updated = client.patch(f"/v1/settings/model-configs/{config_id}", json=update_payload)

    assert updated.status_code == 200
    edited_config = next(
        item for item in updated.json()["model_configurations"]["chat"]["configurations"] if item["config_id"] == config_id
    )
    assert edited_config["display_name"] == "Renamed display name"
    assert edited_config["model_name"] == "display-name-model"
    assert edited_config["base_url"] == "https://api.example.com/v1"
    assert edited_config["api_key_masked"] == "••••0001"


def test_saved_model_connection_test_reports_unreadable_saved_key():
    reset_model_configuration_tables()
    _, config = save_tested_model_config(
        display_name="Broken saved key model",
        model_name="broken-key-model",
        api_key="sk-broken-0001",
        activate=False,
    )
    with SessionLocal() as session:
        session.execute(
            update(ModelProviderConfigRecord)
            .where(ModelProviderConfigRecord.config_id == config["config_id"])
            .values(api_key_encrypted="not-a-valid-encrypted-secret")
        )
        session.commit()

    response = client.post(
        "/v1/settings/model-configs/test",
        json={
            "config_id": config["config_id"],
            "model_route": "chat",
            "display_name": "Broken saved key model",
            "custom_provider_kind": "openai_compatible",
            "custom_base_url": "https://api.example.com/v1",
            "custom_model_name": "broken-key-model",
            "custom_api_key": "",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["runtime_mode"] == "fallback"
    assert "Re-enter the API key" in body["message"]


def test_model_config_is_persisted_and_api_key_is_encrypted_at_rest():
    original = client.get("/v1/settings").json()
    reset_model_configuration_tables()

    try:
        response, config = save_tested_model_config(
            display_name="Persisted custom model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="persisted-custom",
            api_key="sk-persisted-5678",
        )
        assert response["model_configurations"]["chat"]["active_config_id"] == config["config_id"]

        persisted_db = Path(STATE_DIR) / "nasus.db"
        assert persisted_db.exists()
        assert b"sk-persisted-5678" not in persisted_db.read_bytes()

        restored_store = InMemoryStore()
        restored = restored_store.get_settings()
        assert restored.model_preset == "custom"
        assert restored.model_provider == "openai_compatible"
        assert restored.custom_model.model_name == "persisted-custom"
        assert restored.custom_model.has_api_key is True
        assert restored.custom_model.api_key_masked == "••••5678"
        assert restored_store.model_configuration.get_custom_model_api_key("chat") == "sk-persisted-5678"
    finally:
        restore_model_route(original, "chat")


def test_settings_connection_uses_current_saved_configuration():
    original = client.get("/v1/settings").json()
    save_tested_model_config(
        display_name="Connectivity model",
        provider_kind="openai_compatible",
        base_url="https://api.example.com/v1",
        model_name="connectivity-model",
        api_key="sk-live-9999",
    )

    try:
        async def fake_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
            assert custom_model.model_name == "connectivity-model"
            assert custom_api_key == "sk-live-9999"
            assert "No prior conversation history" in history_snapshot
            return "READY"

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post("/v1/settings/test-connection")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["provider"] == "openai_compatible"
        assert body["runtime_mode"] == "live"
        assert body["fallback_provider"] == "mock"
        assert body["latency_ms"] is not None
        refreshed = client.get("/v1/settings").json()
        active_id = refreshed["model_configurations"]["chat"]["active_config_id"]
        active = next(
            item
            for item in refreshed["model_configurations"]["chat"]["configurations"]
            if item["config_id"] == active_id
        )
        assert active["last_test_result"]["ok"] is True
        assert refreshed["model_profiles"]["chat"]["runtime_mode"] == "live"
    finally:
        restore_model_route(original, "chat")


def test_failed_active_model_connection_is_persisted_and_disables_route():
    original = client.get("/v1/settings").json()
    save_tested_model_config(
        display_name="Expiring model",
        provider_kind="openai_compatible",
        base_url="https://api.example.com/v1",
        model_name="expiring-model",
        api_key="sk-expiring-9999",
    )

    try:
        async def failing_call_custom(**_kwargs):
            request = httpx.Request("POST", "https://api.example.com/chat/completions")
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

        with patch.object(store.llm, "_call_custom", new=failing_call_custom):
            response = client.post("/v1/settings/test-connection")

        assert response.status_code == 200
        assert response.json()["ok"] is False
        refreshed = client.get("/v1/settings").json()
        active_id = refreshed["model_configurations"]["chat"]["active_config_id"]
        active = next(
            item
            for item in refreshed["model_configurations"]["chat"]["configurations"]
            if item["config_id"] == active_id
        )
        assert active["last_test_result"]["ok"] is False
        assert active["runtime_mode"] == "fallback"
        assert refreshed["model_profiles"]["chat"]["runtime_mode"] == "fallback"
        assert "HTTP 403" in refreshed["model_profiles"]["chat"]["active_provider_status"]["reason"]
    finally:
        restore_model_route(original, "chat")


def test_settings_connection_redacts_provider_errors():
    payload = {
        "model_route": "chat",
        "display_name": "Failing redaction model",
        "custom_provider_kind": "openai_compatible",
        "custom_base_url": "https://api.example.com",
        "custom_model_name": "connectivity-model",
        "custom_api_key": "sk-redaction-should-not-appear",
    }

    async def failing_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
        request = httpx.Request(
            "POST",
            "https://api.example.com/chat/completions?key=sk-redaction-should-not-appear",
            headers={"Authorization": "Bearer sk-redaction-should-not-appear"},
        )
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError(
            "Client error for url https://api.example.com/chat/completions?key=sk-redaction-should-not-appear",
            request=request,
            response=response,
        )

    with patch.object(store.llm, "_call_custom", new=failing_call_custom):
        response = client.post("/v1/settings/model-configs/test", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["runtime_mode"] == "fallback"
    assert body["message"] == "Connection failed: provider returned HTTP 401"
    assert "sk-redaction-should-not-appear" not in body["message"]
    assert "key=" not in body["message"]
    assert "Authorization" not in body["message"]


def test_system_default_openai_compatible_route_uses_env_configuration():
    from apps.api.app.llm import LLMGateway

    gateway = LLMGateway()
    env_patch = {
        "NASUS_DEFAULT_PROVIDER": "openai_compatible",
        "NASUS_DEFAULT_BASE_URL": "https://gateway.example.com/v1",
        "NASUS_DEFAULT_API_KEY": "sk-system-default",
        "NASUS_DEFAULT_MODEL": "deepseek-compatible",
    }
    with patch.dict(os.environ, env_patch, clear=False):
        settings = gateway.build_settings(
            language="en",
            theme="dark",
            notification_mode="important",
            model_preset="system_default",
        )

    assert settings.model_provider == "openai_compatible"
    assert settings.model_name == "deepseek-compatible"
    assert settings.runtime_mode == "live"
    assert settings.active_provider_status.available is True
    assert settings.active_provider_status.configured_via == "system_default"


def test_system_default_openai_compatible_chat_uses_default_gateway():
    from apps.api.app.llm import LLMGateway

    gateway = LLMGateway()
    env_patch = {
        "NASUS_DEFAULT_PROVIDER": "openai_compatible",
        "NASUS_DEFAULT_BASE_URL": "https://gateway.example.com/v1",
        "NASUS_DEFAULT_API_KEY": "sk-system-default",
        "NASUS_DEFAULT_MODEL": "deepseek-compatible",
    }
    with patch.dict(os.environ, env_patch, clear=False):
        settings = gateway.build_settings(
            language="en",
            theme="dark",
            notification_mode="important",
            model_preset="system_default",
        )

        async def fake_call_openai_compatible(
            *,
            base_url,
            api_key,
            model_name,
            system_prompt,
            user_message,
            context_snapshot,
            history_snapshot,
        ):
            assert base_url == "https://gateway.example.com/v1"
            assert api_key == "sk-system-default"
            assert model_name == "deepseek-compatible"
            assert "memory" in history_snapshot
            assert "context" in context_snapshot
            return "READY"

        with patch.object(gateway, "_call_openai_compatible", new=fake_call_openai_compatible):
            reply = asyncio.run(
                gateway.generate_reply(
                    settings=settings,
                    system_prompt="system",
                    user_message="hello",
                    context_snapshot="context",
                    history_snapshot="memory",
                    fallback_text="fallback",
                )
            )

    assert reply.mode == "live"
    assert reply.provider == "openai_compatible"
    assert reply.model_name == "deepseek-compatible"
    assert reply.content == "READY"
    assert reply.model_calls == 1
    assert reply.input_tokens > 0
    assert reply.output_tokens > 0
    assert reply.usage_source == "estimated"


def test_settings_connection_help_endpoint_is_human_readable():
    response = client.get("/v1/settings/test-connection")
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "POST"
    assert "Use POST /v1/settings/test-connection" in body["message"]
    assert body["current_model_preset"] in {"system_default", "custom"}


def test_tool_catalog_exposes_system_image_tool_chain():
    response = client.get("/v1/tools/catalog")
    assert response.status_code == 200
    tool_ids = {tool["tool_id"] for tool in response.json()}
    assert {
        "project.create",
        "project.assets.connect",
        "project.status.get",
        "version.create",
        "version.inputs.import",
        "version.branch.bind",
        "version.participants.assign",
        "version.risk.initialize",
        "version.progress.get",
        "us.task.start",
        "quality.scope.generate",
        "quality.plan.generate",
        "quality.asset-pack.refresh",
        "run.start",
        "run.retry",
        "run.progress.get",
        "us.status.get",
        "release.advice.get",
        "resolution.merge",
        "progress.get",
        "risk.summary.get",
        "system-image.inspect",
        "conflicts.get",
    }.issubset(tool_ids)
    assert {
        "system_image.sources.register",
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    }.issubset(tool_ids)
    assert {
        "quality.scenario.generate",
        "quality.case.generate",
        "automation.generate",
        "quality.change-doc.generate",
        "failure.analyze",
        "healing.propose",
        "release.assess",
    }.issubset(tool_ids)
    assert {
        "approval.request",
        "approval.decide",
        "release.decision.submit",
        "baseline.promote",
    }.issubset(tool_ids)
    assert "baseline.initialize" not in tool_ids
    assert "version.import.us" not in tool_ids
    assert "merge.resolve" not in tool_ids
    assert "query.run.status" not in tool_ids


def test_agent_service_uses_workflow_runtime_port():
    assert store.agent_workflow_runtime.runtime_kind == "local"
    assert store.agent_service.runtime is store.agent_workflow_runtime
    assert store.agent_loop_runtime.graph_kind == "local"
    assert store.agent_loop_runtime.graph_runtime.steps_for_proposal is not None


def test_agent_workflow_runtime_factory_builds_default_temporal_gateway():
    from apps.api.app.agent_workflow_runtime import build_agent_workflow_runtime

    runtime = build_agent_workflow_runtime(
        store.agent_loop_runtime,
        runtime_kind="temporal",
        workflow_state=store.agent_application_ports.workflow_state,
    )
    assert runtime.runtime_kind == "temporal"
    assert runtime.gateway.__class__.__name__ == "TemporalClientWorkflowGateway"


def test_agent_workflow_runtime_factory_accepts_temporal_gateway():
    from apps.api.app.agent_goal_state_machine import AgentGoalRuntimeCheckpoint
    from apps.api.app.agent_workflow_runtime import build_agent_workflow_runtime

    class FakeTemporalGateway:
        async def start_goal(self, conversation_id, proposal):
            raise AssertionError("factory test should not execute gateway start")

        async def resume_goal(self, goal_id):
            raise AssertionError("factory test should not execute gateway resume")

        def checkpoint(self, goal_id):
            return AgentGoalRuntimeCheckpoint(
                goal_id=goal_id,
                workflow_id="temporal-test",
                status="pending",
                phase="pending",
                current_step_index=None,
                current_step_id=None,
                current_step_title=None,
                blocked_step_index=None,
                blocked_tool_invocation_id=None,
                resume_step_index=None,
                steps_completed=0,
            )

    runtime = build_agent_workflow_runtime(
        store.agent_loop_runtime,
        runtime_kind="temporal",
        temporal_gateway=FakeTemporalGateway(),
    )
    assert runtime.runtime_kind == "temporal"
    assert runtime.checkpoint("goal_test").workflow_id == "temporal-test"


def test_temporal_gateway_starts_and_resumes_agent_goal_workflow():
    from apps.api.app.application.platform.account_models import UserProfile
    from apps.api.app.application.platform.actor_context import actor_scope
    from apps.api.app.agent_runtime_config import TemporalGatewayConfig
    from apps.api.app.agent_runtime_models import AgentGoalProposal, ToolPlanStep
    from apps.api.app.agent_goal_state_machine import AgentGoalRuntimeCheckpoint
    from apps.api.app.temporal_agent_gateway import TemporalClientWorkflowGateway

    class FakeTemporalHandle:
        def __init__(self) -> None:
            self.signals = []
            self.query_count = 0
            self.goal_payload = {
                "id": "goal_temporal",
                "conversation_id": "conv_temporal",
                "project_id": "proj_temporal",
                "us_id": None,
                "title": "Temporal System Image",
                "status": "running",
                "summary": "Temporal worker accepted the system image goal.",
                "steps": [],
                "autonomy_level": "semi_auto",
                "max_steps": 50,
                "steps_completed": 0,
                "pause_reason": None,
                "workflow_id": None,
            }

        async def query(self, query, *args):
            assert query == "current_goal"
            self.query_count += 1
            if self.query_count == 1:
                return {}
            return dict(self.goal_payload)

        async def signal(self, signal, *args):
            self.signals.append((signal, args))
            self.goal_payload.update(
                {
                    "status": "completed",
                    "summary": "Temporal worker completed the system image goal.",
                    "steps_completed": 1,
                }
            )

    class FakeTemporalClient:
        def __init__(self) -> None:
            self.handle = FakeTemporalHandle()
            self.started = None
            self.requested_workflow_id = None

        async def start_workflow(self, workflow, *args, id, task_queue):
            self.started = {
                "workflow": workflow,
                "args": args,
                "id": id,
                "task_queue": task_queue,
            }
            return self.handle

        def get_workflow_handle(self, workflow_id):
            self.requested_workflow_id = workflow_id
            return self.handle

    fake_client = FakeTemporalClient()
    sunk_goals = []

    async def fake_factory(config):
        assert config.address == "temporal:7233"
        return fake_client

    gateway = TemporalClientWorkflowGateway(
        TemporalGatewayConfig(address="temporal:7233", task_queue="agent-task-queue"),
        client_factory=fake_factory,
        checkpoint_provider=lambda goal_id: AgentGoalRuntimeCheckpoint(
            goal_id=goal_id,
            workflow_id="nasus-agent-goal-existing",
            status="running",
            phase="acting",
            current_step_index=1,
            current_step_id="step_act",
            current_step_title="Execute",
            blocked_step_index=None,
            blocked_tool_invocation_id=None,
            resume_step_index=None,
            steps_completed=1,
        ),
        workflow_id_provider=lambda goal_id: "nasus-agent-goal-existing",
        goal_state_sink=lambda goal: sunk_goals.append(goal),
    )
    proposal = AgentGoalProposal(
        goal_template="system_image_build",
        title="Temporal System Image",
        summary="Build a system image through Temporal.",
        goal_description="Register and ingest sources.",
        planned_tools=[
            ToolPlanStep(
                tool_id="system_image.sources.register",
                input_payload={"project_id": "proj_temporal"},
                reason="Register sources.",
            )
        ],
    )

    temporal_actor = UserProfile(
        id="user_temporal",
        name="Temporal User",
        email="temporal@example.com",
        role="qa",
    )
    with actor_scope(temporal_actor, request_id="request-temporal"):
        goal = asyncio.run(gateway.start_goal("conv_temporal", proposal))
    assert goal.id == "goal_temporal"
    assert goal.workflow_id == fake_client.started["id"]
    assert [item.id for item in sunk_goals] == ["goal_temporal"]
    assert fake_client.started["workflow"] == "NasusAgentGoalWorkflow"
    assert fake_client.started["task_queue"] == "agent-task-queue"
    assert fake_client.handle.query_count >= 2
    start_payload = fake_client.started["args"][0]
    assert start_payload["conversation_id"] == "conv_temporal"
    assert start_payload["proposal"]["planned_tools"][0]["tool_id"] == "system_image.sources.register"
    assert start_payload["actor"]["user"]["id"] == "user_temporal"
    assert start_payload["actor"]["request_id"] == "request-temporal"

    with actor_scope(temporal_actor, request_id="request-resume"):
        resumed = asyncio.run(gateway.resume_goal("goal_temporal"))
    assert resumed.id == "goal_temporal"
    assert fake_client.requested_workflow_id == "nasus-agent-goal-existing"
    assert fake_client.handle.signals == [
        (
            "resume_goal",
            (
                {
                    "goal_id": "goal_temporal",
                    "actor": {
                        "user": temporal_actor.model_dump(mode="json"),
                        "request_id": "request-resume",
                    },
                },
            ),
        )
    ]
    assert [item.id for item in sunk_goals] == ["goal_temporal", "goal_temporal"]


def test_agent_goal_workflow_activity_service_uses_agent_loop_runtime_directly():
    from apps.api.app.agent_goal_workflow_worker import AgentGoalWorkflowActivityService
    from apps.api.app.application.agent.activities import AgentWorkflowActivityApplicationService
    from apps.api.app.application.platform.actor_context import current_user
    from apps.api.app.models import AgentGoal

    class FakeGoalProjector:
        def __init__(self) -> None:
            self.upserted_goal_ids = []

        def upsert_in_conversation(self, goal):
            self.upserted_goal_ids.append(goal.id)

    class FakeAgentLoopRuntime:
        def __init__(self) -> None:
            self.started = None
            self.resumed = None
            self.started_actor_id = None
            self.resumed_actor_id = None

        async def start_goal(self, conversation_id, proposal):
            self.started = (conversation_id, proposal)
            self.started_actor_id = current_user().id
            return AgentGoal(
                id="goal_worker",
                conversation_id=conversation_id,
                project_id="proj_worker",
                us_id=None,
                title=proposal.title,
                status="paused",
                summary=proposal.summary,
                steps=[],
                autonomy_level=proposal.suggested_autonomy_level,
                workflow_id="wf_local_worker",
            )

        async def resume_goal(self, goal_id):
            self.resumed = goal_id
            self.resumed_actor_id = current_user().id
            return AgentGoal(
                id=goal_id,
                conversation_id="conv_worker",
                project_id="proj_worker",
                us_id=None,
                title="Worker resumed goal",
                status="completed",
                summary="Worker completed the goal.",
                steps=[],
                workflow_id="wf_worker",
            )

    fake_loop_runtime = FakeAgentLoopRuntime()
    fake_goal_projector = FakeGoalProjector()
    activity_application = AgentWorkflowActivityApplicationService(
        loop_runtime=fake_loop_runtime,
        goal_projector=fake_goal_projector,
    )
    service = AgentGoalWorkflowActivityService(
        activity_application_provider=lambda: activity_application
    )
    payload = {
        "conversation_id": "conv_worker",
        "workflow_id": "temporal-wf-worker",
        "actor": {
            "user": {
                "id": "user_worker",
                "name": "Worker User",
                "email": "worker@example.com",
                "role": "qa",
            },
            "request_id": "request-worker-start",
        },
        "proposal": {
            "goal_template": "system_image_build",
            "title": "Worker System Image",
            "summary": "Build the system image in a worker activity.",
            "goal_description": "Register and ingest sources.",
            "suggested_autonomy_level": "semi_auto",
            "planned_tools": [
                {
                    "tool_id": "system_image.sources.register",
                    "input_payload": {"project_id": "proj_worker"},
                    "reason": "Register source groups.",
                }
            ],
        },
    }

    started = asyncio.run(service.start_agent_goal(payload))
    conversation_id, proposal = fake_loop_runtime.started
    assert conversation_id == "conv_worker"
    assert proposal.planned_tools[0].tool_id == "system_image.sources.register"
    assert proposal.planned_tools[0].input_payload == {"project_id": "proj_worker"}
    assert fake_loop_runtime.started_actor_id == "user_worker"
    assert started["workflow_id"] == "temporal-wf-worker"
    assert fake_goal_projector.upserted_goal_ids == ["goal_worker"]

    resumed = asyncio.run(
        service.resume_agent_goal(
            {
                "goal_id": "goal_worker",
                "actor": {
                    "user": {
                        "id": "user_worker",
                        "name": "Worker User",
                        "email": "worker@example.com",
                        "role": "qa",
                    },
                    "request_id": "request-worker-resume",
                },
            }
        )
    )
    assert resumed["status"] == "completed"
    assert fake_loop_runtime.resumed == "goal_worker"
    assert fake_loop_runtime.resumed_actor_id == "user_worker"


def test_agent_graph_runtime_factory_builds_default_langgraph_gateway():
    from apps.api.app.agent_graph_runtime import build_agent_graph_runtime

    runtime = build_agent_graph_runtime(
        store.agent_application_ports.graph_state,
        store.agent_loop_runtime.state_machine,
        store.agent_goal_plan_compiler,
        graph_kind="langgraph",
    )
    assert runtime.graph_kind == "langgraph"
    assert runtime.gateway.__class__.__name__ == "LangGraphAgentLoopGateway"


def test_agent_graph_runtime_factory_accepts_langgraph_gateway():
    from apps.api.app.agent_graph_runtime import build_agent_graph_runtime

    class FakeLangGraphGateway:
        async def start(self, goal_id, proposal):
            raise AssertionError("factory test should not execute graph start")

        async def resume(self, goal_id):
            raise AssertionError("factory test should not execute graph resume")

        def steps_for_proposal(self, proposal):
            return []

    runtime = build_agent_graph_runtime(
        store.agent_application_ports.graph_state,
        store.agent_loop_runtime.state_machine,
        store.agent_goal_plan_compiler,
        graph_kind="langgraph",
        langgraph_gateway=FakeLangGraphGateway(),
    )
    assert runtime.graph_kind == "langgraph"
    assert runtime.steps_for_proposal(object()) == []


def test_langgraph_runtime_executes_multi_node_graph_and_reuses_terminal_checkpoint():
    from apps.api.app.agent_graph_runtime import build_agent_graph_runtime
    from apps.api.app.agent_loop_runtime import AgentLoopRuntime
    from apps.api.app.agent_runtime_models import AgentGoalProposal, ToolPlanStep
    from apps.api.app.infrastructure.config.agent_runtime_config import LangGraphGatewayConfig
    from apps.api.app.infrastructure.workflow.langgraph_agent_gateway import LangGraphAgentLoopGateway

    project = client.post("/v1/projects", json={"name": "LangGraph Durable Runtime"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    proposal = AgentGoalProposal(
        goal_template="status_query",
        title="Inspect system image status",
        summary="Read the current system image status through the governed tool surface.",
        goal_description="Query current system image status and decide the next action.",
        planned_tools=[
            ToolPlanStep(
                tool_id="query.system_image.status",
                input_payload={"project_id": project["id"]},
                reason="Read the current durable project state.",
            )
        ],
        target_refs=[f"project:{project['id']}"],
    )
    gateway = LangGraphAgentLoopGateway(
        store.agent_application_ports.graph_state,
        store.agent_loop_runtime.state_machine,
        store.agent_goal_plan_compiler,
        config=LangGraphGatewayConfig(
            graph_name="test-agent-loop",
            checkpoint_backend="memory",
        ),
    )
    runtime = build_agent_graph_runtime(
        store.agent_application_ports.graph_state,
        store.agent_loop_runtime.state_machine,
        store.agent_goal_plan_compiler,
        graph_kind="langgraph",
        langgraph_gateway=gateway,
    )
    loop = AgentLoopRuntime(
        store.agent_application_ports.loop_state,
        runtime,
        store.agent_loop_runtime.state_machine,
    )

    goal = asyncio.run(loop.start_goal(conversation["id"], proposal))

    assert goal.status == "completed"
    assert [step.phase for step in goal.steps] == ["thinking", "acting", "observing", "deciding"]
    assert {step.status for step in goal.steps} == {"completed"}
    invocation_ids = [
        step.tool_invocation_id
        for step in goal.steps
        if step.phase == "acting" and step.tool_invocation_id
    ]
    assert len(invocation_ids) == 1
    checkpoint_config = {
        "configurable": {
            "thread_id": f"test-agent-loop:{goal.id}",
        }
    }
    checkpoint = asyncio.run(gateway._graph().aget_state(checkpoint_config))
    assert checkpoint.values["route"] == "end"

    asyncio.run(gateway.start(goal.id, proposal))
    replayed_invocation_ids = [
        item.id
        for item in store.list_tool_invocations(agent_goal_id=goal.id)
    ]
    assert replayed_invocation_ids == invocation_ids


def test_agent_swarm_runs_worker_assignments_concurrently():
    from apps.api.app.agent_runtime_models import AgentGoalProposal
    from apps.api.app.application.agent.swarm import (
        AgentSwarmCoordinator,
        AgentWorkerAnalysis,
    )
    from apps.api.app.application.system_image.system_image_models import RawAssetRecord

    project = client.post("/v1/projects", json={"name": "Concurrent Agent Swarm"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    goal = asyncio.run(
        store.agent_loop_runtime.start_goal(
            conversation["id"],
            AgentGoalProposal(
                goal_template="status_query",
                title="Prepare swarm parent",
                summary="Create a completed parent goal for a bounded worker swarm.",
                goal_description="Prepare a parent goal.",
            ),
        )
    )

    class ConcurrentProbeWorker:
        def __init__(self):
            self.active = 0
            self.max_active = 0

        async def analyze_system_image_source(self, *, project_id, source, assignment):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return AgentWorkerAnalysis(
                candidate_result_ref=f"candidate:{project_id}:{source.id}",
                confidence=0.91,
                summary=f"Analyzed {source.id}",
            )

    worker = ConcurrentProbeWorker()
    coordinator = AgentSwarmCoordinator(
        store.agent_application_ports.swarm_state,
        worker=worker,
    )
    sources = [
        RawAssetRecord(
            id=f"raw_concurrent_{source_type}",
            project_id=project["id"],
            source_type=source_type,
            source_uri=f"/tmp/{source_type}",
            ingestion_status="indexed",
            content_hash=f"hash-{source_type}",
            content_ref=f"object://{source_type}",
            evidence_refs=[f"evidence:{source_type}"],
            file_count=2,
            byte_count=200,
        )
        for source_type in ("code", "us_doc", "test_asset")
    ]

    swarm = asyncio.run(
        coordinator.run_system_image_materialization_swarm(
            parent_goal_id=goal.id,
            conversation_id=conversation["id"],
            project_id=project["id"],
            invocation_id="inv_concurrent_swarm",
            sources=sources,
        )
    )

    assert worker.max_active == 3
    assert swarm.status == "completed"
    assert {assignment.status for assignment in swarm.assignments} == {"completed"}
    assert {assignment.confidence for assignment in swarm.assignments} == {0.91}


def test_tool_invocation_runtime_is_canonical_store_entry_for_gated_tools():
    assert store.tool_invocation_runtime.tool_definition("system_image.baseline.initialize").confirmation_mode == "user_confirm"
    assert store.tool_invocation_runtime.tool_definition("approval.request").confirmation_mode == "user_confirm"
    assert store.tool_invocation_runtime.tool_definition("approval.decide").confirmation_mode == "user_confirm"
    assert store.tool_invocation_runtime.tool_definition("resolution.merge").confirmation_mode == "user_confirm"
    assert store.tool_invocation_runtime.tool_definition("release.decision.submit").confirmation_mode == "approval_required"
    assert store.tool_invocation_runtime.tool_definition("baseline.promote").confirmation_mode == "approval_required"
    assert store.tool_invocation_runtime.handlers.resolve("system_image.baseline.initialize") is not None
    assert store.tool_invocation_runtime.handlers.resolve("quality.scenario.generate") is not None
    assert store.tool_invocation_runtime.handlers.resolve("quality.case.generate") is not None
    assert store.tool_invocation_runtime.handlers.resolve("automation.generate") is not None
    assert store.tool_invocation_runtime.handlers.resolve("failure.analyze") is not None
    assert store.tool_invocation_runtime.handlers.resolve("healing.propose") is not None
    assert store.tool_invocation_runtime.handlers.resolve("release.assess") is not None
    assert store.tool_invocation_runtime.handlers.resolve("approval.request") is not None
    assert store.tool_invocation_runtime.handlers.resolve("approval.decide") is not None
    assert store.tool_invocation_runtime.handlers.resolve("release.decision.submit") is not None
    assert store.tool_invocation_runtime.handlers.resolve("baseline.promote") is not None
    assert store.tool_invocation_runtime.handlers.resolve("query.system_image.status") is not None

    project, conversation, _ = create_project_with_materialized_system_image("Runtime Gate Project")
    response = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.baseline.initialize",
            "input": {"project_id": project["id"]},
            "initiator_surface": "ui",
            "initiator_actor": "user",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "waiting_confirmation"
    assert store.get_tool_invocation(body["id"]).status == "waiting_confirmation"
    conversation_snapshot = client.get(f"/v1/conversations/{conversation['id']}").json()
    conversation_invocation = next(
        invocation for invocation in conversation_snapshot["tool_invocations"] if invocation["id"] == body["id"]
    )
    assert conversation_invocation["status"] == "waiting_confirmation"
    assert conversation_invocation["tool_id"] == "system_image.baseline.initialize"
    gated_audit = client.get(f"/v1/audit-events?tool_invocation_id={body['id']}").json()
    gated_actions = {event["action"] for event in gated_audit}
    assert {"tool.invocation.created", "tool.invocation.gated"}.issubset(gated_actions)
    assert all(event["tool_invocation_id"] == body["id"] for event in gated_audit)

    bypass_attempt = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.baseline.initialize",
            "input": {
                "project_id": project["id"],
                "confirmed_by_user": True,
                "confirmed_at": "2026-01-01T00:00:00Z",
            },
            "initiator_surface": "ui",
            "initiator_actor": "user",
        },
    )
    assert bypass_attempt.status_code == 200
    bypass_body = bypass_attempt.json()
    assert bypass_body["status"] == "waiting_confirmation"
    assert "confirmed_by_user" not in bypass_body["input_payload"]
    assert "confirmed_at" not in bypass_body["input_payload"]

    confirmed = client.post(f"/v1/tool-invocations/{body['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "completed"
    completed_audit = client.get(f"/v1/audit-events?tool_invocation_id={body['id']}").json()
    completed_actions = {event["action"] for event in completed_audit}
    assert {"tool.invocation.confirmed", "tool.invocation.executing", "tool.invocation.completed"}.issubset(
        completed_actions
    )
    assert any("baseline:" in ref for event in completed_audit for ref in event["object_refs"])
    conversation_audit = client.get(f"/v1/audit-events?conversation_id={conversation['id']}").json()
    assert any(event["tool_invocation_id"] == body["id"] for event in conversation_audit)


def test_p0_tool_catalog_entries_execute_through_runtime():
    project = client.post("/v1/projects", json={"name": "P0 Tool Runtime Project"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-p0-tools-")
    source_specs = [
        {"source_type": "code", "source_uri": str(code_dir)},
        {"source_type": "us_doc", "source_uri": str(us_dir)},
        {"source_type": "test_asset", "source_uri": str(tests_dir)},
    ]

    assets = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "project.assets.connect",
            "input": {"project_id": project["id"], "source_specs": source_specs},
        },
    )
    assert assets.status_code == 200
    assert assets.json()["status"] == "completed"
    assert assets.json()["result"]["next_recommended_tools"] == ["system_image.sources.ingest"]

    version = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "version.create",
            "input": {"project_id": project["id"], "name": "2026.P0"},
        },
    ).json()
    version_id = version["result"]["object_refs"][0].split(":", 1)[1]

    import_us = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "version.import.us",
            "input": {
                "project_id": project["id"],
                "version_id": version_id,
                "us_items": [{"id": "us_p0_checkout", "title": "Checkout P0 flow", "owner": "QA Lead"}],
            },
        },
    )
    assert import_us.status_code == 200
    import_body = import_us.json()
    assert import_body["tool_id"] == "version.inputs.import"
    assert import_body["status"] == "completed"
    assert "us:us_p0_checkout" in import_body["result"]["object_refs"]

    for tool_id in [
        "system_image.sources.ingest",
        "system_image.context.materialize",
    ]:
        prepared = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": {"project_id": project["id"], "version_id": version_id},
            },
        )
        assert prepared.status_code == 200, tool_id
        assert prepared.json()["status"] == "completed", tool_id

    for tool_id, payload in [
        ("version.branch.bind", {"branch_name": "release/p0"}),
        ("version.participants.assign", {"assignments": [{"us_id": "us_p0_checkout", "owner": "Alicia"}]}),
        ("version.risk.initialize", {}),
        ("us.task.start", {"us_id": "us_p0_checkout"}),
        ("quality.scope.generate", {"us_id": "us_p0_checkout"}),
        ("quality.asset-pack.refresh", {"us_id": "us_p0_checkout"}),
        ("quality.scenario.generate", {"us_id": "us_p0_checkout"}),
        ("quality.case.generate", {"us_id": "us_p0_checkout"}),
        ("automation.generate", {"us_id": "us_p0_checkout"}),
        ("run.start", {"us_id": "us_p0_checkout", "base_url": TEST_TARGET_BASE_URL}),
        ("release.advice.get", {"us_id": "us_p0_checkout"}),
    ]:
        invoked = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": {"project_id": project["id"], "version_id": version_id, **payload},
            },
        )
        assert invoked.status_code == 200, tool_id
        assert invoked.json()["status"] == "completed", tool_id

    for query_tool in [
        "project.status.get",
        "version.progress.get",
        "run.progress.get",
        "progress.get",
        "risk.summary.get",
        "system-image.inspect",
        "conflicts.get",
    ]:
        invoked = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": query_tool,
                "input": {"project_id": project["id"], "version_id": version_id, "us_id": "us_p0_checkout"},
            },
        )
        assert invoked.status_code == 200, query_tool
        assert invoked.json()["status"] == "completed", query_tool

    merge = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "merge.resolve",
            "input": {
                "project_id": project["id"],
                "version_id": version_id,
                "task_id": "us_p0_checkout",
                "target_ref": "quality_profile:us_p0_checkout",
                "base": {"risk_score": 60, "owner": "QA Lead"},
                "left": {"risk_score": 72, "owner": "QA Lead"},
                "right": {"risk_score": 85, "owner": "QA Lead"},
            },
        },
    )
    assert merge.status_code == 200
    merge_body = merge.json()
    assert merge_body["tool_id"] == "resolution.merge"
    assert merge_body["status"] == "waiting_confirmation"
    confirmed_merge = client.post(f"/v1/tool-invocations/{merge_body['id']}/confirm")
    assert confirmed_merge.status_code == 200
    assert confirmed_merge.json()["status"] == "completed"
    resolution_ref = next(
        ref
        for ref in confirmed_merge.json()["result"]["object_refs"]
        if ref.startswith("merged_resolution:")
    )
    resolution_id = resolution_ref.split(":", 1)[1]
    conflicts = client.get(
        f"/v1/projects/{project['id']}/conflicts",
        params={"task_id": "us_p0_checkout"},
    )
    assert conflicts.status_code == 200
    assert conflicts.json()[0]["id"] == resolution_id
    assert conflicts.json()[0]["status"] == "pending_merge"
    assert conflicts.json()[0]["conflict_entries"][0]["path"] == "/risk_score"

    resolve = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "resolution.merge",
            "input": {
                "project_id": project["id"],
                "resolution_id": resolution_id,
                "manual_resolutions": {"/risk_score": {"choice": "right"}},
            },
        },
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "waiting_confirmation"
    resolved = client.post(f"/v1/tool-invocations/{resolve.json()['id']}/confirm")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "completed"
    resolution = client.get(
        f"/v1/projects/{project['id']}/merged-resolutions/{resolution_id}"
    ).json()
    assert resolution["status"] == "ready_for_approval"
    assert resolution["merged_value"]["risk_score"] == 85
    assert resolution["conflict_entries"] == []
    assert client.get(f"/v1/tasks/us_p0_checkout/conflicts").json() == []

    approval_request = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "approval.request",
            "input": {
                "project_id": project["id"],
                "purpose": "merged_resolution",
                "target_ref": resolution_ref,
            },
        },
    ).json()
    approved_request = client.post(
        f"/v1/tool-invocations/{approval_request['id']}/confirm"
    ).json()
    approval_id = next(
        ref.split(":", 1)[1]
        for ref in approved_request["result"]["object_refs"]
        if ref.startswith("approval:")
    )
    approval_decision = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "approval.decide",
            "input": {
                "project_id": project["id"],
                "approval_id": approval_id,
                "decision": "approved",
            },
        },
    ).json()
    client.post(f"/v1/tool-invocations/{approval_decision['id']}/confirm")
    approved_resolution = client.get(
        f"/v1/projects/{project['id']}/merged-resolutions/{resolution_id}"
    ).json()
    assert approved_resolution["status"] == "approved"
    assert approved_resolution["approval_ref"] == f"approval:{approval_id}"


def test_approval_required_tool_requires_approved_project_approval():
    project, conversation, _ = create_project_with_materialized_system_image("Approval Gate Project")
    tool = store._tool_definition("system_image.baseline.initialize")
    original_confirmation_mode = tool.confirmation_mode
    approved = ApprovalDetail(
        id="approval_ready_for_gate",
        title="Approved baseline gate",
        status="approved",
        summary="Approved by governance reviewer.",
        policy_reason="Baseline promotion requires governance approval.",
        recommended_resolution="Allow the approved baseline initialization.",
        evidence=["policy:baseline_writeback_gate"],
    )

    try:
        tool.confirmation_mode = "approval_required"

        missing = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": "system_image.baseline.initialize",
                "input": {"project_id": project["id"]},
            },
        )
        assert missing.status_code == 200
        assert missing.json()["status"] == "waiting_approval"

        wrong_project = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": "system_image.baseline.initialize",
                "input": {"project_id": project["id"], "approval_id": "approval_442"},
            },
        )
        assert wrong_project.status_code == 200
        assert wrong_project.json()["status"] == "waiting_approval"
        assert "not attached" in wrong_project.json()["summary"]

        store.governance_workspace.save_approval(project["id"], approved)
        allowed = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": "system_image.baseline.initialize",
                "input": {"project_id": project["id"], "approval_id": approved.id},
            },
        )
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "completed"

        audit = client.get(f"/v1/audit-events?tool_invocation_id={allowed.json()['id']}").json()
        assert {"tool.invocation.created", "tool.invocation.executing", "tool.invocation.completed"}.issubset(
            {event["action"] for event in audit}
        )
    finally:
        tool.confirmation_mode = original_confirmation_mode
        store.quality_loop_repository.replace_approvals(project["id"], [])


def test_governance_tool_chain_approves_release_decision_and_promotes_baseline():
    project, conversation, workspace = create_project_with_materialized_system_image("Governance Release Project")
    us_id = workspace["us_items"][0]["id"]
    for tool_id, tool_input in [
        ("quality.scenario.generate", {}),
        ("quality.case.generate", {}),
        ("automation.generate", {}),
        ("run.start", {"base_url": TEST_TARGET_BASE_URL}),
        ("release.assess", {}),
    ]:
        response = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": {"project_id": project["id"], "us_id": us_id, **tool_input},
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    workspace_after_release = client.get(f"/v1/projects/{project['id']}").json()
    assert workspace_after_release["release_decision"] is None
    release = client.get(f"/v1/projects/{project['id']}/release-readiness").json()
    assert release["status"] == "Ready for release review"
    assert release["score"] >= 80
    assert release["score"] == sum(release["score_breakdown"].values())
    assert release["score_breakdown"]["execution"] > 0
    assert release["score_breakdown"]["quality_assets"] == 25
    assert release["evidence_summary"]["passed_runs"] >= 1
    assert release["evidence_summary"]["approved_asset_parts"] == 3

    approval_request = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "approval.request",
            "input": {
                "project_id": project["id"],
                "purpose": "release_decision",
                "target_ref": f"release_readiness:{release['version_id']}",
                "evidence_refs": [f"release_readiness:{release['version_id']}"],
            },
        },
    )
    assert approval_request.status_code == 200
    assert approval_request.json()["status"] == "waiting_confirmation"
    assert "requires user confirmation" in approval_request.json()["summary"]
    assert not any(
        item["title"] == "Release decision approval"
        for item in client.get(f"/v1/projects/{project['id']}/approvals").json()
    )
    confirmed_approval_request = client.post(f"/v1/tool-invocations/{approval_request.json()['id']}/confirm")
    assert confirmed_approval_request.status_code == 200
    assert confirmed_approval_request.json()["status"] == "completed"
    approval_ref = next(
        ref for ref in confirmed_approval_request.json()["result"]["object_refs"] if ref.startswith("approval:")
    )
    approval_id = approval_ref.split(":", 1)[1]
    approval_detail = client.get(f"/v1/projects/{project['id']}/approvals/{approval_id}").json()
    assert approval_detail["status"] == "waiting_approval"

    approval_decide = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "approval.decide",
            "input": {
                "project_id": project["id"],
                "approval_id": approval_id,
                "decision": "approved",
                "rationale": "Release evidence is complete and baseline promotion may proceed.",
            },
        },
    )
    assert approval_decide.status_code == 200
    assert approval_decide.json()["status"] == "waiting_confirmation"
    confirmed_decision = client.post(f"/v1/tool-invocations/{approval_decide.json()['id']}/confirm")
    assert confirmed_decision.status_code == 200
    assert confirmed_decision.json()["status"] == "completed"
    approval_detail = client.get(f"/v1/projects/{project['id']}/approvals/{approval_id}").json()
    assert approval_detail["status"] == "approved"

    submit_release = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "release.decision.submit",
            "input": {
                "project_id": project["id"],
                "version_id": release["version_id"],
                "us_id": us_id,
                "approval_id": approval_id,
            },
        },
    )
    assert submit_release.status_code == 200
    assert submit_release.json()["status"] == "completed"
    submitted_workspace = client.get(f"/v1/projects/{project['id']}").json()
    decision = submitted_workspace["release_decision"]
    assert decision["status"] == "ready"
    assert decision["approval_ref"] == f"approval:{approval_id}"
    assert any(ref.startswith("execution_evidence:") for ref in decision["evidence_refs"])

    promote = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "baseline.promote",
            "input": {
                "project_id": project["id"],
                "version_id": release["version_id"],
                "us_id": us_id,
                "approval_id": approval_id,
            },
        },
    )
    assert promote.status_code == 200
    assert promote.json()["status"] == "completed"
    promoted_image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert promoted_image["baselines"][0]["status"] == "promoted"
    assert promoted_image["build_state"]["status"] == "ready"
    audit = client.get(f"/v1/audit-events?tool_invocation_id={promote.json()['id']}").json()
    assert any("baseline:" in ref for event in audit for ref in event["object_refs"])


def test_build_message_creates_project():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    )
    conversation_id = conversation.json()["id"]

    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": "Help me create a new project called Loyalty Hub"},
    )
    assert response.status_code == 200
    wait_until(lambda: any(project["name"] == "Loyalty Hub" for project in client.get("/v1/projects").json()))
    projects = client.get("/v1/projects").json()
    assert any(project["name"] == "Loyalty Hub" for project in projects)


def test_build_message_without_project_name_requests_clarification():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    )
    conversation_id = conversation.json()["id"]
    before = len(client.get("/v1/projects").json())

    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": "Help me create a new project"},
    )
    assert response.status_code == 200
    wait_until(lambda: len(client.get(f"/v1/conversations/{conversation_id}").json()["messages"]) >= 2)
    refreshed = client.get(f"/v1/conversations/{conversation_id}").json()
    assistant_messages = [message for message in refreshed["messages"] if message["role"] == "assistant"]
    assert any("project name" in block["text"].lower() for message in assistant_messages for block in message["blocks"])
    after = len(client.get("/v1/projects").json())
    assert after == before


def test_build_clarification_follow_up_can_continue_project_creation():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    )
    conversation_id = conversation.json()["id"]

    first = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": "Help me create a new project"},
    )
    assert first.status_code == 200
    wait_until(lambda: len(client.get(f"/v1/conversations/{conversation_id}").json()["messages"]) >= 2)

    second = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": "Loyalty Follow Up"},
    )
    assert second.status_code == 200
    wait_until(lambda: any(project["name"] == "Loyalty Follow Up" for project in client.get("/v1/projects").json()))
    projects = client.get("/v1/projects").json()
    assert any(project["name"] == "Loyalty Follow Up" for project in projects)


def test_build_message_creates_project_from_chinese_name():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    )
    conversation_id = conversation.json()["id"]

    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": "帮我创建一个新项目，名字叫 Loyalty Hub CN"},
    )
    assert response.status_code == 200
    wait_until(lambda: any(project["name"] == "Loyalty Hub CN" for project in client.get("/v1/projects").json()))
    projects = client.get("/v1/projects").json()
    assert any(project["name"] == "Loyalty Hub CN" for project in projects)


def test_tool_invocation_creates_project():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    ).json()

    response = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "project.create",
            "input": {"name": "Agent Ops Hub"},
        },
    )
    assert response.status_code == 200
    invocation_id = response.json()["id"]
    wait_until(lambda: client.get(f"/v1/tool-invocations/{invocation_id}").json()["status"] == "completed")
    projects = client.get("/v1/projects").json()
    assert any(project["name"] == "Agent Ops Hub" for project in projects)


def test_conversation_snapshot_includes_tool_invocations():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build-tool-snapshot", "title": "Build Tool Snapshot"},
    ).json()

    response = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "project.create",
            "input": {"name": "Tool Snapshot Project"},
        },
    )

    assert response.status_code == 200
    invocation = response.json()
    snapshot = client.get(f"/v1/conversations/{conversation['id']}").json()
    matching = [item for item in snapshot["tool_invocations"] if item["id"] == invocation["id"]]
    assert matching
    assert matching[0]["tool_id"] == "project.create"
    assert matching[0]["status"] == "completed"

    reloaded = InMemoryStore()
    reloaded_snapshot = reloaded.get_conversation(conversation["id"])
    assert any(item.id == invocation["id"] for item in reloaded_snapshot.tool_invocations)


def test_tool_invocation_idempotency_key_reuses_existing_invocation():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    ).json()
    payload = {
        "conversation_id": conversation["id"],
        "tool_id": "project.create",
        "input": {"name": "Idempotent Project"},
        "idempotency_key": "project-create-idempotent-project",
    }

    first = client.post("/v1/tool-invocations", json=payload)
    second = client.post("/v1/tool-invocations", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["input_payload"]["idempotency_key"] == payload["idempotency_key"]

    projects = [project for project in client.get("/v1/projects").json() if project["name"] == "Idempotent Project"]
    assert len(projects) == 1

    invocations = [
        invocation
        for invocation in client.get(
            "/v1/tool-invocations",
            params={"conversation_id": conversation["id"], "tool_id": "project.create"},
        ).json()
        if invocation["input_payload"].get("idempotency_key") == payload["idempotency_key"]
    ]
    assert len(invocations) == 1

    audit = client.get(f"/v1/audit-events?tool_invocation_id={first.json()['id']}").json()
    assert sum(1 for event in audit if event["action"] == "tool.invocation.created") == 1


def test_tool_invocation_idempotency_key_rejects_a_different_payload():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    ).json()
    base_payload = {
        "conversation_id": conversation["id"],
        "tool_id": "project.create",
        "input": {"name": "Idempotency Owner"},
        "idempotency_key": "project-create-conflicting-payload",
    }

    first = client.post("/v1/tool-invocations", json=base_payload)
    conflicting = client.post(
        "/v1/tool-invocations",
        json={
            **base_payload,
            "input": {"name": "Different Project"},
        },
    )

    assert first.status_code == 200
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "tool_idempotency_conflict"
    assert not any(
        project["name"] == "Different Project"
        for project in client.get("/v1/projects").json()
    )


def test_project_api_creation_is_backed_by_tool_invocation_and_audit():
    project = client.post("/v1/projects", json={"name": "API Tool Project"}).json()

    invocations = client.get(
        "/v1/tool-invocations",
        params={"tool_id": "project.create", "status": "completed"},
    ).json()
    matching = [
        invocation
        for invocation in invocations
        if f"project:{project['id']}" in (invocation.get("result") or {}).get("object_refs", [])
    ]
    assert matching
    audit = client.get(f"/v1/audit-events?tool_invocation_id={matching[-1]['id']}").json()
    assert {"tool.invocation.created", "tool.invocation.completed"}.issubset({event["action"] for event in audit})


def test_system_image_exposes_long_term_baseline_shape():
    response = client.get("/v1/projects/proj_payment/system-image")
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["system_image_status"] == "ready"
    assert {source["source_type"] for source in body["sources"]} == {"code", "us_doc", "test_asset"}
    assert body["baselines"][0]["kind"] == "official"
    assert body["baselines"][0]["fork_strategy"] == "copy_on_write"
    assert len(body["relationships"]) >= 3
    assert {metric["metric_group"] for metric in body["metric_snapshots"]} == {
        "code_quality",
        "us_completion_quality",
        "test_quality",
        "release_readiness",
    }


def test_created_project_requires_real_sources_before_baseline_initialize():
    project = client.post("/v1/projects", json={"name": "System Image Long Term"}).json()

    draft = client.get(f"/v1/projects/{project['id']}/system-image")
    assert draft.status_code == 200
    draft_body = draft.json()
    assert draft_body["project"]["system_image_status"] == "draft"
    assert draft_body["build_state"]["status"] == "source_required"
    assert draft_body["build_state"]["missing_source_types"] == ["code"]
    assert {source["source_type"] for source in draft_body["sources"]} == {"code", "us_doc", "test_asset"}
    assert all(source["ingestion_status"] == "pending" for source in draft_body["sources"])
    assert draft_body["baselines"][0]["status"] == "draft"

    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    invoked = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.baseline.initialize",
            "input": {"project_id": project["id"]},
        },
    )
    assert invoked.status_code == 200
    invocation_id = invoked.json()["id"]
    assert invoked.json()["status"] == "waiting_confirmation"
    confirmed = client.post(f"/v1/tool-invocations/{invocation_id}/confirm")
    assert confirmed.status_code == 200
    wait_until(lambda: client.get(f"/v1/tool-invocations/{invocation_id}").json()["status"] == "failed")
    failed_invocation = client.get(f"/v1/tool-invocations/{invocation_id}").json()
    assert failed_invocation["result"]["requires_followup"] is True
    assert failed_invocation["result"]["followup_reason"] == "missing_source_binding"

    blocked = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert blocked["project"]["system_image_status"] == "draft"
    assert blocked["build_state"]["status"] == "source_required"
    assert blocked["build_state"]["missing_source_types"] == ["code"]
    assert all(source["ingestion_status"] == "pending" for source in blocked["sources"])
    assert blocked["baselines"][0]["status"] == "draft"
    assert blocked["objects"] == []
    assert blocked["metric_snapshots"] == []


def test_legacy_baseline_initialize_alias_is_normalized_to_canonical_tool():
    project = client.post("/v1/projects", json={"name": "Legacy Baseline Alias"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    invoked = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "baseline.initialize",
            "input": {"project_id": project["id"]},
        },
    )

    assert invoked.status_code == 200
    body = invoked.json()
    assert body["tool_id"] == "system_image.baseline.initialize"
    assert body["input_payload"]["requested_tool_id"] == "baseline.initialize"
    assert body["status"] == "waiting_confirmation"


def test_system_image_tools_can_register_and_ingest_real_source_files():
    project = client.post("/v1/projects", json={"name": "Real Source Ingestion"}).json()
    source_root = Path(tempfile.mkdtemp(prefix="nasus-source-ingestion-"))
    code_dir = source_root / "code"
    us_dir = source_root / "us"
    tests_dir = source_root / "tests"
    code_dir.mkdir()
    us_dir.mkdir()
    tests_dir.mkdir()
    (code_dir / "checkout.py").write_text("def checkout(cart):\n    return cart.total\n", encoding="utf-8")
    (us_dir / "US-101.md").write_text("# US-101\nAs a buyer, I can checkout with saved cards.\n", encoding="utf-8")
    (tests_dir / "test_checkout.py").write_text("def test_checkout():\n    assert True\n", encoding="utf-8")

    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    source_specs = [
        {"source_type": "code", "source_uri": str(code_dir), "label": "Code repository"},
        {"source_type": "us_doc", "source_uri": str(us_dir), "label": "Historical US documents"},
        {"source_type": "test_asset", "source_uri": str(tests_dir), "label": "Historical test assets"},
    ]

    registered = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {"project_id": project["id"], "source_specs": source_specs},
        },
    )
    assert registered.status_code == 200
    assert registered.json()["status"] == "completed"
    registered_image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert registered_image["build_state"]["status"] == "sources_registered"
    assert registered_image["build_state"]["next_recommended_tools"] == ["system_image.sources.ingest"]
    registered_sources = {source["source_type"]: source for source in registered_image["sources"]}
    assert registered_sources["code"]["source_label"] == "Code repository"
    assert registered_sources["code"]["registered_by_actor"] == "user"
    assert registered_sources["code"]["registered_from_invocation_id"] == registered.json()["id"]
    assert registered_sources["code"]["permission_status"] == "not_checked"

    ingested = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.ingest",
            "input": {"project_id": project["id"]},
        },
    )
    assert ingested.status_code == 200
    assert ingested.json()["status"] == "completed"

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["build_state"]["status"] == "indexed"
    assert image["build_state"]["next_recommended_tools"] == ["system_image.context.materialize"]
    sources = {source["source_type"]: source for source in image["sources"]}
    assert sources["code"]["source_uri"] == str(code_dir)
    assert sources["us_doc"]["source_uri"] == str(us_dir)
    assert sources["test_asset"]["source_uri"] == str(tests_dir)
    assert all(source["ingestion_status"] == "indexed" for source in sources.values())
    assert all(source["permission_status"] == "allowed" for source in sources.values())
    assert all(source["failure_reason"] is None for source in sources.values())
    assert all(source["file_count"] == 1 for source in sources.values())
    assert all(source["byte_count"] > 0 for source in sources.values())
    assert all(source["ingest_started_at"] for source in sources.values())
    assert all(source["permission_checked_at"] for source in sources.values())
    assert all(source["content_hash"].startswith("sha256:") for source in sources.values())
    assert any("file:checkout.py" in ref for ref in sources["code"]["evidence_refs"])
    assert any("file:US-101.md" in ref for ref in sources["us_doc"]["evidence_refs"])
    assert any("file:test_checkout.py" in ref for ref in sources["test_asset"]["evidence_refs"])
    assert len(image["chunks"]) >= 3
    chunk_paths = {chunk["section_path"] for chunk in image["chunks"]}
    assert {"checkout.py", "US-101.md", "test_checkout.py"}.issubset(chunk_paths)
    assert all(chunk["content_ref"].startswith(("local-object://", "s3://")) for chunk in image["chunks"])
    assert all(chunk["content_hash"].startswith("sha256:") for chunk in image["chunks"])
    assert all(chunk["token_estimate"] > 0 for chunk in image["chunks"])

    materialized = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.context.materialize",
            "input": {"project_id": project["id"]},
        },
    )
    assert materialized.status_code == 200
    assert materialized.json()["status"] == "completed"

    materialized_image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert materialized_image["build_state"]["status"] == "materialized"
    assert materialized_image["build_state"]["next_recommended_tools"] == ["system_image.baseline.initialize"]
    object_names = {item["name"] for item in materialized_image["objects"]}
    object_types = {item["type"] for item in materialized_image["objects"]}
    relationship_types = {item["relationship_type"] for item in materialized_image["relationships"]}
    materialized_code_source = next(
        source
        for source in materialized_image["sources"]
        if source["source_type"] == "code"
    )
    metrics_by_group = {item["metric_group"]: item["metrics"] for item in materialized_image["metric_snapshots"]}
    assert any("checkout" in name for name in object_names)
    assert any("US-101" in name for name in object_names)
    assert any("test_checkout" in name for name in object_names)
    assert {"CodeFunction", "USWorkItem", "TestCase"}.issubset(object_types)
    assert {"implements", "impacts", "covers", "validates", "belongs_to"}.issubset(
        relationship_types
    )
    assert any(
        ref.startswith("parser:tree-sitter:")
        for ref in materialized_code_source["evidence_refs"]
    )
    assert any(
        ref.startswith("code-intelligence:tree-sitter:")
        for ref in materialized_code_source["evidence_refs"]
    )
    assert metrics_by_group["code_quality"]["code_symbols"] >= 1
    assert metrics_by_group["code_quality"]["implemented_requirement_count"] >= 1
    assert metrics_by_group["code_quality"]["test_covered_code_count"] >= 1
    assert metrics_by_group["us_completion_quality"]["requirements_count"] >= 1
    assert metrics_by_group["us_completion_quality"]["traceability_coverage"] > 0
    assert metrics_by_group["us_completion_quality"]["validated_requirement_count"] >= 1
    assert metrics_by_group["test_quality"]["test_count"] >= 1
    assert metrics_by_group["test_quality"]["cross_source_link_count"] >= 3
    assert materialized_image["embedding_records"]
    assert len(materialized_image["retrieval_runs"]) == len(materialized_image["task_contexts"]) >= 1
    assert len(materialized_image["rerank_records"]) == len(materialized_image["retrieval_runs"])
    assert len(materialized_image["quality_profiles"]) == len(materialized_image["task_contexts"])
    source_embedding = next(item for item in materialized_image["embedding_records"] if item["source_ref"] == sources["code"]["id"])
    object_embedding = next(item for item in materialized_image["embedding_records"] if item["object_ref"])
    assert source_embedding["embedding_model"]
    assert source_embedding["provider"] in {"mock", "openai", "openai_compatible", "gemini", "anthropic"}
    assert source_embedding["vector_ref"].startswith(("local-hash-vector://", "pgvector://"))
    assert source_embedding["dimensions"] == 32
    assert source_embedding["status"] in {"ready", "fallback"}
    assert object_embedding["content_hash"].startswith("sha256:")
    chunk_ids = {chunk["id"] for chunk in materialized_image["chunks"]}
    chunk_embedding = next(item for item in materialized_image["embedding_records"] if item["chunk_ref"])
    assert chunk_embedding["chunk_ref"] in chunk_ids
    assert all(chunk["embedding_record_id"] for chunk in materialized_image["chunks"])
    task_context = materialized_image["task_contexts"][0]
    quality_profile = materialized_image["quality_profiles"][0]
    retrieval_run = materialized_image["retrieval_runs"][0]
    rerank_record = materialized_image["rerank_records"][0]
    assert task_context["readiness"] == "ready"
    assert task_context["retrieval_run_id"] == retrieval_run["id"]
    assert task_context["source_refs"]
    assert task_context["object_refs"]
    assert task_context["relationship_refs"]
    assert task_context["metric_refs"]
    assert task_context["context_hash"]
    assert any(ref.startswith("raw_asset_chunk:") for ref in task_context["evidence_refs"])
    assert any(ref.startswith(("local-object://", "s3://")) for ref in task_context["evidence_refs"])
    assert quality_profile["task_context_id"] == task_context["id"]
    assert 0 <= quality_profile["risk_score"] <= 100
    assert 0 <= quality_profile["coverage_score"] <= 100
    assert 0 <= quality_profile["release_score"] <= 100
    assert quality_profile["regression_scope_refs"]
    assert rerank_record["retrieval_run_id"] == retrieval_run["id"]
    assert rerank_record["status"] in {"completed", "fallback"}
    assert any(ref.startswith("raw_asset_chunk:") for ref in retrieval_run["result_refs"])
    assert retrieval_run["candidate_count"] == len(retrieval_run["result_refs"])
    assert retrieval_run["embedding_record_ids"]
    assert set(retrieval_run["embedding_record_ids"]).issubset({item["id"] for item in materialized_image["embedding_records"]})

    workspace = client.get(f"/v1/projects/{project['id']}").json()
    us_id = workspace["us_items"][0]["id"]
    workspace_task_context = next(
        item for item in materialized_image["task_contexts"] if item["us_id"] == us_id
    )
    workspace_quality_profile = next(
        item for item in materialized_image["quality_profiles"] if item["us_id"] == us_id
    )
    assert workspace["task_context"]["id"] == workspace_task_context["id"]
    assert workspace["quality_profile"]["id"] == workspace_quality_profile["id"]
    us_workspace = client.get(f"/v1/projects/{project['id']}/workspaces/{us_id}").json()
    assert us_workspace["task_context"]["id"] == workspace_task_context["id"]
    assert us_workspace["quality_profile"]["id"] == workspace_quality_profile["id"]

    baseline = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.baseline.initialize",
            "input": {"project_id": project["id"]},
        },
    )
    assert baseline.status_code == 200
    assert baseline.json()["status"] == "waiting_confirmation"
    confirmed = client.post(f"/v1/tool-invocations/{baseline.json()['id']}/confirm")
    assert confirmed.status_code == 200
    wait_until(lambda: client.get(f"/v1/tool-invocations/{baseline.json()['id']}").json()["status"] == "completed")

    ready_image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert ready_image["project"]["system_image_status"] == "ready"
    assert ready_image["build_state"]["status"] == "ready"
    assert len(ready_image["relationships"]) == len(materialized_image["relationships"])
    assert len(ready_image["metric_snapshots"]) == len(materialized_image["metric_snapshots"])
    assert len(ready_image["chunks"]) == len(materialized_image["chunks"])
    assert len(ready_image["embedding_records"]) == len(materialized_image["embedding_records"])
    assert len(ready_image["task_contexts"]) == len(materialized_image["task_contexts"])
    assert len(ready_image["quality_profiles"]) == len(materialized_image["quality_profiles"])
    assert any("checkout" in item["name"] for item in ready_image["objects"])

    restored_store = InMemoryStore()
    restored_image = restored_store.get_system_image(project["id"])
    assert restored_image.task_contexts
    assert restored_image.quality_profiles
    assert restored_image.chunks
    assert restored_image.embedding_records
    assert any(item.chunk_ref for item in restored_image.embedding_records)
    assert restored_image.retrieval_runs[0].embedding_record_ids
    assert restored_image.task_contexts[0].retrieval_run_id == restored_image.retrieval_runs[0].id


def test_uploaded_document_and_test_sources_are_ingested_through_tool_invocations():
    project = client.post("/v1/projects", json={"name": "Managed Source Upload"}).json()
    source_root = Path(tempfile.mkdtemp(prefix="nasus-upload-code-"))
    code_dir = source_root / "code"
    code_dir.mkdir()
    (code_dir / "checkout.py").write_text(
        "def checkout_with_saved_card(card_id):\n    return card_id\n",
        encoding="utf-8",
    )

    us_upload = client.post(
        f"/v1/projects/{project['id']}/source-files",
        data={"source_type": "us_doc"},
        files=[
            (
                "files",
                ("US-901.md", b"# US-901\nCheckout with a saved card", "text/markdown"),
            )
        ],
    )
    assert us_upload.status_code == 200
    assert us_upload.json()["source_uri"].startswith(("local-object://", "s3://"))
    assert "connector:browser-upload" in us_upload.json()["evidence_refs"]

    test_upload = client.post(
        f"/v1/projects/{project['id']}/source-files",
        data={"source_type": "test_asset"},
        files=[
            (
                "files",
                ("test_checkout.py", b"def test_saved_card_checkout():\n    assert True\n", "text/x-python"),
            )
        ],
    )
    assert test_upload.status_code == 200

    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    source_specs = [
        {"source_type": "code", "source_uri": str(code_dir), "label": "Code repository"},
        {
            "source_type": "us_doc",
            "source_uri": us_upload.json()["source_uri"],
            "label": "Uploaded US documents",
        },
        {
            "source_type": "test_asset",
            "source_uri": test_upload.json()["source_uri"],
            "label": "Uploaded test assets",
        },
    ]
    registered = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {"project_id": project["id"], "source_specs": source_specs},
        },
    )
    assert registered.status_code == 200
    assert registered.json()["status"] == "completed"

    ingested = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.ingest",
            "input": {"project_id": project["id"]},
        },
    )
    assert ingested.status_code == 200
    assert ingested.json()["status"] == "completed"

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    sources = {source["source_type"]: source for source in image["sources"]}
    assert sources["us_doc"]["source_uri"] == us_upload.json()["source_uri"]
    assert sources["test_asset"]["source_uri"] == test_upload.json()["source_uri"]
    assert "connector:object-storage-bundle" in sources["us_doc"]["evidence_refs"]
    assert "connector:object-storage-bundle" in sources["test_asset"]["evidence_refs"]
    assert {chunk["section_path"] for chunk in image["chunks"]}.issuperset(
        {"US-901.md", "test_checkout.py"}
    )


def test_source_upload_rejects_unknown_projects_and_unsafe_source_types():
    missing = client.post(
        "/v1/projects/missing/source-files",
        data={"source_type": "us_doc"},
        files=[("files", ("US.md", b"story", "text/markdown"))],
    )
    assert missing.status_code == 404

    project = client.post("/v1/projects", json={"name": "Invalid Source Upload"}).json()
    invalid_type = client.post(
        f"/v1/projects/{project['id']}/source-files",
        data={"source_type": "code"},
        files=[("files", ("code.py", b"print('x')", "text/x-python"))],
    )
    assert invalid_type.status_code == 400


def test_code_only_source_can_initialize_official_system_image_baseline():
    project = client.post("/v1/projects", json={"name": "Code Only Baseline"}).json()
    source_root = Path(tempfile.mkdtemp(prefix="nasus-code-only-"))
    (source_root / "payment_service.py").write_text(
        "class PaymentService:\n"
        "    def authorize_checkout(self, amount):\n"
        "        return amount > 0\n",
        encoding="utf-8",
    )
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    def invoke(tool_id: str, input_payload: dict) -> dict:
        response = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": input_payload,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        return response.json()

    invoke(
        "system_image.sources.register",
        {
            "project_id": project["id"],
            "source_specs": [
                {
                    "source_type": "code",
                    "source_uri": str(source_root),
                    "label": "Required code repository",
                }
            ],
        },
    )
    invoke("system_image.sources.ingest", {"project_id": project["id"]})

    indexed_image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    indexed_sources = {source["source_type"]: source for source in indexed_image["sources"]}
    assert indexed_image["build_state"]["status"] == "indexed"
    assert indexed_image["build_state"]["missing_source_types"] == []
    assert indexed_sources["code"]["ingestion_status"] == "indexed"
    assert indexed_sources["us_doc"]["ingestion_status"] == "pending"
    assert indexed_sources["test_asset"]["ingestion_status"] == "pending"

    invoke("system_image.context.materialize", {"project_id": project["id"]})
    materialized = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert materialized["build_state"]["status"] == "materialized"
    assert any(item["type"] in {"CodeClass", "CodeFunction"} for item in materialized["objects"])
    assert {item["metric_group"] for item in materialized["metric_snapshots"]} == {
        "code_quality",
        "us_completion_quality",
        "test_quality",
    }

    baseline = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.baseline.initialize",
            "input": {"project_id": project["id"]},
        },
    )
    assert baseline.status_code == 200
    assert baseline.json()["status"] == "waiting_confirmation"
    assert client.post(f"/v1/tool-invocations/{baseline.json()['id']}/confirm").status_code == 200
    wait_until(
        lambda: client.get(f"/v1/tool-invocations/{baseline.json()['id']}").json()["status"]
        == "completed"
    )

    ready = client.get(f"/v1/projects/{project['id']}/system-image").json()
    ready_sources = {source["source_type"]: source for source in ready["sources"]}
    assert ready["project"]["system_image_status"] == "ready"
    assert ready["build_state"]["status"] == "ready"
    assert ready["baselines"][0]["status"] == "ready"
    assert ready_sources["us_doc"]["ingestion_status"] == "pending"
    assert ready_sources["test_asset"]["ingestion_status"] == "pending"
    assert ready_sources["us_doc"]["evidence_refs"] == []
    assert ready_sources["test_asset"]["evidence_refs"] == []


def test_optional_source_failure_is_reported_without_blocking_baseline():
    project = client.post("/v1/projects", json={"name": "Optional Source Gap"}).json()
    code_root = Path(tempfile.mkdtemp(prefix="nasus-required-code-"))
    (code_root / "orders.py").write_text(
        "def submit_order(order):\n    return order.id\n",
        encoding="utf-8",
    )
    missing_us_root = code_root / "missing-us-docs"
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    def invoke(tool_id: str, input_payload: dict) -> dict:
        response = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": input_payload,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        return response.json()

    invoke(
        "system_image.sources.register",
        {
            "project_id": project["id"],
            "source_specs": [
                {"source_type": "code", "source_uri": str(code_root), "label": "Code"},
                {
                    "source_type": "us_doc",
                    "source_uri": str(missing_us_root),
                    "label": "Unavailable optional requirements",
                },
            ],
        },
    )
    invoke("system_image.sources.ingest", {"project_id": project["id"]})
    indexed = client.get(f"/v1/projects/{project['id']}/system-image").json()
    indexed_sources = {source["source_type"]: source for source in indexed["sources"]}
    assert indexed["build_state"]["status"] == "indexed"
    assert indexed["build_state"]["failed_source_ids"] == [indexed_sources["us_doc"]["id"]]
    assert indexed_sources["code"]["ingestion_status"] == "indexed"
    assert indexed_sources["us_doc"]["ingestion_status"] == "failed"

    invoke("system_image.context.materialize", {"project_id": project["id"]})
    materialized = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert materialized["build_state"]["status"] == "materialized"
    assert materialized["build_state"]["failed_source_ids"] == [indexed_sources["us_doc"]["id"]]

    baseline = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.baseline.initialize",
            "input": {"project_id": project["id"]},
        },
    )
    assert baseline.status_code == 200
    assert baseline.json()["status"] == "waiting_confirmation"
    assert client.post(f"/v1/tool-invocations/{baseline.json()['id']}/confirm").status_code == 200
    wait_until(
        lambda: client.get(f"/v1/tool-invocations/{baseline.json()['id']}").json()["status"]
        == "completed"
    )

    ready = client.get(f"/v1/projects/{project['id']}/system-image").json()
    ready_sources = {source["source_type"]: source for source in ready["sources"]}
    assert ready["build_state"]["status"] == "ready"
    assert ready["build_state"]["failed_source_ids"] == [ready_sources["us_doc"]["id"]]
    assert ready_sources["us_doc"]["ingestion_status"] == "failed"
    assert "optional source gaps" in ready["build_state"]["label"]


def test_system_image_materialization_uses_live_embedding_and_rerank_adapters():
    async def fake_embed_texts(*, settings, texts, custom_api_key=None, call_context=None):
        del call_context
        return EmbeddingBatchResult(
            vectors=[[0.1, 0.2, 0.3, 0.4] for _ in texts],
            provider="openai_compatible",
            model_name="embed-live",
            mode="live",
            dimensions=4,
            reason="provider_success",
        )

    async def fake_rerank_candidates(*, settings, query, documents, custom_api_key=None, call_context=None):
        del call_context
        return RerankBatchResult(
            ranked_indices=list(reversed(range(len(documents)))),
            provider="openai_compatible",
            model_name="rerank-live",
            mode="live",
            reason="provider_success",
            latency_ms=17,
        )

    with patch.object(store.llm, "embed_texts", fake_embed_texts), patch.object(
        store.llm, "rerank_candidates", fake_rerank_candidates
    ):
        project, _conversation, _workspace = create_project_with_materialized_system_image("Live Retrieval Project")

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["embedding_records"]
    assert all(item["status"] == "ready" for item in image["embedding_records"])
    assert all(item["provider"] == "openai_compatible" for item in image["embedding_records"])
    assert all(item["embedding_model"] == "embed-live" for item in image["embedding_records"])
    assert all(item["dimensions"] == 4 for item in image["embedding_records"])
    assert image["retrieval_runs"]
    assert all(item["strategy"] == "hybrid_graph_vector" for item in image["retrieval_runs"])
    assert all(item["fallback_used"] is False for item in image["retrieval_runs"])
    assert all(item["embedding_record_ids"] for item in image["retrieval_runs"])
    assert image["rerank_records"]
    assert all(item["status"] == "completed" for item in image["rerank_records"])
    assert all(item["rerank_model"] == "rerank-live" for item in image["rerank_records"])
    assert all(item["latency_ms"] == 17 for item in image["rerank_records"])


def test_production_system_image_materialization_rolls_back_embedding_fallback():
    project = client.post(
        "/v1/projects",
        json={"name": f"Embedding Rollback {time.time_ns()}"},
    ).json()
    code_root = Path("tests/fixtures/system-image/code").resolve()
    store.system_image_service.register_sources(
        project["id"],
        [SourceSpec(source_type="code", source_uri=str(code_root), label="Code")],
    )
    store.system_image_service.ingest_sources(project["id"])
    before = _system_image_materialization_projection(project["id"])

    async def fallback_embed_texts(*, settings, texts, custom_api_key=None, call_context=None):
        del call_context
        return EmbeddingBatchResult(
            vectors=[[0.1] * 32 for _ in texts],
            provider="mock",
            model_name="mock-hash-embedding",
            mode="fallback",
            dimensions=32,
            reason="provider timeout",
        )

    previous_policy = store.system_image_workspace._require_live_model_routes
    store.system_image_workspace._require_live_model_routes = True
    try:
        with patch.object(store.llm, "embed_texts", fallback_embed_texts):
            with pytest.raises(
                RuntimeError,
                match="embedding route must be live in production",
            ):
                asyncio.run(store.system_image_service.materialize_context(project["id"]))
    finally:
        store.system_image_workspace._require_live_model_routes = previous_policy

    assert _system_image_materialization_projection(project["id"]) == before
    restored = InMemoryStore()
    assert _system_image_materialization_projection(
        project["id"],
        target_store=restored,
    ) == before


def test_production_system_image_materialization_rolls_back_rerank_fallback():
    project = client.post(
        "/v1/projects",
        json={"name": f"Rerank Rollback {time.time_ns()}"},
    ).json()
    code_root = Path("tests/fixtures/system-image/code").resolve()
    store.system_image_service.register_sources(
        project["id"],
        [SourceSpec(source_type="code", source_uri=str(code_root), label="Code")],
    )
    store.system_image_service.ingest_sources(project["id"])
    before = _system_image_materialization_projection(project["id"])

    async def live_embed_texts(*, settings, texts, custom_api_key=None, call_context=None):
        del call_context
        return EmbeddingBatchResult(
            vectors=[[0.1, 0.2, 0.3, 0.4] for _ in texts],
            provider="openai_compatible",
            model_name="embed-live",
            mode="live",
            dimensions=4,
            reason="provider_success",
        )

    async def fallback_rerank(*, settings, query, documents, custom_api_key=None, call_context=None):
        del call_context
        return RerankBatchResult(
            ranked_indices=list(range(len(documents))),
            provider="mock",
            model_name="rule-based-fusion",
            mode="fallback",
            reason="provider returned 503",
            latency_ms=5,
        )

    previous_policy = store.system_image_workspace._require_live_model_routes
    store.system_image_workspace._require_live_model_routes = True
    try:
        with patch.object(store.llm, "embed_texts", live_embed_texts), patch.object(
            store.llm,
            "rerank_candidates",
            fallback_rerank,
        ):
            with pytest.raises(
                RuntimeError,
                match="rerank route must be live in production",
            ):
                asyncio.run(store.system_image_service.materialize_context(project["id"]))
    finally:
        store.system_image_workspace._require_live_model_routes = previous_policy

    assert _system_image_materialization_projection(project["id"]) == before
    restored = InMemoryStore()
    assert _system_image_materialization_projection(
        project["id"],
        target_store=restored,
    ) == before


def _system_image_materialization_projection(
    project_id: str,
    *,
    target_store=store,
) -> dict:
    image = target_store.get_system_image(project_id)
    us_items = target_store.quality_loop_repository.list_us_items(project_id)
    asset_lanes = target_store.quality_loop_repository.list_asset_lanes(project_id)
    return {
        "project": image.project.model_dump(),
        "chunks": [
            item.model_dump(exclude={"created_at"})
            for item in image.chunks
        ],
        "objects": [item.model_dump() for item in image.objects],
        "relationships": [item.model_dump() for item in image.relationships],
        "metrics": [item.model_dump() for item in image.metric_snapshots],
        "baselines": [
            item.model_dump(exclude={"updated_at"})
            for item in image.baselines
        ],
        "embeddings": [item.model_dump() for item in image.embedding_records],
        "retrieval_runs": [item.model_dump() for item in image.retrieval_runs],
        "rerank_records": [item.model_dump() for item in image.rerank_records],
        "task_contexts": [item.model_dump() for item in image.task_contexts],
        "quality_profiles": [item.model_dump() for item in image.quality_profiles],
        "us_items": [
            item.model_dump()
            for item in us_items
        ],
        "asset_lanes": {
            item.id: [
                lane.model_dump()
                for lane in asset_lanes.get(item.id, [])
            ]
            for item in us_items
        },
    }


def test_system_image_ingestion_rejects_empty_code_index_results():
    project = client.post("/v1/projects", json={"name": "Empty Code Index"}).json()
    code_root = Path(tempfile.mkdtemp(prefix="nasus-empty-code-index-"))
    (code_root / "service.py").write_text("def service():\n    return True\n", encoding="utf-8")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    registered = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {
                "project_id": project["id"],
                "source_specs": [
                    {"source_type": "code", "source_uri": str(code_root)},
                ],
            },
        },
    )
    assert registered.status_code == 200
    assert registered.json()["status"] == "completed"

    empty_result = IngestedSource(
        content_hash="sha256:empty",
        content_ref=f"nasus://raw/{project['id']}/code/empty",
        evidence_refs=["source:code", "files:0", "bytes:0"],
        file_count=0,
        byte_count=0,
    )
    with patch.object(store.system_image_service.source_ingestion, "ingest", return_value=empty_result):
        ingested = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": "system_image.sources.ingest",
                "input": {"project_id": project["id"]},
            },
        )

    assert ingested.status_code == 200
    body = ingested.json()
    assert body["status"] == "failed"
    assert body["result"]["followup_reason"] == "required_source_ingestion_failed"
    assert body["result"]["next_recommended_tools"] == ["system_image.sources.register"]
    assert "Required system image source types were not indexed: code" in body["summary"]
    assert "Indexed 0" not in body["summary"]

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    code_source = next(source for source in image["sources"] if source["source_type"] == "code")
    assert image["project"]["system_image_status"] == "draft"
    assert image["build_state"]["status"] == "failed"
    assert code_source["ingestion_status"] == "failed"
    assert code_source["file_count"] == 0
    assert code_source["failure_reason"] == "code source produced no ingestible files"
    assert image["chunks"] == []


def test_system_image_ingestion_rejects_disallowed_external_source_scheme():
    project = client.post("/v1/projects", json={"name": "Disallowed Source Scheme"}).json()
    _, us_dir, tests_dir = create_system_image_source_dirs("nasus-disallowed-source-")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    registered = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {
                "project_id": project["id"],
                "source_specs": [
                    {"source_type": "code", "source_uri": "ftp://example.invalid/repo"},
                    {"source_type": "us_doc", "source_uri": str(us_dir)},
                    {"source_type": "test_asset", "source_uri": str(tests_dir)},
                ],
            },
        },
    )
    assert registered.status_code == 200

    ingested = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.ingest",
            "input": {"project_id": project["id"]},
        },
    )
    assert ingested.status_code == 200
    assert ingested.json()["status"] == "failed"

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["build_state"]["status"] == "partially_failed"
    sources = {source["source_type"]: source for source in image["sources"]}
    assert sources["code"]["ingestion_status"] == "failed"
    assert sources["code"]["permission_status"] == "denied"
    assert "scheme is not allowed" in sources["code"]["failure_reason"]
    assert sources["us_doc"]["ingestion_status"] == "indexed"
    assert sources["test_asset"]["ingestion_status"] == "indexed"


def test_agent_memory_context_packages_system_image_state():
    project = client.post("/v1/projects", json={"name": "Agent Memory Image"}).json()
    source_root = Path(tempfile.mkdtemp(prefix="nasus-agent-memory-"))
    code_dir = source_root / "code"
    us_dir = source_root / "us"
    tests_dir = source_root / "tests"
    code_dir.mkdir()
    us_dir.mkdir()
    tests_dir.mkdir()
    (code_dir / "checkout.py").write_text("def checkout(cart):\n    return cart.total\n", encoding="utf-8")
    (us_dir / "US-202.md").write_text("# US-202\nAs a buyer, I can retry payment.\n", encoding="utf-8")
    (tests_dir / "test_retry.py").write_text("def test_retry_payment():\n    assert True\n", encoding="utf-8")

    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    source_specs = [
        {"source_type": "code", "source_uri": str(code_dir)},
        {"source_type": "us_doc", "source_uri": str(us_dir)},
        {"source_type": "test_asset", "source_uri": str(tests_dir)},
    ]
    client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {"project_id": project["id"], "source_specs": source_specs},
        },
    )
    client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.context.materialize",
            "input": {"project_id": project["id"]},
        },
    )
    asyncio.run(store.append_message(conversation["id"], "user", "What does the image know about checkout?"))

    memory = asyncio.run(
        store.agent_memory.build_context(store.get_conversation(conversation["id"]))
    )
    assert "[system_image]" in memory.context_snapshot
    assert "source=code; status=indexed" in memory.context_snapshot
    assert "context_object=" in memory.context_snapshot
    assert "relationship=implements" in memory.context_snapshot
    assert "metric=code_quality" in memory.context_snapshot
    assert "[retrieved_system_image_memory]" in memory.context_snapshot
    assert memory.retrieval_query.endswith("Agent Memory Image")
    assert memory.retrieved_context_refs
    assert any(ref.startswith("raw_asset_chunk:") for ref in memory.retrieved_context_refs)
    assert any(ref.startswith("context_object:") for ref in memory.retrieved_context_refs)
    assert "checkout" in memory.context_snapshot.lower()
    assert "hits across" in memory.retrieved_context_summary
    assert "User: What does the image know about checkout?" in memory.history_snapshot
    assert memory.recent_turn_count >= 1
    assert memory.retrieval_run_refs == []


def test_agent_memory_uses_replaceable_system_image_retriever_port():
    from apps.api.app.agent_memory import AgentMemoryManager
    from apps.api.app.system_image_retriever import (
        SystemImageMemoryHit,
        SystemImageMemorySearchResult,
    )

    class FakeSystemImageRetriever:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        async def search_project_memory(
            self,
            conversation,
            query,
            *,
            limit=8,
            trace=False,
        ):
            self.calls.append((conversation.id, query, limit))
            return SystemImageMemorySearchResult(
                hits=(
                    SystemImageMemoryHit(
                        ref="external_code_memory:checkout-controller",
                        kind="external_code_memory",
                        score=9.8,
                        summary="Checkout controller links US-001 and historical checkout tests.",
                    ),
                )
            )

    project = client.post("/v1/projects", json={"name": "Retriever Port Project"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    asyncio.run(store.append_message(conversation["id"], "user", "Find checkout controller knowledge."))

    retriever = FakeSystemImageRetriever()
    memory_manager = AgentMemoryManager(
        store.agent_application_ports.memory_state,
        system_image_retriever=retriever,
        system_image_workspace=store.system_image_workspace,
        conversation_summaries=store.conversation_summaries,
    )
    memory = asyncio.run(
        memory_manager.build_context(store.get_conversation(conversation["id"]))
    )

    assert retriever.calls == [
        (
            conversation["id"],
            "Find checkout controller knowledge. Retriever Port Project",
            8,
        )
    ]
    assert memory.retrieved_context_refs == ["external_code_memory:checkout-controller"]
    assert "external_code_memory" in memory.retrieved_context_summary
    assert "Checkout controller links US-001" in memory.context_snapshot


def test_agent_goal_think_step_records_memory_context_package():
    from apps.api.app.agent_runtime_models import AgentGoalProposal

    project, conversation, _ = create_project_with_materialized_system_image("Think Memory Package")
    asyncio.run(store.append_message(conversation["id"], "user", "Remember checkout is the first system image target."))

    proposal = AgentGoalProposal(
        goal_template="system_image_build",
        title="Memory-Aware System Image",
        summary="Build the project system image using the current memory package.",
        goal_description="Use project memory and available tools to plan system image construction.",
    )

    goal = asyncio.run(store.agent_loop_runtime.start_goal(conversation["id"], proposal))

    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    think_step = refreshed["steps"][0]
    assert refreshed["id"] == goal.id
    assert think_step["phase"] == "thinking"
    assert think_step["status"] == "completed"
    assert think_step["memory_context_hash"].startswith("sha256:")
    assert "sections=space, project" in think_step["memory_context_summary"]
    assert "checkout is the first system image target" in think_step["memory_retrieval_query"]
    assert think_step["memory_retrieval_run_refs"]
    assert think_step["retrieved_context_refs"]
    assert any(
        ref.startswith(("context_object:", "raw_asset_chunk:"))
        for ref in think_step["retrieved_context_refs"]
    )
    assert "hits across" in think_step["retrieved_context_summary"]
    assert think_step["memory_recent_turn_count"] >= 1
    assert "system_image.sources.register" in think_step["available_tool_ids"]
    assert "Memory context includes" in think_step["reasoning"]

    retrieval_run_id = think_step["memory_retrieval_run_refs"][0].removeprefix("retrieval_run:")
    retrieval_run = next(
        item
        for item in store.system_image_repository.load_project_snapshot(
            project["id"]
        ).retrieval_runs
        if item.id == retrieval_run_id
    )
    assert retrieval_run.query == think_step["memory_retrieval_query"]
    assert retrieval_run.result_refs == think_step["retrieved_context_refs"]
    assert retrieval_run.candidate_count >= len(think_step["retrieved_context_refs"])
    assert retrieval_run.strategy in {"hybrid_graph_vector", "rule_based_fusion"}
    persisted_runs = store.project_repository.load_retrieval_runs()
    assert any(item.id == retrieval_run_id for item in persisted_runs[project["id"]])


def test_agent_memory_context_endpoint_exposes_system_image_agent_memory_view():
    project = client.post("/v1/projects", json={"name": "Inspectable Agent Memory"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Build the official system image from code, US docs, and tests"},
    )

    assert response.status_code == 200
    goal_id = response.json()["agent_goal"]["id"]
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")

    memory = client.get(f"/v1/agent-memory/context?agent_goal_id={goal_id}")
    assert memory.status_code == 200
    body = memory.json()
    assert body["conversation_id"] == conversation["id"]
    assert body["agent_goal_id"] == goal_id
    assert body["context_hash"].startswith("sha256:")
    assert "system_image" in body["context_summary"]
    assert body["working_memory"]["active_goal_id"] == goal_id
    assert body["working_memory"]["status"] == "paused"
    assert body["working_memory"]["pause_reason"] == "missing_source_binding"
    assert body["conversation_memory"]["recent_turn_count"] >= 1
    assert "Build the official system image" in body["retrieved_context"]["query"]
    assert isinstance(body["retrieved_context"]["refs"], list)
    assert body["retrieved_context"]["summary"]
    assert body["project_long_term_memory"]["project_id"] == project["id"]
    assert body["project_long_term_memory"]["system_image_status"] == "draft"
    assert any(":code:" in ref for ref in body["project_long_term_memory"]["source_refs"])
    assert "system_image.sources.register" in body["tool_catalog"]["tool_ids"]
    assert "system_image.baseline.initialize" in body["tool_catalog"]["tool_ids"]


def test_agent_goal_events_use_structured_sse_envelope():
    from apps.api.app.agent_runtime_models import AgentGoalProposal

    project = client.post("/v1/projects", json={"name": "Structured Agent Events"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    proposal = AgentGoalProposal(
        goal_template="system_image_build",
        title="Structured Event System Image",
        summary="Verify that AgentGoal events expose a mergeable SSE envelope.",
        goal_description="Start a system image goal and inspect event payload metadata.",
    )

    goal = asyncio.run(store.agent_loop_runtime.start_goal(conversation["id"], proposal))

    events = list(store.event_queues[conversation["id"]]._queue)
    agent_events = [
        event
        for event in events
        if event.event_type == "agent.goal.updated" and event.entity_id == goal.id
    ]
    assert agent_events
    first_event = agent_events[0]
    assert first_event.occurred_at
    assert first_event.correlation_id
    assert first_event.conversation_id == conversation["id"]
    assert first_event.agent_goal_id == goal.id
    assert first_event.entity_type == "agent_goal"
    assert first_event.mutation_kind == "patch"
    assert first_event.payload["patch"] == first_event.patch
    assert first_event.payload["agent_goal"]["id"] == goal.id
    assert first_event.agent_step_id is not None
    assert ["conversation", conversation["id"]] in first_event.query_keys


def test_conversation_message_events_include_message_snapshot():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "dashboard", "space_id": "dashboard", "title": "Dashboard Event Stream"},
    ).json()

    message = asyncio.run(store.append_message(conversation["id"], "assistant", "Streaming-ready message."))

    events = list(store.event_queues[conversation["id"]]._queue)
    message_events = [
        event
        for event in events
        if event.event_type == "conversation.message.created"
        and event.patch.get("message_id") == message.id
    ]
    assert message_events
    event = message_events[-1]
    assert event.conversation_id == conversation["id"]
    assert event.payload["message"]["id"] == message.id
    assert event.payload["message"]["blocks"][0]["text"] == "Streaming-ready message."


def test_live_planner_receives_unified_memory_context_with_system_image_state():
    original = client.get("/v1/settings").json()
    project = client.post("/v1/projects", json={"name": "Planner Memory Image"}).json()
    source_root = Path(tempfile.mkdtemp(prefix="nasus-planner-memory-"))
    code_dir = source_root / "code"
    us_dir = source_root / "us"
    tests_dir = source_root / "tests"
    code_dir.mkdir()
    us_dir.mkdir()
    tests_dir.mkdir()
    (code_dir / "checkout.py").write_text("def checkout(cart):\n    return cart.total\n", encoding="utf-8")
    (us_dir / "US-404.md").write_text("# US-404\nAs a buyer, I can recover a failed payment.\n", encoding="utf-8")
    (tests_dir / "test_payment_recovery.py").write_text("def test_payment_recovery():\n    assert True\n", encoding="utf-8")

    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    source_specs = [
        {"source_type": "code", "source_uri": str(code_dir)},
        {"source_type": "us_doc", "source_uri": str(us_dir)},
        {"source_type": "test_asset", "source_uri": str(tests_dir)},
    ]
    client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {"project_id": project["id"], "source_specs": source_specs},
        },
    )
    client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.ingest",
            "input": {"project_id": project["id"]},
        },
    )
    client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.context.materialize",
            "input": {"project_id": project["id"]},
        },
    )
    asyncio.run(store.append_message(conversation["id"], "user", "Remember that payment recovery is the hot path."))

    captured: dict[str, str] = {}

    async def fake_call_custom(
        *,
        custom_model,
        custom_api_key,
        system_prompt,
        user_message,
        context_snapshot,
        history_snapshot,
    ):
        captured["system_prompt"] = system_prompt
        captured["user_message"] = user_message
        captured["context_snapshot"] = context_snapshot
        captured["history_snapshot"] = history_snapshot
        return json.dumps(
            {
                "kind": "clarification",
                "question": "Should I initialize the baseline now or inspect risks first?",
                "reason": "planner_memory_context_verified",
                "missing_context": ["confirmation_preference"],
            }
        )

    try:
        save_tested_model_config(
            display_name="Planner memory model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="planner-memory-model",
            api_key="sk-planner-memory",
        )
        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Use what you remember and plan the next system image step"},
            )

        assert response.status_code == 200
        assert response.json()["clarification"]["reason"] == "planner_memory_context_verified"
        assert captured["system_prompt"].startswith("You are Nasus Agent")
        assert "Nasus structured agent planner" in captured["system_prompt"]
        assert "Use what you remember" in captured["user_message"]
        assert "[tool_catalog]" in captured["context_snapshot"]
        assert "system_image.baseline.initialize" in captured["context_snapshot"]
        assert "source=code; status=indexed" in captured["context_snapshot"]
        assert "context_object=" in captured["context_snapshot"]
        assert "metric=code_quality" in captured["context_snapshot"]
        assert "User: Remember that payment recovery is the hot path." in captured["history_snapshot"]
    finally:
        restore_model_route(original, "chat")


def test_live_planner_can_author_system_image_agent_goal_and_emit_thinking_delta():
    original = client.get("/v1/settings").json()
    project = client.post("/v1/projects", json={"name": "Live Planned System Image"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    captured: dict[str, str] = {}

    async def fake_call_custom(
        *,
        custom_model,
        custom_api_key,
        system_prompt,
        user_message,
        context_snapshot,
        history_snapshot,
    ):
        captured["system_prompt"] = system_prompt
        captured["user_message"] = user_message
        captured["context_snapshot"] = context_snapshot
        captured["history_snapshot"] = history_snapshot
        return json.dumps(
            {
                "kind": "agent_goal",
                "goal_template": "system_image_build",
                "title": "LLM Planned Official System Image",
                "summary": "The live planner chose the system image construction goal.",
                "goal_description": "Register sources first, then use tool results to continue the system image build.",
                "suggested_autonomy_level": "semi_auto",
                "estimated_steps": 4,
                "target_refs": [f"project:{project['id']}", f"system-image:{project['id']}"],
                "steps": [
                    {
                        "tool_id": "system_image.sources.register",
                        "input": {"project_id": project["id"]},
                        "reason": "Identify and bind code, US, and test sources before ingestion.",
                        "target_scope": "central",
                    }
                ],
                "query_keys": [["project", project["id"]], ["system-image", project["id"]]],
                "kickoff_message": "I will plan the system image build from the project memory and tool catalog.",
            }
        )

    try:
        save_tested_model_config(
            display_name="Live system image planner",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="system-image-planner-model",
            api_key="sk-system-image-planner",
        )
        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Initialize the system image from code, US docs, and test assets"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["agent_goal"]["title"] == "LLM Planned Official System Image"
        assert "Nasus structured agent planner" in captured["system_prompt"]
        assert "[tool_catalog]" in captured["context_snapshot"]
        assert "system_image.sources.register" in captured["context_snapshot"]

        refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
        goal = refreshed["agent_goals"][-1]
        assert goal["title"] == "LLM Planned Official System Image"
        assert goal["goal_template"] == "system_image_build"
        assert goal["planner_kind"] == "llm_structured"
        assert goal["goal_description"] == "Register sources first, then use tool results to continue the system image build."
        assert f"system-image:{project['id']}" in goal["target_refs"]
        assert ["system-image", project["id"]] in goal["query_keys"]
        assert "tools=system_image.sources.register" in goal["planning_summary"]
        assert goal["pause_reason"] == "missing_source_binding"
        first_act = next(step for step in goal["steps"] if step["phase"] == "acting")
        assert first_act["selected_tool_id"] == "system_image.sources.register"
        assert first_act["reasoning"] == "Identify and bind code, US, and test sources before ingestion."
        explanation = client.get(f"/v1/agent-goals/{goal['id']}/explanation").json()
        assert explanation["planner_kind"] == "llm_structured"
        assert explanation["goal_template"] == "system_image_build"
        assert explanation["target_refs"] == goal["target_refs"]
        assert explanation["query_keys"] == goal["query_keys"]

        thinking_events = [
            event
            for event in store.event_queues[conversation["id"]]._queue
            if event.event_type == "agent.step.thinking.delta"
        ]
        assert thinking_events
        thinking_event = thinking_events[-1]
        assert thinking_event.agent_goal_id == goal["id"]
        assert thinking_event.patch["agent_step_phase"] == "thinking"
        assert thinking_event.patch["memory_context_hash"].startswith("sha256:")
        assert "Initialize the system image" in thinking_event.patch["memory_retrieval_query"]
        assert thinking_event.patch["memory_retrieval_run_refs"]
        assert isinstance(thinking_event.patch["retrieved_context_refs"], list)
        assert thinking_event.patch["retrieved_context_summary"]
        assert thinking_event.patch["planned_tool_ids"] == ["system_image.sources.register"]
        assert thinking_event.patch["sequence"] == 1
        assert thinking_event.patch["chunk_index"] == 0
        assert thinking_event.patch["is_final"] is True
        assert thinking_event.patch["agent_step"]["id"] == thinking_event.agent_step_id
        assert thinking_event.payload["agent_goal"]["id"] == goal["id"]
    finally:
        restore_model_route(original, "chat")


def test_canonical_ui_system_image_command_uses_deterministic_goal_when_live_planner_enabled():
    original = client.get("/v1/settings").json()
    project = client.post("/v1/projects", json={"name": "Canonical UI System Image"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    called = False

    async def fake_call_custom(**kwargs):
        nonlocal called
        called = True
        return json.dumps({"kind": "direct_answer", "text": "live planner should not handle UI commands"})

    try:
        save_tested_model_config(
            display_name="Live planner that should be skipped",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="ui-command-skip-model",
            api_key="sk-ui-command-skip",
        )
        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={
                    "content": (
                        "Build the official system image from code, historical US documents, "
                        "and historical test assets."
                    ),
                    "canonical_action_id": "system-image.build-goal",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert called is False
        assert body["agent_goal"]["title"] == "Build Official System Image"
        assert body["agent_goal"]["goal_template"] == "system_image_build"
        assert body["agent_goal"]["planner_kind"] == "deterministic"
    finally:
        restore_model_route(original, "chat")


def test_system_image_ingest_failure_blocks_context_materialization():
    project = client.post("/v1/projects", json={"name": "Broken Source Ingestion"}).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-broken-source-")
    missing_code = code_dir.parent / "missing-code"
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    registered = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {
                "project_id": project["id"],
                "source_specs": [
                    {"source_type": "code", "source_uri": str(missing_code)},
                    {"source_type": "us_doc", "source_uri": str(us_dir)},
                    {"source_type": "test_asset", "source_uri": str(tests_dir)},
                ],
            },
        },
    )
    assert registered.status_code == 200

    ingested = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.ingest",
            "input": {"project_id": project["id"]},
        },
    )
    assert ingested.status_code == 200
    assert ingested.json()["status"] == "failed"

    materialized = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.context.materialize",
            "input": {"project_id": project["id"]},
        },
    )
    assert materialized.status_code == 200
    assert materialized.json()["status"] == "failed"
    assert "source ingestion failed" in materialized.json()["summary"]

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["project"]["system_image_status"] == "draft"
    assert image["build_state"]["status"] == "partially_failed"
    assert image["build_state"]["failed_source_ids"]
    assert any(source["ingestion_status"] == "failed" for source in image["sources"])


def test_project_conversation_can_initialize_system_image_from_natural_language():
    project = client.post("/v1/projects", json={"name": "Conversation System Image"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Initialize the system image from code, US docs, and test assets"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_goal"]["title"] == "Build Official System Image"
    assert body["agent_goal"]["goal_template"] == "system_image_build"
    assert body["agent_goal"]["goal_description"] == "Register sources, ingest evidence, materialize context, and initialize the baseline."
    assert body["agent_goal"]["planner_kind"] == "deterministic"
    assert f"project:{project['id']}" in body["agent_goal"]["target_refs"]
    assert ["system-image", project["id"]] in body["agent_goal"]["query_keys"]
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")
    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
    goal = refreshed["agent_goals"][-1]
    assert goal["pause_reason"] == "missing_source_binding"
    assert goal["goal_template"] == "system_image_build"
    assert goal["planner_kind"] == "deterministic"
    assert "tools=system_image.sources.register" in goal["planning_summary"]
    assert [step["selected_tool_id"] for step in goal["steps"] if step["phase"] == "acting"] == [
        "system_image.sources.register",
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    ]
    blocked = next(step for step in goal["steps"] if step["status"] == "blocked")
    assert blocked["selected_tool_id"] == "system_image.sources.register"
    assert blocked["tool_invocation_id"]
    assert all(
        step["status"] == "pending"
        for step in goal["steps"]
        if step["selected_tool_id"] in {
            "system_image.sources.ingest",
            "system_image.context.materialize",
            "system_image.baseline.initialize",
        }
    )
    assert any(
        message["metadata"].get("planner_kind") == "source_binding_required"
        for message in refreshed["messages"]
    )
    explanation = client.get(f"/v1/agent-goals/{goal['id']}/explanation")
    assert explanation.status_code == 200
    explanation_body = explanation.json()
    assert explanation_body["status"] == "paused"
    assert explanation_body["goal_template"] == "system_image_build"
    assert explanation_body["goal_description"] == goal["goal_description"]
    assert explanation_body["planner_kind"] == "deterministic"
    assert f"project:{project['id']}" in explanation_body["target_refs"]
    assert ["knowledge", project["id"]] in explanation_body["query_keys"]
    assert "template=system_image_build" in explanation_body["planning_summary"]
    assert explanation_body["phase"] == "paused"
    assert explanation_body["waiting_on"] == "source_binding"
    assert "Provide code path or Git URL" in explanation_body["next_action"]
    assert explanation_body["blocked_step"]["selected_tool_id"] == "system_image.sources.register"
    assert explanation_body["plan"][0]["phase"] == "thinking"
    assert explanation_body["memory_context"]["context_hash"].startswith("sha256:")
    assert "Memory context includes" in explanation_body["reasoning_summary"]

    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-guided-system-image-")
    source_binding = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": system_image_source_prompt(code_dir, us_dir, tests_dir)},
    )
    assert source_binding.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["pause_reason"] == "waiting_confirmation")
    goal = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    confirmation_explanation = client.get(f"/v1/agent-goals/{goal['id']}/explanation").json()
    assert confirmation_explanation["waiting_on"] == "user_confirmation"
    assert "Confirm tool invocation" in confirmation_explanation["next_action"]
    assert "system_image.baseline.initialize" in confirmation_explanation["executed_tool_ids"]
    resume = client.post(f"/v1/agent-goals/{goal['id']}/resume")
    assert resume.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "completed")

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["project"]["system_image_status"] == "ready"
    assert all(source["ingestion_status"] == "indexed" for source in image["sources"])
    completed_explanation = client.get(f"/v1/agent-goals/{goal['id']}/explanation").json()
    assert completed_explanation["status"] == "completed"
    assert completed_explanation["waiting_on"] == "none"
    assert completed_explanation["memory_refs"]
    restored_store = InMemoryStore()
    restored_goal = restored_store.get_agent_goal(goal["id"])
    assert restored_goal.goal_template == "system_image_build"
    assert restored_goal.planner_kind == "deterministic"
    assert f"system-image:{project['id']}" in restored_goal.target_refs


def test_system_image_agent_goal_lifecycle_is_audited_end_to_end():
    project = client.post("/v1/projects", json={"name": "Audited System Image"}).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-audited-system-image-")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": (
                "Build the official system image with "
                f"{system_image_source_prompt(code_dir, us_dir, tests_dir)}"
            )
        },
    )

    assert response.status_code == 200
    goal_id = response.json()["agent_goal"]["id"]
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")

    paused_audit = client.get(f"/v1/audit-events?agent_goal_id={goal_id}")
    assert paused_audit.status_code == 200
    paused_actions = {event["action"] for event in paused_audit.json()}
    assert {"agent.goal.created", "agent.goal.proposed", "agent.goal.started", "agent.goal.paused"}.issubset(
        paused_actions
    )
    assert "agent.goal.resumed" not in paused_actions
    assert all(event["agent_goal_id"] == goal_id for event in paused_audit.json())
    assert any(
        f"project:{project['id']}" in event["object_refs"] and event["metadata"]["max_steps"] == 50
        for event in paused_audit.json()
    )

    resume = client.post(f"/v1/agent-goals/{goal_id}/resume")
    assert resume.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "completed")

    completed_audit = client.get(f"/v1/audit-events?agent_goal_id={goal_id}").json()
    completed_actions = {event["action"] for event in completed_audit}
    assert {"agent.goal.resume_requested", "agent.goal.resumed", "agent.goal.completed"}.issubset(completed_actions)
    assert any(
        event["action"] == "agent.goal.completed" and event["metadata"]["steps_completed"] >= 1
        for event in completed_audit
    )


def test_agent_goal_budget_exhaustion_pauses_before_extra_tool_calls():
    from apps.api.app.agent_runtime_models import AgentGoalProposal, ToolPlanStep
    from apps.api.app.models import AgentGoalCreateRequest

    project = client.post("/v1/projects", json={"name": "Budget Guard System Image"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    proposal = AgentGoalProposal(
        goal_template="system_image_build",
        title="Budget Guard System Image",
        summary="Verify that the agent loop pauses when its step budget is exhausted.",
        goal_description="Build a system image, but stop before tool execution when max_steps is reached.",
        planned_tools=[
            ToolPlanStep(
                tool_id="system_image.sources.register",
                input_payload={"project_id": project["id"]},
                reason="Register source groups before ingestion.",
            )
        ],
    )
    steps = store.agent_loop_runtime.graph_runtime.steps_for_proposal(proposal)
    goal = store.create_agent_goal(
        AgentGoalCreateRequest(
            conversation_id=conversation["id"],
            project_id=project["id"],
            title=proposal.title,
            summary=proposal.summary,
            max_steps=1,
            steps=steps,
        )
    )

    asyncio.run(store.agent_loop_runtime.graph_runtime.start(goal.id, proposal))

    refreshed_goal = store.get_agent_goal(goal.id)
    assert refreshed_goal.status == "paused"
    assert refreshed_goal.pause_reason == "budget_exhausted"
    assert refreshed_goal.budget_exhausted_reason == "max_steps"
    assert not any(
        invocation.input_payload.get("agent_goal_id") == goal.id
        for invocation in store.conversation_repository.load_tool_invocations()
    )
    audit_actions = {event.action for event in store.list_audit_events(agent_goal_id=goal.id)}
    assert "agent.goal.budget_exhausted" in audit_actions


def test_agent_goal_runtime_budgets_round_trip_through_api_and_repository():
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "build",
            "space_id": "budget-runtime-persistence",
            "title": "Budget persistence",
        },
    ).json()
    response = client.post(
        "/v1/agent-goals",
        json={
            "conversation_id": conversation["id"],
            "title": "Persist runtime budgets",
            "summary": "Verify durable production budget fields.",
            "max_steps": 17,
            "max_model_calls": 9,
            "max_thinking_tokens": 12_345,
            "max_runtime_seconds": 240,
            "max_no_progress_observations": 2,
            "model_calls_used": 1,
            "thinking_input_tokens_used": 80,
            "thinking_output_tokens_used": 20,
        },
    )

    assert response.status_code == 200
    goal = response.json()
    assert goal["max_model_calls"] == 9
    assert goal["thinking_tokens_used"] == 100
    persisted = next(
        candidate
        for loaded_conversation in store.conversation_repository.load_all()
        for candidate in loaded_conversation.agent_goals
        if candidate.id == goal["id"]
    )
    assert persisted.max_steps == 17
    assert persisted.max_model_calls == 9
    assert persisted.max_thinking_tokens == 12_345
    assert persisted.max_runtime_seconds == 240
    assert persisted.max_no_progress_observations == 2
    assert persisted.model_calls_used == 1
    assert persisted.thinking_input_tokens_used == 80
    assert persisted.thinking_output_tokens_used == 20
    assert persisted.thinking_tokens_used == 100

    explanation = client.get(
        f"/v1/agent-goals/{goal['id']}/explanation"
    ).json()
    assert explanation["budget"]["max_model_calls"] == 9
    assert explanation["budget"]["thinking_tokens_used"] == 100


def test_paused_agent_goal_budget_can_be_increased_before_resume():
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "build",
            "space_id": "budget-runtime-update",
            "title": "Budget update",
        },
    ).json()
    goal = client.post(
        "/v1/agent-goals",
        json={
            "conversation_id": conversation["id"],
            "title": "Increase exhausted budget",
            "summary": "Make budget pause operationally recoverable.",
            "max_model_calls": 1,
            "model_calls_used": 1,
        },
    ).json()
    stored = store.get_agent_goal(goal["id"])
    stored.status = "paused"
    stored.pause_reason = "budget_exhausted"
    stored.budget_exhausted_reason = "max_model_calls"
    store.agent_goal_projection.upsert_in_conversation(stored)

    response = client.patch(
        f"/v1/agent-goals/{goal['id']}/budget",
        json={"max_model_calls": 3},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "paused"
    assert updated["max_model_calls"] == 3
    assert updated["model_calls_used"] == 1
    assert updated["budget_exhausted_reason"] is None
    audit_actions = {
        event["action"]
        for event in client.get(
            "/v1/audit-events",
            params={"agent_goal_id": goal["id"]},
        ).json()
    }
    assert "agent.goal.budget_updated" in audit_actions


def test_agent_goal_runtime_compiles_system_image_plan_from_goal_context():
    from apps.api.app.agent_runtime_models import AgentGoalProposal

    project = client.post("/v1/projects", json={"name": "Autonomous Plan Image"}).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-autonomous-plan-image-")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    registered = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {
                "project_id": project["id"],
                "source_specs": [
                    {"source_type": "code", "source_uri": str(code_dir)},
                    {"source_type": "us_doc", "source_uri": str(us_dir)},
                    {"source_type": "test_asset", "source_uri": str(tests_dir)},
                ],
            },
        },
    )
    assert registered.status_code == 200
    assert registered.json()["status"] == "completed"
    proposal = AgentGoalProposal(
        goal_template="system_image_build",
        title="Autonomously Build System Image",
        summary="Build the system image from the current project context without a prefilled tool chain.",
        goal_description="Use the current project context to decide the required system image construction tools.",
    )

    goal = asyncio.run(store.agent_loop_runtime.start_goal(conversation["id"], proposal))

    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    compiled_tool_ids = [step["selected_tool_id"] for step in refreshed["steps"] if step["phase"] == "acting"]
    assert compiled_tool_ids == [
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    ]
    assert refreshed["status"] == "paused"
    assert refreshed["pause_reason"] == "waiting_confirmation"
    proposed_audit = next(
        event for event in store.list_audit_events(agent_goal_id=goal.id)
        if event.action == "agent.goal.proposed"
    )
    assert proposed_audit.metadata["planned_tool_ids"] == compiled_tool_ids

    resumed = client.post(f"/v1/agent-goals/{goal.id}/resume")
    assert resumed.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "completed")
    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["project"]["system_image_status"] == "ready"


def test_system_image_agent_replans_remaining_steps_after_partial_tool_plan():
    from apps.api.app.agent_runtime_models import AgentGoalProposal, ToolPlanStep

    project = client.post("/v1/projects", json={"name": "Partial Replan System Image"}).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-partial-replan-image-")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    registered = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.sources.register",
            "input": {
                "project_id": project["id"],
                "source_specs": [
                    {"source_type": "code", "source_uri": str(code_dir)},
                    {"source_type": "us_doc", "source_uri": str(us_dir)},
                    {"source_type": "test_asset", "source_uri": str(tests_dir)},
                ],
            },
        },
    )
    assert registered.status_code == 200
    assert registered.json()["status"] == "completed"

    proposal = AgentGoalProposal(
        goal_template="system_image_build",
        title="Continue System Image From Ingestion",
        summary="The planner only selected ingestion; the runtime must replan remaining system image work.",
        goal_description="Continue system image construction from the current project state.",
        planned_tools=[
            ToolPlanStep(
                tool_id="system_image.sources.ingest",
                input_payload={"project_id": project["id"]},
                reason="Index the already registered system image sources.",
            )
        ],
    )

    goal = asyncio.run(store.agent_loop_runtime.start_goal(conversation["id"], proposal))

    replanned = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    assert replanned["id"] == goal.id
    assert replanned["status"] == "paused"
    assert replanned["pause_reason"] == "waiting_confirmation"
    assert [step["selected_tool_id"] for step in replanned["steps"] if step["phase"] == "acting"] == [
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    ]
    assert all(
        step["status"] == "completed"
        for step in replanned["steps"]
        if step["selected_tool_id"] in {"system_image.sources.ingest", "system_image.context.materialize"}
    )
    assert any(
        event.patch.get("plan_extended") == "system_image_state_replan"
        for event in store.event_queues[conversation["id"]]._queue
    )

    resumed = client.post(f"/v1/agent-goals/{goal.id}/resume")
    assert resumed.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "completed")
    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["project"]["system_image_status"] == "ready"

    event_types = [event.event_type for event in store.event_queues[conversation["id"]]._queue]
    assert "agent.step.updated" in event_types
    assert "agent.step.observation.delta" in event_types
    assert "agent.step.decision.delta" in event_types
    assert any(
        event.event_type == "agent.step.observation.delta"
        and event.patch["observed_tool_id"] == "system_image.baseline.initialize"
        and event.patch["object_refs"]
        for event in store.event_queues[conversation["id"]]._queue
    )
    assert any(
        event.event_type == "agent.step.decision.delta"
        and event.patch["decision"] == "complete"
        and "Official System Image is ready" in event.patch["decision_rationale"]
        for event in store.event_queues[conversation["id"]]._queue
    )

    completed_conversation = client.get(f"/v1/conversations/{conversation['id']}").json()
    completion_message = next(
        message
        for message in completed_conversation["messages"]
        if message["metadata"].get("agent_runtime") == "goal_completion"
    )
    assert completion_message["metadata"]["agent_goal_id"] == goal.id
    assert "Completed AgentGoal: Continue System Image From Ingestion" in completion_message["blocks"][0]["text"]
    assert "system_image.baseline.initialize" in completion_message["metadata"]["executed_tool_ids"]
    assert completion_message["tool_refs"]
    assert completion_message["object_refs"]

    checkpoint_id = completed_conversation["latest_summary_checkpoint_id"]
    assert checkpoint_id is not None
    checkpoint = next(
        checkpoint
        for checkpoint in ConversationRepository().load_summary_checkpoints()
        if checkpoint.id == checkpoint_id
    )
    assert checkpoint.created_by == "system"
    assert "Completed AgentGoal: Continue System Image From Ingestion" in checkpoint.summary_text

    memory = asyncio.run(
        store.agent_memory.build_context(store.get_conversation(conversation["id"]))
    )
    assert memory.checkpoint_count >= 1
    assert "Conversation checkpoint:" in memory.history_snapshot
    assert "Completed AgentGoal: Continue System Image From Ingestion" in memory.history_snapshot
    assert "[project_long_term_memory]" in memory.context_snapshot

    project_memories = [
        item
        for item in store.conversation_repository.load_agent_memory_items()
        if item.owner_ref == f"project:{project['id']}" and item.memory_scope == "project_long_term"
    ]
    assert project_memories
    memory_item = project_memories[-1]
    assert f"agent_goal:{goal.id}" in memory_item.source_refs
    assert f"conversation:{conversation['id']}" in memory_item.source_refs
    assert f"conversation_message:{completion_message['id']}" in memory_item.source_refs
    assert any(ref.startswith("tool_invocation:") for ref in memory_item.source_refs)
    assert memory_item.object_refs
    assert "Completed AgentGoal: Continue System Image From Ingestion" in memory_item.summary

    memory_links = [
        link
        for link in store.conversation_repository.load_agent_memory_links()
        if link.memory_id == memory_item.id
    ]
    assert any(link.target_ref == f"project:{project['id']}" and link.link_kind == "belongs_to" for link in memory_links)
    assert any(link.target_ref == f"system_image:{project['id']}" and link.link_kind == "supports" for link in memory_links)
    assert any(link.link_kind == "derived_from" for link in memory_links)

    persisted_items = store.conversation_repository.load_agent_memory_items()
    assert any(item.id == memory_item.id for item in persisted_items)
    persisted_links = store.conversation_repository.load_agent_memory_links()
    assert any(link.memory_id == memory_item.id for link in persisted_links)

    memory_body = client.get(f"/v1/agent-memory/context?agent_goal_id={goal.id}").json()
    assert any(
        item["id"] == memory_item.id
        for item in memory_body["project_long_term_memory"]["memory_items"]
    )

    asyncio.run(store.append_message(conversation["id"], "user", "What did the previous system image agent complete?"))
    recalled_memory = asyncio.run(
        store.agent_memory.build_context(store.get_conversation(conversation["id"]))
    )
    assert f"agent_memory:{memory_item.id}" in recalled_memory.retrieved_context_refs

    followup = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "What did the previous system image agent complete?"},
    )
    assert followup.status_code == 200
    followup_body = followup.json()
    assert followup_body["tool_invocations"][0]["tool_id"] == "query.system_image.status"
    followup_invocation_id = followup_body["tool_invocations"][0]["id"]
    followup_invocation = client.get(f"/v1/tool-invocations/{followup_invocation_id}").json()
    assert "Recent Agent memory:" in followup_invocation["result"]["summary"]
    assert "Completed AgentGoal: Continue System Image From Ingestion" in followup_invocation["result"]["summary"]

    refreshed_messages = client.get(f"/v1/conversations/{conversation['id']}").json()["messages"]
    assert any(
        message["role"] == "assistant"
        and "Recent Agent memory:" in message["blocks"][0]["text"]
        for message in refreshed_messages
    )


def test_under_specified_system_image_goal_replans_after_source_binding_followup():
    from apps.api.app.agent_runtime_models import AgentGoalProposal

    project = client.post("/v1/projects", json={"name": "Followup Replanned Image"}).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-followup-replanned-image-")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
    proposal = AgentGoalProposal(
        goal_template="system_image_build",
        title="Build System Image From Goal Only",
        summary="Build the project system image without a pre-filled tool chain.",
        goal_description="Autonomously plan the system image construction flow from the current project state.",
    )

    goal = asyncio.run(store.agent_loop_runtime.start_goal(conversation["id"], proposal))

    paused = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    assert paused["id"] == goal.id
    assert paused["status"] == "paused"
    assert paused["pause_reason"] == "missing_source_binding"
    assert [step["selected_tool_id"] for step in paused["steps"] if step["phase"] == "acting"] == [
        "system_image.sources.register"
    ]

    source_binding = asyncio.run(
        store.handle_message(
            conversation["id"],
            system_image_source_prompt(code_dir, us_dir, tests_dir),
        )
    )
    assert source_binding["agent_goal"].id == goal.id
    replanned = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    assert replanned["status"] == "paused"
    assert replanned["pause_reason"] == "waiting_confirmation"
    assert [step["selected_tool_id"] for step in replanned["steps"] if step["phase"] == "acting"] == [
        "system_image.sources.register",
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    ]
    assert all(
        step["status"] == "completed"
        for step in replanned["steps"]
        if step["selected_tool_id"] in {
            "system_image.sources.register",
            "system_image.sources.ingest",
            "system_image.context.materialize",
        }
    )

    resumed = client.post(f"/v1/agent-goals/{goal.id}/resume")
    assert resumed.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "completed")
    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["project"]["system_image_status"] == "ready"
    assert all(source["ingestion_status"] == "indexed" for source in image["sources"])


def test_project_conversation_binds_explicit_system_image_sources_from_natural_language():
    project = client.post("/v1/projects", json={"name": "Conversation Bound Sources"}).json()
    source_root = Path(tempfile.mkdtemp(prefix="nasus-conversation-sources-"))
    code_dir = source_root / "code"
    us_dir = source_root / "us"
    tests_dir = source_root / "tests"
    code_dir.mkdir()
    us_dir.mkdir()
    tests_dir.mkdir()
    (code_dir / "checkout.py").write_text("def checkout(cart):\n    return cart.total\n", encoding="utf-8")
    (us_dir / "US-303.md").write_text("# US-303\nAs a buyer, I can confirm checkout.\n", encoding="utf-8")
    (tests_dir / "test_checkout_confirm.py").write_text("def test_checkout_confirm():\n    assert True\n", encoding="utf-8")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": (
                "Build the official system image with "
                f"code path {code_dir}, US docs path {us_dir}, tests path {tests_dir}"
            )
        },
    )
    assert response.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")
    goal = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    register_step = next(step for step in goal["steps"] if step["selected_tool_id"] == "system_image.sources.register")
    source_specs = register_step["tool_input_payload"]["source_specs"]
    assert {spec["source_type"]: spec["source_uri"] for spec in source_specs} == {
        "code": str(code_dir),
        "us_doc": str(us_dir),
        "test_asset": str(tests_dir),
    }

    client.post(f"/v1/agent-goals/{goal['id']}/resume")
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "completed")
    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    object_names = {item["name"] for item in image["objects"]}
    assert image["project"]["system_image_status"] == "ready"
    assert any("checkout" in name for name in object_names)
    assert any("US-303" in name for name in object_names)
    assert any("test_checkout_confirm" in name for name in object_names)
    swarm = next(
        item for item in store.conversation_repository.load_agent_swarms()
        if item.parent_goal_id == goal["id"] and item.swarm_kind == "ingestion"
    )
    assert swarm.status == "completed"
    assert swarm.budget_ref == f"agent_goal:{goal['id']}:budget"
    assert swarm.result_summary.startswith("Merged 3 source-specific candidates")
    assert {assignment.status for assignment in swarm.assignments} == {"completed"}
    assert {assignment.timeout_seconds for assignment in swarm.assignments} == {120}
    assert {assignment.target_refs[-1] for assignment in swarm.assignments} == {
        "source_type:code",
        "source_type:us_doc",
        "source_type:test_asset",
    }
    swarm_updates = [
        event
        for event in store.event_queues[conversation["id"]]._queue
        if event.event_type == "agent.swarm.updated" and event.swarm_run_id == swarm.id
    ]
    assert swarm_updates
    assert swarm_updates[-1].patch["transition_event_type"] == "agent.swarm.completed"
    assert swarm_updates[-1].patch["agent_swarm"]["status"] == "completed"
    assert swarm_updates[-1].payload["agent_swarm"]["id"] == swarm.id
    fetched_swarm = client.get(f"/v1/agent-swarms/{swarm.id}")
    assert fetched_swarm.status_code == 200
    assert fetched_swarm.json()["id"] == swarm.id
    assert len(fetched_swarm.json()["assignments"]) == 3
    listed_swarms = client.get(
        "/v1/agent-swarms",
        params={"conversation_id": conversation["id"], "parent_goal_id": goal["id"]},
    )
    assert listed_swarms.status_code == 200
    assert [item["id"] for item in listed_swarms.json()] == [swarm.id]
    async def first_swarm_event():
        stream = store.stream_swarm_events(swarm.id)
        event = await stream.__anext__()
        await stream.aclose()
        return event

    snapshot_event = asyncio.run(first_swarm_event())
    assert snapshot_event.event_type == "agent.swarm.snapshot"
    assert snapshot_event.swarm_run_id == swarm.id
    assert snapshot_event.agent_goal_id == goal["id"]
    assert snapshot_event.payload["agent_swarm"]["id"] == swarm.id
    assert snapshot_event.payload["agent_swarm"]["status"] == "completed"
    restored_store = InMemoryStore()
    restored_swarm = restored_store.get_agent_swarm(swarm.id)
    assert restored_swarm.status == "completed"
    assert restored_swarm.budget_ref == f"agent_goal:{goal['id']}:budget"
    assert {assignment.timeout_seconds for assignment in restored_swarm.assignments} == {120}


def test_agent_goal_tool_invocations_are_queryable_as_system_image_execution_trace():
    project = client.post("/v1/projects", json={"name": "Traceable System Image"}).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-traceable-system-image-")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": (
                "Build the official system image with "
                f"{system_image_source_prompt(code_dir, us_dir, tests_dir)}"
            )
        },
    )

    assert response.status_code == 200
    goal_id = response.json()["agent_goal"]["id"]
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")

    paused_trace = client.get(f"/v1/tool-invocations?agent_goal_id={goal_id}").json()
    assert [item["tool_id"] for item in paused_trace] == [
        "system_image.sources.register",
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    ]
    assert all(item["conversation_id"] == conversation["id"] for item in paused_trace)
    assert all(item["initiator_actor"] == "agent" for item in paused_trace)
    assert all(item["initiator_surface"] == "agent_loop" for item in paused_trace)
    assert any(item["status"] == "waiting_confirmation" for item in paused_trace)

    completed = client.post(f"/v1/agent-goals/{goal_id}/resume")
    assert completed.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "completed")

    completed_trace = client.get(f"/v1/tool-invocations?conversation_id={conversation['id']}&status=completed").json()
    assert [item["tool_id"] for item in completed_trace] == [
        "system_image.sources.register",
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    ]
    assert all(item["result"] and item["result"]["summary"] for item in completed_trace)


def test_agent_service_keeps_single_active_goal_per_conversation():
    project = client.post("/v1/projects", json={"name": "Single Active Goal"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    created = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Initialize the official system image from code, US docs, and tests"},
    )
    assert created.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")
    first_goal = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]

    duplicate = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Build the official system image again before the first one completes"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["agent_goal"]["id"] == first_goal["id"]
    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
    assert [goal["id"] for goal in refreshed["agent_goals"]].count(first_goal["id"]) == 1
    assert len(refreshed["agent_goals"]) == 1
    assert any(
        message["metadata"].get("agent_runtime") == "active_goal_guard"
        for message in refreshed["messages"]
    )


def test_development_live_planner_provider_failure_falls_back_to_deterministic_write_plan():
    original = client.get("/v1/settings").json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    ).json()

    try:
        save_tested_model_config(
            display_name="Planner guard model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="planner-model",
            api_key="sk-planner-9999",
        )

        async def failing_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
            raise RuntimeError("planner provider unavailable")

        with patch.object(store.llm, "_call_custom", new=failing_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Help me create a new project called Deterministic Planner Guard"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["agent_goal"]["title"] == "Create project Deterministic Planner Guard"
        assert any(
            project["name"] == "Deterministic Planner Guard"
            for project in client.get("/v1/projects").json()
        )
    finally:
        restore_model_route(original, "chat")


def test_production_planner_provider_failure_blocks_deterministic_write_plan():
    original = client.get("/v1/settings").json()
    project_name = "Blocked Planner Write"
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    ).json()
    existing_goal_ids = {
        goal["id"]
        for goal in client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"]
    }

    try:
        save_tested_model_config(
            display_name="Production planner guard model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="planner-model",
            api_key="sk-planner-production-9999",
        )

        async def failing_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
            raise RuntimeError("planner provider unavailable")

        with (
            patch.object(store.planner, "allow_deterministic_write_fallback", False),
            patch.object(store.llm, "_call_custom", new=failing_call_custom),
        ):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": f"Help me create a new project called {project_name}"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["clarification"]["reason"] == (
            "planner_provider_unavailable:provider_fallback"
        )
        assert body["clarification"]["missing_context"] == ["live_chat_model"]
        assert all(
            project["name"] != project_name
            for project in client.get("/v1/projects").json()
        )
        detail = client.get(f"/v1/conversations/{conversation['id']}").json()
        assert {goal["id"] for goal in detail["agent_goals"]} == existing_goal_ids
    finally:
        restore_model_route(original, "chat")


def test_production_canonical_ui_action_requires_explicit_action_id():
    original = client.get("/v1/settings").json()
    project = client.post(
        "/v1/projects",
        json={"name": "Canonical Action Contract"},
    ).json()
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "project",
            "space_id": project["id"],
            "project_id": project["id"],
            "title": project["name"],
        },
    ).json()
    command = (
        "Build the official system image from code, historical US documents, "
        "and historical test assets."
    )

    try:
        save_tested_model_config(
            display_name="Canonical action guard model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="planner-model",
            api_key="sk-canonical-action-9999",
        )

        async def failing_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
            raise RuntimeError("planner provider unavailable")

        with (
            patch.object(store.planner, "allow_deterministic_write_fallback", False),
            patch.object(store.llm, "_call_custom", new=failing_call_custom),
        ):
            plain_chat = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": command},
            )
            canonical_action = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={
                    "content": command,
                    "canonical_action_id": "system-image.build-goal",
                },
            )

        assert plain_chat.status_code == 200
        assert plain_chat.json()["clarification"]["reason"] == (
            "planner_provider_unavailable:provider_fallback"
        )
        assert canonical_action.status_code == 200
        assert canonical_action.json()["agent_goal"]["goal_template"] == (
            "system_image_build"
        )
        detail = client.get(f"/v1/conversations/{conversation['id']}").json()
        canonical_messages = [
            message
            for message in detail["messages"]
            if message["role"] == "user"
            and message["metadata"].get("canonical_action_id")
            == "system-image.build-goal"
        ]
        assert len(canonical_messages) == 1
        assert canonical_messages[0]["metadata"]["initiator_surface"] == "ui"
    finally:
        restore_model_route(original, "chat")


def test_live_llm_structured_planner_can_drive_open_build_goal():
    original = client.get("/v1/settings").json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    ).json()

    try:
        save_tested_model_config(
            display_name="Structured planner model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="planner-model",
            api_key="sk-planner-9999",
        )

        async def fake_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
            assert "Nasus structured agent planner" in system_prompt
            assert "project.create" in context_snapshot
            return json.dumps(
                {
                    "kind": "agent_goal",
                    "goal_template": "project_setup",
                    "title": "LLM Planned Project Setup",
                    "summary": "Create a project from an open-ended build request.",
                    "goal_description": "Create the project and prepare source import guidance.",
                    "steps": [
                        {
                            "tool_id": "project.create",
                            "input": {"name": "LLM Open Planner Project"},
                            "reason": "Create the project shell from the open-ended build intent.",
                        },
                    ],
                    "target_refs": ["space:build:build"],
                    "query_keys": [["build"], ["dashboard"], ["projects"]],
                    "kickoff_message": "I will create this project using the structured planner.",
                }
            )

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Launch an assurance workspace for enterprise checkout"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["agent_goal"]["title"] == "LLM Planned Project Setup"
        assert any(
            project["name"] == "LLM Open Planner Project"
            for project in client.get("/v1/projects").json()
        )
    finally:
        restore_model_route(original, "chat")


def test_live_llm_planner_can_drive_quality_domain_tools_with_bound_workspace_scope():
    original = client.get("/v1/settings").json()
    project, _, workspace = create_project_with_materialized_system_image(
        "Live Quality Planner Project"
    )
    us_id = workspace["us_items"][0]["id"]
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "workspace",
            "space_id": us_id,
            "project_id": project["id"],
            "us_id": us_id,
            "title": f"{us_id} Workspace",
        },
    ).json()

    try:
        save_tested_model_config(
            display_name="Live quality planner",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="quality-planner-model",
            api_key="sk-quality-planner",
        )

        async def fake_call_custom(
            *,
            custom_model,
            custom_api_key,
            system_prompt,
            user_message,
            context_snapshot,
            history_snapshot,
        ):
            assert "quality.asset-pack.refresh" in context_snapshot
            assert '"description"' in context_snapshot
            return json.dumps(
                {
                    "kind": "agent_goal",
                    "goal_template": "us.quality.prepare",
                    "title": "Prepare the US quality workspace",
                    "summary": "Start the US task and refresh its governed asset pack.",
                    "goal_description": user_message,
                    "steps": [
                        {
                            "tool_id": "us.task.start",
                            "input": {},
                            "reason": "Start the quality task in the active US workspace.",
                        },
                        {
                            "tool_id": "quality.asset-pack.refresh",
                            "input": {},
                            "reason": "Refresh the versioned asset pack after task initialization.",
                        },
                    ],
                }
            )

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Prepare this US for governed quality work and refresh its assets"},
            )

        assert response.status_code == 200
        goal = response.json()["agent_goal"]
        assert goal["planner_kind"] == "llm_structured"
        wait_until(
            lambda: client.get(f"/v1/agent-goals/{goal['id']}").json()["status"]
            == "completed"
        )
        trace = client.get(
            "/v1/tool-invocations",
            params={"agent_goal_id": goal["id"]},
        ).json()
        assert [item["tool_id"] for item in trace] == [
            "us.task.start",
            "quality.asset-pack.refresh",
        ]
        assert all(item["input_payload"]["project_id"] == project["id"] for item in trace)
        assert all(item["input_payload"]["us_id"] == us_id for item in trace)
        assert all(item["input_payload"]["conversation_id"] == conversation["id"] for item in trace)
        refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
        assert any(
            message["metadata"].get("agent_runtime") == "goal_completion"
            and message["metadata"].get("agent_goal_id") == goal["id"]
            for message in refreshed["messages"]
        )
        memory = client.get(
            "/v1/agent-memory/context",
            params={"conversation_id": conversation["id"]},
        ).json()
        assert memory["checkpoint_count"] >= 1
        assert any(
            item.summary.startswith("Completed AgentGoal: Prepare the US quality workspace")
            for item in store.conversation_repository.load_agent_memory_items()
            if item.owner_ref == f"project:{project['id']}"
        )
        audit = client.get(
            "/v1/audit-events",
            params={"agent_goal_id": goal["id"]},
        ).json()
        assert {
            "agent.goal.proposed",
            "agent.goal.started",
            "agent.goal.completed",
            "tool.invocation.created",
            "tool.invocation.completed",
        }.issubset({event["action"] for event in audit})
    finally:
        restore_model_route(original, "chat")


def test_live_agent_replans_remaining_quality_steps_after_observation():
    original = client.get("/v1/settings").json()
    project, _, workspace = create_project_with_materialized_system_image(
        "Observe Replan Quality Project"
    )
    us_id = workspace["us_items"][0]["id"]
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "workspace",
            "space_id": us_id,
            "project_id": project["id"],
            "us_id": us_id,
            "title": f"{us_id} Workspace",
        },
    ).json()
    provider_calls: list[str] = []

    try:
        save_tested_model_config(
            display_name="Observe replan model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="observe-replan-model",
            api_key="sk-observe-replan",
        )

        async def fake_call_custom(**kwargs):
            provider_calls.append(kwargs["system_prompt"])
            if "Nasus observe/replan planner" in kwargs["system_prompt"]:
                replan_input = json.loads(kwargs["user_message"])
                assert [step["tool_id"] for step in replan_input["completed_steps"]] == [
                    "us.task.start"
                ]
                assert [step["tool_id"] for step in replan_input["validated_remaining_steps"]] == [
                    "quality.asset-pack.refresh"
                ]
                return json.dumps(
                    {
                        "action": "replace_remaining",
                        "rationale": "Generate current scope instead of refreshing an empty asset pack.",
                        "confidence": 0.93,
                        "steps": [
                            {
                                "tool_id": "quality.scope.generate",
                                "input": {},
                                "reason": "Materialize the first quality asset after task start.",
                            }
                        ],
                    }
                )
            return json.dumps(
                {
                    "kind": "agent_goal",
                    "goal_template": "us.quality.prepare",
                    "title": "Prepare quality work with observation replanning",
                    "summary": "Start the task and adjust the next asset action from persisted state.",
                    "goal_description": kwargs["user_message"],
                    "steps": [
                        {
                            "tool_id": "us.task.start",
                            "input": {},
                            "reason": "Start the governed US task.",
                        },
                        {
                            "tool_id": "quality.asset-pack.refresh",
                            "input": {},
                            "reason": "Initial pending action that the observation may replace.",
                        },
                    ],
                }
            )

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Prepare this US and adapt the plan after each result"},
            )

        assert response.status_code == 200
        goal = response.json()["agent_goal"]
        wait_until(
            lambda: client.get(f"/v1/agent-goals/{goal['id']}").json()["status"]
            == "completed"
        )
        trace = client.get(
            "/v1/tool-invocations",
            params={"agent_goal_id": goal["id"]},
        ).json()
        assert [item["tool_id"] for item in trace] == [
            "us.task.start",
            "quality.scope.generate",
        ]
        assert sum(
            "Nasus structured agent planner" in prompt
            for prompt in provider_calls
        ) == 1
        assert sum(
            "Nasus observe/replan planner" in prompt
            for prompt in provider_calls
        ) == 1
        audit = client.get(
            "/v1/audit-events",
            params={"agent_goal_id": goal["id"]},
        ).json()
        replan_events = [event for event in audit if event["action"] == "agent.goal.replanned"]
        assert len(replan_events) == 1
        assert replan_events[0]["metadata"]["planner_kind"] == "llm_structured"
        assert replan_events[0]["metadata"]["removed_tool_ids"] == [
            "quality.asset-pack.refresh"
        ]
        assert replan_events[0]["metadata"]["added_tool_ids"] == [
            "quality.scope.generate"
        ]
    finally:
        restore_model_route(original, "chat")


def test_live_agent_replan_cannot_complete_quality_goal_before_release_assessment():
    original = client.get("/v1/settings").json()
    project, _, workspace = create_project_with_materialized_system_image(
        "Observe Replan Release Guard Project"
    )
    us_id = workspace["us_items"][0]["id"]
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "workspace",
            "space_id": us_id,
            "project_id": project["id"],
            "us_id": us_id,
            "title": f"{us_id} Workspace",
        },
    ).json()

    try:
        save_tested_model_config(
            display_name="Release guard replan model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="release-guard-replan-model",
            api_key="sk-release-guard-replan",
        )

        async def fake_call_custom(**kwargs):
            if "Nasus observe/replan planner" in kwargs["system_prompt"]:
                return json.dumps(
                    {
                        "action": "complete",
                        "rationale": "The generated scope appears sufficient.",
                        "confidence": 0.98,
                    }
                )
            return json.dumps(
                {
                    "kind": "agent_goal",
                    "goal_template": "us.quality.complete",
                    "title": "Guard release assessment completion",
                    "summary": "Generate scope and assess release readiness.",
                    "goal_description": kwargs["user_message"],
                    "steps": [
                        {
                            "tool_id": "quality.scope.generate",
                            "input": {},
                            "reason": "Generate current quality scope.",
                        },
                        {
                            "tool_id": "release.assess",
                            "input": {},
                            "reason": "Assess release readiness before completion.",
                        },
                    ],
                }
            )

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Complete this quality goal without skipping release assessment"},
            )

        assert response.status_code == 200
        goal = response.json()["agent_goal"]
        wait_until(
            lambda: client.get(f"/v1/agent-goals/{goal['id']}").json()["status"]
            == "completed"
        )
        trace = client.get(
            "/v1/tool-invocations",
            params={"agent_goal_id": goal["id"]},
        ).json()
        assert [item["tool_id"] for item in trace] == [
            "quality.scope.generate",
            "release.assess",
        ]
        audit = client.get(
            "/v1/audit-events",
            params={"agent_goal_id": goal["id"]},
        ).json()
        replan_events = [event for event in audit if event["action"] == "agent.goal.replanned"]
        assert len(replan_events) == 1
        assert (
            replan_events[0]["metadata"]["planner_kind"]
            == "replan_policy:incomplete_goal_plan"
        )
        assert replan_events[0]["metadata"]["removed_tool_ids"] == []
    finally:
        restore_model_route(original, "chat")


def test_live_llm_planner_can_author_complete_quality_loop_plan():
    original = client.get("/v1/settings").json()
    project, _, workspace = create_project_with_materialized_system_image(
        "Complete Quality Planner Project"
    )
    us_id = workspace["us_items"][0]["id"]
    conversation_payload = client.post(
        "/v1/conversations",
        json={
            "space_type": "workspace",
            "space_id": us_id,
            "project_id": project["id"],
            "us_id": us_id,
            "title": f"{us_id} Workspace",
        },
    ).json()
    conversation = store.get_conversation(conversation_payload["id"])
    target_url = "https://quality-planner.example.test"

    try:
        save_tested_model_config(
            display_name="Complete quality planner",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="complete-quality-model",
            api_key="sk-complete-quality",
        )

        async def fake_call_custom(**kwargs):
            return json.dumps(
                {
                    "kind": "agent_goal",
                    "goal_template": "us.quality.complete",
                    "title": "Complete quality loop",
                    "summary": "Generate assets, execute automation, and assess release readiness.",
                    "goal_description": kwargs["user_message"],
                    "steps": [
                        {"tool_id": "quality.scope.generate", "input": {}, "reason": "Generate scope."},
                        {"tool_id": "quality.scenario.generate", "input": {}, "reason": "Generate scenarios."},
                        {"tool_id": "quality.case.generate", "input": {}, "reason": "Generate cases."},
                        {"tool_id": "automation.generate", "input": {}, "reason": "Generate automation."},
                        {
                            "tool_id": "run.start",
                            "input": {"base_url": target_url},
                            "reason": "Execute against the supplied target.",
                        },
                        {"tool_id": "release.assess", "input": {}, "reason": "Assess release readiness."},
                    ],
                }
            )

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            decision = asyncio.run(
                store.planner.plan(
                    conversation,
                    f"Complete this US quality loop against {target_url}",
                )
            )

        assert decision.kind == "agent_goal"
        assert decision.agent_goal is not None
        assert decision.agent_goal.planner_kind == "llm_structured"
        assert [step.tool_id for step in decision.agent_goal.planned_tools] == [
            "quality.scope.generate",
            "quality.scenario.generate",
            "quality.case.generate",
            "automation.generate",
            "run.start",
            "release.assess",
        ]
        assert decision.agent_goal.planned_tools[4].input_payload["base_url"] == target_url
        assert all(
            step.input_payload["project_id"] == project["id"]
            and step.input_payload["us_id"] == us_id
            for step in decision.agent_goal.planned_tools
        )
    finally:
        restore_model_route(original, "chat")


def test_live_llm_planner_can_execute_multi_tool_read_plan_without_agent_goal():
    original = client.get("/v1/settings").json()
    project, _, _ = create_project_with_materialized_system_image(
        "Live Read Planner Project"
    )
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "project",
            "space_id": project["id"],
            "project_id": project["id"],
            "title": project["name"],
        },
    ).json()

    try:
        save_tested_model_config(
            display_name="Live read planner",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="read-planner-model",
            api_key="sk-read-planner",
        )

        async def fake_call_custom(**kwargs):
            return json.dumps(
                {
                    "kind": "tool_plan",
                    "intent_kind": "project_health_review",
                    "steps": [
                        {
                            "tool_id": "query.project.status",
                            "input": {},
                            "reason": "Read project progress and active quality state.",
                        },
                        {
                            "tool_id": "query.system_image.status",
                            "input": {},
                            "reason": "Read source freshness and baseline readiness.",
                        },
                    ],
                }
            )

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Compare project progress with system image readiness"},
            )

        assert response.status_code == 200
        body = response.json()
        assert "agent_goal" not in body
        assert [item["tool_id"] for item in body["tool_invocations"]] == [
            "query.project.status",
            "query.system_image.status",
        ]
        assert all(item["status"] == "completed" for item in body["tool_invocations"])
        assert all(item["input_payload"]["project_id"] == project["id"] for item in body["tool_invocations"])
    finally:
        restore_model_route(original, "chat")


def test_live_llm_planner_rejects_cross_project_tool_scope_before_invocation():
    original = client.get("/v1/settings").json()
    project, _, workspace = create_project_with_materialized_system_image(
        "Planner Scope Guard Project"
    )
    us_id = workspace["us_items"][0]["id"]
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "workspace",
            "space_id": us_id,
            "project_id": project["id"],
            "us_id": us_id,
            "title": f"{us_id} Workspace",
        },
    ).json()

    try:
        save_tested_model_config(
            display_name="Planner scope guard",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="scope-guard-model",
            api_key="sk-scope-guard",
        )

        async def fake_call_custom(**kwargs):
            return json.dumps(
                {
                    "kind": "agent_goal",
                    "goal_template": "forged_scope",
                    "title": "Cross-scope release assessment",
                    "summary": "Attempt to assess another project.",
                    "goal_description": "Assess another project.",
                    "steps": [
                        {
                            "tool_id": "release.assess",
                            "input": {
                                "project_id": "proj_not_current",
                                "us_id": us_id,
                            },
                            "reason": "This should be rejected before invocation.",
                        }
                    ],
                }
            )

        before_ids = {
            invocation.id
            for invocation in store.conversation_repository.load_tool_invocations()
        }
        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Assess the release status in another project"},
            )

        assert response.status_code == 200
        assert response.json()["clarification"]["reason"] == "planner_policy:scope_conflict"
        assert {
            invocation.id
            for invocation in store.conversation_repository.load_tool_invocations()
        } == before_ids
    finally:
        restore_model_route(original, "chat")


def test_live_llm_planner_requests_missing_execution_target_before_starting_goal():
    original = client.get("/v1/settings").json()
    project, _, workspace = create_project_with_materialized_system_image(
        "Planner Execution Context Project"
    )
    us_id = workspace["us_items"][0]["id"]
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "workspace",
            "space_id": us_id,
            "project_id": project["id"],
            "us_id": us_id,
            "title": f"{us_id} Workspace",
        },
    ).json()

    try:
        save_tested_model_config(
            display_name="Execution context planner",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="execution-context-model",
            api_key="sk-execution-context",
        )

        async def fake_call_custom(**kwargs):
            return json.dumps(
                {
                    "kind": "agent_goal",
                    "goal_template": "us.quality.complete",
                    "title": "Execute the US automation",
                    "summary": "Run automation for the active US.",
                    "goal_description": "Run automation.",
                    "steps": [
                        {
                            "tool_id": "run.start",
                            "input": {},
                            "reason": "Execute the generated automation.",
                        }
                    ],
                }
            )

        before_ids = {
            invocation.id
            for invocation in store.conversation_repository.load_tool_invocations()
        }
        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Run the generated automation"},
            )

        assert response.status_code == 200
        assert response.json()["clarification"]["reason"] == "planner_policy:missing_context"
        assert response.json()["clarification"]["missing_context"] == ["base_url"]
        assert {
            invocation.id
            for invocation in store.conversation_repository.load_tool_invocations()
        } == before_ids
    finally:
        restore_model_route(original, "chat")


def test_live_llm_planned_high_risk_action_still_pauses_at_governance_gate():
    original = client.get("/v1/settings").json()
    project = client.post("/v1/projects", json={"name": "Planner Governance Gate"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "project",
            "space_id": project["id"],
            "project_id": project["id"],
            "title": project["name"],
        },
    ).json()

    try:
        save_tested_model_config(
            display_name="Governed planner",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="governed-planner-model",
            api_key="sk-governed-planner",
        )

        async def fake_call_custom(**kwargs):
            return json.dumps(
                {
                    "kind": "tool_plan",
                    "intent_kind": "release_governance",
                    "steps": [
                        {
                            "tool_id": "approval.request",
                            "input": {"purpose": "release_decision"},
                            "reason": "A reviewer must approve the release decision.",
                        }
                    ],
                }
            )

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Prepare a formal release approval request"},
            )

        assert response.status_code == 200
        goal = response.json()["agent_goal"]
        wait_until(
            lambda: client.get(f"/v1/agent-goals/{goal['id']}").json()["status"]
            == "paused"
        )
        refreshed_goal = client.get(f"/v1/agent-goals/{goal['id']}").json()
        assert refreshed_goal["pause_reason"] == "waiting_confirmation"
        trace = client.get(
            "/v1/tool-invocations",
            params={"agent_goal_id": goal["id"]},
        ).json()
        assert len(trace) == 1
        assert trace[0]["tool_id"] == "approval.request"
        assert trace[0]["status"] == "waiting_confirmation"
        assert "confirmed_by_user" not in trace[0]["input_payload"]

        resumed = client.post(f"/v1/agent-goals/{goal['id']}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "completed"
        resumed_trace = client.get(
            "/v1/tool-invocations",
            params={"agent_goal_id": goal["id"]},
        ).json()
        assert len(resumed_trace) == 1
        assert resumed_trace[0]["id"] == trace[0]["id"]
        assert resumed_trace[0]["status"] == "completed"
        audit = client.get(
            "/v1/audit-events",
            params={"agent_goal_id": goal["id"]},
        ).json()
        assert {
            "agent.goal.paused",
            "agent.goal.resume_requested",
            "agent.goal.resumed",
            "agent.goal.completed",
            "tool.invocation.gated",
            "tool.invocation.confirmed",
            "tool.invocation.completed",
        }.issubset({event["action"] for event in audit})
    finally:
        restore_model_route(original, "chat")


def test_project_conversation_confirmation_message_resumes_paused_system_image_goal():
    project = client.post("/v1/projects", json={"name": "Chat Confirm System Image"}).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-chat-confirm-system-image-")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": (
                "Initialize the system image with "
                f"{system_image_source_prompt(code_dir, us_dir, tests_dir)}"
            )
        },
    )
    assert response.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")

    confirmation = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "确认，继续执行"},
    )
    assert confirmation.status_code == 200
    body = confirmation.json()
    assert body["agent_goal"]["status"] == "completed"
    assert body["tool_invocation"]["status"] == "completed"

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["project"]["system_image_status"] == "ready"
    assert all(source["ingestion_status"] == "indexed" for source in image["sources"])


def test_paused_system_image_agent_goal_can_resume_after_store_restart():
    project = client.post("/v1/projects", json={"name": "Restartable System Image"}).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-restartable-system-image-")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": (
                "Build the system image from source evidence with "
                f"{system_image_source_prompt(code_dir, us_dir, tests_dir)}"
            )
        },
    )
    assert response.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")
    paused_goal = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    assert paused_goal["pause_reason"] == "waiting_confirmation"
    checkpoint = client.get(f"/v1/agent-goals/{paused_goal['id']}/checkpoint").json()
    assert checkpoint["status"] == "paused"
    assert checkpoint["phase"] == "paused"
    assert checkpoint["blocked_step_index"] == checkpoint["resume_step_index"]
    assert checkpoint["blocked_tool_invocation_id"]

    restored_store = InMemoryStore()
    restored_goal = restored_store.get_agent_goal(paused_goal["id"])
    assert restored_goal.status == "paused"
    assert any(step.tool_invocation_id for step in restored_goal.steps if step.status == "blocked")
    restored_checkpoint = restored_store.get_agent_goal_checkpoint(paused_goal["id"])
    assert restored_checkpoint.blocked_tool_invocation_id == checkpoint["blocked_tool_invocation_id"]
    assert restored_checkpoint.resume_step_index == checkpoint["resume_step_index"]

    resumed = asyncio.run(restored_store.resume_agent_goal(paused_goal["id"]))
    assert resumed.status == "completed"
    image = restored_store.get_system_image(project["id"])
    assert image.project.system_image_status == "ready"
    assert all(source.ingestion_status == "indexed" for source in image.sources)


def test_missing_source_binding_agent_goal_can_resume_after_store_restart():
    project = client.post("/v1/projects", json={"name": "Restartable Source Binding"}).json()
    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-restartable-source-binding-")
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Build the official system image from code, US docs, and tests"},
    )
    assert response.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")
    paused_goal = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    assert paused_goal["pause_reason"] == "missing_source_binding"
    checkpoint = client.get(f"/v1/agent-goals/{paused_goal['id']}/checkpoint").json()
    blocked_invocation_id = checkpoint["blocked_tool_invocation_id"]
    assert blocked_invocation_id

    restored_store = InMemoryStore()
    restored_goal = restored_store.get_agent_goal(paused_goal["id"])
    assert restored_goal.status == "paused"
    assert restored_goal.pause_reason == "missing_source_binding"
    restored_invocation = restored_store.get_tool_invocation(blocked_invocation_id)
    assert restored_invocation.result is not None
    assert restored_invocation.result.requires_followup is True
    assert restored_invocation.result.followup_reason == "missing_source_binding"

    resumed_after_source = asyncio.run(
        restored_store.handle_message(
            conversation["id"],
            system_image_source_prompt(code_dir, us_dir, tests_dir),
        )
    )
    assert resumed_after_source["agent_goal"].id == paused_goal["id"]
    assert resumed_after_source["agent_goal"].status == "paused"
    assert resumed_after_source["agent_goal"].pause_reason == "waiting_confirmation"
    restored_with_sources = restored_store.get_system_image(project["id"])
    assert all(source.ingestion_status == "indexed" for source in restored_with_sources.sources)

    completed = asyncio.run(restored_store.resume_agent_goal(paused_goal["id"]))
    assert completed.status == "completed"
    image = restored_store.get_system_image(project["id"])
    assert image.project.system_image_status == "ready"


def test_project_conversation_routes_system_image_query_to_canonical_tool():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": "proj_payment", "title": "Payment System"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Show me the current system image freshness and baseline status"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_invocations"][0]["tool_id"] == "query.system_image.status"


def test_project_and_version_are_persisted_across_store_restart():
    project = client.post("/v1/projects", json={"name": "Persistent Project"}).json()
    version = client.post(f"/v1/projects/{project['id']}/versions", json={"name": "2026.Q4"}).json()

    restored_store = InMemoryStore()
    restored_projects = restored_store.list_projects()
    assert any(item.name == "Persistent Project" for item in restored_projects)
    restored_versions = restored_store.project_repository.list_versions(project["id"])
    assert any(item.name == "2026.Q4" for item in restored_versions)
    assert version["id"] in {item.id for item in restored_versions}
    assert (
        restored_store.quality_loop_repository.get_release_readiness(version["id"]).status
        == "Draft"
    )


def test_version_api_creation_is_backed_by_tool_invocation_and_audit():
    project = client.post("/v1/projects", json={"name": "API Version Project"}).json()
    version = client.post(f"/v1/projects/{project['id']}/versions", json={"name": "2026.Q5"}).json()

    invocations = client.get(
        "/v1/tool-invocations",
        params={"tool_id": "version.create", "status": "completed"},
    ).json()
    matching = [
        invocation
        for invocation in invocations
        if f"version:{version['id']}" in (invocation.get("result") or {}).get("object_refs", [])
    ]
    assert matching
    audit = client.get(f"/v1/audit-events?tool_invocation_id={matching[-1]['id']}").json()
    assert {"tool.invocation.created", "tool.invocation.completed"}.issubset({event["action"] for event in audit})


def test_workspace_message_generates_agent_goal():
    project, _, workspace = create_project_with_materialized_system_image("Workspace Goal Project")
    us_id = workspace["us_items"][0]["id"]
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": us_id, "title": f"{us_id} Workspace"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Generate scenarios for this US"},
    )
    assert response.status_code == 200
    wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"]) == 1)
    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
    goal = refreshed["agent_goals"][0]
    assert goal["status"] in {"running", "completed"}
    wait_until(lambda: len(client.get(f"/v1/tool-invocations?agent_goal_id={goal['id']}").json()) >= 1)
    trace = client.get(f"/v1/tool-invocations?agent_goal_id={goal['id']}").json()
    assert [item["tool_id"] for item in trace] == ["quality.scenario.generate"]


def test_workspace_quality_loop_request_creates_agent_goal_proposal_and_runtime_goal():
    project, _, workspace = create_project_with_materialized_system_image("Workspace Quality Goal Project")
    us_id = workspace["us_items"][0]["id"]
    assert workspace["quality_loop_state"]["status"] == "not_started"
    assert workspace["quality_loop_state"]["next_recommended_tools"] == ["quality.scenario.generate"]
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": us_id, "title": f"{us_id} Workspace"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Help me complete the quality loop for this US"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent_goal"]["title"].startswith("Advance quality loop")
    wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"]) >= 1)
    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
    assert refreshed["agent_goals"][-1]["status"] in {"running", "completed"}


def test_quality_generation_failure_is_atomic_and_marks_tool_failed():
    project, conversation, workspace = create_project_with_materialized_system_image("Atomic Quality Generation")
    us_id = workspace["us_items"][0]["id"]
    resolved_handler = store.tool_invocation_runtime.handlers.resolve("quality.scenario.generate")
    quality_handler = resolved_handler.fn.__self__
    original_generator = quality_handler.quality_loop_app.quality_steps.quality_generator

    class FailingQualityGenerator:
        async def generate(self, request):
            raise QualityGenerationError("provider returned invalid structured output")

    before_lanes = [
        lane.model_dump()
        for lane in store.quality_loop_repository.list_asset_lanes_for_us(us_id)
    ]
    before_pack = store.quality_loop_repository.get_quality_asset_pack(
        project["id"], us_id
    )
    quality_handler.quality_loop_app.quality_steps.quality_generator = FailingQualityGenerator()
    try:
        response = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": "quality.scenario.generate",
                "input": {"project_id": project["id"], "us_id": us_id},
            },
        )
    finally:
        quality_handler.quality_loop_app.quality_steps.quality_generator = original_generator

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "invalid structured output" in response.json()["result"]["summary"]
    assert [
        lane.model_dump()
        for lane in store.quality_loop_repository.list_asset_lanes_for_us(us_id)
    ] == before_lanes
    assert (
        store.quality_loop_repository.get_quality_asset_pack(project["id"], us_id)
        == before_pack
    )


def test_quality_generation_requires_exact_materialized_context_for_target_us():
    project, conversation, workspace = create_project_with_materialized_system_image(
        "Exact Quality Context"
    )
    first_us_id = workspace["us_items"][0]["id"]
    second_us_id = f"{first_us_id}_unmaterialized"
    us_items = store.quality_loop_repository.list_us_items(project["id"])
    us_items.append(
        USItem(
            id=second_us_id,
            title="Unmaterialized follow-up risk",
            owner="QA Lead",
            status="analysis",
            risk="medium",
            progress=12,
            next_action="Generate scenarios",
        )
    )
    store.project_repository.replace_us_items(
        project["id"],
        workspace["current_version_id"] or None,
        us_items,
    )

    response = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "quality.scenario.generate",
            "input": {"project_id": project["id"], "us_id": second_us_id},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "requires its own materialized TaskContext" in response.json()["result"]["summary"]
    assert store.quality_loop_repository.list_asset_lanes_for_us(second_us_id) == []
    assert (
        store.quality_loop_repository.get_quality_asset_pack(
            project["id"], second_us_id
        )
        is None
    )
    task_contexts = store.system_image_repository.list_task_contexts(project["id"])
    assert any(
        context.us_id == first_us_id
        for context in task_contexts
    )
    assert not any(
        context.us_id == second_us_id
        for context in task_contexts
    )

    materialized = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.context.materialize",
            "input": {
                "project_id": project["id"],
                "version_id": workspace["current_version_id"],
            },
        },
    )
    assert materialized.status_code == 200
    assert materialized.json()["status"] == "completed"

    retried = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "quality.scenario.generate",
            "input": {"project_id": project["id"], "us_id": second_us_id},
        },
    )
    assert retried.status_code == 200
    retry_body = retried.json()
    assert retry_body["status"] == "completed", retry_body.get("result")
    assert (
        store.quality_loop_repository.get_quality_asset_pack(
            project["id"], second_us_id
        ).us_id
        == second_us_id
    )


def test_quality_loop_continue_starts_from_first_incomplete_asset_lane():
    project, conversation, workspace = create_project_with_materialized_system_image("State Aware Quality Project")
    us_id = workspace["us_items"][0]["id"]
    scenario = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "quality.scenario.generate",
            "input": {"project_id": project["id"], "us_id": us_id},
        },
    )
    assert scenario.status_code == 200
    assert scenario.json()["status"] == "completed"

    workspace_conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "workspace",
            "space_id": us_id,
            "project_id": project["id"],
            "us_id": us_id,
            "title": f"{us_id} Workspace",
        },
    ).json()
    response = client.post(
        f"/v1/conversations/{workspace_conversation['id']}/messages",
        json={
            "content": (
                f"Continue the quality loop for this US against {TEST_TARGET_BASE_URL}"
            )
        },
    )

    assert response.status_code == 200
    goal_id = response.json()["agent_goal"]["id"]
    wait_until(lambda: len(client.get(f"/v1/tool-invocations?agent_goal_id={goal_id}").json()) >= 8)
    trace = client.get(f"/v1/tool-invocations?agent_goal_id={goal_id}").json()
    assert [item["tool_id"] for item in trace] == [
        "quality.scope.generate",
        "quality.scenario.generate",
        "quality.plan.generate",
        "quality.case.generate",
        "automation.generate",
        "run.start",
        "quality.change-doc.generate",
        "release.assess",
    ]


def test_quality_execution_clarification_resumes_when_user_supplies_target_url():
    project, conversation, workspace = create_project_with_materialized_system_image(
        "Clarified Execution Target Project"
    )
    us_id = workspace["us_items"][0]["id"]
    for tool_id in [
        "quality.scenario.generate",
        "quality.case.generate",
        "automation.generate",
    ]:
        response = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": {"project_id": project["id"], "us_id": us_id},
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    workspace_conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "workspace",
            "space_id": us_id,
            "project_id": project["id"],
            "us_id": us_id,
            "title": f"{us_id} Workspace",
        },
    ).json()
    clarification = client.post(
        f"/v1/conversations/{workspace_conversation['id']}/messages",
        json={"content": "Run the automation now"},
    )

    assert clarification.status_code == 200
    assert clarification.json()["clarification"]["reason"] == "quality_execution_target"
    assert clarification.json()["clarification"]["missing_context"] == ["base_url"]
    assert client.get(f"/v1/projects/{project['id']}/runs").json() == []

    resumed = client.post(
        f"/v1/conversations/{workspace_conversation['id']}/messages",
        json={"content": TEST_TARGET_BASE_URL},
    )

    assert resumed.status_code == 200
    goal_id = resumed.json()["agent_goal"]["id"]
    wait_until(
        lambda: len(
            client.get(f"/v1/tool-invocations?agent_goal_id={goal_id}").json()
        )
        >= 1
    )
    trace = client.get(f"/v1/tool-invocations?agent_goal_id={goal_id}").json()
    assert [item["tool_id"] for item in trace] == ["run.start"]
    assert trace[0]["input_payload"]["base_url"] == TEST_TARGET_BASE_URL


def test_project_quality_loop_request_selects_first_us_and_completes_release_assessment():
    project, conversation, workspace = create_project_with_materialized_system_image("Quality Loop Project")
    us_id = workspace["us_items"][0]["id"]
    assert workspace["asset_lanes"]

    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": (
                "Continue the quality loop and generate scenarios for the riskiest open US "
                f"against {TEST_TARGET_BASE_URL}"
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent_goal"]["title"].startswith("Advance quality loop")

    def quality_loop_completed() -> bool:
        current_workspace = client.get(f"/v1/projects/{project['id']}/workspaces/{us_id}").json()
        lanes = {lane["label"]: lane for lane in current_workspace["asset_lanes"]}
        return (
            lanes.get("Scenarios", {}).get("status") == "approved"
            and lanes.get("Cases", {}).get("status") == "approved"
            and lanes.get("Automation", {}).get("status") == "completed"
            and lanes.get("Release Assessment", {}).get("status") == "completed"
            and bool(current_workspace["runs"])
        )

    wait_until(quality_loop_completed, timeout=3)
    completed_workspace = client.get(f"/v1/projects/{project['id']}").json()
    assert completed_workspace["quality_loop_state"]["status"] == "ready_for_release"
    assert completed_workspace["quality_loop_state"]["stage_index"] == completed_workspace["quality_loop_state"]["stage_total"]
    assert completed_workspace["quality_loop_state"]["release_score"] >= 80
    assert completed_workspace["quality_asset_pack"]["status"] == "completed"
    assert {
        part["part_type"]
        for part in completed_workspace["quality_asset_pack"]["parts"]
    } == {
        "scope_pack",
        "scenario_set",
        "verification_plan",
        "case_set",
        "automation_blueprint",
        "change_document",
        "release_assessment",
    }
    generated_parts = {
        part["part_type"]: part
        for part in completed_workspace["quality_asset_pack"]["parts"]
        if part["part_type"] in {
            "scope_pack",
            "scenario_set",
            "verification_plan",
            "case_set",
            "change_document",
        }
    }
    assert generated_parts["scenario_set"]["structured_content"]["scenarios"]
    assert generated_parts["case_set"]["structured_content"]["cases"]
    assert generated_parts["verification_plan"]["structured_content"]["priorities"]
    assert generated_parts["change_document"]["structured_content"]["deltas"]
    assert generated_parts["scenario_set"]["generation"]["prompt_id"] == "quality.scenario.generate"
    assert generated_parts["case_set"]["generation"]["prompt_id"] == "quality.case.generate"
    assert generated_parts["verification_plan"]["generation"]["prompt_id"] == "quality.plan.generate"
    assert generated_parts["change_document"]["generation"]["prompt_id"] == "quality.change-doc.generate"
    assert generated_parts["scenario_set"]["generation"]["mode"] in {"live", "fallback"}
    assert completed_workspace["execution_evidence"]
    assert all(item["content_hash"].startswith("sha256:") for item in completed_workspace["execution_evidence"])
    assert all(
        item["storage_ref"].startswith(("local-object://", "s3://"))
        for item in completed_workspace["execution_evidence"]
    )
    assert completed_workspace["release_decision"] is None
    release = client.get(f"/v1/projects/{project['id']}/release-readiness").json()
    assert release["status"] == "Ready for release review"
    assert release["score"] >= 80

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    quality_loop_metrics = [
        metric
        for metric in image["metric_snapshots"]
        if metric["us_id"] == us_id and metric["metrics"].get("source") == "quality_loop_tool"
    ]
    assert {metric["metrics"]["quality_loop_step"] for metric in quality_loop_metrics} == {
        "scope",
        "scenarios",
        "verification_plan",
        "cases",
        "automation",
        "change_document",
        "release",
    }
    assert image["baselines"][0]["metric_snapshot_count"] == len(image["metric_snapshots"])
    assert {
        overlay["field_path"]
        for overlay in image["overlays"]
        if overlay["object_id"] == us_id and overlay["status"] == "candidate"
    } >= {
        "quality_loop.scenarios",
        "quality_loop.verification_plan",
        "quality_loop.cases",
        "quality_loop.automation",
        "quality_loop.change_document",
        "quality_loop.release",
    }

    restored_store = InMemoryStore()
    restored_image = restored_store.get_system_image(project["id"])
    assert any(
        metric.us_id == us_id and metric.metrics.get("quality_loop_step") == "release"
        for metric in restored_image.metric_snapshots
    )
    restored_workspace = restored_store.get_project_workspace(project["id"])
    assert restored_workspace.quality_asset_pack is not None
    assert restored_workspace.quality_asset_pack.status == "completed"
    assert restored_workspace.execution_evidence
    assert restored_workspace.release_decision is None


def test_full_quality_loop_prompt_mentions_release_without_skipping_assets():
    project, _, workspace = create_project_with_materialized_system_image("Release Mention Full Loop Project")
    us_id = workspace["us_items"][0]["id"]
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": (
                "Complete the end-to-end quality loop for the riskiest open US through release readiness. "
                f"Target environment: {TEST_TARGET_BASE_URL}"
            )
        },
    )

    assert response.status_code == 200
    goal_id = response.json()["agent_goal"]["id"]
    wait_until(lambda: len(client.get(f"/v1/tool-invocations?agent_goal_id={goal_id}").json()) >= 8)
    trace = client.get(f"/v1/tool-invocations?agent_goal_id={goal_id}").json()
    assert [item["tool_id"] for item in trace] == [
        "quality.scope.generate",
        "quality.scenario.generate",
        "quality.plan.generate",
        "quality.case.generate",
        "automation.generate",
        "run.start",
        "quality.change-doc.generate",
        "release.assess",
    ]
    completed_workspace = client.get(f"/v1/projects/{project['id']}/workspaces/{us_id}").json()
    assert completed_workspace["quality_loop_state"]["status"] == "ready_for_release"


def test_project_workspace_selects_latest_quality_context_us():
    project, conversation, workspace = create_project_with_materialized_system_image("Multi US Quality Context")
    first_us_id = workspace["us_items"][0]["id"]
    second_us_id = f"{first_us_id}_followup"
    second_us = USItem(
        id=second_us_id,
        title="Follow-up checkout risk US",
        owner="QA Lead",
        status="analysis",
        risk="medium",
        progress=12,
        next_action="Generate scenarios",
    )
    us_items = store.quality_loop_repository.list_us_items(project["id"])
    us_items.append(second_us)
    store.project_repository.replace_us_items(
        project["id"],
        workspace["current_version_id"] or None,
        us_items,
    )
    rematerialized = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "system_image.context.materialize",
            "input": {
                "project_id": project["id"],
                "version_id": workspace["current_version_id"],
            },
        },
    )
    assert rematerialized.status_code == 200
    assert rematerialized.json()["status"] == "completed"
    assert any(
        context.us_id == second_us_id
        for context in store.system_image_repository.list_task_contexts(project["id"])
    )

    for tool_id, tool_input in [
        ("quality.scope.generate", {}),
        ("quality.scenario.generate", {}),
        ("quality.plan.generate", {}),
        ("quality.case.generate", {}),
        ("automation.generate", {}),
        ("run.start", {"base_url": TEST_TARGET_BASE_URL}),
        ("quality.change-doc.generate", {}),
        ("release.assess", {}),
    ]:
        response = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": {
                    "project_id": project["id"],
                    "us_id": second_us_id,
                    **tool_input,
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    project_workspace = client.get(f"/v1/projects/{project['id']}").json()
    assert project_workspace["quality_loop_state"]["status"] == "ready_for_release"
    assert project_workspace["quality_asset_pack"]["us_id"] == second_us_id
    assert project_workspace["release_decision"] is None
    assert {lane["label"]: lane["status"] for lane in project_workspace["asset_lanes"]} == {
        "Scenarios": "approved",
        "Verification Plan": "approved",
        "Cases": "approved",
        "Automation": "completed",
        "Change Document": "completed",
        "Release Assessment": "completed",
    }


def test_run_start_failed_runner_result_creates_report_and_blocks_release():
    project, conversation, workspace = create_project_with_materialized_system_image("Runner Failure Project")
    us_id = workspace["us_items"][0]["id"]

    for tool_id in ["quality.scenario.generate", "quality.case.generate"]:
        response = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": {"project_id": project["id"], "us_id": us_id},
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    automation = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "automation.generate",
            "input": {"project_id": project["id"], "us_id": us_id},
        },
    )

    assert automation.status_code == 200
    automation_body = automation.json()
    assert automation_body["status"] == "completed"
    assert not any(ref.startswith("run:") for ref in automation_body["result"]["object_refs"])
    assert automation_body["result"]["next_recommended_tools"] == ["run.start"]

    execution = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "run.start",
            "input": {
                "project_id": project["id"],
                "us_id": us_id,
                "base_url": TEST_TARGET_BASE_URL,
                "runner_result": {
                    "status": "failed",
                    "runner_job_id": "runner_job_checkout_failed",
                    "failure_summary": "Checkout confirm selector changed after redirect.",
                    "timeline": [
                        "Loaded the current versioned automation asset.",
                        "Submitted job to web runner.",
                        "Runner detected selector drift after redirect.",
                    ],
                    "evidence": [
                        f"script://run_{us_id}_automation",
                        f"trace://run_{us_id}_automation",
                        f"screenshot://run_{us_id}_automation/redirect",
                        f"failure_artifact://run_{us_id}_automation",
                    ],
                },
            },
        },
    )

    assert execution.status_code == 200
    execution_body = execution.json()
    assert execution_body["status"] == "completed"
    assert any(ref.startswith("failure_report:") for ref in execution_body["result"]["object_refs"])
    assert "healing.propose" in execution_body["result"]["next_recommended_tools"]

    run_id = next(ref.split(":", 1)[1] for ref in execution_body["result"]["object_refs"] if ref.startswith("run:"))
    run_detail = client.get(f"/v1/projects/{project['id']}/runs/{run_id}").json()
    assert run_detail["status"] == "failed"
    assert run_detail["runner_job_id"] == "runner_job_checkout_failed"
    assert run_detail["task_context_id"]
    assert run_detail["healing_status"] == "under_review"
    assert run_detail["healing_depth"] == 0
    assert run_detail["last_failure_fingerprint"]

    completed_workspace = client.get(f"/v1/projects/{project['id']}").json()
    reports = completed_workspace["failure_reports"]
    assert len(reports) == 1
    assert reports[0]["status"] == "under_review"
    assert reports[0]["healing_attempt_count"] == 0
    assert reports[0]["failure_fingerprint"] == run_detail["last_failure_fingerprint"]
    assert any(item["evidence_type"] == "failure_artifact" for item in completed_workspace["execution_evidence"])
    assert all(
        item["storage_ref"].startswith(("local-object://", "s3://"))
        for item in completed_workspace["execution_evidence"]
    )
    automation_part = next(
        part for part in completed_workspace["quality_asset_pack"]["parts"] if part["part_type"] == "automation_blueprint"
    )
    assert automation_part["status"] == "blocked"

    release_assessment = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "release.assess",
            "input": {"project_id": project["id"], "us_id": us_id},
        },
    )
    assert release_assessment.status_code == 200
    assert release_assessment.json()["status"] == "completed"

    release = client.get(f"/v1/projects/{project['id']}/release-readiness").json()
    assert release["status"] == "Blocked by failure analysis"
    assert release["blockers"] == 1
    assert release["score"] <= 59
    assert release["evidence_summary"]["open_failures"] == 1
    assert release["evidence_summary"]["passed_runs"] == 0
    blocked_workspace = client.get(f"/v1/projects/{project['id']}").json()
    assert blocked_workspace["release_decision"] is None

    restored_workspace = InMemoryStore().get_project_workspace(project["id"])
    assert restored_workspace.runs[0].status == "failed"
    restored_run = InMemoryStore().get_run_detail(project["id"], run_id)
    assert restored_run.runner_job_id == "runner_job_checkout_failed"
    assert restored_run.last_failure_fingerprint == reports[0]["failure_fingerprint"]


def test_run_start_fails_closed_without_persisted_automation_asset():
    project, conversation, workspace = create_project_with_materialized_system_image(
        "Run Requires Asset Project"
    )
    us_id = workspace["us_items"][0]["id"]

    response = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "run.start",
            "input": {
                "project_id": project["id"],
                "us_id": us_id,
                "base_url": TEST_TARGET_BASE_URL,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "requires a generated automation blueprint" in body["result"]["summary"]
    assert body["result"]["next_recommended_tools"] == ["automation.generate"]
    assert client.get(f"/v1/projects/{project['id']}/runs").json() == []


def test_run_start_executes_persisted_asset_and_rejects_client_step_injection():
    project, conversation, workspace = create_project_with_materialized_system_image(
        "Run Uses Persisted Asset Project"
    )
    us_id = workspace["us_items"][0]["id"]
    for tool_id in [
        "quality.scenario.generate",
        "quality.case.generate",
        "automation.generate",
    ]:
        generated = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": {"project_id": project["id"], "us_id": us_id},
            },
        )
        assert generated.status_code == 200
        assert generated.json()["status"] == "completed"

    pack = store.quality_loop_repository.get_quality_asset_pack(
        project["id"], us_id
    )
    assert pack is not None
    automation_part = next(
        part for part in pack.parts if part.part_type == "automation_blueprint"
    )
    persisted_steps = automation_part.structured_content["scripts"][0]["steps"]
    expected_steps = [
        {key: value for key, value in step.items() if value is not None}
        for step in persisted_steps
    ]
    captured: dict = {}
    original_execute = store.run_orchestrator.execute_automation

    def capture_execute(project_id, selected_us_id, *, invocation_input):
        captured.update(invocation_input)
        return original_execute(
            project_id,
            selected_us_id,
            invocation_input=invocation_input,
        )

    with patch.object(
        store.run_orchestrator,
        "execute_automation",
        new=capture_execute,
    ):
        response = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": "run.start",
                "input": {
                    "project_id": project["id"],
                    "us_id": us_id,
                    "base_url": TEST_TARGET_BASE_URL,
                    "runner_request": {
                        "base_url": "http://untrusted.example.test",
                        "steps": [{"action": "shell", "value": "rm -rf /"}],
                    },
                    "runner_result": {
                        "status": "passed",
                        "runner_job_id": "persisted_asset_job",
                    },
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert captured["runner_request"]["steps"] == expected_steps
    assert all(
        value is not None
        for step in captured["runner_request"]["steps"]
        for value in step.values()
    )
    assert not any(step.get("action") == "shell" for step in captured["runner_request"]["steps"])
    assert captured["runner_request"]["base_url"] == TEST_TARGET_BASE_URL
    assert captured["runner_request"]["automation_asset_ref"] == (
        f"quality_asset_part:{automation_part.id}:revision:{automation_part.revision}"
    )


def test_run_retry_replays_persisted_context_without_mutating_asset_revision():
    project, conversation, workspace = create_project_with_materialized_system_image(
        "Run Retry Context Project"
    )
    us_id = workspace["us_items"][0]["id"]
    for tool_id in [
        "quality.scenario.generate",
        "quality.case.generate",
        "automation.generate",
    ]:
        generated = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": tool_id,
                "input": {"project_id": project["id"], "us_id": us_id},
            },
        )
        assert generated.status_code == 200
        assert generated.json()["status"] == "completed"

    started = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "run.start",
            "input": {
                "project_id": project["id"],
                "us_id": us_id,
                "base_url": TEST_TARGET_BASE_URL,
                "runner_result": {
                    "status": "passed",
                    "runner_job_id": "initial_retry_source",
                },
            },
        },
    )
    assert started.status_code == 200
    assert started.json()["status"] == "completed"
    source_run = store.quality_loop_repository.list_run_details(project["id"])[0]
    pack_before = store.quality_loop_repository.get_quality_asset_pack(
        project["id"], us_id
    )
    assert pack_before is not None
    revision_before = pack_before.current_revision

    captured: dict = {}
    original_execute = store.run_orchestrator.execute_automation

    def capture_retry(project_id, selected_us_id, *, invocation_input):
        captured.update(invocation_input)
        return original_execute(
            project_id,
            selected_us_id,
            invocation_input=invocation_input,
        )

    with patch.object(
        store.run_orchestrator,
        "execute_automation",
        new=capture_retry,
    ):
        retried = client.post(
            "/v1/tool-invocations",
            json={
                "conversation_id": conversation["id"],
                "tool_id": "run.retry",
                "input": {
                    "project_id": project["id"],
                    "us_id": us_id,
                    "run_id": source_run.id,
                    "base_url": "http://untrusted.example.test",
                    "runner_request": {
                        "steps": [{"action": "shell", "value": "rm -rf /"}],
                    },
                    "runner_result": {
                        "status": "passed",
                        "runner_job_id": "retry_job",
                    },
                },
            },
        )

    assert retried.status_code == 200
    retry_body = retried.json()
    assert retry_body["status"] == "completed", retry_body.get("result", {}).get("summary")
    request = captured["runner_request"]
    assert request["base_url"] == source_run.target_base_url
    assert request["steps"] == source_run.execution_plan
    assert request["automation_asset_ref"] == source_run.automation_asset_ref
    assert request["automation_script_id"] == source_run.automation_script_id
    assert request["retry_of_run_id"] == source_run.id
    assert request["attempt"] == 2
    assert not any(step.get("action") == "shell" for step in request["steps"])

    runs = store.quality_loop_repository.list_run_details(project["id"])
    retry_run = next(item for item in runs if item.retry_of_run_id == source_run.id)
    assert retry_run.attempt == 2
    assert retry_run.target_base_url == source_run.target_base_url
    assert retry_run.execution_plan == source_run.execution_plan
    pack_after = store.quality_loop_repository.get_quality_asset_pack(
        project["id"], us_id
    )
    assert pack_after is not None
    assert pack_after.current_revision == revision_before


def test_failed_run_creates_failure_report_and_falls_back_to_human_after_healing_limit():
    from apps.api.app.models import RunDetail

    project, conversation, workspace = create_project_with_materialized_system_image("Failure Loop Project")
    us_id = workspace["us_items"][0]["id"]
    run = RunDetail(
        id=f"run_{us_id}_failed_selector",
        status="failed",
        channel="web_runner",
        title="Checkout confirmation regression",
        summary="Selector assertion failed after checkout redirect.",
        started_at="2026-06-19 12:00",
        timeline=[
            "Generated browser automation from approved cases.",
            "Executed checkout confirmation path.",
            "Detected selector assertion mismatch after redirect.",
            "Captured trace, screenshot, and log evidence.",
        ],
        evidence=[
            f"trace://run_{us_id}_failed_selector",
            f"screenshot://run_{us_id}_failed_selector/step-4",
            f"log://run_{us_id}_failed_selector",
        ],
        failure_summary="Selector assertion failed after checkout redirect.",
        healing_status="not_started",
    )
    store.project_repository.replace_runs(project["id"], [run])

    analyzed = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "failure.analyze",
            "input": {"project_id": project["id"], "us_id": us_id, "run_id": run.id},
        },
    )
    assert analyzed.status_code == 200
    assert analyzed.json()["status"] == "completed"
    assert any(ref.startswith("failure_report:") for ref in analyzed.json()["result"]["object_refs"])

    first_healing = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "healing.propose",
            "input": {"project_id": project["id"], "us_id": us_id, "run_id": run.id},
        },
    ).json()
    assert first_healing["status"] == "completed"

    second_healing = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "healing.propose",
            "input": {"project_id": project["id"], "us_id": us_id, "run_id": run.id},
        },
    ).json()
    assert second_healing["status"] == "completed"

    release_assessment = client.post(
        "/v1/tool-invocations",
        json={
            "conversation_id": conversation["id"],
            "tool_id": "release.assess",
            "input": {"project_id": project["id"], "us_id": us_id},
        },
    ).json()
    assert release_assessment["status"] == "completed"

    completed_workspace = client.get(f"/v1/projects/{project['id']}").json()
    reports = completed_workspace["failure_reports"]
    assert len(reports) == 1
    assert reports[0]["status"] == "fallback_to_human"
    assert reports[0]["healing_attempt_count"] == 2
    assert reports[0]["fallback_to_human"] is True
    assert reports[0]["evidence_refs"]
    assert completed_workspace["release_decision"] is None
    release = client.get(f"/v1/projects/{project['id']}/release-readiness").json()
    assert release["status"] == "Blocked by failure analysis"
    assert release["blockers"] == 1

    run_detail = client.get(f"/v1/projects/{project['id']}/runs/{run.id}").json()
    assert run_detail["healing_status"] == "fallback_to_human"

    restored_workspace = InMemoryStore().get_project_workspace(project["id"])
    assert restored_workspace.failure_reports
    assert restored_workspace.failure_reports[0].status == "fallback_to_human"
    assert restored_workspace.failure_reports[0].healing_attempt_count == 2
    assert restored_workspace.release_decision is None


def test_agent_goal_interrupt_and_resume_update_conversation_snapshot():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_123", "title": "US-123 Workspace"},
    ).json()

    created = client.post(
        "/v1/agent-goals",
        json={
            "conversation_id": conversation["id"],
            "title": "Manual quality review",
            "summary": "A manually managed agent goal used to verify lifecycle controls.",
            "steps": [
                {
                    "id": "step_manual_approval",
                    "title": "Request manual quality approval",
                    "status": "pending",
                    "phase": "acting",
                    "selected_tool_id": "approval.request",
                    "tool_input_payload": {"purpose": "manual_quality_review"},
                }
            ],
        },
    )
    assert created.status_code == 200
    goal_id = created.json()["id"]
    wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"]) >= 1)

    paused = client.post(f"/v1/agent-goals/{goal_id}/interrupt")
    assert paused.status_code == 200
    wait_until(
        lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused"
    )

    resumed = client.post(f"/v1/agent-goals/{goal_id}/resume")
    assert resumed.status_code == 200
    wait_until(
        lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"]
        == "completed"
    )


def test_workspace_asset_lane_updates_are_persisted_across_store_restart():
    project, _, workspace = create_project_with_materialized_system_image("Restartable Quality Loop")
    us_id = workspace["us_items"][0]["id"]
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": us_id, "title": f"{us_id} Workspace"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": (
                f"Complete the quality loop for this US against {TEST_TARGET_BASE_URL}"
            )
        },
    )
    assert response.status_code == 200

    def release_lane_persisted() -> bool:
        current_workspace = client.get(f"/v1/projects/{project['id']}/workspaces/{us_id}").json()
        release = next((lane for lane in current_workspace["asset_lanes"] if lane["label"] == "Release Assessment"), None)
        return release is not None and release["status"] == "completed"

    wait_until(release_lane_persisted, timeout=6)

    restored_store = InMemoryStore()
    restored_lanes = (
        restored_store.quality_loop_repository.list_asset_lanes_for_us(us_id)
    )
    scenarios = next(lane for lane in restored_lanes if lane.label == "Scenarios")
    cases = next(lane for lane in restored_lanes if lane.label == "Cases")
    automation = next(lane for lane in restored_lanes if lane.label == "Automation")
    release = next(lane for lane in restored_lanes if lane.label == "Release Assessment")
    assert scenarios.status == "approved"
    assert "risk-based test scenarios" in scenarios.summary
    assert cases.status == "approved"
    assert automation.status == "completed"
    assert release.status == "completed"


def test_project_message_can_create_version():
    project = client.post("/v1/projects", json={"name": "Versioned Project"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": "Project Overview"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": 'Create version branch "2026.Q3" for this project'},
    )
    assert response.status_code == 200
    wait_until(
        lambda: any(
            version["name"] == "2026.Q3"
            for version in client.get(f"/v1/projects/{project['id']}/versions").json()
        )
    )
    versions = client.get(f"/v1/projects/{project['id']}/versions").json()
    assert any(version["name"] == "2026.Q3" for version in versions)


def test_dashboard_message_returns_portfolio_summary():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "dashboard", "space_id": "dashboard", "title": "Dashboard"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Show me the current testing progress across the portfolio"},
    )
    assert response.status_code == 200
    wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["messages"]) >= 2)
    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
    assistant_messages = [message for message in refreshed["messages"] if message["role"] == "assistant"]
    assert any("active projects" in block["text"] for message in assistant_messages for block in message["blocks"])


def test_dashboard_query_routes_through_query_tool_plan():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "dashboard", "space_id": "dashboard", "title": "Dashboard"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "What is the current testing progress across the portfolio?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "tool_invocations" in body
    assert body["tool_invocations"][0]["tool_id"] == "query.dashboard.progress"


def test_workspace_status_query_routes_through_workspace_query_tool():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_123", "title": "US-123 Workspace"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "What is the current workspace status?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "tool_invocations" in body
    assert body["tool_invocations"][0]["tool_id"] == "query.workspace.status"


def test_direct_conversation_answer_is_persisted_as_query_answer_tool_invocation():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "build", "space_id": "build", "title": "Build"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Hello Nasus"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_invocation"]["tool_id"] == "query.answer"
    assert body["tool_invocation"]["status"] == "completed"

    invocation_id = body["tool_invocation"]["id"]
    persisted = client.get(f"/v1/tool-invocations/{invocation_id}")
    assert persisted.status_code == 200
    assert persisted.json()["tool_id"] == "query.answer"
    assert persisted.json()["input_payload"]["user_message"] == "Hello Nasus"

    audit = client.get(f"/v1/audit-events?tool_invocation_id={invocation_id}").json()
    assert {"tool.invocation.created", "tool.invocation.completed"}.issubset({event["action"] for event in audit})
    assert all(event["conversation_id"] == conversation["id"] for event in audit)

    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
    assistant_messages = [message for message in refreshed["messages"] if message["role"] == "assistant"]
    assert assistant_messages[-1]["metadata"]["planner_kind"] == "direct_answer"


def test_dashboard_message_uses_current_model_preset_metadata():
    original = client.get("/v1/settings").json()
    client.post("/v1/settings/model-configs/chat/use-system-default")
    current_settings = client.get("/v1/settings").json()

    try:
        conversation = client.post(
            "/v1/conversations",
            json={"space_type": "dashboard", "space_id": "dashboard", "title": "Dashboard"},
        ).json()

        response = client.post(
            f"/v1/conversations/{conversation['id']}/messages",
            json={"content": "Show me the current testing progress across the portfolio"},
        )
        assert response.status_code == 200
        wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["messages"]) >= 2)
        refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
        assistant_messages = [message for message in refreshed["messages"] if message["role"] == "assistant"]
        last_message = assistant_messages[-1]
        assert last_message["metadata"]["settings_preset"] == "system_default"
        assert last_message["metadata"]["llm_provider"] == current_settings["model_provider"]
        assert last_message["metadata"]["llm_mode"] in {"fallback", "live"}
    finally:
        restore_model_route(original, "chat")


def test_conversation_can_be_archived_and_searched():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "dashboard", "space_id": "dashboard", "title": "Delivery Watch"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Show me the riskiest project and blocked versions"},
    )
    assert response.status_code == 200

    archived = client.patch(
        f"/v1/conversations/{conversation['id']}/archive",
        json={"archive": True},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    search = client.get("/v1/conversations/search", params={"q": "riskiest project"})
    assert search.status_code == 200
    assert any(item["conversation_id"] == conversation["id"] for item in search.json()["message_hits"])


def test_conversation_merge_moves_messages_into_target():
    source = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_124", "title": "Refund Workspace"},
    ).json()
    target = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_123", "title": "Checkout Workspace"},
    ).json()

    post_source = client.post(
        f"/v1/conversations/{source['id']}/messages",
        json={"content": "What is the current workspace status for refund status timeline?"},
    )
    assert post_source.status_code == 200
    wait_until(lambda: len(client.get(f"/v1/conversations/{source['id']}").json()["messages"]) >= 2)

    merged = client.post(
        f"/v1/conversations/{source['id']}/merge",
        json={"target_conversation_id": target["id"]},
    )
    assert merged.status_code == 200
    merged_body = merged.json()
    assert merged_body["target_conversation_id"] == target["id"]
    link_id = merged_body["link"]["id"]

    refreshed_source = client.get(f"/v1/conversations/{source['id']}").json()
    refreshed_target = client.get(f"/v1/conversations/{target['id']}").json()
    assert refreshed_source["status"] == "merged"
    assert refreshed_source["merged_into_conversation_id"] == target["id"]
    assert len(refreshed_target["messages"]) >= 2
    assert any(
        link.id == link_id
        for link in store.conversation_repository.load_conversation_links()
    )

    restored_link = next(
        link
        for link in ConversationRepository().load_conversation_links()
        if link.id == link_id
    )
    assert restored_link.left_conversation_id == source["id"]
    assert restored_link.right_conversation_id == target["id"]


def test_conversation_messages_are_persisted_across_store_restart():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "dashboard", "space_id": "dashboard", "title": "Dashboard"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Show me the current testing progress across the portfolio"},
    )
    assert response.status_code == 200
    wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["messages"]) >= 2)

    restored_store = InMemoryStore()
    restored = restored_store.get_conversation(conversation["id"])
    assert len(restored.messages) >= 2
    assert any(message.role == "assistant" for message in restored.messages)


def test_agent_conversation_reads_postgresql_without_process_local_projection():
    conversation = client.post(
        "/v1/conversations",
        json={
            "space_type": "documentation",
            "space_id": "durable-agent-read",
            "title": "Durable Agent Read",
        },
    ).json()

    response = client.get(f"/v1/conversations/{conversation['id']}")

    assert response.status_code == 200
    assert response.json()["title"] == "Durable Agent Read"
    assert not hasattr(store, "conversations")
    restored = ConversationRepository().get_conversation(conversation["id"])
    assert restored is not None
    assert restored.title == "Durable Agent Read"


def test_conversation_summary_checkpoint_is_created_and_persisted():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_123", "title": "US-123 Workspace"},
    ).json()

    prompts = [
        "Summarize the current workspace risk",
        "What is the current workspace status?",
        "What should we do after this status check?",
        "Give me a concise delivery recommendation",
    ]
    for prompt in prompts:
        response = client.post(
            f"/v1/conversations/{conversation['id']}/messages",
            json={"content": prompt},
        )
        assert response.status_code == 200

    wait_until(
        lambda: client.get(f"/v1/conversations/{conversation['id']}").json().get("latest_summary_checkpoint_id") is not None
    )

    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
    assert refreshed["latest_summary_checkpoint_id"] is not None

    restored_store = InMemoryStore()
    restored = restored_store.get_conversation(conversation["id"])
    assert restored.latest_summary_checkpoint_id is not None
    checkpoint = next(
        checkpoint
        for checkpoint in ConversationRepository().load_summary_checkpoints()
        if checkpoint.id == restored.latest_summary_checkpoint_id
    )
    assert checkpoint.summary_text
    assert checkpoint.message_range_end is not None


def test_agent_memory_checkpoint_can_be_created_explicitly_for_system_image_goal():
    project = client.post("/v1/projects", json={"name": "Manual Memory Checkpoint"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Build the official system image from code, US docs, and tests"},
    )
    assert response.status_code == 200
    goal_id = response.json()["agent_goal"]["id"]
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")

    checkpoint = client.post(
        "/v1/agent-memory/checkpoints",
        json={"agent_goal_id": goal_id, "created_by": "user"},
    )
    assert checkpoint.status_code == 200
    checkpoint_body = checkpoint.json()
    assert checkpoint_body["conversation_id"] == conversation["id"]
    assert checkpoint_body["created_by"] == "user"
    assert "Build the official system image" in checkpoint_body["summary_text"]

    memory = client.get(f"/v1/agent-memory/context?agent_goal_id={goal_id}").json()
    assert memory["checkpoint_count"] >= 1
    assert memory["conversation_memory"]["latest_summary_checkpoint_id"] == checkpoint_body["id"]

    restored_store = InMemoryStore()
    restored = restored_store.get_conversation(conversation["id"])
    assert restored.latest_summary_checkpoint_id == checkpoint_body["id"]
    assert any(
        checkpoint.id == checkpoint_body["id"] and checkpoint.summary_text
        for checkpoint in ConversationRepository().load_summary_checkpoints()
    )


def test_llm_generate_reply_receives_conversation_history_snapshot():
    original = client.get("/v1/settings").json()

    try:
        save_tested_model_config(
            display_name="Memory-aware model",
            provider_kind="openai_compatible",
            base_url="https://api.example.com/v1",
            model_name="memory-aware-model",
            api_key="sk-memory-9999",
        )

        conversation = client.post(
            "/v1/conversations",
            json={"space_type": "dashboard", "space_id": "dashboard", "title": "Dashboard"},
        ).json()

        first = client.post(
            f"/v1/conversations/{conversation['id']}/messages",
            json={"content": "Show me the current testing progress across the portfolio"},
        )
        assert first.status_code == 200
        wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["messages"]) >= 2)

        captured: dict[str, str] = {}

        async def fake_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
            captured["history_snapshot"] = history_snapshot
            return "Memory-aware response."

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Which project is riskiest right now?"},
            )

        assert response.status_code == 200
        wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["messages"]) >= 4)
        assert "Show me the current testing progress across the portfolio" in captured["history_snapshot"]
        assert "Recent turns:" in captured["history_snapshot"]
    finally:
        restore_model_route(original, "chat")


def test_detail_endpoints_return_seeded_project_data():
    knowledge = client.get("/v1/projects/proj_payment/knowledge")
    assert knowledge.status_code == 200
    assert knowledge.json()[0]["id"] == "OBJ-CHECKOUT"

    knowledge_detail = client.get("/v1/projects/proj_payment/knowledge/OBJ-CHECKOUT")
    assert knowledge_detail.status_code == 200
    assert knowledge_detail.json()["name"] == "Checkout Flow"

    run_detail = client.get("/v1/projects/proj_payment/runs/run_9021")
    assert run_detail.status_code == 200
    assert "checkout confirm selector changed" in run_detail.json()["failure_summary"]

    approval_detail = client.get("/v1/projects/proj_payment/approvals/approval_442")
    assert approval_detail.status_code == 200
    assert "Version Shared promotion" in approval_detail.json()["policy_reason"]

    release = client.get("/v1/projects/proj_payment/release-readiness")
    assert release.status_code == 200
    assert release.json()["status"] == "Conditionally Ready"


def test_documentation_endpoint_returns_seeded_entries():
    response = client.get("/v1/documentation")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 3
    assert {item["title"] for item in payload} >= {"Getting Started", "Quality Asset Pack"}


def test_event_outbox_persists_ordered_events_and_replays_from_cursor():
    suffix = str(time.time_ns())
    conversation_id = f"conv_outbox_{suffix}"
    entity_id = f"goal_outbox_{suffix}"
    repository = EventOutboxRepository()

    def event(index: int) -> EventPayload:
        return EventPayload(
            event_id=f"evt_outbox_{suffix}_{index}",
            event_type="agent.goal.updated",
            occurred_at="2026-07-28T00:00:00+00:00",
            correlation_id=entity_id,
            conversation_id=conversation_id,
            agent_goal_id=entity_id,
            entity_type="agent_goal",
            entity_id=entity_id,
            entity_version=0,
            mutation_kind="patch",
            patch={"steps_completed": index},
            query_keys=[["conversation", conversation_id], ["agent-goal", entity_id]],
        )

    first = repository.append(event(1))
    second = repository.append(event(2))

    assert first.entity_version > 0
    assert second.entity_version > first.entity_version
    assert [
        item.event_id
        for item in EventOutboxRepository().list_after(
            stream_kind="conversation",
            stream_id=conversation_id,
            after_event_id=None,
        )
    ] == [first.event_id, second.event_id]
    replay = EventOutboxRepository().list_after(
        stream_kind="conversation",
        stream_id=conversation_id,
        after_event_id=first.event_id,
    )
    assert [item.event_id for item in replay] == [second.event_id]
    assert repository.latest_entity_version(
        entity_type="agent_goal",
        entity_id=entity_id,
    ) == second.entity_version


def test_sse_encoding_exposes_reconnect_cursor_event_name_and_heartbeat():
    event = EventPayload(
        event_id="evt_encoding",
        event_type="tool.invocation.updated",
        occurred_at="2026-07-28T00:00:00+00:00",
        correlation_id="inv_encoding",
        conversation_id="conv_encoding",
        tool_invocation_id="inv_encoding",
        entity_type="tool_invocation",
        entity_id="inv_encoding",
        entity_version=7,
        mutation_kind="patch",
        patch={"status": "running"},
    )

    encoded = encode_event(event)
    assert encoded.startswith("id: evt_encoding\nevent: tool.invocation.updated\n")
    assert '"entity_version":7' in encoded
    assert encoded.endswith("\n\n")
    assert encode_heartbeat() == ": heartbeat\n\n"
