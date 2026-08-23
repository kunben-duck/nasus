from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from apps.api.app.application.platform.model_settings import StudioSettings
from apps.api.app.domain.platform.llm_call import LLMCall, LLMCallContext
from apps.api.app.infrastructure.llm.gateway import LLMGateway
from apps.api.app.infrastructure.persistence.llm_call_repository import (
    SQLAlchemyLLMCallRepository,
)
from apps.api.app.infrastructure.persistence.database import init_database


class RecordingAuditPort:
    def __init__(self) -> None:
        self.calls: list[LLMCall] = []

    def persist_llm_call(self, call: LLMCall) -> None:
        self.calls.append(call)

    def list_llm_calls(self, **kwargs):
        del kwargs
        return list(self.calls)


def test_gateway_audits_all_model_routes_without_raw_content() -> None:
    audit = RecordingAuditPort()
    gateway = LLMGateway(audit)
    settings = StudioSettings()
    context = LLMCallContext(
        purpose="test.model_route",
        project_id="project_audit",
        conversation_id="conversation_audit",
    )

    reply = asyncio.run(
        gateway.generate_reply(
            settings=settings,
            system_prompt="private system prompt",
            user_message="private user input",
            context_snapshot="private context",
            history_snapshot="private history",
            fallback_text="private fallback output",
            call_context=context,
        )
    )
    embedding = asyncio.run(
        gateway.embed_texts(
            settings=settings,
            texts=["private embedding input"],
            call_context=context,
        )
    )
    rerank = asyncio.run(
        gateway.rerank_candidates(
            settings=settings,
            query="private query",
            documents=["private candidate"],
            call_context=context,
        )
    )

    assert [call.route for call in audit.calls] == ["chat", "embedding", "rerank"]
    assert reply.llm_call_id == audit.calls[0].id
    assert embedding.llm_call_id == audit.calls[1].id
    assert rerank.llm_call_id == audit.calls[2].id
    assert all(call.project_id == "project_audit" for call in audit.calls)
    assert all(call.request_hash.startswith("sha256:") for call in audit.calls)
    assert all(call.response_hash.startswith("sha256:") for call in audit.calls)
    serialized = repr(audit.calls)
    for sensitive_value in (
        "private system prompt",
        "private user input",
        "private context",
        "private fallback output",
        "private embedding input",
        "private candidate",
    ):
        assert sensitive_value not in serialized


def test_sqlalchemy_llm_call_repository_round_trip_and_filters() -> None:
    init_database()
    repository = SQLAlchemyLLMCallRepository()
    call = LLMCall(
        id=f"llmcall_test_{uuid4().hex}",
        occurred_at=datetime.now(timezone.utc),
        route="chat",
        purpose="test.repository",
        provider="mock",
        model_name="mock-model",
        selected_provider="openai_compatible",
        selected_model_name="configured-model",
        runtime_mode="fallback",
        outcome="fallback",
        reason="test",
        project_id="project_repository_filter",
        request_hash="sha256:request",
        response_hash="sha256:response",
    )

    repository.persist_llm_call(call)
    rows = repository.list_llm_calls(
        route="chat",
        project_id="project_repository_filter",
        limit=10,
    )

    stored = next(row for row in rows if row.id == call.id)
    assert stored.purpose == call.purpose
    assert stored.selected_provider == call.selected_provider
    assert stored.request_hash == call.request_hash
    assert repository.list_llm_calls(route="rerank", project_id=call.project_id) == []
