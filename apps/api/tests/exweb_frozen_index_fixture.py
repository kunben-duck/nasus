"""Fixed exweb + real PG/MinIO; embedding vectors are explicit transport fixtures, not quality gold."""
import asyncio
from datetime import datetime, timezone
import json
from uuid import uuid4

import httpx

from apps.api.app.application.system_image.frozen_indexes import FrozenIndexApplicationService
from apps.api.app.application.system_image.index_inputs import IndexSelection, IndexBuildRequest, INDEX_BUILD_TOOL
from apps.api.app.application.system_image.context_retrieval_inputs import ContextRetrievalSelection
from apps.api.app.application.system_image.context_retrieval import ContextRetrievalApplicationService
from apps.api.app.application.system_image.context_retrieval_ports import ContextRetrievalRequest, CONTEXT_RETRIEVE_TOOL
from apps.api.app.infrastructure.persistence.context_retrieval_repository import ContextRetrievalRepository
from apps.api.app.infrastructure.llm.index_embedding import HTTPIndexEmbedding
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.frozen_index_repository import FrozenIndexRepository
from apps.api.app.infrastructure.persistence.llm_call_repository import SQLAlchemyLLMCallRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.frozen_index_artifacts import FrozenIndexArtifacts
from apps.api.tests.test_semantic_link_model import saved_config


def build_exweb_index(images, publications, published, profiles, storage, head):
    project_id = head["project_id"]
    config = saved_config(config_id=str(uuid4()), route="embedding")
    profiles.repository.save_model_config(config, "explicit-index-fixture-key")
    calls = []
    def response(request):
        body = json.loads(request.content)
        calls.append(len(body["input"]))
        return httpx.Response(200, json={"model": config.model_name,
            "data": [{"index": i, "embedding": [1, 0.25, 0.75]} for i in range(len(body["input"]))]})
    service = FrozenIndexApplicationService(images, publications, published, profiles,
        HTTPIndexEmbedding(transport=httpx.MockTransport(response)), FrozenIndexRepository(),
        FrozenIndexArtifacts(storage), SQLAlchemyLLMCallRepository())
    preview = service.preview(IndexSelection(project_id=project_id, publication_id=head["publication_id"], model_config_id=config.config_id))
    assert not calls and preview["document_count"] >= 725
    assert len(preview["source_binding_ids"]) == 3
    request = IndexBuildRequest.model_validate(preview["request"])
    invocation_id = str(uuid4())
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation_id, tool_id=INDEX_BUILD_TOOL, status="running",
            summary="Explicit static exweb native embedding transport fixture", input_payload={**request.model_dump(),
                "confirmed_by_user": True, "confirmed_at": datetime.now(timezone.utc).isoformat()}))
    result = asyncio.run(service.build(request, invocation_id=invocation_id))
    assert len(calls) == preview["max_model_calls"] and sum(calls) == result["document_count"]
    record = service.repository.get(project_id, invocation_id)
    assert record["artifact_ref"].startswith("s3://")
    artifact = service.artifacts.read(project_id, record["artifact_ref"], record["artifact_hash"])
    indexed_code = {item["document"]["object_id"] for item in artifact["documents"] if item["document"]["kind"] == "code_entity"}
    assert len(indexed_code) == 725
    assert len({item["document"]["binding_id"] for item in artifact["documents"]}) == 3
    found = asyncio.run(service.search(published.read(project_id), "ChatController", trace=True))
    assert found.hits and found.retrieval_run_refs and found.image_read_state.pin.publication_id == head["publication_id"]
    trace = service.read_trace(project_id, found.retrieval_run_refs[0].split(":", 1)[1])
    assert trace["index_artifact_hash"] == result["artifact_hash"]
    calls_before = len(calls)
    assert asyncio.run(service.build(request, invocation_id=invocation_id)) == result
    assert len(calls) == calls_before
    context_query_plan = service.context_retrieval_preview(ContextRetrievalSelection(
        project_id=project_id, publication_id=head["publication_id"], generation_id=invocation_id))
    assert context_query_plan["query_count"] == 1 and context_query_plan["state"] == "prepared"
    assert context_query_plan["input_bytes"] > 0 and context_query_plan["max_model_calls"] == 1
    assert context_query_plan["model_calls_made"] == 0 and context_query_plan["execution_available"] is True
    assert len(calls) == calls_before
    queries = ContextRetrievalApplicationService(service, ContextRetrievalRepository())
    query_request = ContextRetrievalRequest(**context_query_plan["request"], expected_plan_digest=context_query_plan["plan_digest"])
    query_id = str(uuid4())
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=query_id, tool_id=CONTEXT_RETRIEVE_TOOL, status="running",
            summary="Explicit exweb AC query execution fixture; not business approval", input_payload={**query_request.model_dump(),
                "confirmed_by_user": True, "confirmed_at": datetime.now(timezone.utc).isoformat(),
                "confirmed_actor_id": images.authorization.scope(project_id).actor_id}))
    query_result = asyncio.run(queries.execute(query_request, invocation_id=query_id))
    assert len(calls) == calls_before + 1 and len(query_result["retrieval_bindings"]) == 1
    query_record = queries.repository.result(project_id, query_id)
    assert query_record["artifact_ref"].startswith("s3://")
    assert queries.read(project_id, query_id) == query_result
    assert asyncio.run(queries.execute(query_request, invocation_id=query_id)) == query_result
    assert len(calls) == calls_before + 1
    report = {"metadata": result, "indexed_code_objects": len(indexed_code), "source_bindings": 3,
        "native_batches": preview["max_model_calls"], "document_count": result["document_count"],
        "input_bytes": preview["input_bytes"], "minio_roundtrip_verified": True,
        "pgvector_fts_trace_verified": True, "retrieval_run_refs": list(found.retrieval_run_refs),
        "lost_completion_no_duplicate_egress": True,
        "context_query_plan": context_query_plan,
        "context_retrieval": {"result": query_result, "minio_roundtrip_verified": True,
            "lost_completion_no_duplicate_egress": True, "native_query_batches": 1,
            "canonical_actor_fixture": True, "temporal_execution": False},
        "embedding_basis": "explicit_constant_vector_transport_fixture_not_real_model_or_semantic_gold",
        "quality_generation_authorized": False}
    return service, result, report
