"""Agent context integration using real accounts, PG source policies and facts."""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from apps.api.app.application.agent.agent_models import ConversationMessage, MessageBlock
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, SourceAccessRule, StaleSourceAccessScope
from apps.api.app.infrastructure.system_image.source_context_reader import SQLAlchemySystemImageContextReader
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_scoped_memory_retriever import scoped_project, retrieval


def set_policy(v, rule):
    epoch = v.policies.load_snapshot(v.project_id).acl_epoch
    v.policies.set_policy(v.project_id, v.binding.binding_id, rule, expected_epoch=epoch,
                         changed_by=v.owner["id"], invocation_id="context-test-" + uuid4().hex)


def prepare_manager(v, monkeypatch):
    manager = get_runtime_assembly().agent_memory
    retriever, models = retrieval(v)
    monkeypatch.setattr(manager, "system_image_retriever", retriever)
    message = ConversationMessage(id="old-" + uuid4().hex, role="assistant", created_at="2026-09-09T12:00:00Z",
                                  blocks=[MessageBlock(type="text", text="RestrictedPaymentSecret historical reasoning")])
    v.conversations.append_message(v.session.id, message)
    return manager, models, v.conversations.get_conversation(v.session.id)


def test_agent_context_and_http_view_exclude_unproven_history_and_derived_metadata(scoped_project, monkeypatch):
    v = scoped_project
    manager, models, session = prepare_manager(v, monkeypatch)
    before = v.repository.load_project_snapshot(v.project_id)
    with actor_scope(v.actor):
        context = asyncio.run(manager.build_context(session, trace_retrieval=True))
    assert "context_object=" in context.context_snapshot and "Orders" in context.context_snapshot
    assert "code_evidence_query=" in context.context_snapshot
    assert "[context_visibility]" in context.context_snapshot and "withheld" in context.history_snapshot
    assert "RestrictedPaymentSecret" not in context.context_snapshot + context.history_snapshot + context.retrieval_query
    assert v.hidden_source.id not in context.context_snapshot
    assert context.recent_turn_count == context.checkpoint_count == 0
    assert "[version]" not in context.context_snapshot and "[project]" not in context.context_snapshot
    assert "baseline=" not in context.context_snapshot and "metric=" not in context.context_snapshot
    assert context.retrieval_query == "system image" and context.retrieval_run_refs == []
    assert models.embedding_inputs == [["system image"]]
    assert "RestrictedPaymentSecret" not in str(models.rerank_inputs)

    response = v.client.get("/v1/agent-memory/context", headers=v.member_headers,
                            params={"conversation_id": session.id})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    view = response.json()
    assert "RestrictedPaymentSecret" not in json.dumps(view)
    assert view["conversation_memory"]["recent_message_refs"] == []
    assert view["candidate_memory"] == {"session_only_refs": [], "candidate_overlay_refs": []}
    project_memory = view["project_long_term_memory"]
    assert project_memory["system_image_status"] is None
    assert project_memory["baseline_refs"] == project_memory["metric_groups"] == project_memory["memory_items"] == []
    assert project_memory["context_object_refs"] and project_memory["source_refs"]
    assert v.hidden_source.id not in json.dumps(project_memory)
    assert v.repository.load_project_snapshot(v.project_id) == before


def test_http_context_returns_conflict_if_source_policy_changes_during_retrieval(scoped_project, monkeypatch):
    v = scoped_project
    manager, _, session = prepare_manager(v, monkeypatch)
    retriever, models = retrieval(v, on_embed=lambda: set_policy(v, SourceAccessRule("restricted", (v.actor.id,))))
    monkeypatch.setattr(manager, "system_image_retriever", retriever)
    response = v.client.get("/v1/agent-memory/context", headers=v.member_headers,
                            params={"conversation_id": session.id})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "source_scope_changed"
    assert "RestrictedPaymentSecret" not in response.text
    assert models.rerank_inputs == []


def test_policy_change_after_query_composition_stops_before_embedding(scoped_project, monkeypatch):
    v = scoped_project
    manager, models, session = prepare_manager(v, monkeypatch)
    set_policy(v, SourceAccessRule())
    original = manager._retrieval_query

    def restrict_after_query(conversation):
        query = original(conversation)
        assert "RestrictedPaymentSecret" in query
        set_policy(v, SourceAccessRule("restricted"))
        return query

    monkeypatch.setattr(manager, "_retrieval_query", restrict_after_query)
    with actor_scope(v.actor), pytest.raises(StaleSourceAccessScope):
        asyncio.run(manager.build_context(session))
    assert models.embedding_inputs == models.rerank_inputs == []


@pytest.mark.parametrize("invalid_scope", ["stale", "other_project"])
def test_retriever_validates_callers_scope_before_any_model_call(scoped_project, invalid_scope):
    v = scoped_project
    retriever, models = retrieval(v)
    with actor_scope(v.actor):
        scope = v.access.scope(v.project_id)
        if invalid_scope == "stale":
            set_policy(v, SourceAccessRule("restricted", (v.actor.id,)))
        else:
            v.session.project_id = "different-project"
        with pytest.raises((StaleSourceAccessScope, SourceAccessDenied)):
            asyncio.run(retriever.search_project_memory(v.session, "private query", expected_scope=scope))
    assert models.embedding_inputs == models.rerank_inputs == []


def test_direct_reader_checks_membership_before_snapshot_and_after_io(scoped_project, monkeypatch):
    v = scoped_project
    reader = SQLAlchemySystemImageContextReader(v.repository, v.access, lambda _: "should-not-be-used")
    original = v.repository.load_project_snapshot
    calls = []

    def revoke_during_read(project_id):
        calls.append(project_id)
        snapshot = original(project_id)
        assert v.client.delete(v.membership_url, headers=v.headers).status_code == 200
        return snapshot

    monkeypatch.setattr(v.repository, "load_project_snapshot", revoke_during_read)
    with actor_scope(v.actor), pytest.raises(PlatformApplicationError):
        reader.read(v.project_id)
    assert len(calls) == 1
    with actor_scope(v.actor), pytest.raises(PlatformApplicationError):
        reader.read(v.project_id)
    assert len(calls) == 1
