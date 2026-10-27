import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.agent.agent_models import ConversationSession
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.system_image.index_inputs import IndexSelection, IndexBuildRequest, INDEX_BUILD_TOOL, INDEX_PREVIEW_TOOL
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.publication import PublicationChanged
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.llm.index_embedding import HTTPIndexEmbedding
from apps.api.app.infrastructure.persistence.frozen_index_models import FrozenIndexReservationRecord as Reservation
from apps.api.app.infrastructure.persistence.frozen_index_models import FrozenIndexGenerationRecord as Generation
from apps.api.app.infrastructure.persistence.frozen_index_models import FrozenIndexDocumentRecord as Document, FrozenRetrievalRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_published_image_reads import publish
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count
from apps.api.tests.test_semantic_link_model import saved_config
from apps.api.tests.test_source_access_api import grant_member


@pytest.fixture
def indexed(publication, monkeypatch):
    v = publication
    head = publish(v)
    service = app.state.container.frozen_indexes
    config = saved_config(config_id=uuid4().hex, route="embedding")
    encrypted = service.models.secrets.encrypt_api_key("private-index-key")
    service.models.repository.save_model_config(config, encrypted)
    calls = []
    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"model": config.model_name, "data": [
            {"index": i, "embedding": [1, 0.25, 0.75]} for i, _ in enumerate(body["input"])], "usage": {"prompt_tokens": 42}})
    monkeypatch.setattr(service, "provider", HTTPIndexEmbedding(transport=httpx.MockTransport(handle)))
    selection = dict(project_id=v["project_id"], publication_id=head["publication_id"], model_config_id=config.config_id)
    preview_result = completed(invoke(v, INDEX_PREVIEW_TOOL, selection))
    preview = preview_result["result"]["index_preview"]
    v.update(index_service=service, index_head=head, index_config=config, index_encrypted=encrypted,
        index_calls=calls, index_preview=preview, index_request=preview["request"], index_preview_invocation=preview_result["id"])
    return v


def build(v):
    response = invoke(v, INDEX_BUILD_TOOL, v["index_request"], key=uuid4().hex)
    assert response.status_code == 200 and response.json()["status"] == "waiting_confirmation", response.text
    assert not v["index_calls"]
    return completed(confirm(v, response.json()))


def search(v, *, trace=True):
    conversation = ConversationSession.model_validate({**v["conversation"].json(), "version_id": None})
    return asyncio.run(app.state.container.agent._memory.system_image_retriever.search_project_memory(conversation, "original", trace=trace))


def test_confirmed_index_atomic_pg_search_and_immutable_provenance(indexed):
    v = indexed
    assert not v["index_calls"] and v["index_preview"]["document_count"] > 0
    result = build(v)
    generation_id = result["id"]
    assert len(v["index_calls"]) == v["index_preview"]["max_model_calls"]
    assert count(v, Generation) == count(v, Reservation) == 1
    assert count(v, Document) == v["index_preview"]["document_count"]
    service = v["index_service"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        metadata = service.describe(v["project_id"], generation_id)
        assert metadata["publication_pin"]["publication_id"] == v["index_head"]["publication_id"]
        found = search(v)
        assert found.hits and found.strategy == "published_hybrid_rrf_rerank_withheld"
        assert len(found.retrieval_run_refs) == 1 and found.image_read_state.pin.publication_id == v["index_head"]["publication_id"]
        assert all(hit.ref.startswith(f"image_revision:{v['index_head']['image_revision_id']}:") for hit in found.hits)
        assert all("text_hash=" in hit.summary and "evidence=" in hit.summary and "original" not in hit.summary for hit in found.hits)
    with session_scope() as session:
        trace = session.scalar(select(FrozenRetrievalRecord).where(FrozenRetrievalRecord.project_id == v["project_id"]))
        assert trace.generation_id == generation_id and trace.publication_id == v["index_head"]["publication_id"]
        artifact = service.artifacts.read(v["project_id"], trace.artifact_ref, trace.artifact_hash)
        assert artifact["selected"] and artifact["query"] == "original" and not artifact["relationship_authority"]
        trace_id = trace.retrieval_id
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == generation_id)).all()
        assert {e.event_type for e in events} >= {"system_image.index.reserved", "system_image.index.completed"}
        stored = json.dumps([e.event_payload for e in events])
        assert "private-index-key" not in stored and "Empty input" not in stored
    for path in (f"indexes/{generation_id}", f"retrievals/{trace_id}"):
        response = v["client"].get(v["image_url"] + "/" + path, headers=v["headers"])
        assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
        assert "s3://" not in response.text and "private-index-key" not in response.text
        if path.startswith("retrievals"):
            assert all("text" not in item["document"] for item in response.json()["candidates"])
            assert len(response.content) <= 65536 and response.json()["selected_document_ids"]
    for model in (Generation, Document, Reservation, FrozenRetrievalRecord):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(update(model).where(model.project_id == v["project_id"]).values(project_id="changed"))
    call_count = len(v["index_calls"])
    v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"]}
    new_head = publish(v)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        old = service.describe(v["project_id"], generation_id)
        assert old == metadata
        restored = asyncio.run(service.build(IndexBuildRequest.model_validate(v["index_request"]), invocation_id=generation_id))
        assert restored == metadata
        found = search(v)
        assert found.image_read_state.pin.publication_id == new_head["publication_id"]
        assert "unversioned_index_withheld" in found.strategy  # No generation for this publication.
    assert len(v["index_calls"]) == call_count


def test_changed_model_consent_prevents_any_export_and_old_vectors_are_never_reused(indexed):
    v = indexed
    done = build(v)
    service = v["index_service"]
    service.models.repository.save_model_config(v["index_config"].model_copy(update={"updated_at": "changed"}), v["index_encrypted"])
    calls = len(v["index_calls"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.describe(v["project_id"], done["id"])["generation_id"] == done["id"]
        with pytest.raises(ImageRevisionIntegrityError, match="model changed"):
            search(v)
    pending = invoke(v, INDEX_BUILD_TOOL, v["index_request"], key=uuid4().hex)
    response = confirm(v, pending.json())
    assert response.json()["status"] == "failed" and len(v["index_calls"]) == calls
    assert count(v, Generation) == count(v, Reservation) == 1


def test_unknown_provider_outcome_is_reserved_but_never_searchable_or_retried(indexed, monkeypatch):
    v = indexed
    calls = []
    def fail(request):
        calls.append(request)
        raise httpx.ReadError("private-index-key interrupted", request=request)
    monkeypatch.setattr(v["index_service"], "provider", HTTPIndexEmbedding(transport=httpx.MockTransport(fail)))
    pending = invoke(v, INDEX_BUILD_TOOL, v["index_request"], key=uuid4().hex).json()
    result = confirm(v, pending)
    assert result.json()["status"] == "failed" and "private-index-key" not in result.text
    assert len(calls) == 1 and count(v, Reservation) == 1 and count(v, Generation) == count(v, Document) == 0
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ValueError, match="not automatically retried"):
            asyncio.run(v["index_service"].build(IndexBuildRequest.model_validate(v["index_request"]), invocation_id=pending["id"]))
    assert len(calls) == 1


def test_direct_application_cannot_bypass_canonical_runtime(indexed):
    v = indexed
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(ImageRevisionIntegrityError, match="canonical"):
            asyncio.run(v["index_service"].build(IndexBuildRequest.model_validate(v["index_request"]), invocation_id="fake"))
    assert not v["index_calls"] and count(v, Reservation) == 0


@pytest.mark.parametrize("change", ["cancel", "head", "acl", "model", "artifact_write"])
def test_changes_during_export_or_before_commit_never_publish_partial_index(indexed, monkeypatch, change):
    v = indexed
    service = v["index_service"]
    pending = invoke(v, INDEX_BUILD_TOOL, v["index_request"], key=uuid4().hex).json()
    def mutate():
        if change == "cancel":
            with session_scope() as session:
                session.get(ToolInvocationRecord, pending["id"]).status = "cancelled"
        elif change in {"head", "artifact_write"}:
            v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"]}
            publish(v)
        elif change == "model":
            service.models.repository.save_model_config(v["index_config"].model_copy(update={"updated_at": "changed"}), v["index_encrypted"])
        else:
            repo = SourceAccessRepository()
            scope = repo.load_snapshot(v["project_id"])
            repo.set_policy(v["project_id"], scope.bindings[0].binding_id, SourceAccessRule("restricted"),
                expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="index-revoke")
    if change == "artifact_write":
        original = service.artifacts.put
        def put(*args):
            result = original(*args)
            mutate()
            return result
        monkeypatch.setattr(service.artifacts, "put", put)
    else:
        original = service.provider.embed
        async def embed(*args):
            result = await original(*args)
            mutate()
            return result
        monkeypatch.setattr(service.provider, "embed", embed)
    response = confirm(v, pending)
    assert response.json()["status"] in {"failed", "cancelled"}, response.text
    assert count(v, Reservation) == 1 and count(v, Generation) == count(v, Document) == 0


def test_query_rechecks_current_head_before_returning_or_writing_trace(indexed, monkeypatch):
    v = indexed
    build(v)
    original = v["index_service"].provider.embed
    async def move(*args):
        result = await original(*args)
        v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"]}
        publish(v)
        return result
    monkeypatch.setattr(v["index_service"].provider, "embed", move)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PublicationChanged):
            search(v)
    assert count(v, FrozenRetrievalRecord) == 0


def test_source_revocation_hides_index_and_trace_and_nonadmin_cannot_export(indexed):
    v = indexed
    grant_member(v)
    selection = {key: v["index_request"][key] for key in ("project_id", "publication_id", "model_config_id", "method_version")}
    refused = invoke(v, INDEX_PREVIEW_TOOL, selection, headers=v["member_headers"])
    assert refused.status_code == 403 or refused.json()["status"] == "failed"
    assert not v["index_calls"]
    done = build(v)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        found = search(v)
    trace_id = found.retrieval_run_refs[0].split(":", 1)[1]
    index_url = v["image_url"] + f"/indexes/{done['id']}"
    trace_url = v["image_url"] + f"/retrievals/{trace_id}"
    assert v["client"].get(index_url, headers=v["member_headers"]).status_code == 200
    assert v["client"].get(trace_url, headers=v["member_headers"]).status_code == 403  # Another actor's query.
    repo = SourceAccessRepository()
    scope = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], scope.bindings[0].binding_id, SourceAccessRule("restricted"),
        expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="index-read-revoke")
    assert v["client"].get(index_url, headers=v["member_headers"]).status_code == 403
    assert v["client"].get(v["image_url"] + "/indexes", params={"publication_id": v["index_head"]["publication_id"]},
        headers=v["member_headers"]).status_code == 403


def test_current_index_status_never_exports_and_marks_changed_model(indexed):
    v = indexed
    url = v["image_url"] + "/indexes"
    params = {"publication_id": v["index_head"]["publication_id"]}
    before = v["client"].get(url, params=params, headers=v["headers"])
    assert before.status_code == 200 and before.headers["cache-control"] == "private, no-store"
    assert before.json()["state"] == "not_built" and before.json()["generation"] is None
    assert before.json()["can_build"] and not before.json()["quality_generation_authorized"]
    assert not v["index_calls"]
    done = build(v)
    calls = len(v["index_calls"])
    grant_member(v)
    member = v["client"].get(url, params=params, headers=v["member_headers"])
    assert member.status_code == 200 and member.json()["state"] == "ready" and not member.json()["can_build"]
    assert member.json()["generation"]["generation_id"] == done["id"]
    assert "private-index-key" not in member.text and "artifact_ref" not in member.text
    service = v["index_service"]
    service.models.repository.save_model_config(v["index_config"].model_copy(update={"updated_at": "changed"}), v["index_encrypted"])
    changed = v["client"].get(url, params=params, headers=v["headers"])
    assert changed.status_code == 200 and changed.json()["state"] == "rebuild_required"
    assert changed.json()["generation"] == member.json()["generation"]
    assert len(v["index_calls"]) == calls
    v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"]}
    next_head = publish(v)
    assert v["client"].get(url, params=params, headers=v["headers"]).status_code == 409
    next_status = v["client"].get(url, params={"publication_id": next_head["publication_id"]}, headers=v["headers"])
    assert next_status.status_code == 200 and next_status.json()["state"] == "not_built"
    assert next_status.json()["generation"] is None


def test_portal_command_without_conversation_keeps_confirmation_and_idempotency(indexed):
    v = indexed
    selection = {key: v["index_request"][key] for key in ("project_id", "publication_id", "model_config_id", "method_version")}
    preview = completed(v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": INDEX_PREVIEW_TOOL, "initiator_surface": "ui", "input": selection, "idempotency_key": uuid4().hex}))
    assert preview["tool_id"] == INDEX_PREVIEW_TOOL and not preview["conversation_id"]
    payload = {"tool_id": INDEX_BUILD_TOOL, "initiator_surface": "ui", "initiator_actor": "user", "target_scope": "central",
        "input": preview["result"]["index_preview"]["request"], "idempotency_key": uuid4().hex}
    pending = v["client"].post("/v1/tool-invocations", headers=v["headers"], json=payload)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation"
    assert pending.json()["input_payload"] == {**payload["input"], "idempotency_key": payload["idempotency_key"]}
    assert not v["index_calls"]
    done = completed(confirm(v, pending.json()))
    assert done["result"]["object_refs"] == [f"image_index:{done['id']}"]
    calls = len(v["index_calls"])
    replay = completed(v["client"].post("/v1/tool-invocations", headers=v["headers"], json=payload))
    assert replay["id"] == done["id"] and len(v["index_calls"]) == calls
    status = v["client"].get(v["image_url"] + "/indexes", headers=v["headers"],
        params={"publication_id": v["index_head"]["publication_id"]})
    assert status.status_code == 200 and status.json()["generation"]["generation_id"] == done["id"]


def test_index_status_revalidates_head_after_reading_generation(indexed, monkeypatch):
    v = indexed
    build(v)
    service = v["index_service"]
    original = service.describe
    def describe(*args):
        result = original(*args)
        v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"]}
        publish(v)
        return result
    monkeypatch.setattr(service, "describe", describe)
    response = v["client"].get(v["image_url"] + "/indexes", params={"publication_id": v["index_head"]["publication_id"]}, headers=v["headers"])
    assert response.status_code == 409
    assert "generation_id" not in response.text


def test_changed_preview_digest_cannot_be_used_for_export(indexed):
    v = indexed
    pending = invoke(v, INDEX_BUILD_TOOL, {**v["index_request"], "input_digest": "sha256:" + "0" * 64}, key=uuid4().hex).json()
    assert confirm(v, pending).json()["status"] == "failed"
    assert not v["index_calls"] and count(v, Reservation) == 0


def test_query_provider_failure_is_explicit_same_generation_lexical_fallback(indexed, monkeypatch):
    v = indexed
    done = build(v)
    def fail(request):
        return httpx.Response(503, text="private-index-key")
    monkeypatch.setattr(v["index_service"], "provider", HTTPIndexEmbedding(transport=httpx.MockTransport(fail)))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        result = search(v)
        assert result.strategy == "published_lexical_embedding_unavailable" and result.hits
        trace = v["index_service"].read_trace(v["project_id"], result.retrieval_run_refs[0].split(":", 1)[1])
        assert trace["generation_id"] == done["id"] and trace["embedding_fallback_reason"] == "embedding_provider_unavailable"
        assert trace["query_vector_hash"] is None


def test_two_workers_cannot_spend_the_same_index_reservation_twice(indexed):
    v = indexed
    invocation = str(uuid4())
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation, tool_id=INDEX_BUILD_TOOL, status="running",
            summary="Explicit competing-worker fixture", input_payload={**v["index_request"], "confirmed_by_user": True,
                "confirmed_at": datetime.now(timezone.utc).isoformat()}))
    async def compete():
        request = IndexBuildRequest.model_validate(v["index_request"])
        return await asyncio.gather(*(v["index_service"].build(request, invocation_id=invocation) for _ in range(2)), return_exceptions=True)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        results = asyncio.run(compete())
    assert any(isinstance(result, dict) for result in results)
    assert all(isinstance(result, (dict, ValueError)) for result in results), results
    assert len(v["index_calls"]) == v["index_preview"]["max_model_calls"]
    assert count(v, Generation) == count(v, Reservation) == 1


def test_later_batch_dimension_change_discards_the_entire_generation(indexed, monkeypatch):
    from apps.api.tests.test_reference_links_api import candidate
    v = indexed
    v["path"].write_text(v["path"].read_text() + "\n" + "\n".join(f"def original_extra_{i}():\n    return {i}\n" for i in range(40)))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    next_image = candidate(v)
    v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"],
        "image_revision_id": next_image["image_revision_id"], "image_artifact_hash": next_image["artifact_hash"]}
    head = publish(v)
    selection = IndexSelection(project_id=v["project_id"], publication_id=head["publication_id"], model_config_id=v["index_config"].config_id)
    service = v["index_service"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        preview = service.preview(selection)
    assert preview["max_model_calls"] > 1
    calls = []
    def change_dimensions(request):
        data = json.loads(request.content)
        calls.append(data)
        dimensions = [1, 0, 1] if len(calls) == 1 else [1, 0]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": dimensions} for i in range(len(data["input"]))]})
    monkeypatch.setattr(service, "provider", HTTPIndexEmbedding(transport=httpx.MockTransport(change_dimensions)))
    pending = invoke(v, INDEX_BUILD_TOOL, preview["request"], key=uuid4().hex).json()
    assert confirm(v, pending).json()["status"] == "failed"
    assert len(calls) == 2 and count(v, Generation) == count(v, Document) == 0
    assert count(v, Reservation) == 1


def test_agent_preview_observation_revalidates_consent_instead_of_trusting_old_receipt(indexed):
    v = indexed
    observer = app.state.container.tool_evidence
    with actor_scope(UserProfile.model_validate(v["owner"])):
        current = observer.describe(v["index_preview_invocation"], v["project_id"])
        assert current == v["index_preview"] and not v["index_calls"]
    service = v["index_service"]
    service.models.repository.save_model_config(v["index_config"].model_copy(update={"updated_at": "changed"}), v["index_encrypted"])
    from apps.api.app.application.platform.errors import PlatformApplicationError
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PlatformApplicationError, match="Index preview changed"):
            observer.describe(v["index_preview_invocation"], v["project_id"])
    assert not v["index_calls"] and count(v, Reservation) == 0
