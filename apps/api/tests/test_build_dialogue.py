from types import SimpleNamespace
import asyncio

import pytest

from apps.api.app.application.agent.build_dialogue_inputs import (
    BuildIntake, BuildIntakeExtractor, is_build_request, is_intake_confirmation, validate_fields,
)
from apps.api.app.application.agent.build_dialogue_recovery import recoverable_project, image_status
from apps.api.app.application.agent.system_image_status_queries import is_build_status_question
from apps.api.app.application.agent.build_dialogue import GuidedBuildConversation
from apps.api.app.application.agent.build_dialogue_routing import is_project_name_question
from apps.api.app.application.agent.messages import ConversationMessageApplicationService
from apps.api.app.domain.agent.runtime_models import OrchestratorDecision, DirectAnswer
from unittest.mock import AsyncMock, Mock


def dialogue_fixture(stage, *, goal_status="paused"):
    state = BuildIntake(stage=stage, locale="zh", project_id=None if stage == "name" else "project",
        project_name="" if stage == "name" else "Old cached name", goal_id="goal" if stage == "building" else None)
    saved = state.model_dump(mode="json")
    conversation = SimpleNamespace(id="chat", space_type="build", project_id=state.project_id,
        messages=[SimpleNamespace(role="assistant", metadata={"system_image_intake": saved}, object_refs=[], tool_refs=[])], tool_invocations=[],
        agent_goals=[SimpleNamespace(id="goal", goal_template="system_image_build", project_id="project",
            status=goal_status, pause_reason=None)] if stage == "building" else [])
    runtime = Mock()
    runtime.get_conversation.return_value = conversation
    runtime.append_message = AsyncMock(return_value=SimpleNamespace(id="reply"))
    runtime.active_goal_for_conversation.return_value = None
    runtime.is_confirmation_message.return_value = False
    runtime.plan_message = AsyncMock(return_value=OrchestratorDecision(kind="direct_answer",
        direct_answer=DirectAnswer(fallback_text="Normal answer", query_keys=[["conversation", "chat"]])))
    extractor = BuildIntakeExtractor(llm=None, settings=lambda: SimpleNamespace(runtime_mode="fallback"), secret=None, memory=None)
    snapshots = Mock()
    guide = GuidedBuildConversation(runtime=runtime, conversations=Mock(), build_entries=Mock(), extractor=extractor,
        snapshots=snapshots, revisions=Mock(), project_reader=Mock(return_value=SimpleNamespace(name="Actual project")))
    return guide, runtime, conversation, saved, snapshots


@pytest.mark.parametrize("stage", ["name", "sources", "review", "existing", "building"])
@pytest.mark.parametrize("question", ["你好", "介绍一下你能做什么", "质量闭环进度怎么样", "解释一下候选画像和正式基线的区别", "确认按钮的作用是什么"])
def test_off_topic_turns_reach_planner_without_changing_build_state(stage, question):
    guide, runtime, conversation, saved, snapshots = dialogue_fixture(stage, goal_status="completed")
    runtime.is_confirmation_message.return_value = "确认" in question
    messages = ConversationMessageApplicationService(runtime)
    messages.guided_build = guide
    result = asyncio.run(messages.prepare_message("chat", question))
    assert result["route"] == "direct_answer"
    runtime.plan_message.assert_awaited_once_with(conversation, question)
    runtime.append_message.assert_not_called()
    snapshots.get_system_image.assert_not_called()
    guide.build_entries.plan.assert_not_called()
    assert conversation.messages[0].metadata["system_image_intake"] == saved


@pytest.mark.parametrize("stage", ["name", "sources", "review", "existing", "building"])
def test_project_name_question_reads_identity_not_cached_intake_or_image(stage):
    guide, runtime, conversation, saved, snapshots = dialogue_fixture(stage, goal_status="completed")
    result = asyncio.run(guide.handle("chat", "当前项目名称是什么"))
    assert result == {"message_id": "reply"}
    text = runtime.append_message.await_args.args[2]
    assert ("还没有创建项目" if stage == "name" else "Actual project") in text
    assert "候选画像" not in text
    if stage != "name":
        guide.project_reader.assert_called_once_with("project")
    else:
        guide.project_reader.assert_not_called()
    snapshots.get_system_image.assert_not_called()
    assert conversation.messages[0].metadata["system_image_intake"] == saved


def test_status_question_during_goal_creation_recovery_does_not_restart_work():
    guide, runtime, conversation, saved, _ = dialogue_fixture("building")
    saved["goal_id"] = None
    conversation.agent_goals = []
    guide._image_status = Mock(return_value={"status": "not_built", "summary": "Continue to prepare the build", "next_action": "build_candidate"})
    asyncio.run(guide.handle("chat", "系统画像是不是已经构建完成了"))
    runtime.create_tool_invocation.assert_not_called()
    runtime.start_goal_from_proposal.assert_not_called()
    guide.build_entries.plan.assert_not_called()


@pytest.mark.parametrize("question", ["当前项目名称是什么", "项目叫什么名字？", "What is the current project name?"])
def test_identity_question_recognition(question):
    assert is_project_name_question(question)


@pytest.mark.parametrize("question", ["项目名称是Orders", "把项目名称改为Orders", '"当前项目名称是什么"', "当前项目名称是什么，然后发布"])
def test_identity_reader_does_not_claim_commands_or_compound_requests(question):
    assert not is_project_name_question(question)


@pytest.mark.parametrize("template,project", [("project_setup", "project"), ("system_image_build", "other")])
def test_continue_cannot_mislabel_another_active_task_as_an_image_build(template, project):
    replies = []
    async def append(conversation_id, role, text, *, metadata):
        replies.append(text)
        return SimpleNamespace(id="message")
    guide = GuidedBuildConversation(runtime=SimpleNamespace(append_message=append), conversations=None,
        build_entries=None, extractor=None, snapshots=None, revisions=None, project_reader=None)
    state = BuildIntake(stage="existing", project_id="project", locale="zh")
    conversation = SimpleNamespace(id="chat", agent_goals=[SimpleNamespace(
        status="paused", goal_template=template, project_id=project)])
    asyncio.run(guide._prepare_build(conversation, state))
    assert state.stage == "existing" and state.goal_id is None
    assert "其他未结束的任务" in replies[-1]


@pytest.mark.parametrize("message", [
    '"系统画像是不是已经构建完成了"', '系统画像完成了吗，然后发布',
    'Is the system image ready? Then deploy it', '不要构建系统画像',
])
def test_status_recognition_never_grants_additional_actions(message):
    assert not is_build_status_question(message)


def test_recovery_uses_verified_recent_receipts_not_assistant_prose_or_array_order():
    def receipt(ident, project):
        return SimpleNamespace(id=ident, tool_id="project.create", conversation_id="chat", status="completed",
            result=SimpleNamespace(status="completed", object_refs=[f"project:{project}"]), input_payload={})
    first, current, unrelated = receipt("a", "first"), receipt("b", "current"), receipt("c", "unrelated")
    summary = SimpleNamespace(role="assistant", object_refs=["project:current"], tool_refs=["tool_invocation:b"])
    chat = SimpleNamespace(id="chat", project_id=None, tool_invocations=[current, unrelated, first], messages=[summary])
    assert recoverable_project(chat, "系统画像是不是已经构建完成了") == "current"
    chat.messages = [SimpleNamespace(role="user", object_refs=["project:current"], tool_refs=["tool_invocation:b"])]
    assert recoverable_project(chat, "系统画像是不是已经构建完成了") is None
    chat.messages = [SimpleNamespace(role="assistant", object_refs=["project:current"], tool_refs=["tool_invocation:a"])]
    assert recoverable_project(chat, "系统画像是不是已经构建完成了") is None
    chat.messages = [summary]
    current.status = "failed"
    assert recoverable_project(chat, "系统画像是不是已经构建完成了") is None


def test_completed_legacy_baseline_is_not_a_verified_publication():
    image = SimpleNamespace(visibility=SimpleNamespace(mode="full"), sources=[], source_manifest=None,
        candidate_revision=SimpleNamespace(object_count=10, relationship_count=4),
        project=SimpleNamespace(system_image_status="ready"))
    published = SimpleNamespace(read_state=SimpleNamespace(mode="legacy_draft", pin=None))
    status = image_status(image, published, "zh")
    assert status["status"] == "candidate" and "尚未正式发布" in status["summary"]
    published.read_state = SimpleNamespace(mode="published", pin=object())
    assert image_status(image, published, "zh")["status"] == "published"


@pytest.mark.parametrize("message", ["帮我构建一个系统画像", "我想创建一个新项目", "Please help me build a system image"])
def test_build_requests_start_intake(message):
    assert is_build_request(message)


@pytest.mark.parametrize("message", ['解释“帮我构建系统画像”', '> build a system image', '"create project"'])
def test_quoted_build_is_not_execution(message):
    assert not is_build_request(message)


def test_collect_sources_in_separate_turns():
    state = BuildIntake(stage="sources", project_name="Orders")
    fields = BuildIntakeExtractor._literal_fields("仓库 https://example.com/orders.git，分支 main，没有需求和测试", state)
    assert fields == {"code": "https://example.com/orders.git", "code_ref": "main", "optional_decided": True}
    assert BuildIntakeExtractor._literal_fields("跳过可选资料", BuildIntake()) == {"optional_decided": True}
    assert BuildIntakeExtractor._literal_fields("项目叫订单中心", BuildIntake())["project_name"] == "订单中心"
    assert BuildIntakeExtractor._literal_fields("帮我创建一个新的质量项目", BuildIntake()) == {}


@pytest.mark.parametrize("message", ["不要确认", "确认之前告诉我预算", "confirm then publish", "是否继续", "不要跳过确认"])
def test_confirmation_must_be_unambiguous(message):
    assert not is_intake_confirmation(message)


def test_invalid_source_values_cannot_become_paths():
    assert validate_fields({"code": "invented repository", "tests": "run tests"}) == {}


def test_live_intake_does_not_accept_model_invented_sources():
    class Model:
        async def generate_reply(self, **kwargs):
            return SimpleNamespace(mode="live", content='{"code":"/invented/path", "project_name":"Orders"}')
    async def memory(conversation):
        return SimpleNamespace(context_snapshot="", history_snapshot="")
    extractor = BuildIntakeExtractor(llm=Model(), settings=lambda: SimpleNamespace(runtime_mode="live"),
        secret=lambda: "", memory=memory)
    result = asyncio.run(extractor.extract(SimpleNamespace(id="chat", project_id=None), "项目叫 Orders", BuildIntake()))
    assert result == {"project_name": "Orders"}
