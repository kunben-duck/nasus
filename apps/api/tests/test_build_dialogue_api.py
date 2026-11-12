"""Build chat uses real tools, persistence and source bytes, not a canned success."""
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest

from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_natural_build_entries_api import send
from apps.api.tests.test_agent_investigation_continuation import replace_graph
from apps.api.app.application.agent.build_dialogue_inputs import STATE_KEY


def draft(conversation):
    return next(message["metadata"][STATE_KEY] for message in reversed(conversation["messages"])
        if STATE_KEY in message["metadata"])


def start(v):
    v["conversation"] = v["client"].post("/v1/conversations", headers=v["headers"], json={
        "space_type": "build", "space_id": "build-" + uuid4().hex, "title": "Guided build",
    })
    assert v["conversation"].status_code == 200


def legacy_tool(v, tool, payload):
    result = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": tool, "input": payload,
    })
    assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    return result.json()


def legacy_project(v, name="Legacy build"):
    return legacy_tool(v, "project.create", {"name": name})["result"]["object_refs"][0].removeprefix("project:")


def test_legacy_project_setup_resumes_intake_without_creating_another_project(evidence_api):
    v = evidence_api
    start(v)
    project = legacy_project(v)
    status = send(v, "系统画像是不是已经构建完成了")
    assert status["project_id"] == project
    assert status["messages"][-1]["metadata"]["system_image_status"]["status"] == "source_required"
    assert "代码来源" in status["messages"][-1]["blocks"][0]["text"]
    assert not status["agent_goals"]
    sources = send(v, f"代码路径 {v['path']}")
    assert draft(sources)["project_id"] == project and draft(sources)["stage"] == "sources"
    send(v, "跳过可选资料")
    prepared = send(v, "确认接入并构建")
    assert prepared["agent_goals"][0]["pause_reason"] == "waiting_confirmation"
    assert sum(item["tool_id"] == "project.create" for item in prepared["tool_invocations"]) == 1


def test_legacy_captured_sources_continue_without_recapture_or_implicit_consent(evidence_api):
    v = evidence_api
    start(v)
    project = legacy_project(v)
    legacy_tool(v, "system_image.sources.register", {"project_id": project,
        "source_specs": [{"source_type": "code", "source_uri": str(v["path"])}]})
    legacy_tool(v, "system_image.sources.ingest", {"project_id": project})
    status = send(v, "系统画像是不是已经构建完成了")
    assert status["messages"][-1]["metadata"]["system_image_status"]["status"] == "not_built"
    assert not status["agent_goals"] and len(status["tool_invocations"]) == 3
    prepared = send(v, "继续构建")
    goal = prepared["agent_goals"][0]
    assert goal["project_id"] == project and goal["pause_reason"] == "waiting_confirmation"
    queried = send(v, "系统画像构建到哪一步了？")
    assert queried["agent_goals"][0] == goal
    assert len(queried["tool_invocations"]) == len(prepared["tool_invocations"])
    built = send(v, "确认")
    assert built["agent_goals"][0]["pause_reason"] == "structural_candidate_review"
    for tool in ("project.create", "system_image.sources.register", "system_image.sources.ingest"):
        assert sum(item["tool_id"] == tool for item in built["tool_invocations"]) == 1


def test_legacy_registered_sources_need_explicit_capture_before_build(evidence_api):
    v = evidence_api
    start(v)
    project = legacy_project(v)
    legacy_tool(v, "system_image.sources.register", {"project_id": project,
        "source_specs": [{"source_type": "code", "source_uri": str(v["path"])}]})
    status = send(v, "系统画像是不是已经构建完成了")
    assert status["messages"][-1]["metadata"]["system_image_status"]["status"] == "sources_pending"
    assert len(status["tool_invocations"]) == 2 and not status["agent_goals"]
    prepared = send(v, "确认采集已有资料")
    assert prepared["agent_goals"][0]["pause_reason"] == "waiting_confirmation"
    for tool in ("project.create", "system_image.sources.register", "system_image.sources.ingest"):
        assert sum(item["tool_id"] == tool for item in prepared["tool_invocations"]) == 1


def test_legacy_candidate_restores_verified_context_among_multiple_created_projects(evidence_api):
    from apps.api.app.infrastructure.persistence.db_models import ConversationMessageRecord
    from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
    v = evidence_api
    start(v)
    legacy_project(v, "Other draft")
    project = legacy_project(v, "Actual image")
    legacy_tool(v, "system_image.sources.register", {"project_id": project,
        "source_specs": [{"source_type": "code", "source_uri": str(v["path"])}]})
    receipt = legacy_tool(v, "system_image.sources.ingest", {"project_id": project})
    legacy_tool(v, "system_image.context.materialize", {"project_id": project})
    chat_id = v["conversation"].json()["id"]
    with session_scope() as session:
        # Old goal-completion messages have canonical tool/object references but
        # the Build conversation itself was left unbound.
        session.add(ConversationMessageRecord(id="legacy_" + uuid4().hex, conversation_id=chat_id,
            role="assistant", status="completed", content_type="text", created_at="2026-01-01T00:00:00Z",
            blocks=[{"type": "text", "text": "Project task completed."}], message_metadata={},
            object_refs=[f"project:{project}"], tool_refs=[f"tool_invocation:{receipt['id']}"]))
    status = send(v, "系统画像是不是已经构建完成了")
    assert status["project_id"] == project and draft(status)["stage"] == "existing"
    observed = status["messages"][-1]["metadata"]["system_image_status"]
    assert observed["status"] == "candidate" and "尚未正式发布" in observed["summary"]
    assert "Use a direct build request" not in status["messages"][-1]["blocks"][0]["text"]
    assert len(status["tool_invocations"]) == 5 and not status["agent_goals"]
    continued = send(v, "继续分析")
    assert continued["messages"][-1]["metadata"]["system_image_status"]["next_action"] == "review"
    assert len(continued["tool_invocations"]) == 5
    assert v["client"].get(f"/v1/conversations/{chat_id}", headers=v["member_headers"]).status_code == 403


def test_ambiguous_legacy_projects_require_selection_not_another_creation(evidence_api):
    v = evidence_api
    start(v)
    first = legacy_project(v, "First")
    legacy_project(v, "Second")
    question = send(v, "系统画像是不是已经构建完成了")
    assert question["project_id"] is None and not question["agent_goals"]
    assert question["messages"][-1]["metadata"]["planner_kind"] == "build_project_selection"
    selected = send(v, f"选择项目 {first}")
    assert selected["project_id"] == first and len(selected["tool_invocations"]) == 2


def test_concurrent_build_open_reuses_one_private_conversation(evidence_api):
    v = evidence_api
    payload = {"space_type": "build", "space_id": "build-" + uuid4().hex, "title": "Build"}
    barrier = Barrier(4)

    def open_chat(_):
        barrier.wait(timeout=10)
        response = v["client"].post("/v1/conversations", headers=v["headers"], json=payload)
        assert response.status_code == 200, response.text
        return response.json()["id"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(open_chat, range(4)))
    assert len(set(ids)) == 1
    rows = v["client"].get("/v1/conversations?space_type=build", headers=v["headers"]).json()
    assert len([row for row in rows if row["space_id"] == payload["space_id"]]) == 1


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_guided_build_creates_project_captures_real_code_and_retains_goal(evidence_api, monkeypatch, graph_kind):
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    start(v)
    first = send(v, "帮我构建一个系统画像")
    assert draft(first)["stage"] == "name" and first["project_id"] is None
    assert not first["agent_goals"]
    assert len([message for message in first["messages"] if STATE_KEY in message["metadata"]]) == 1
    named = send(v, "项目叫 对话试用")
    state = draft(named)
    assert state["stage"] == "sources" and named["project_id"] == state["project_id"]
    project_id = state["project_id"]
    assert project_id != v["project_id"]
    assert len([item for item in named["tool_invocations"] if item["tool_id"] == "project.create"]) == 1
    source = send(v, f"代码路径 {v['path']}")
    assert draft(source)["code"] == str(v["path"])
    review = send(v, "跳过可选资料")
    assert draft(review)["stage"] == "review"
    assert not review["agent_goals"]
    prepared = send(v, "确认接入并构建")
    assert draft(prepared)["stage"] == "building", prepared
    goal = prepared["agent_goals"][0]
    assert goal["pause_reason"] == "waiting_confirmation", goal
    assert goal["project_id"] == project_id
    image = v["client"].get(f"/v1/projects/{project_id}/system-image", headers=v["headers"]).json()
    assert any(item["status"] == "captured" for item in image["source_manifest"]["members"])
    # Questions and negated confirmation must not consume execution consent.
    for question in ("当前系统画像构建到哪一步了", "确认之前请告诉我预算", "不要确认", "do not proceed"):
        result = send(v, question)
        assert result["agent_goals"][0]["id"] == goal["id"]
        assert result["agent_goals"][0]["pause_reason"] == "waiting_confirmation"
    built = send(v, "确认")
    assert built["agent_goals"][0]["pause_reason"] == "structural_candidate_review", built
    assert built["agent_goals"][0]["id"] == goal["id"]
    replace_graph(monkeypatch, graph_kind)
    investigate = send(v, "继续分析")
    assert investigate["agent_goals"][0]["pause_reason"] == "waiting_confirmation"
    final = send(v, "确认")
    assert final["agent_goals"][0]["pause_reason"] == "build_completion_review", final
    assert all(step["status"] == "completed" for step in final["agent_goals"][0]["steps"] if step["phase"] == "acting")
    assert len(final["agent_goals"]) == 1
    replay = send(v, "当前系统画像是否已经完成构建")
    assert len(replay["tool_invocations"]) == len(final["tool_invocations"])
    # The user's original Build chat survives reload without switching projects.
    reloaded = v["client"].get(f"/v1/conversations/{built['id']}", headers=v["headers"]).json()
    assert draft(reloaded)["project_id"] == project_id
    assert reloaded["agent_goals"][0]["id"] == goal["id"]
    reopened = v["client"].post("/v1/conversations", headers=v["headers"], json={
        "space_type": "build", "space_id": built["space_id"], "title": "Build",
    })
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["id"] == built["id"]
    assert v["client"].get(f"/v1/conversations/{built['id']}", headers=v["member_headers"]).status_code == 403


def test_missing_code_never_starts_a_build(evidence_api):
    v = evidence_api
    start(v)
    send(v, "帮我构建系统画像")
    send(v, "项目叫 Missing Code")
    result = send(v, "跳过可选资料")
    assert draft(result)["stage"] == "sources"
    result = send(v, "确认接入并构建")
    assert not result["agent_goals"]
    assert not any(item["tool_id"] == "system_image.sources.ingest" for item in result["tool_invocations"])


def test_chat_uploads_optional_sources_and_keeps_failed_capture_recoverable(evidence_api):
    v = evidence_api
    start(v)
    named = send(v, "帮我构建系统画像，项目叫 Source intake retry")
    project_id = named["project_id"]
    assert project_id
    for kind, label, filename, content in (
        ("us_doc", "需求文档地址", "US.md", b"# US-1\nSubmit an order."),
        ("test_asset", "测试资产地址", "cases.csv", b"id,title\nTC-1,Submit order\n"),
    ):
        uploaded = v["client"].post(f"/v1/projects/{project_id}/source-files", headers=v["headers"],
            data={"source_type": kind}, files=[("files", (filename, content, "text/plain"))])
        assert uploaded.status_code == 200, uploaded.text
        send(v, f"{label} {uploaded.json()['source_uri']}")
    missing = v['path'].parent / 'missing.py'
    review = send(v, f"代码路径 {missing}")
    assert draft(review)["stage"] == "review"
    failed = send(v, "确认接入并构建")
    assert not failed["agent_goals"]
    assert draft(failed)["stage"] == "review"
    assert draft(failed)["revision"] > draft(review)["revision"]
    changed = send(v, f"代码路径 {v['path']}")
    assert draft(changed)["code"] == str(missing)
    missing.write_text("def submit_order():\n    return 'accepted'\n")
    prepared = send(v, "确认接入并构建")
    assert prepared["agent_goals"][0]["pause_reason"] == "waiting_confirmation", prepared
    image = v["client"].get(f"/v1/projects/{project_id}/system-image?view=working", headers=v["headers"]).json()
    assert {member["source_type"] for member in image["source_manifest"]["members"] if member["status"] == "captured"} == {"code", "us_doc", "test_asset"}
    assert len([item for item in prepared["tool_invocations"] if item["tool_id"] == "project.create"]) == 1
