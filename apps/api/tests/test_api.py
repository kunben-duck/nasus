import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

STATE_DIR = tempfile.mkdtemp(prefix="nasus-api-tests-")
os.environ["NASUS_STATE_DIR"] = STATE_DIR

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.store import InMemoryStore, store


client = TestClient(app)


def wait_until(predicate, timeout: float = 1.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition was not met before timeout")


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
    if original["custom_model"]["has_api_key"]:
        return

    try:
        response = client.patch(
            "/v1/settings",
            json={
                "model_preset": "custom",
                "custom_provider_kind": "openai_compatible",
                "custom_base_url": "https://api.example.com/v1",
                "custom_model_name": "example-model",
                "custom_api_key": "sk-custom-1234",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["model_preset"] == "custom"
        assert body["model_provider"] == "openai_compatible"
        assert body["custom_model"]["provider_kind"] == "openai_compatible"
        assert body["custom_model"]["base_url"] == "https://api.example.com/v1"
        assert body["custom_model"]["model_name"] == "example-model"
        assert body["custom_model"]["has_api_key"] is True
        assert body["custom_model"]["api_key_masked"] == "••••1234"
        assert body["runtime_mode"] == "live"
        assert body["active_provider_status"]["provider"] == "openai_compatible"
    finally:
        client.patch(
            "/v1/settings",
            json={
                "language": original["language"],
                "theme": original["theme"],
                "model_preset": original["model_preset"],
                "notification_mode": original["notification_mode"],
                "custom_provider_kind": original["custom_model"]["provider_kind"],
                "custom_base_url": original["custom_model"]["base_url"],
                "custom_model_name": original["custom_model"]["model_name"],
                "custom_api_key": "",
            },
        )


def test_model_config_is_persisted_and_api_key_is_encrypted_at_rest():
    original = client.get("/v1/settings").json()

    try:
        response = client.patch(
            "/v1/settings",
            json={
                "model_preset": "custom",
                "custom_provider_kind": "anthropic",
                "custom_model_name": "claude-custom",
                "custom_api_key": "sk-persisted-5678",
            },
        )
        assert response.status_code == 200

        persisted_db = Path(STATE_DIR) / "nasus.db"
        assert persisted_db.exists()
        assert b"sk-persisted-5678" not in persisted_db.read_bytes()

        restored_store = InMemoryStore()
        restored = restored_store.get_settings()
        assert restored.model_preset == "custom"
        assert restored.model_provider == "anthropic"
        assert restored.custom_model.model_name == "claude-custom"
        assert restored.custom_model.has_api_key is True
        assert restored.custom_model.api_key_masked == "••••5678"
        assert restored_store.custom_model_api_key_encrypted
    finally:
        client.patch(
            "/v1/settings",
            json={
                "language": original["language"],
                "theme": original["theme"],
                "model_preset": original["model_preset"],
                "notification_mode": original["notification_mode"],
                "custom_provider_kind": original["custom_model"]["provider_kind"],
                "custom_base_url": original["custom_model"]["base_url"],
                "custom_model_name": original["custom_model"]["model_name"],
                "custom_api_key": "",
            },
        )


def test_settings_connection_uses_current_saved_configuration():
    original = client.get("/v1/settings").json()

    try:
        client.patch(
            "/v1/settings",
            json={
                "model_preset": "custom",
                "custom_provider_kind": "openai_compatible",
                "custom_base_url": "https://api.example.com/v1",
                "custom_model_name": "connectivity-model",
                "custom_api_key": "sk-live-9999",
            },
        )

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
    finally:
        client.patch(
            "/v1/settings",
            json={
                "language": original["language"],
                "theme": original["theme"],
                "model_preset": original["model_preset"],
                "notification_mode": original["notification_mode"],
                "custom_provider_kind": original["custom_model"]["provider_kind"],
                "custom_base_url": original["custom_model"]["base_url"],
                "custom_model_name": original["custom_model"]["model_name"],
                "custom_api_key": "",
            },
        )


def test_settings_connection_help_endpoint_is_human_readable():
    response = client.get("/v1/settings/test-connection")
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "POST"
    assert "Use POST /v1/settings/test-connection" in body["message"]
    assert body["current_model_preset"] in {"system_default", "custom"}


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


def test_project_and_version_are_persisted_across_store_restart():
    project = client.post("/v1/projects", json={"name": "Persistent Project"}).json()
    version = client.post(f"/v1/projects/{project['id']}/versions", json={"name": "2026.Q4"}).json()

    restored_store = InMemoryStore()
    restored_projects = restored_store.list_projects()
    assert any(item.name == "Persistent Project" for item in restored_projects)
    assert any(item.name == "2026.Q4" for item in restored_store.versions[project["id"]])
    assert version["id"] in {item.id for item in restored_store.versions[project["id"]]}
    assert restored_store.release_readiness[version["id"]].status == "Draft"


def test_workspace_message_generates_agent_goal():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_123", "title": "US-123 Workspace"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Generate scenarios for this US"},
    )
    assert response.status_code == 200
    wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"]) == 1)
    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
    assert refreshed["agent_goals"][0]["status"] in {"running", "completed"}


def test_workspace_quality_loop_request_creates_agent_goal_proposal_and_runtime_goal():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_123", "title": "US-123 Workspace"},
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


def test_agent_goal_interrupt_and_resume_update_conversation_snapshot():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_123", "title": "US-123 Workspace"},
    ).json()

    created = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Help me complete the quality loop for this US"},
    )
    assert created.status_code == 200
    goal_id = created.json()["agent_goal"]["id"]
    wait_until(lambda: len(client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"]) >= 1)

    paused = client.post(f"/v1/agent-goals/{goal_id}/interrupt")
    assert paused.status_code == 200
    wait_until(
        lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused"
    )

    resumed = client.post(f"/v1/agent-goals/{goal_id}/resume")
    assert resumed.status_code == 200
    wait_until(
        lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "running"
    )


def test_workspace_asset_lane_updates_are_persisted_across_store_restart():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_123", "title": "US-123 Workspace"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Generate scenarios for this US"},
    )
    assert response.status_code == 200

    def scenario_lane_persisted() -> bool:
        workspace = client.get("/v1/projects/proj_payment/workspaces/us_123").json()
        scenarios = next((lane for lane in workspace["asset_lanes"] if lane["id"] == "lane_scenarios"), None)
        return scenarios is not None and scenarios["status"] == "approved"

    wait_until(scenario_lane_persisted)

    restored_store = InMemoryStore()
    restored_lanes = restored_store.asset_lanes["us_123"]
    scenarios = next(lane for lane in restored_lanes if lane.id == "lane_scenarios")
    cases = next(lane for lane in restored_lanes if lane.id == "lane_cases")
    assert scenarios.status == "approved"
    assert "8 scenarios grouped" in scenarios.summary
    assert cases.status == "ready_for_review"


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


def test_dashboard_message_uses_current_model_preset_metadata():
    original = client.get("/v1/settings").json()
    client.patch("/v1/settings", json={"model_preset": "system_default"})
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
        client.patch(
            "/v1/settings",
            json={
                "language": original["language"],
                "theme": original["theme"],
                "model_preset": original["model_preset"],
                "notification_mode": original["notification_mode"],
            },
        )


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
        json={"content": "Generate scenarios for refund status timeline"},
    )
    assert post_source.status_code == 200
    wait_until(lambda: len(client.get(f"/v1/conversations/{source['id']}").json()["messages"]) >= 2)

    merged = client.post(
        f"/v1/conversations/{source['id']}/merge",
        json={"target_conversation_id": target["id"]},
    )
    assert merged.status_code == 200
    assert merged.json()["target_conversation_id"] == target["id"]

    refreshed_source = client.get(f"/v1/conversations/{source['id']}").json()
    refreshed_target = client.get(f"/v1/conversations/{target['id']}").json()
    assert refreshed_source["status"] == "merged"
    assert refreshed_source["merged_into_conversation_id"] == target["id"]
    assert len(refreshed_target["messages"]) >= 2


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


def test_conversation_summary_checkpoint_is_created_and_persisted():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "workspace", "space_id": "us_123", "title": "US-123 Workspace"},
    ).json()

    prompts = [
        "Summarize the current quality risk",
        "Generate scenarios for this US",
        "What should we do after scenarios?",
        "Give me a concise execution recommendation",
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
    checkpoint = restored_store.conversation_summary_checkpoints[restored.latest_summary_checkpoint_id]
    assert checkpoint.summary_text
    assert checkpoint.message_range_end is not None


def test_llm_generate_reply_receives_conversation_history_snapshot():
    original = client.get("/v1/settings").json()

    try:
        client.patch(
            "/v1/settings",
            json={
                "model_preset": "custom",
                "custom_provider_kind": "openai_compatible",
                "custom_base_url": "https://api.example.com/v1",
                "custom_model_name": "memory-aware-model",
                "custom_api_key": "sk-memory-9999",
            },
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
        client.patch(
            "/v1/settings",
            json={
                "language": original["language"],
                "theme": original["theme"],
                "model_preset": original["model_preset"],
                "notification_mode": original["notification_mode"],
                "custom_provider_kind": original["custom_model"]["provider_kind"],
                "custom_base_url": original["custom_model"]["base_url"],
                "custom_model_name": original["custom_model"]["model_name"],
                "custom_api_key": "",
            },
        )


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
