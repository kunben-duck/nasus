"""Conversation proposals are separate from the persisted iteration state."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from apps.api.app.application.agent.delivery_dialogue import GuidedDeliveryConversation
from apps.api.app.application.agent.delivery_dialogue_inputs import DELIVERY_STATE_KEY, delivery_turn
from apps.api.app.application.agent.messages import ConversationMessageApplicationService


@pytest.fixture
def dialogue():
    conversation = SimpleNamespace(id="chat", space_type="build", project_id="project", version_id=None,
        messages=[], tool_invocations=[])
    runtime = Mock()
    runtime.get_conversation.return_value = conversation
    runtime.is_confirmation_message.return_value = False
    async def append(ident, role, text, *, metadata):
        message = SimpleNamespace(id="m" + str(len(conversation.messages)), role=role, content=text, metadata=deepcopy(metadata))
        conversation.messages.append(message)
        return message
    runtime.append_message = AsyncMock(side_effect=append)
    command = SimpleNamespace(id="tool_one", status="completed",
        result=SimpleNamespace(status="completed", object_refs=["version:iteration-one"]))
    runtime.create_tool_invocation = AsyncMock(return_value=command)
    publications = Mock()
    publications.pin.return_value = SimpleNamespace(publication_id="pub-one", image_revision_id="image-one",
        image_artifact_hash="sha256:" + "a" * 64)
    publications.history.return_value = {"head": {"publication_id": "pub-one"}}
    snapshots = Mock()
    snapshots.get_system_image.return_value = SimpleNamespace(visibility=SimpleNamespace(mode="full"),
        baselines=[SimpleNamespace(id="baseline")])
    projects = Mock()
    projects.list_versions.return_value = [SimpleNamespace(id="iteration-one", name="Sprint 1"),
        SimpleNamespace(id="iteration-two", name="Sprint 2")]
    delivery_read = Mock(side_effect=lambda project, version: {"project_id": project, "version_id": version,
        "stage": "image_pinned", "enabled": True})
    guide = GuidedDeliveryConversation(runtime=runtime, projects=projects, snapshots=snapshots,
        publications=publications, delivery_read=delivery_read)
    return guide, runtime, conversation


@pytest.mark.parametrize("content", [
    "当前项目名称是什么", "介绍一下迭代的作用", "如何创建迭代？", "不要创建迭代", "创建迭代之后会怎样？",
    "创建迭代 Sprint1，然后发布", '"创建迭代 Sprint1"', "> confirm iteration creation", "确认创建迭代并发布",
    "帮我构建一个系统画像", "继续分析", "confirm", "Are the tests passing?",
])
def test_unrelated_questions_quotes_and_compound_commands_do_not_control_delivery(dialogue, content):
    guide, runtime, _ = dialogue
    assert delivery_turn(content) is None
    assert asyncio.run(guide.handle("chat", content)) is None
    runtime.append_message.assert_not_called()
    runtime.create_tool_invocation.assert_not_called()


def test_create_requires_explicit_name_pin_and_confirmation_and_survives_reload(dialogue):
    guide, runtime, chat = dialogue
    asyncio.run(guide.handle("chat", "创建迭代 Sprint 1"))
    state = chat.messages[-1].metadata[DELIVERY_STATE_KEY]
    assert state["stage"] == "selection" and state["image_binding"] is None
    assert state["publication_id"] is None
    runtime.create_tool_invocation.assert_not_called()
    asyncio.run(guide.handle("chat", "使用画像发布 pub-one"))
    prepared = deepcopy(chat.messages[-1].metadata[DELIVERY_STATE_KEY])
    assert prepared["stage"] == "confirmation" and prepared["name"] == "Sprint 1"
    assert asyncio.run(guide.handle("chat", "当前项目名称是什么")) is None
    # A new application object uses durable assistant metadata, not in-memory cursor state.
    fresh = GuidedDeliveryConversation(runtime=runtime, projects=guide.projects, snapshots=guide.snapshots,
        publications=guide.publications, delivery_read=guide.delivery_read)
    asyncio.run(fresh.handle("chat", "确认创建迭代"))
    request = runtime.create_tool_invocation.await_args.args[0]
    assert request.tool_id == "version.create" and request.input == {"project_id": "project", "name": "Sprint 1",
        "image_binding": prepared["image_binding"]}
    assert request.idempotency_key == "delivery:" + prepared["proposal_id"]
    assert chat.messages[-1].metadata["version_delivery"]["version_id"] == "iteration-one"
    assert chat.messages[-1].metadata[DELIVERY_STATE_KEY]["stage"] == "created"
    asyncio.run(fresh.handle("chat", "确认创建迭代"))
    assert runtime.create_tool_invocation.await_count == 1


def test_selection_before_name_is_retained_without_auto_selecting_latest(dialogue):
    guide, runtime, chat = dialogue
    asyncio.run(guide.handle("chat", "使用画像发布 pub-one"))
    asyncio.run(guide.handle("chat", "迭代名称：Sprint 1"))
    assert chat.messages[-1].metadata[DELIVERY_STATE_KEY]["stage"] == "confirmation"
    assert chat.messages[-1].metadata[DELIVERY_STATE_KEY]["publication_id"] == "pub-one"
    runtime.create_tool_invocation.assert_not_called()


def test_confirmation_cannot_be_invented_from_a_query_or_model_text(dialogue):
    guide, runtime, chat = dialogue
    asyncio.run(guide.handle("chat", "确认创建迭代"))
    assert "还没有" in chat.messages[-1].content
    runtime.create_tool_invocation.assert_not_called()


def test_retry_keeps_original_command_key_after_lost_acknowledgement(dialogue):
    guide, runtime, chat = dialogue
    asyncio.run(guide.handle("chat", "创建迭代 Sprint 1，使用画像发布 pub-one"))
    original_append = runtime.append_message.side_effect
    async def lost_ack(*args, **kwargs):
        raise ConnectionError("lost reply")
    runtime.append_message.side_effect = lost_ack
    with pytest.raises(ConnectionError):
        asyncio.run(guide.handle("chat", "确认创建迭代"))
    first = runtime.create_tool_invocation.await_args.args[0]
    runtime.append_message.side_effect = original_append
    asyncio.run(guide.handle("chat", "确认创建迭代"))
    assert runtime.create_tool_invocation.await_args.args[0] == first
    guide.publications.pin.assert_called_with("project", "pub-one", require_current=False)


def test_source_access_is_rechecked_before_confirmation(dialogue):
    guide, runtime, _ = dialogue
    asyncio.run(guide.handle("chat", "create iteration Sprint 1 using publication pub-one"))
    guide.publications.pin.side_effect = PermissionError("source revoked")
    with pytest.raises(PermissionError):
        asyncio.run(guide.handle("chat", "confirm iteration creation"))
    runtime.create_tool_invocation.assert_not_called()


def test_publication_request_only_hands_off_to_independent_review(dialogue):
    guide, runtime, chat = dialogue
    asyncio.run(guide.handle("chat", "发布系统画像"))
    assert chat.messages[-1].metadata["delivery_next_action"]["action"] == "review_publication"
    runtime.create_tool_invocation.assert_not_called()
    guide.publications.publish.assert_not_called()


def test_status_does_not_choose_first_version_and_explicit_query_keeps_scope(dialogue):
    guide, runtime, chat = dialogue
    asyncio.run(guide.handle("chat", "迭代进度"))
    guide.delivery_read.assert_not_called()
    assert "iteration-one" in chat.messages[-1].content and "iteration-two" in chat.messages[-1].content
    asyncio.run(guide.handle("chat", "查看迭代 iteration-two"))
    guide.delivery_read.assert_called_once_with("project", "iteration-two")
    runtime.create_tool_invocation.assert_not_called()


def test_delivery_route_precedes_old_build_goal_but_does_not_intercept_other_turns(dialogue):
    guide, runtime, _ = dialogue
    messages = ConversationMessageApplicationService(runtime)
    messages.guided_delivery = guide
    messages.guided_build = Mock(handle=AsyncMock(return_value={"old": True}))
    result = asyncio.run(messages.prepare_message("chat", "创建迭代 Sprint 1"))
    assert result["route"] == "finalize"
    messages.guided_build.handle.assert_not_called()
    asyncio.run(messages.prepare_message("chat", "继续分析"))
    messages.guided_build.handle.assert_awaited_once()


def test_no_project_or_cancelled_proposal_cannot_create(dialogue):
    guide, runtime, chat = dialogue
    asyncio.run(guide.handle("chat", "创建迭代 Sprint 1，使用画像发布 pub-one"))
    asyncio.run(guide.handle("chat", "取消创建迭代"))
    asyncio.run(guide.handle("chat", "确认创建迭代"))
    runtime.create_tool_invocation.assert_not_called()
    chat.project_id = None
    asyncio.run(guide.handle("chat", "创建迭代"))
    assert "先创建项目" in chat.messages[-1].content
