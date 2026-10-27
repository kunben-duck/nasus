import asyncio
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from ...domain.system_image.evidence import text_digest
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.retrieval_index import BATCH_SIZE, validate_vectors
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import snapshot_digest
from .context_retrieval_inputs import ContextRetrievalSelection
from .context_retrieval_ports import CONTEXT_RETRIEVE_TOOL, ContextRetrievalRequest, UncertainContextBatch
from .index_ports import IndexEmbeddingFailure


class ContextRetrievalApplicationService:
    """Complete AC query execution, with durable egress reservations and atomic trace publication."""

    def __init__(self, indexes, repository):
        self.indexes, self.repository = indexes, repository

    async def execute(self, request: ContextRetrievalRequest, *, invocation_id):
        scope = await asyncio.to_thread(self.indexes._scope, request.project_id, exporting=True)
        existing = await asyncio.to_thread(self.repository.result, request.project_id, invocation_id)
        if existing is not None:
            if existing["plan"]["request"] != request.model_dump() or existing["plan"]["actor_id"] != scope.actor_id:
                raise ImageRevisionIntegrityError("context retrieval recovery request changed")
            return await asyncio.to_thread(self.read, request.project_id, invocation_id)
        await asyncio.to_thread(self.repository.require_running, request, invocation_id, scope.actor_id)
        selection = ContextRetrievalSelection.model_validate(request.model_dump(exclude={"expected_plan_digest"}))
        scope, pin, record, index, model, queries, preview = await asyncio.to_thread(self.indexes.prepare_context_retrieval, selection)
        if preview["plan_digest"] != request.expected_plan_digest or not queries:
            raise ImageRevisionIntegrityError("context retrieval needs the complete nonempty confirmed query plan")

        def current():
            _, _, actor = self.repository.execution(invocation_id)
            # Reload the account as well as source/project ACLs on every egress
            # and commit boundary; a worker's initial identity is not a grant.
            from ..platform.actor_context import actor_scope
            with actor_scope(actor):
                fresh_scope = self.indexes._scope(request.project_id, exporting=True)
                if fresh_scope.fingerprint != scope.fingerprint or actor.id != scope.actor_id:
                    raise SourceAccessDenied("context retrieval actor scope changed")
            self.indexes._require(scope, pin, model)
            self.repository.require_running(request, invocation_id, scope.actor_id)

        await asyncio.to_thread(self.repository.prepare, request, preview, invocation_id=invocation_id,
            actor_id=scope.actor_id, require_current=current)
        traces, bindings, receipts, batches = [], {}, [], []
        for offset in range(0, len(queries), BATCH_SIZE):
            subset, ordinal = queries[offset:offset + BATCH_SIZE], offset // BATCH_SIZE
            identity = {"schema": "nasus.context-retrieval-batch.v1", "project_id": request.project_id,
                "invocation_id": invocation_id, "plan_digest": preview["plan_digest"], "ordinal": ordinal,
                "queries": [{"target_id": item.target_object_id, "query_hash": text_digest(item.text)} for item in subset]}
            digest = snapshot_digest(identity)
            owner = str(uuid4())
            await asyncio.to_thread(current)
            claimed = await asyncio.to_thread(self.repository.reserve_batch, request, invocation_id, ordinal, digest, owner,
                actor_id=scope.actor_id, require_current=current)
            if claimed:
                try:
                    reply = await self.indexes._embed(tuple(item.text for item in subset), model, project_id=request.project_id,
                        invocation_id=invocation_id, dimensions=index["dimensions"], purpose=CONTEXT_RETRIEVE_TOOL)
                    vectors = [list(vector) for vector in validate_vectors(reply.vectors, len(subset), index["dimensions"])]
                except IndexEmbeddingFailure:
                    vectors = None
                await asyncio.to_thread(current)
                body = {**identity, "vectors": vectors, "fallback_reason": None if vectors is not None else "embedding_provider_unavailable"}
                ref, artifact_hash = await asyncio.to_thread(self.indexes.artifacts.put, request.project_id, body)
                await asyncio.to_thread(self.repository.complete_batch, request, invocation_id, ordinal, owner, ref, artifact_hash,
                    actor_id=scope.actor_id, require_current=current)
            # Another attempt may still be completing a reserved call. Wait for its
            # durable result, but never reissue an ambiguous provider request.
            while True:
                await asyncio.to_thread(current)
                batch = await asyncio.to_thread(self.repository.batch, request.project_id, invocation_id, ordinal)
                if batch is None or batch["input_digest"] != digest:
                    raise ImageRevisionIntegrityError("context retrieval batch input changed")
                if batch["artifact_ref"]:
                    break
                if batch["expires_at"] <= datetime.now(timezone.utc):
                    raise UncertainContextBatch("reserved embedding call has no durable outcome; explicit new consent is required")
                await asyncio.sleep(0.25)
            body = await asyncio.to_thread(self.indexes.artifacts.read, request.project_id, batch["artifact_ref"], batch["artifact_hash"])
            if any(body.get(key) != value for key, value in identity.items()):
                raise ImageRevisionIntegrityError("context retrieval batch artifact mismatch")
            vectors = body.get("vectors")
            if vectors is None:
                if body.get("fallback_reason") != "embedding_provider_unavailable":
                    raise ImageRevisionIntegrityError("context retrieval batch lacks an explicit fallback")
            else:
                if body.get("fallback_reason") is not None:
                    raise ImageRevisionIntegrityError("context retrieval batch has inconsistent fallback")
                vectors = validate_vectors(vectors, len(subset), index["dimensions"])
            batches.append({"ordinal": ordinal, "artifact_hash": batch["artifact_hash"], "fallback": vectors is None})
            for position, query in enumerate(subset):
                await asyncio.to_thread(current)
                vector = vectors[position] if vectors is not None else None
                candidates, selected = await asyncio.to_thread(self.indexes.collect_candidates, scope, index, query.text, vector, limit=100)
                retrieval_id = str(uuid5(NAMESPACE_URL, f"nasus-context-retrieval:{invocation_id}:{query.target_object_id}"))
                trace = await asyncio.to_thread(self.indexes.archive_trace, scope, pin, record, index, query.text, vector,
                    candidates, selected, retrieval_id)
                traces.append(trace)
                bindings[query.target_object_id] = retrieval_id
                receipts.append({"target_id": query.target_object_id, "query_hash": text_digest(query.text),
                    "retrieval_id": retrieval_id, "artifact_hash": trace["artifact_hash"]})
        metadata = {"schema": "nasus.context-retrieval.v1", "project_id": request.project_id, "invocation_id": invocation_id,
            "publication_pin": pin.model_dump(), "generation_id": request.generation_id, "index_artifact_hash": record["artifact_hash"],
            "model": index["model"], "plan_digest": preview["plan_digest"], "queries_digest": preview["queries_digest"],
            "query_count": len(queries), "retrieval_bindings": bindings, "queries": receipts, "batches": batches,
            "relationship_authority": False, "quality_generation_authorized": False, "rerank_egress_authorized": False}
        ref, artifact_hash = await asyncio.to_thread(self.indexes.artifacts.put, request.project_id, metadata)
        await asyncio.to_thread(self.repository.complete, request, invocation_id, traces, metadata, ref, artifact_hash,
            actor_id=scope.actor_id, require_current=current)
        return metadata

    def read(self, project_id, invocation_id):
        scope = self.indexes._scope(project_id)
        result = self.repository.result(project_id, invocation_id)
        if result is None:
            raise KeyError("completed context retrieval not found")
        plan, metadata = result["plan"], result["metadata"]
        if plan["actor_id"] != scope.actor_id and scope.effective_project_role not in {"platform_admin", "project_admin"}:
            raise SourceAccessDenied("context retrieval belongs to another actor")
        artifact = self.indexes.artifacts.read(project_id, result["artifact_ref"], result["artifact_hash"])
        preview = plan["preview"]
        if (artifact != metadata or metadata.get("schema") != "nasus.context-retrieval.v1"
                or metadata.get("project_id") != project_id or metadata.get("invocation_id") != invocation_id
                or any(metadata.get(key) != preview[key] for key in
                    ("publication_pin", "model", "plan_digest", "queries_digest", "query_count", "index_artifact_hash"))
                or metadata.get("generation_id") != plan["request"]["generation_id"]
                or any(metadata.get(key) is not False for key in
                    ("relationship_authority", "quality_generation_authorized", "rerank_egress_authorized"))
                or len(metadata["queries"]) != preview["query_count"]
                or {item["target_id"]: item["retrieval_id"] for item in metadata["queries"]} != metadata["retrieval_bindings"]):
            raise ImageRevisionIntegrityError("context retrieval completed mapping mismatch")
        for item in metadata["queries"]:
            trace = self.indexes.replay_candidates(project_id, item["retrieval_id"], metadata["publication_pin"], historical=True)
            if (trace["artifact_hash"] != item["artifact_hash"] or trace["query_hash"] != item["query_hash"]
                    or trace["generation_id"] != metadata["generation_id"] or trace["model"] != metadata["model"]):
                raise ImageRevisionIntegrityError("context retrieval trace pin mismatch")
        self.indexes.images.authorization.require_current(scope)
        return metadata
