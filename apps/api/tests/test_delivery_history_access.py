import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.api.app.application.agent.agent_models import ConversationCreateRequest, ConversationMergeRequest, ConversationMessage, MessageBlock
from apps.api.app.application.agent.conversations import ConversationManagementApplicationService
from apps.api.app.application.agent.delivery_read_access import DeliveryConversationReadAccess
from apps.api.app.application.agent.memory import AgentMemoryManager
from apps.api.app.application.platform.delivery_event_access import DeliveryConversationEventAccess
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.event_streams import PlatformEventStreamApplicationService
from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.tests.test_agent_conversation_application import InMemoryConversationState


def message(metadata, ident="message"):
    return ConversationMessage(id=ident, role="assistant", created_at="2026-11-12T00:00:00+00:00",
        blocks=[MessageBlock(type="text", text="private publication reference")], metadata=metadata)


@pytest.fixture
def guarded():
    sources = Mock(spec=["require_all_sources_access"])
    access = DeliveryConversationReadAccess(sources)
    state = InMemoryConversationState()
    service = ConversationManagementApplicationService(state, read_guard=access.require_access)
    request = ConversationCreateRequest(space_type="project", space_id="project", title="Delivery")
    chat = service.ensure_conversation(request)
    return SimpleNamespace(sources=sources, access=access, state=state, service=service, chat=chat, request=request)


@pytest.mark.parametrize("key", ["delivery_intake", "version_delivery"])
def test_delivery_history_checks_fresh_acl_once_per_read_not_per_message(guarded, key):
    v = guarded
    v.chat.messages = [message({key: {"project_id": "project"}}, str(index)) for index in range(30)]
    assert v.service.get_conversation(v.chat.id) is v.chat
    v.sources.require_all_sources_access.assert_called_once_with("project")
    v.sources.require_all_sources_access.side_effect = SourceAccessDenied("revoked")
    for operation in (lambda: v.service.get_conversation(v.chat.id),
            lambda: v.service.list_conversation_messages(v.chat.id),
            lambda: v.service.list_conversation_messages(v.chat.id, "0"),
            lambda: v.service.ensure_conversation(v.request)):
        with pytest.raises(PlatformApplicationError) as error:
            operation()
        assert error.value.status_code == 403
    assert v.sources.require_all_sources_access.call_count == 5
    v.sources.require_all_sources_access.side_effect = None
    assert v.service.get_conversation(v.chat.id) is v.chat


def test_list_and_search_omit_protected_conversation_and_excerpts(guarded):
    v = guarded
    v.chat.messages = [message({"delivery_intake": {"project_id": "project"}})]
    safe = v.service.get_or_create_conversation("project", "other", "Safe")
    v.sources.require_all_sources_access.side_effect = SourceAccessDenied("revoked")
    assert v.service.list_conversations() == [safe]
    assert v.service.list_conversations(project_id="project") == []
    result = v.service.search_conversations("private")
    assert result["conversations"] == result["message_hits"] == []


@pytest.mark.parametrize("protected_side", ["source", "target"])
def test_merge_checks_both_sides_before_any_mutation(guarded, protected_side):
    v = guarded
    target = v.service.get_or_create_conversation("knowledge", "other-space", "Target", project_id="project")
    protected = v.chat if protected_side == "source" else target
    protected.messages = [message({"version_delivery": {"project_id": "project"}})]
    before = (v.chat.model_dump(), target.model_dump())
    v.sources.require_all_sources_access.side_effect = SourceAccessDenied("revoked")
    with pytest.raises(PlatformApplicationError) as error:
        v.service.merge_conversations(v.chat.id, ConversationMergeRequest(target_conversation_id=target.id))
    assert error.value.status_code == 403
    assert (v.chat.model_dump(), target.model_dump()) == before
    assert not v.state.links


def test_authorized_merge_retains_protection_on_copied_history(guarded):
    v = guarded
    target = v.service.get_or_create_conversation("knowledge", "other-space", "Target", project_id="project")
    v.chat.messages = [message({"delivery_intake": {"project_id": "project"}})]
    v.service.merge_conversations(v.chat.id, ConversationMergeRequest(target_conversation_id=target.id))
    assert target.messages[0].metadata == v.chat.messages[0].metadata
    v.sources.require_all_sources_access.side_effect = SourceAccessDenied("revoked after merge")
    with pytest.raises(PlatformApplicationError) as error:
        v.service.get_conversation(target.id)
    assert error.value.status_code == 403


@pytest.mark.parametrize("selector", ["conversation", "goal", "space", "project"])
def test_memory_selectors_guard_m1_before_summary_or_context_reads(guarded, selector):
    v = guarded
    v.chat.space_type = "knowledge"
    v.chat.messages = [message({"version_delivery": {"project_id": "project"}})]
    state = Mock()
    state.get_conversation.return_value = v.chat
    state.get_goal.return_value = SimpleNamespace(conversation_id=v.chat.id)
    state.list_conversations.return_value = [v.chat]
    images = Mock()
    memory = AgentMemoryManager(state, Mock(), images, read_guard=v.access.require_access)
    selected = {"conversation": {"conversation_id": v.chat.id}, "goal": {"agent_goal_id": "goal"},
        "space": {"space_ref": "knowledge:" + v.chat.space_id}, "project": {"space_ref": "project:project"}}[selector]
    v.sources.require_all_sources_access.side_effect = SourceAccessDenied("revoked")
    for operation in (memory.create_summary_checkpoint, memory.get_context_view):
        with pytest.raises(PlatformApplicationError) as error:
            asyncio.run(operation(**selected))
        assert error.value.status_code == 403
    state.list_summary_checkpoints.assert_not_called()
    state.persist_summary_checkpoint.assert_not_called()
    images.scope.assert_not_called()


def test_legacy_m1_summary_rechecks_acl_after_publishing_checkpoint(guarded):
    v = guarded
    v.chat.messages = [message({"delivery_intake": {"project_id": "project"}})]
    state = Mock()
    state.get_conversation.return_value = v.chat
    state.list_summary_checkpoints.return_value = []
    async def revoke(*_args):
        v.sources.require_all_sources_access.side_effect = SourceAccessDenied("revoked during publish")
    state.publish_memory_checkpointed = revoke
    memory = AgentMemoryManager(state, Mock(), Mock(), read_guard=v.access.require_access)
    with pytest.raises(PlatformApplicationError) as error:
        asyncio.run(memory.create_summary_checkpoint(conversation_id=v.chat.id))
    assert error.value.status_code == 403
    state.persist_summary_checkpoint.assert_called_once()


def test_non_delivery_and_unbound_guidance_do_not_require_sources(guarded):
    v = guarded
    v.chat.project_id = None
    v.chat.messages = [message({"planner_kind": "guided_delivery"}), message({"planner_kind": "ordinary"})]
    v.sources.require_all_sources_access.side_effect = AssertionError("ordinary history must not load source ACLs")
    assert v.service.get_conversation(v.chat.id) is v.chat
    assert v.service.list_conversation_messages(v.chat.id) == v.chat.messages
    v.sources.require_all_sources_access.assert_not_called()


@pytest.mark.parametrize("metadata", [
    {"delivery_intake": None}, {"version_delivery": {}},
    {"version_delivery": {"project_id": "foreign"}},
    {"delivery_intake": {"project_id": "project"}, "version_delivery": {"project_id": "foreign"}},
])
def test_invalid_history_scope_fails_closed(guarded, metadata):
    v = guarded
    v.chat.messages = [message(metadata)]
    with pytest.raises(PlatformApplicationError) as error:
        v.service.get_conversation(v.chat.id)
    assert error.value.status_code == 502
    v.sources.require_all_sources_access.assert_not_called()


def test_acl_change_during_read_is_denied_but_backend_failure_is_not_hidden(guarded):
    v = guarded
    v.chat.messages = [message({"version_delivery": {"project_id": "project"}})]
    v.sources.require_all_sources_access.side_effect = StaleSourceAccessScope("changed")
    with pytest.raises(PlatformApplicationError) as error:
        v.service.get_conversation(v.chat.id)
    assert error.value.status_code == 403
    v.sources.require_all_sources_access.side_effect = RuntimeError("ACL unavailable")
    with pytest.raises(RuntimeError, match="ACL unavailable"):
        v.service.list_conversations()


def event(ident, metadata=None):
    return EventPayload(event_id=ident, event_type="conversation.message.created", occurred_at="2026-11-12T00:00:00+00:00",
        correlation_id=ident, conversation_id="chat", entity_type="conversation", entity_id="chat", entity_version=1,
        mutation_kind="patch", patch={"message_id": ident},
        payload={"message_id": ident, "message": message(metadata or {}, ident).model_dump()})


def event_policy(v):
    scope = SimpleNamespace(id="chat", project_id="project", space_type="project", initiator_id="member")
    return DeliveryConversationEventAccess(v.access, conversation_scope=Mock(return_value=scope),
        require_conversation_access=Mock())


def test_existing_stream_reauthorizes_each_event_and_replay_after_cursor(guarded):
    v, calls = guarded, []
    policy = event_policy(v)
    first = event("first", {"delivery_intake": {"project_id": "project"}})
    second = event("second", {"version_delivery": {"project_id": "project"}})
    safe = event("safe")
    third = event("third", {"version_delivery": {"project_id": "project"}})

    def list_after(**args):
        cursor = args["after_event_id"]
        calls.append(cursor)
        return {None: [first, second, safe], "first": [second, safe], "safe": [third]}[cursor]

    service = PlatformEventStreamApplicationService(SimpleNamespace(list_after=list_after),
        SimpleNamespace(conversation_queue=lambda _: asyncio.Queue()), poll_seconds=.05, heartbeat_seconds=1,
        authorize_event=policy.can_access)

    async def observe():
        stream = service.stream_conversation_events("chat")
        try:
            assert (await stream.__anext__()).event_id == "first"
            v.sources.require_all_sources_access.side_effect = SourceAccessDenied("revoked after connection")
            assert (await stream.__anext__()).event_id == "safe"
            v.sources.require_all_sources_access.side_effect = None
            assert (await stream.__anext__()).event_id == "third"
        finally:
            await stream.aclose()
        v.sources.require_all_sources_access.side_effect = SourceAccessDenied("revoked before replay")
        replay = service.stream_conversation_events("chat", "first")
        try:
            assert (await replay.__anext__()).event_id == "safe"
        finally:
            await replay.aclose()

    asyncio.run(observe())
    assert calls == [None, "safe", "first"]
    assert v.sources.require_all_sources_access.call_count == 4
    assert policy.conversation_scope.call_count == 4


def test_event_policy_preserves_private_chat_ownership_and_fails_closed(guarded):
    v = guarded
    policy = event_policy(v)
    protected = event("protected", {"version_delivery": {"project_id": "project"}})
    policy.require_conversation_access.side_effect = PlatformApplicationError("conversation_access_denied", "private Build chat", 403)
    assert not policy.can_access(protected)
    v.sources.require_all_sources_access.assert_not_called()
    policy.require_conversation_access.side_effect = None
    policy.conversation_scope.return_value = None
    assert not policy.can_access(protected)
    policy = event_policy(v)
    with pytest.raises(PlatformApplicationError) as error:
        policy.can_access(protected.model_copy(update={"conversation_id": None}))
    assert error.value.status_code == 502
    v.sources.require_all_sources_access.side_effect = RuntimeError("ACL unavailable")
    with pytest.raises(RuntimeError, match="ACL unavailable"):
        policy.can_access(protected)


def test_ordinary_token_deltas_do_not_load_history_or_sources(guarded):
    v = guarded
    policy = event_policy(v)
    delta = event("delta").model_copy(update={"event_type": "conversation.message.delta",
        "payload": {"stream_id": "stream", "sequence": 1, "delta": "ordinary token"}})
    for _ in range(100):
        assert policy.can_access(delta)
    policy.conversation_scope.assert_not_called()
    policy.require_conversation_access.assert_not_called()
    v.sources.require_all_sources_access.assert_not_called()
