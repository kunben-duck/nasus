"""Real PG/HTTP projections of explicit receipt specimens, never plan execution."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.main import app
from apps.api.tests.test_run_plan_receipt_access import receipt, require_public_receipt
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_source_evidence_api import evidence_api


@pytest.mark.parametrize("tool", ["quality.run_plan.prepare", "query.quality.run_plan_preview"])
def test_real_shared_conversation_and_all_outbox_replays_keep_plan_specimens_private(evidence_api, tool):
    v = evidence_api
    conversation_id = v["conversation"].json()["id"]
    command = receipt(tool).model_copy(update={"id": "plan-receipt-specimen-" + uuid4().hex,
        "conversation_id": conversation_id}, deep=True)
    command.input_payload["project_id"] = v["project_id"]
    command.input_payload["environment"]["base_url"] = "http://private-plan-fixture.invalid"
    original = deepcopy(command.model_dump())
    repository = ConversationRepository()
    app.state.container.agent._events.tool_projection.persist_and_project(command)
    assert repository.get_tool_invocation(command.id).model_dump() == original
    grant_member(v)
    policy(v)
    denied = v["client"].get(f"{v['url']}/{v['evidence']['evidence_id']}", headers=v["member_headers"])
    assert denied.status_code == 403

    for path, params in ((f"/v1/conversations/{conversation_id}", {}),
            ("/v1/conversations", {"project_id": v["project_id"]}),
            ("/v1/conversations/search", {"q": v["conversation"].json()["title"]})):
        response = v["client"].get(path, headers=v["member_headers"], params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        conversations = body if isinstance(body, list) else body["conversations"] if path.endswith("/search") else [body]
        view = next(item for conversation in conversations for item in conversation["tool_invocations"]
            if item["id"] == command.id)
        require_public_receipt(view, command)
        assert "private-plan-fixture.invalid" not in response.text

    events = app.state.container.agent._events
    with actor_scope(UserProfile.model_validate(v["owner"])):
        fresh = events.build_conversation_event(conversation_id=conversation_id, event_type="tool.invocation.updated",
            entity_type="tool_invocation", entity_id=command.id, mutation_kind="replace",
            patch={"status": command.status, "input_payload": command.input_payload},
            query_keys=[["conversation", conversation_id]])
    outbox = EventOutboxRepository()
    outbox.append(fresh)
    historical = fresh.model_copy(update={"event_id": "evt_" + uuid4().hex,
        "agent_goal_id": "goal-plan-receipt-specimen-" + uuid4().hex,
        "swarm_run_id": "swarm-plan-receipt-specimen-" + uuid4().hex,
        "patch": {"input_payload": deepcopy(command.input_payload), "summary": command.summary},
        "payload": {"tool_invocation": deepcopy(original), "private_target": deepcopy(command.input_payload)}}, deep=True)
    outbox.append(historical)
    historical_snapshot = deepcopy(historical.model_dump())

    async def replay(kind, ident):
        stream = getattr(events, f"stream_{kind}_events")(ident, fresh.event_id)
        try:
            while True:
                result = await asyncio.wait_for(stream.__anext__(), timeout=5)
                if result is not None and result.event_id == historical.event_id:
                    return result
        finally:
            await stream.aclose()

    with actor_scope(UserProfile.model_validate(v["member"])):
        for kind, ident in (("conversation", conversation_id), ("goal", historical.agent_goal_id),
                ("swarm", historical.swarm_run_id)):
            result = asyncio.run(replay(kind, ident))
            require_public_receipt(result.payload["tool_invocation"], command)
            expected_patch = {"status": command.status, "summary": f"Execution plan command status: {command.status}.", "tool_id": tool}
            assert result.patch == result.payload["patch"] == expected_patch
            assert set(result.payload) == {"patch", "tool_invocation"}
            assert "private-plan-fixture.invalid" not in str(result.model_dump())
            assert result.entity_version == historical.entity_version and result.event_id == historical.event_id

    assert repository.get_tool_invocation(command.id).model_dump() == original
    with session_scope() as session:
        stored = session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == historical.event_id))
        assert stored.event_payload == historical_snapshot
        fresh_row = session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == fresh.event_id))
        require_public_receipt(fresh_row.event_payload["payload"]["tool_invocation"], command)
