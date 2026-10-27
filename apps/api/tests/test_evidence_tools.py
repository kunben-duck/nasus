from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import replace

import pytest
from pydantic import ValidationError

from apps.api.app.application.platform.tool_handlers.evidence import EvidenceToolHandler, READ_EVIDENCE_TOOL
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.system_image.evidence_tool_models import EvidenceListInput, EvidenceReadInput
from apps.api.app.application.system_image.evidence_tools import EvidenceToolApplicationService
from apps.api.app.domain.system_image.evidence import EvidenceIntegrityError
from apps.api.tests.test_source_evidence import service


def read_input(**updates):
    return EvidenceReadInput(project_id="project", source_revision_id="revision", evidence_id="evidence", **updates)


def test_evidence_receipt_round_trip_is_bounded_and_has_no_source_body():
    queries, reader, _ = service()
    app = EvidenceToolApplicationService(queries)
    listed = app.list(EvidenceListInput(project_id="project", source_revision_id="revision", object_id="object"))
    assert listed.items[0].evidence_id == "evidence"
    assert reader.calls == 0
    receipt = app.read(read_input(max_lines=1))
    result = ToolResult(invocation_id="tool", status="completed", summary="verified", evidence_query=receipt)
    serialized = result.model_dump_json()
    assert "return 'ok'" not in serialized and "def run()" not in serialized and "s3://" not in serialized
    assert "content" not in serialized
    assert ToolResult.model_validate_json(serialized).evidence_query == receipt
    assert app.expand(receipt).content == "def run():\n"
    assert reader.calls == 2
    assert receipt.next_start_line == 2


@pytest.mark.parametrize("updates", [{"max_lines": True}, {"max_lines": 1.5}, {"max_lines": "10"},
                                    {"max_lines": 201}, {"start_line": False}, {"start_line": 0},
                                    {"file_path": "/etc/passwd"}, {"content": "not trusted"}])
def test_evidence_tool_input_rejects_coercion_and_arbitrary_paths(updates):
    with pytest.raises(ValidationError):
        read_input(**updates)


def test_pinned_revision_is_checked_before_any_storage_read():
    queries, reader, _ = service()
    app = EvidenceToolApplicationService(queries)
    request = read_input().model_copy(update={"source_revision_id": "different"})
    with pytest.raises(KeyError):
        app.read(request)
    assert reader.calls == 0


def test_receipt_expansion_reauthorizes_and_does_not_trust_previous_verified_content():
    queries, reader, authorization = service()
    app = EvidenceToolApplicationService(queries)
    receipt = app.read(read_input())
    authorization.allowed = False
    with pytest.raises(PermissionError):
        app.expand(receipt)
    assert reader.calls == 1
    authorization.allowed = True
    reader.body = b"altered source"
    with pytest.raises(EvidenceIntegrityError):
        app.expand(receipt)
    assert reader.calls == 2


def test_receipt_metadata_and_range_are_revalidated():
    queries, _, _ = service()
    app = EvidenceToolApplicationService(queries)
    receipt = app.read(read_input())
    for changed in (
        receipt.model_copy(update={"excerpt_hash": "sha256:" + "a" * 64}),
        receipt.model_copy(update={"end_line": 1}),
        receipt.model_copy(update={"evidence": replace(receipt.evidence, file_hash="sha256:" + "b" * 64)}),
    ):
        with pytest.raises(EvidenceIntegrityError):
            app.expand(changed)


def test_async_handler_preserves_actor_context_and_sanitizes_failures():
    actor = ContextVar("evidence_test_actor", default="wrong")
    queries, reader, _ = service()
    original = reader.read

    def read(target):
        assert actor.get() == "reviewer"
        return original(target)

    reader.read = read

    class Access:
        def require_invocation_project_scope(self, invocation):
            assert actor.get() == "reviewer"

    class Events:
        values = []

        async def emit_tool_status(self, *args):
            self.values.append(args)

    events = Events()
    handler = EvidenceToolHandler(EvidenceToolApplicationService(queries), events, Access())
    invocation = ToolInvocation(id="tool", tool_id=READ_EVIDENCE_TOOL, status="pending", summary="pending",
                                input_payload={**read_input().model_dump(), "agent_loop_iteration_id": "goal:step:0"})
    token = actor.set("reviewer")
    try:
        asyncio.run(handler.handle(invocation))
        assert events.values[-1][1] == "completed"
        assert events.values[-1][-1].evidence_query.integrity == "verified"

        def fail(target):
            raise RuntimeError("s3://private/credentials-and-source")

        reader.read = fail
        asyncio.run(handler.handle(invocation))
        assert events.values[-1][1] == "failed"
        assert "credentials-and-source" not in str(events.values)
        assert events.values[-1][-1].evidence_query is None
    finally:
        actor.reset(token)
