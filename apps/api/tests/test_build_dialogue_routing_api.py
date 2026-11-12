"""A saved Build flow must not capture every later conversation turn."""
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_build_dialogue_api import start, legacy_project, legacy_tool, draft
from apps.api.tests.test_natural_build_entries_api import send


def answer(conversation):
    return "\n".join(block.get("text") or "" for block in conversation["messages"][-1]["blocks"])


def test_candidate_followups_can_switch_topics_and_return_to_image_status(evidence_api):
    v = evidence_api
    start(v)
    project = legacy_project(v, "Conversation routing project")
    legacy_tool(v, "system_image.sources.register", {"project_id": project,
        "source_specs": [{"source_type": "code", "source_uri": str(v["path"])}]})
    legacy_tool(v, "system_image.sources.ingest", {"project_id": project})
    legacy_tool(v, "system_image.context.materialize", {"project_id": project})
    status = send(v, "系统画像是不是已经构建完成了")
    assert status["messages"][-1]["metadata"]["system_image_status"]["status"] == "candidate"
    before = draft(status)

    unsupported = send(v, "删除当前所有的项目")
    assert "尚未实现项目删除" in answer(unsupported) and "未执行删除" in answer(unsupported)
    assert unsupported["messages"][-1]["metadata"]["clarification_kind"] == "capability_unavailable:project.delete"
    assert draft(unsupported) == before and unsupported["tool_invocations"] == status["tool_invocations"]

    named = send(v, "当前项目名称是什么")
    assert answer(named) == "当前项目名称是 **Conversation routing project**。"
    assert named["messages"][-1]["metadata"]["planner_kind"] == "project_identity"
    assert len(named["tool_invocations"]) == len(status["tool_invocations"])

    general = send(v, "介绍一下你能做什么")
    assert general["messages"][-1]["metadata"]["tool_id"] == "query.answer"
    assert "结构候选画像已生成" not in answer(general)
    assert draft(general) == before and general["project_id"] == project and not general["agent_goals"]
    history = send(v, "查看执行记录")
    assert "system_image.sources.ingest" in answer(history) and "结构候选画像已生成" not in answer(history)
    status_again = send(v, "系统画像是不是已经构建完成了")
    assert status_again["messages"][-1]["metadata"]["system_image_status"]["status"] == "candidate"
    assert draft(status_again) == before
    assert len(status_again["tool_invocations"]) == len(status["tool_invocations"]) + 1


def test_side_questions_preserve_intake_and_pending_build_confirmation(evidence_api):
    v = evidence_api
    start(v)
    send(v, "帮我构建系统画像")
    unnamed = send(v, "当前项目名称是什么")
    assert "还没有创建项目" in answer(unnamed)
    assert not unnamed["tool_invocations"] and draft(unnamed)["stage"] == "name"
    named = send(v, "项目叫 Context preserved")
    project = named["project_id"]
    for question in ("当前项目名称是什么", "介绍一下你能做什么"):
        result = send(v, question)
        assert draft(result) == draft(named) and result["project_id"] == project
        assert "Git 仓库地址" not in answer(result)
    send(v, f"代码路径 {v['path']}")
    send(v, "跳过可选资料")
    prepared = send(v, "确认接入并构建")
    goal = prepared["agent_goals"][0]
    assert goal["pause_reason"] == "waiting_confirmation"
    for question in ("当前项目名称是什么", "介绍一下你能做什么", "确认按钮的作用是什么", "确认接入并构建", "确认删除所有项目"):
        result = send(v, question)
        assert result["agent_goals"][0] == goal and draft(result) == draft(prepared)
    continued = send(v, "确认")
    assert continued["agent_goals"][0]["id"] == goal["id"]
    assert continued["agent_goals"][0]["pause_reason"] == "structural_candidate_review"
    assert sum(tool["tool_id"] == "project.create" for tool in continued["tool_invocations"]) == 1


def test_delete_request_cannot_become_a_new_project_during_name_intake(evidence_api):
    v = evidence_api
    start(v)
    before = send(v, "帮我构建系统画像")
    result = send(v, "删除当前所有的项目")
    assert "尚未实现项目删除" in answer(result) and "未执行删除" in answer(result)
    assert draft(result) == draft(before) and result["project_id"] is None
    assert not result["tool_invocations"] and not result["agent_goals"]
    project = v["client"].get(f"/v1/projects/{v['project_id']}", headers=v["headers"])
    assert project.status_code == 200 and project.json()["project"]["id"] == v["project_id"]
