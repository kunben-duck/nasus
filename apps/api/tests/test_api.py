import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

STATE_DIR = tempfile.mkdtemp(prefix="nasus-api-tests-")
os.environ["NASUS_STATE_DIR"] = STATE_DIR

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.conversation_orchestrator import ConversationOrchestrator
from apps.api.app.store import InMemoryStore, store


client = TestClient(app)


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


def test_model_routes_can_be_configured_independently():
    original = client.get("/v1/settings").json()
    profiles = original["model_profiles"]
    if profiles["embedding"]["custom_model"]["has_api_key"] or profiles["rerank"]["custom_model"]["has_api_key"]:
        return

    try:
        embedding_response = client.patch(
            "/v1/settings",
            json={
                "model_route": "embedding",
                "model_preset": "custom",
                "custom_provider_kind": "openai_compatible",
                "custom_base_url": "https://vectors.example.com/v1",
                "custom_model_name": "embed-large",
                "custom_api_key": "sk-embedding-1111",
            },
        )
        assert embedding_response.status_code == 200
        embedding_body = embedding_response.json()
        assert embedding_body["model_preset"] == original["model_preset"]
        assert embedding_body["model_profiles"]["chat"]["model_preset"] == original["model_preset"]
        assert embedding_body["model_profiles"]["embedding"]["model_preset"] == "custom"
        assert embedding_body["model_profiles"]["embedding"]["model_provider"] == "openai_compatible"
        assert embedding_body["model_profiles"]["embedding"]["custom_model"]["base_url"] == "https://vectors.example.com/v1"
        assert embedding_body["model_profiles"]["embedding"]["custom_model"]["model_name"] == "embed-large"
        assert embedding_body["model_profiles"]["embedding"]["custom_model"]["api_key_masked"] == "••••1111"

        rerank_response = client.patch(
            "/v1/settings",
            json={
                "model_route": "rerank",
                "model_preset": "custom",
                "custom_provider_kind": "openai_compatible",
                "custom_base_url": "https://rank.example.com/v1",
                "custom_model_name": "rerank-v1",
                "custom_api_key": "sk-rerank-2222",
            },
        )
        assert rerank_response.status_code == 200
        rerank_body = rerank_response.json()
        assert rerank_body["model_profiles"]["embedding"]["custom_model"]["model_name"] == "embed-large"
        assert rerank_body["model_profiles"]["rerank"]["model_preset"] == "custom"
        assert rerank_body["model_profiles"]["rerank"]["custom_model"]["api_key_masked"] == "••••2222"

        persisted_db = Path(STATE_DIR) / "nasus.db"
        assert b"sk-embedding-1111" not in persisted_db.read_bytes()
        assert b"sk-rerank-2222" not in persisted_db.read_bytes()
    finally:
        for route in ("embedding", "rerank"):
            profile = profiles[route]
            custom = profile["custom_model"]
            client.patch(
                "/v1/settings",
                json={
                    "model_route": route,
                    "model_preset": profile["model_preset"],
                    "custom_provider_kind": custom["provider_kind"],
                    "custom_base_url": custom["base_url"],
                    "custom_model_name": custom["model_name"],
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


def test_tool_catalog_exposes_system_image_tool_chain():
    response = client.get("/v1/tools/catalog")
    assert response.status_code == 200
    tool_ids = {tool["tool_id"] for tool in response.json()}
    assert {
        "system_image.sources.register",
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    }.issubset(tool_ids)
    assert "baseline.initialize" not in tool_ids


def test_agent_service_uses_workflow_runtime_port():
    assert store.agent_workflow_runtime.runtime_kind == "local"
    assert store.agent_service.runtime is store.agent_workflow_runtime
    assert store.agent_loop_runtime.graph_kind == "local"
    assert store.agent_loop_runtime.graph_runtime.steps_for_proposal is not None


def test_agent_workflow_runtime_factory_builds_default_temporal_gateway():
    from apps.api.app.agent_workflow_runtime import build_agent_workflow_runtime

    runtime = build_agent_workflow_runtime(store.agent_loop_runtime, runtime_kind="temporal")
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
    from apps.api.app.agent_runtime_config import TemporalGatewayConfig
    from apps.api.app.agent_runtime_models import AgentGoalProposal, ToolPlanStep
    from apps.api.app.agent_goal_state_machine import AgentGoalRuntimeCheckpoint
    from apps.api.app.temporal_agent_gateway import TemporalClientWorkflowGateway

    class FakeTemporalHandle:
        def __init__(self) -> None:
            self.signals = []

        async def query(self, query, *args):
            assert query == "current_goal"
            return {
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

        async def signal(self, signal, *args):
            self.signals.append((signal, args))

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

    goal = asyncio.run(gateway.start_goal("conv_temporal", proposal))
    assert goal.id == "goal_temporal"
    assert goal.workflow_id == fake_client.started["id"]
    assert [item.id for item in sunk_goals] == ["goal_temporal"]
    assert fake_client.started["workflow"] == "NasusAgentGoalWorkflow"
    assert fake_client.started["task_queue"] == "agent-task-queue"
    start_payload = fake_client.started["args"][0]
    assert start_payload["conversation_id"] == "conv_temporal"
    assert start_payload["proposal"]["planned_tools"][0]["tool_id"] == "system_image.sources.register"

    resumed = asyncio.run(gateway.resume_goal("goal_temporal"))
    assert resumed.id == "goal_temporal"
    assert fake_client.requested_workflow_id == "nasus-agent-goal-existing"
    assert fake_client.handle.signals == [("resume_goal", ({"goal_id": "goal_temporal"},))]
    assert [item.id for item in sunk_goals] == ["goal_temporal", "goal_temporal"]


def test_agent_goal_workflow_activity_service_uses_agent_loop_runtime_directly():
    from apps.api.app.agent_goal_workflow_worker import AgentGoalWorkflowActivityService
    from apps.api.app.models import AgentGoal

    class FakeConversationRepository:
        def __init__(self) -> None:
            self.upserted_goal_ids = []

        def upsert_goal(self, goal):
            self.upserted_goal_ids.append(goal.id)

    class FakeAgentLoopRuntime:
        def __init__(self) -> None:
            self.started = None
            self.resumed = None

        async def start_goal(self, conversation_id, proposal):
            self.started = (conversation_id, proposal)
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
                workflow_id=None,
            )

        async def resume_goal(self, goal_id):
            self.resumed = goal_id
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

    class FakeStore:
        def __init__(self) -> None:
            self.agent_loop_runtime = FakeAgentLoopRuntime()
            self.conversation_repository = FakeConversationRepository()
            self.conversation_goal_updates = []

        def _upsert_goal_in_conversation(self, goal):
            self.conversation_goal_updates.append(goal.id)

    fake_store = FakeStore()
    service = AgentGoalWorkflowActivityService(store_provider=lambda: fake_store)
    payload = {
        "conversation_id": "conv_worker",
        "workflow_id": "temporal-wf-worker",
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
    conversation_id, proposal = fake_store.agent_loop_runtime.started
    assert conversation_id == "conv_worker"
    assert proposal.planned_tools[0].tool_id == "system_image.sources.register"
    assert proposal.planned_tools[0].input_payload == {"project_id": "proj_worker"}
    assert started["workflow_id"] == "temporal-wf-worker"
    assert fake_store.conversation_repository.upserted_goal_ids == ["goal_worker"]
    assert fake_store.conversation_goal_updates == ["goal_worker"]

    resumed = asyncio.run(service.resume_agent_goal({"goal_id": "goal_worker"}))
    assert resumed["status"] == "completed"
    assert fake_store.agent_loop_runtime.resumed == "goal_worker"


def test_agent_graph_runtime_factory_builds_default_langgraph_gateway():
    from apps.api.app.agent_graph_runtime import build_agent_graph_runtime

    runtime = build_agent_graph_runtime(store, store.agent_loop_runtime.state_machine, graph_kind="langgraph")
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
        store,
        store.agent_loop_runtime.state_machine,
        graph_kind="langgraph",
        langgraph_gateway=FakeLangGraphGateway(),
    )
    assert runtime.graph_kind == "langgraph"
    assert runtime.steps_for_proposal(object()) == []


def test_tool_invocation_runtime_is_canonical_store_entry_for_gated_tools():
    assert store.tool_invocation_runtime.tool_definition("system_image.baseline.initialize").confirmation_mode == "user_confirm"
    assert store.tool_invocation_runtime.handlers.resolve("system_image.baseline.initialize") is not None
    assert store.tool_invocation_runtime.handlers.resolve("quality.scenario.generate") is not None
    assert store.tool_invocation_runtime.handlers.resolve("query.system_image.status") is not None

    project = client.post("/v1/projects", json={"name": "Runtime Gate Project"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
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
    gated_audit = client.get(f"/v1/audit-events?tool_invocation_id={body['id']}").json()
    gated_actions = {event["action"] for event in gated_audit}
    assert {"tool.invocation.created", "tool.invocation.gated"}.issubset(gated_actions)
    assert all(event["tool_invocation_id"] == body["id"] for event in gated_audit)

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


def test_created_project_has_draft_system_image_and_can_initialize_via_tool():
    project = client.post("/v1/projects", json={"name": "System Image Long Term"}).json()

    draft = client.get(f"/v1/projects/{project['id']}/system-image")
    assert draft.status_code == 200
    draft_body = draft.json()
    assert draft_body["project"]["system_image_status"] == "draft"
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
    wait_until(lambda: client.get(f"/v1/tool-invocations/{invocation_id}").json()["status"] == "completed")

    ready = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert ready["project"]["system_image_status"] == "ready"
    assert all(source["ingestion_status"] == "indexed" for source in ready["sources"])
    assert ready["baselines"][0]["status"] == "ready"
    assert len(ready["objects"]) >= 3
    assert len(ready["metric_snapshots"]) == 4


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
    assert sources["code"]["source_uri"] == str(code_dir)
    assert sources["us_doc"]["source_uri"] == str(us_dir)
    assert sources["test_asset"]["source_uri"] == str(tests_dir)
    assert all(source["ingestion_status"] == "indexed" for source in sources.values())
    assert all(source["content_hash"].startswith("sha256:") for source in sources.values())
    assert any("file:checkout.py" in ref for ref in sources["code"]["evidence_refs"])
    assert any("file:US-101.md" in ref for ref in sources["us_doc"]["evidence_refs"])
    assert any("file:test_checkout.py" in ref for ref in sources["test_asset"]["evidence_refs"])

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
    object_names = {item["name"] for item in materialized_image["objects"]}
    object_types = {item["type"] for item in materialized_image["objects"]}
    relationship_types = {item["relationship_type"] for item in materialized_image["relationships"]}
    metrics_by_group = {item["metric_group"]: item["metrics"] for item in materialized_image["metric_snapshots"]}
    assert any("checkout" in name for name in object_names)
    assert any("US-101" in name for name in object_names)
    assert any("test_checkout" in name for name in object_names)
    assert {"CodeFunction", "USWorkItem", "TestCase"}.issubset(object_types)
    assert {"implements", "impacts", "covers"}.issubset(relationship_types)
    assert metrics_by_group["code_quality"]["code_symbols"] >= 1
    assert metrics_by_group["us_completion_quality"]["requirements_count"] >= 1
    assert metrics_by_group["test_quality"]["test_count"] >= 1

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
    assert len(ready_image["relationships"]) == len(materialized_image["relationships"])
    assert len(ready_image["metric_snapshots"]) == len(materialized_image["metric_snapshots"])
    assert any("checkout" in item["name"] for item in ready_image["objects"])


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

    memory = store.agent_memory.build_context(store.get_conversation(conversation["id"]))
    assert "[system_image]" in memory.context_snapshot
    assert "source=code; status=indexed" in memory.context_snapshot
    assert "context_object=" in memory.context_snapshot
    assert "relationship=implements" in memory.context_snapshot
    assert "metric=code_quality" in memory.context_snapshot
    assert "User: What does the image know about checkout?" in memory.history_snapshot
    assert memory.recent_turn_count >= 1


def test_agent_goal_think_step_records_memory_context_package():
    from apps.api.app.agent_runtime_models import AgentGoalProposal

    project = client.post("/v1/projects", json={"name": "Think Memory Package"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()
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
    assert think_step["memory_recent_turn_count"] >= 1
    assert "system_image.sources.register" in think_step["available_tool_ids"]
    assert "Memory context includes" in think_step["reasoning"]


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
        client.patch(
            "/v1/settings",
            json={
                "model_preset": "custom",
                "custom_provider_kind": "openai_compatible",
                "custom_base_url": "https://api.example.com/v1",
                "custom_model_name": "planner-memory-model",
                "custom_api_key": "sk-planner-memory",
            },
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


def test_system_image_ingest_failure_blocks_context_materialization():
    project = client.post("/v1/projects", json={"name": "Broken Source Ingestion"}).json()
    source_root = Path(tempfile.mkdtemp(prefix="nasus-broken-source-"))
    missing_code = source_root / "missing-code"
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
                "source_specs": [{"source_type": "code", "source_uri": str(missing_code)}],
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
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")
    refreshed = client.get(f"/v1/conversations/{conversation['id']}").json()
    goal = refreshed["agent_goals"][-1]
    assert goal["pause_reason"] == "missing_source_binding"
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

    code_dir, us_dir, tests_dir = create_system_image_source_dirs("nasus-guided-system-image-")
    source_binding = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": system_image_source_prompt(code_dir, us_dir, tests_dir)},
    )
    assert source_binding.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["pause_reason"] == "waiting_confirmation")
    goal = client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]
    resume = client.post(f"/v1/agent-goals/{goal['id']}/resume")
    assert resume.status_code == 200
    wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "completed")

    image = client.get(f"/v1/projects/{project['id']}/system-image").json()
    assert image["project"]["system_image_status"] == "ready"
    assert all(source["ingestion_status"] == "indexed" for source in image["sources"])


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
    assert not any(
        invocation.input_payload.get("agent_goal_id") == goal.id
        for invocation in store.tool_invocations.values()
    )
    audit_actions = {event.action for event in store.list_audit_events(agent_goal_id=goal.id)}
    assert "agent.goal.budget_exhausted" in audit_actions


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
        item for item in store.agent_swarms.values()
        if item.parent_goal_id == goal["id"] and item.swarm_kind == "ingestion"
    )
    assert swarm.status == "completed"
    assert swarm.result_summary.startswith("Merged 3 source-specific candidates")
    assert {assignment.status for assignment in swarm.assignments} == {"completed"}
    assert {assignment.target_refs[-1] for assignment in swarm.assignments} == {
        "source_type:code",
        "source_type:us_doc",
        "source_type:test_asset",
    }
    fetched_swarm = client.get(f"/v1/agent-swarms/{swarm.id}")
    assert fetched_swarm.status_code == 200
    assert fetched_swarm.json()["id"] == swarm.id
    assert len(fetched_swarm.json()["assignments"]) == 3
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
    assert restored_store.get_agent_swarm(swarm.id).status == "completed"


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


def test_live_llm_structured_planner_can_drive_system_image_goal():
    original = client.get("/v1/settings").json()
    project = client.post("/v1/projects", json={"name": "LLM Planner System Image"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": project["id"], "title": project["name"]},
    ).json()

    try:
        client.patch(
            "/v1/settings",
            json={
                "model_preset": "custom",
                "custom_provider_kind": "openai_compatible",
                "custom_base_url": "https://api.example.com/v1",
                "custom_model_name": "planner-model",
                "custom_api_key": "sk-planner-9999",
            },
        )

        async def fake_call_custom(*, custom_model, custom_api_key, system_prompt, user_message, context_snapshot, history_snapshot):
            assert "Nasus structured agent planner" in system_prompt
            assert "system_image.sources.register" in context_snapshot
            return json.dumps(
                {
                    "kind": "agent_goal",
                    "goal_template": "system_image_build",
                    "title": "LLM Planned System Image Build",
                    "summary": "Build a system image using the structured planner.",
                    "goal_description": "Register, ingest, materialize, and initialize the project baseline.",
                    "steps": [
                        {
                            "tool_id": "system_image.sources.register",
                            "input": {"project_id": project["id"]},
                            "reason": "Register source groups.",
                        },
                        {
                            "tool_id": "system_image.sources.ingest",
                            "input": {"project_id": project["id"]},
                            "reason": "Ingest source evidence.",
                        },
                        {
                            "tool_id": "system_image.context.materialize",
                            "input": {"project_id": project["id"]},
                            "reason": "Materialize context.",
                        },
                        {
                            "tool_id": "system_image.baseline.initialize",
                            "input": {"project_id": project["id"]},
                            "reason": "Initialize baseline after governance confirmation.",
                        },
                    ],
                    "target_refs": [f"project:{project['id']}"],
                    "query_keys": [["project", project["id"]], ["system-image", project["id"]]],
                    "kickoff_message": "I will build this system image using the structured planner.",
                }
            )

        with patch.object(store.llm, "_call_custom", new=fake_call_custom):
            response = client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                json={"content": "Plan and build the official system image"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["agent_goal"]["title"] == "LLM Planned System Image Build"
        wait_until(lambda: client.get(f"/v1/conversations/{conversation['id']}").json()["agent_goals"][-1]["status"] == "paused")
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


def test_project_quality_loop_request_selects_first_us_and_generates_scenarios():
    conversation = client.post(
        "/v1/conversations",
        json={"space_type": "project", "space_id": "proj_payment", "title": "Payment System"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Continue the quality loop and generate scenarios for the riskiest open US"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent_goal"]["title"].startswith("Advance quality loop")

    def scenario_lane_persisted() -> bool:
        workspace = client.get("/v1/projects/proj_payment/workspaces/us_123").json()
        scenarios = next((lane for lane in workspace["asset_lanes"] if lane["id"] == "lane_scenarios"), None)
        return scenarios is not None and scenarios["status"] == "approved"

    wait_until(scenario_lane_persisted)


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
    assert restored_store.conversation_summary_checkpoints[checkpoint_body["id"]].summary_text


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
