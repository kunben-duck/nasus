import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import math
import json
import time
from uuid import uuid4

from ...domain.platform.llm_call import LLMCall
from ...domain.system_image.evidence import text_digest
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ...domain.system_image.retrieval_index import BATCH_SIZE, CHUNK_BYTES, INDEX_METHOD, IndexDocument, IndexConfigurationChanged, validate_vectors
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import snapshot_digest
from ..platform.model_execution_profiles import ModelExecutionProfileApplicationService
from .index_inputs import FrozenIndexInputs, IndexSelection, IndexBuildRequest, INDEX_BUILD_TOOL
from .context_retrieval_inputs import ContextRetrievalInputs, ContextRetrievalSelection
from .index_ports import IndexEmbeddingPort, FrozenIndexRepositoryPort, FrozenIndexArtifactPort, IndexEmbeddingFailure
from .publication_read_models import PublishedImagePin
from .retrieval import SystemImageMemoryHit, SystemImageMemorySearchResult


class FrozenIndexApplicationService:
    """Confirmed immutable generations; a build never mutates a publication or business authority."""

    def __init__(self, images, publications, published, models: ModelExecutionProfileApplicationService,
                 provider: IndexEmbeddingPort, repository: FrozenIndexRepositoryPort,
                 artifacts: FrozenIndexArtifactPort, audit):
        self.images, self.publications, self.published = images, publications, published
        self.models, self.provider, self.repository, self.artifacts, self.audit = models, provider, repository, artifacts, audit
        self.inputs = FrozenIndexInputs(images)

    def _scope(self, project_id, *, exporting=False):
        scope = self.images.authorization.scope(project_id)
        if exporting and scope.effective_project_role not in {"platform_admin", "project_admin"}:
            raise SourceAccessDenied("index model egress requires a project administrator")
        return scope

    def _preview(self, selection, pin, docs, digest, model):
        request = IndexBuildRequest(**selection.model_dump(), input_digest=digest, model_config_digest=model.binding.config_digest)
        return {"request": request.model_dump(), "publication_pin": pin.model_dump(), "model": asdict(model.binding),
            "source_binding_ids": sorted({doc.binding_id for doc in docs}), "document_count": len(docs),
            "input_bytes": sum(len(doc.text.encode()) for doc in docs), "max_model_calls": math.ceil(len(docs) / BATCH_SIZE),
            "batch_size": BATCH_SIZE, "timeout_per_call_seconds": 60, "cost_estimate_available": False,
            "query_egress": "Authorized project retrieval queries use this exact embedding destination and config digest.",
            "rerank_egress_authorized": False, "quality_generation_authorized": False}

    def preview(self, selection: IndexSelection):
        scope = self._scope(selection.project_id, exporting=True)
        pin = self.publications.pin(selection.project_id, selection.publication_id, require_current=True)
        docs, digest = self.inputs.prepare(selection.project_id, pin)
        model = self.models.resolve(selection.model_config_id, route="embedding")
        self._require(scope, pin, model)
        return self._preview(selection, pin, docs, digest, model)

    def _require(self, scope, pin, model=None):
        self.images.authorization.require_current(scope)
        if self.publications.pin(scope.project_id, pin.publication_id, require_current=True) != pin:
            raise ImageRevisionIntegrityError("index publication changed")
        if model is not None:
            try:
                current = self.models.resolve(model.binding.config_id, route="embedding")
            except (KeyError, ValueError) as exc:
                raise IndexConfigurationChanged("index model configuration unavailable") from exc
            if current.binding != model.binding:
                raise IndexConfigurationChanged("index model configuration changed; rebuild with new consent")
        self.images.authorization.require_current(scope)

    async def _embed(self, texts, model, *, project_id, invocation_id=None, conversation_id=None, dimensions=None, purpose=None):
        started, reply, valid = time.monotonic(), None, False
        try:
            reply = await asyncio.wait_for(self.provider.embed(texts, model), timeout=60)
            validate_vectors(reply.vectors, len(texts), dimensions)
            valid = True
            return reply
        finally:
            call = LLMCall(id=str(uuid4()), occurred_at=datetime.now(timezone.utc), route="embedding",
                purpose=purpose or (INDEX_BUILD_TOOL if invocation_id else "system_image.index.query"), provider=model.binding.provider,
                model_name=model.binding.model_name, selected_provider=model.binding.provider,
                selected_model_name=model.binding.model_name, runtime_mode="live", outcome="success" if valid else "error",
                reason="native_embedding_completed" if valid else "native_embedding_failed_or_interrupted",
                project_id=project_id, tool_invocation_id=invocation_id, conversation_id=conversation_id,
                model_calls=1, input_item_count=len(texts), output_item_count=len(reply.vectors) if reply else 0,
                input_token_count=reply.input_tokens if reply else 0, usage_source=reply.usage_source if reply else "none",
                latency_ms=int((time.monotonic() - started) * 1000), request_hash=snapshot_digest(list(texts)),
                response_hash=snapshot_digest(reply.vectors) if reply else "")
            self.audit.persist_llm_call(call)

    async def build(self, request: IndexBuildRequest, *, invocation_id):
        scope = self._scope(request.project_id, exporting=True)
        reservation = await asyncio.to_thread(self.repository.reservation, request.project_id, invocation_id)
        if reservation:
            if reservation["request"] != request.model_dump():
                raise ImageRevisionIntegrityError("index invocation request changed")
            old = await asyncio.to_thread(self.repository.get, request.project_id, invocation_id)
            if old is None:
                raise ValueError("index was already reserved; uncertain or partial calls are not automatically retried")
            return await asyncio.to_thread(self.describe, request.project_id, invocation_id)
        pin = await asyncio.to_thread(self.publications.pin, request.project_id, request.publication_id, require_current=True)
        docs, digest = await asyncio.to_thread(self.inputs.prepare, request.project_id, pin)
        model = await asyncio.to_thread(self.models.resolve, request.model_config_id, route="embedding")
        if (request.input_digest, request.model_config_digest) != (digest, model.binding.config_digest):
            raise ImageRevisionIntegrityError("index consent pins changed; preview again")
        selection = IndexSelection.model_validate(request.model_dump(exclude={"input_digest", "model_config_digest"}))
        preview = self._preview(selection, pin, docs, digest, model)
        def current():
            self._require(scope, pin, model)
            self.repository.require_running(request, invocation_id)
        await asyncio.to_thread(self.repository.reserve, request, pin, preview, invocation_id=invocation_id,
            actor_id=scope.actor_id, require_current=current)
        vectors, dimensions = [], None
        for offset in range(0, len(docs), BATCH_SIZE):
            await asyncio.to_thread(current)
            texts = tuple(doc.text for doc in docs[offset:offset + BATCH_SIZE])
            reply = await self._embed(texts, model, project_id=request.project_id, invocation_id=invocation_id, dimensions=dimensions)
            batch = validate_vectors(reply.vectors, len(texts), dimensions)
            dimensions = len(batch[0])
            vectors.extend(batch)
            await asyncio.to_thread(current)
        payload = {"schema": "nasus.frozen-index.v1", "project_id": request.project_id, "generation_id": invocation_id,
            "request": request.model_dump(), "publication_pin": pin.model_dump(), "model": asdict(model.binding),
            "dimensions": dimensions, "documents": [{"document": asdict(doc), "vector_hash": snapshot_digest(list(vector))}
                for doc, vector in zip(docs, vectors)], "quality_generation_authorized": False}
        ref, artifact_hash = await asyncio.to_thread(self.artifacts.put, request.project_id, payload)
        await asyncio.to_thread(self.repository.complete, request, invocation_id=invocation_id, documents=docs, vectors=vectors,
            artifact_ref=ref, artifact_hash=artifact_hash, require_current=current)
        return await asyncio.to_thread(self.describe, request.project_id, invocation_id)

    def _read(self, project_id, record):
        scope = self._scope(project_id)
        reservation = self.repository.reservation(project_id, record["generation_id"])
        payload = self.artifacts.read(project_id, record["artifact_ref"], record["artifact_hash"])
        if (payload.get("schema") != "nasus.frozen-index.v1" or payload.get("generation_id") != record["generation_id"]
                or not reservation or payload.get("request") != reservation["request"]
                or payload.get("publication_pin") != reservation["pin"] or payload.get("model") != reservation["preview"]["model"]
                or payload.get("dimensions") != record["dimensions"] or len(payload.get("documents", [])) != record["document_count"]
                or payload.get("quality_generation_authorized") is not False):
            raise ImageRevisionIntegrityError("index generation manifest mismatch")
        pin = self.publications.pin(project_id, record["publication_id"], require_current=False)
        if pin.model_dump() != payload["publication_pin"]:
            raise ImageRevisionIntegrityError("index publication membership mismatch")
        docs = [IndexDocument(**item["document"]) for item in payload["documents"]]
        if (len({doc.document_id for doc in docs}) != len(docs)
                or any(text_digest(doc.text) != doc.text_hash for doc in docs)
                or snapshot_digest({"method": INDEX_METHOD, "publication": pin.model_dump(), "documents": [asdict(doc) for doc in docs]})
                    != reservation["request"]["input_digest"]):
            raise ImageRevisionIntegrityError("index documents do not match consent")
        self.images.authorization.require_current(scope)
        return payload

    def describe(self, project_id, generation_id):
        self._scope(project_id)
        record = self.repository.get(project_id, generation_id)
        if record is None:
            raise KeyError("completed index not found")
        payload = self._read(project_id, record)
        return {key: payload[key] for key in ("project_id", "generation_id", "request", "publication_pin", "model", "dimensions", "quality_generation_authorized")} | {
            "document_count": record["document_count"], "artifact_hash": record["artifact_hash"]}

    def status(self, project_id, publication_id):
        """Inspect the exact current head without a provider call or implicit rebuild."""
        scope = self._scope(project_id)
        pin = self.publications.pin(project_id, publication_id, require_current=True)
        record = self.repository.latest(project_id, publication_id)
        generation, state = None, "not_built"
        if record is not None:
            generation = self.describe(project_id, record["generation_id"])
            if generation["publication_pin"] != pin.model_dump():
                raise ImageRevisionIntegrityError("index status publication mismatch")
            try:
                model = self.models.resolve(generation["model"]["config_id"], route="embedding")
                compatible = asdict(model.binding) == generation["model"]
            except (KeyError, ValueError):
                compatible = False
            state = "ready" if compatible else "rebuild_required"
        self._require(scope, pin)
        return {"project_id": project_id, "publication_pin": pin.model_dump(), "state": state,
            "generation": generation, "can_build": scope.effective_project_role in {"platform_admin", "project_admin"},
            "quality_generation_authorized": False}

    def context_retrieval_preview(self, selection: ContextRetrievalSelection):
        return self.prepare_context_retrieval(selection)[-1]

    def prepare_context_retrieval(self, selection: ContextRetrievalSelection):
        scope = self._scope(selection.project_id, exporting=True)
        pin = self.publications.pin(selection.project_id, selection.publication_id, require_current=True)
        record = self.repository.get(selection.project_id, selection.generation_id)
        if record is None:
            raise KeyError("completed context retrieval index not found")
        index = self._read(selection.project_id, record)
        if index["publication_pin"] != pin.model_dump():
            raise ImageRevisionIntegrityError("context retrieval index belongs to a different publication")
        model = self.models.resolve(index["model"]["config_id"], route="embedding")
        if asdict(model.binding) != index["model"]:
            raise IndexConfigurationChanged("context retrieval model changed; rebuild with new consent")
        self._require(scope, pin, model)
        queries, preview = ContextRetrievalInputs(self.images).prepare(selection, pin, index, record["artifact_hash"])
        body = {key: value for key, value in preview.items() if key != "plan_digest"}
        body.update(scope_fingerprint=scope.fingerprint, acl_epoch=scope.acl_epoch)
        preview = {**body, "plan_digest": snapshot_digest(body)}
        self._require(scope, pin, model)
        return scope, pin, record, index, model, queries, preview

    def collect_candidates(self, scope, index, query, vector, *, limit):
        candidates = self.repository.search(index, query, vector,
            binding_ids=scope.binding_ids, limit=min(4096, max(72, limit * 9)))
        documents = {item["document"]["document_id"]: item["document"] for item in index["documents"]}
        if (len(candidates) > min(4096, max(72, limit * 9))
                or len({item["document"]["document_id"] for item in candidates}) != len(candidates)):
            raise ImageRevisionIntegrityError("retrieval adapter returned duplicate or excessive candidates")
        selected, seen = [], set()
        for candidate in candidates:
            document = candidate["document"]
            if (documents.get(document["document_id"]) != document
                    or type(candidate["score"]) not in {int, float} or not math.isfinite(candidate["score"]) or candidate["score"] < 0):
                raise ImageRevisionIntegrityError("retrieval adapter returned an unpinned document")
            if document["binding_id"] not in scope.binding_ids:
                raise SourceAccessDenied("index adapter returned a forbidden source")
            if document["object_id"] not in seen and len(selected) < limit:
                selected.append(candidate)
            seen.add(document["object_id"])
        return candidates, selected

    def archive_trace(self, scope, pin, record, index, query, vector, candidates, selected, retrieval_id):
        payload = {"schema": "nasus.frozen-retrieval.v1", "project_id": scope.project_id, "retrieval_id": retrieval_id,
            "publication_pin": pin.model_dump(), "generation_id": record["generation_id"], "index_artifact_hash": record["artifact_hash"],
            "model": index["model"], "query": query, "query_vector_hash": snapshot_digest(list(vector)) if vector else None,
            "scope_fingerprint": scope.fingerprint, "acl_epoch": scope.acl_epoch,
            "strategy": "published_hybrid_rrf_rerank_withheld" if vector else "published_lexical_embedding_unavailable",
            "embedding_fallback_reason": None if vector else "embedding_provider_unavailable",
            "candidates": candidates, "selected": selected, "relationship_authority": False}
        ref, digest = self.artifacts.put(scope.project_id, payload)
        return {"retrieval_id": retrieval_id, "project_id": scope.project_id,
            "generation_id": record["generation_id"], "publication_id": pin.publication_id, "actor_id": scope.actor_id,
            "scope_fingerprint": scope.fingerprint, "query_hash": text_digest(query), "artifact_ref": ref,
            "artifact_hash": digest, "created_at": datetime.now(timezone.utc).isoformat()}

    def _verified_trace(self, project_id, retrieval_id):
        scope = self._scope(project_id)
        row = self.repository.trace(project_id, retrieval_id)
        if row["actor_id"] != scope.actor_id and scope.effective_project_role not in {"project_admin", "platform_admin"}:
            raise SourceAccessDenied("retrieval query belongs to another actor")
        generation = self.repository.get(project_id, row["generation_id"])
        if generation is None:
            raise ImageRevisionIntegrityError("retrieval generation missing")
        index = self._read(project_id, generation)
        payload = self.artifacts.read(project_id, row["artifact_ref"], row["artifact_hash"])
        if (payload.get("schema") != "nasus.frozen-retrieval.v1" or payload.get("retrieval_id") != retrieval_id
                or payload.get("project_id") != project_id or payload.get("relationship_authority") is not False
                or payload.get("generation_id") != row["generation_id"]
                or payload.get("index_artifact_hash") != generation["artifact_hash"]
                or payload.get("publication_pin") != index["publication_pin"]
                or payload.get("publication_pin", {}).get("publication_id") != row["publication_id"]
                or text_digest(payload.get("query", "")) != row["query_hash"]
                or payload.get("model") != index["model"] or payload.get("scope_fingerprint") != row["scope_fingerprint"]):
            raise ImageRevisionIntegrityError("retrieval trace integrity mismatch")
        documents = {item["document"]["document_id"]: item["document"] for item in index["documents"]}
        for item in (*payload["candidates"], *payload["selected"]):
            if (documents.get(item["document"]["document_id"]) != item["document"]
                    or type(item["score"]) not in {int, float} or not math.isfinite(item["score"]) or item["score"] < 0):
                raise ImageRevisionIntegrityError("retrieval trace document mismatch")
        candidate_ids = [item["document"]["document_id"] for item in payload["candidates"]]
        selected_ids = [item["document"]["document_id"] for item in payload["selected"]]
        if (len(candidate_ids) != len(set(candidate_ids)) or len(selected_ids) != len(set(selected_ids))
                or not set(selected_ids) <= set(candidate_ids)):
            raise ImageRevisionIntegrityError("retrieval trace selection mismatch")
        self.images.authorization.require_current(scope)
        return scope, row, generation, payload

    def replay_candidates(self, project_id, retrieval_id, publication_pin, *, historical=False):
        """Application-only bounded replay. No provider calls, source text or implicit requery."""
        scope, row, generation, payload = self._verified_trace(project_id, retrieval_id)
        if payload["publication_pin"] != publication_pin:
            raise ImageRevisionIntegrityError("retrieval trace belongs to a different context publication")
        if not historical:
            self.require_replay_current(project_id, payload)
        result = {"retrieval_id": retrieval_id, "artifact_hash": row["artifact_hash"],
            "generation_id": generation["generation_id"], "index_artifact_hash": generation["artifact_hash"],
            "publication_pin": payload["publication_pin"], "model": payload["model"], "query_hash": row["query_hash"],
            "strategy": payload["strategy"], "embedding_fallback_reason": payload["embedding_fallback_reason"],
            "candidates": [{"document": {key: value for key, value in item["document"].items() if key != "text"},
                "score": item["score"]} for item in payload["candidates"]],
            # A saved search has a bounded pool, not an exhaustive semantic corpus.
            "pool_may_be_truncated": len(payload["candidates"]) < generation["document_count"],
            "relationship_authority": False}
        self.images.authorization.require_current(scope)
        return result

    def require_replay_current(self, project_id, replay):
        scope = self._scope(project_id)
        try:
            model = self.models.resolve(replay["model"]["config_id"], route="embedding")
        except (KeyError, ValueError) as exc:
            raise IndexConfigurationChanged("retrieval model is no longer available") from exc
        if asdict(model.binding) != replay["model"]:
            raise IndexConfigurationChanged("retrieval model configuration changed")
        self._require(scope, PublishedImagePin.model_validate(replay["publication_pin"]), model)

    def read_trace(self, project_id, retrieval_id, *, offset=0, limit=25):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("invalid retrieval trace page")
        scope, _, _, payload = self._verified_trace(project_id, retrieval_id)
        if offset > len(payload["candidates"]):
            raise ValueError("retrieval trace page is outside the candidate list")
        end = min(offset + limit, len(payload["candidates"]))
        result = {key: value for key, value in payload.items() if key not in {"candidates", "selected"}}
        result.update(selected_document_ids=[item["document"]["document_id"] for item in payload["selected"]],
            candidates=[{"document": {key: value for key, value in item["document"].items() if key != "text"}, "score": item["score"]}
                for item in payload["candidates"][offset:end]], total_candidates=len(payload["candidates"]),
            next_offset=end if end < len(payload["candidates"]) else None)
        if len(json.dumps(result, ensure_ascii=False).encode()) > 65536:
            raise ImageRevisionPageTooLarge("retrieval trace page exceeds 64 KiB; request fewer candidates")
        self.images.authorization.require_current(scope)
        return result

    async def search(self, published, query, *, limit=8, trace=False, conversation_id=None):
        pin = published.state.pin
        if pin is None:
            return None
        project_id = published.scope.project_id
        self.published.require_current(published)
        record = await asyncio.to_thread(self.repository.latest, project_id, pin.publication_id)
        if record is None:
            return None
        if not query or len(query.encode()) > CHUNK_BYTES or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("versioned query exceeds the retrieval budget")
        payload = await asyncio.to_thread(self._read, project_id, record)
        if payload["publication_pin"] != pin.model_dump():
            raise ImageRevisionIntegrityError("retrieval index belongs to a different publication")
        model = await asyncio.to_thread(self.models.resolve, payload["model"]["config_id"], route="embedding")
        if asdict(model.binding) != payload["model"]:
            raise ImageRevisionIntegrityError("index model changed; explicitly rebuild before semantic retrieval")
        def current():
            self.published.require_current(published)
            self._require(published.scope, pin, model)
        await asyncio.to_thread(current)
        strategy, fallback_reason = "published_hybrid_rrf_rerank_withheld", None
        try:
            reply = await self._embed((query,), model, project_id=project_id, conversation_id=conversation_id, dimensions=payload["dimensions"])
            vector = validate_vectors(reply.vectors, 1, payload["dimensions"])[0]
        except IndexEmbeddingFailure:
            vector = None
            strategy, fallback_reason = "published_lexical_embedding_unavailable", "embedding_provider_unavailable"
        await asyncio.to_thread(current)
        candidates, selected = await asyncio.to_thread(self.collect_candidates, published.scope, payload, query, vector, limit=limit)
        refs = ()
        if trace:
            retrieval_id = str(uuid4())
            row = await asyncio.to_thread(self.archive_trace, published.scope, pin, record, payload, query, vector,
                candidates, selected, retrieval_id)
            await asyncio.to_thread(self.repository.append_trace, row, require_current=current)
            refs = (f"image_retrieval_run:{retrieval_id}",)
        await asyncio.to_thread(current)
        return SystemImageMemorySearchResult(hits=tuple(SystemImageMemoryHit(
            ref=f"image_revision:{pin.image_revision_id}:context_object:{item['document']['object_id']}", kind="context_object",
            score=item["score"], summary=(f"index_generation={record['generation_id']}; evidence={item['document']['evidence_id']}; "
                f"source_revision={item['document']['source_revision_id']}; chunk={item['document']['ordinal']}; "
                f"text_hash={item['document']['text_hash']}; retrieved_not_asserted"))
            for item in selected), retrieval_run_refs=refs, image_read_state=published.state,
            strategy=strategy)
