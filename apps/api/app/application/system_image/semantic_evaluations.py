from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
import time
from typing import Callable, Literal, Optional, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from ...domain.platform.llm_call import LLMCall
from ...domain.system_image.evidence import text_digest
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.semantic_link_input import SEMANTIC_LINK_METHOD
from ...domain.system_image.source_access import SourceAccessDenied
from ...domain.system_image.source_snapshots import snapshot_digest
from ..platform.llm_calls import LLMCallAuditPort
from ..platform.model_execution_profiles import ModelExecutionProfileApplicationService
from .semantic_link_inputs import SemanticLinkInputApplicationService
from .semantic_link_output import validate_semantic_output
from .semantic_model_port import SemanticModelPort, SEMANTIC_TIMEOUT_SECONDS
from .semantic_screening import SemanticScreeningItem
from .image_query_models import ImageScreenedCandidatesReceipt


SEMANTIC_PREVIEW_TOOL = "query.system_image.links.evaluation_preview"
SEMANTIC_EVALUATE_TOOL = "system_image.links.evaluate"
SEMANTIC_REPORT_SCHEMA = "nasus.semantic-evaluation.v1"


class SemanticSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    project_id: str = Field(min_length=1, max_length=128)
    image_revision_id: str = Field(min_length=1, max_length=128)
    target_object_id: str = Field(min_length=1, max_length=128)
    relation: Literal["implements", "asserts"]
    subject_object_ids: list[str] = Field(min_length=1, max_length=30)
    expected_image_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model_config_id: str = Field(min_length=1, max_length=128)
    recall_limit: int = Field(default=30, ge=1, le=100)
    recall_invocation_id: Optional[str] = Field(default=None, min_length=1, max_length=128)

    @model_serializer(mode="wrap")
    def serialize_request(self, handler):
        result = handler(self)
        # Keep legacy selection/request hashes byte-compatible.
        for field in ("recall_invocation_id", "review_scope_digest"):
            if result.get(field) is None:
                result.pop(field, None)
        return result


class SemanticEvaluationRequest(SemanticSelection):
    input_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model_config_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    review_scope_digest: Optional[str] = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

class SemanticPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: SemanticEvaluationRequest
    provider: str
    model_name: str
    destination: str
    source_binding_ids: list[str]
    input_bytes: int
    max_model_calls: Literal[1] = 1
    timeout_seconds: Literal[60] = 60
    max_output_tokens: Literal[8192] = 8192
    method_version: Literal["nasus.semantic-link-judgment.v1"] = SEMANTIC_LINK_METHOD
    purpose: Literal["source_egress_for_proposed_semantic_review"] = "source_egress_for_proposed_semantic_review"
    cost_estimate_available: Literal[False] = False
    review_screening: list[SemanticScreeningItem] = Field(default_factory=list)


class SemanticEvaluationRepositoryPort(Protocol):
    def get(self, project_id: str, invocation_id: str): ...
    def list_for_target(self, project_id: str, image_revision_id: str, target_object_id: str, relation: str, after_id: str, limit: int): ...
    def reserve(self, request, preview, prepared, *, invocation_id, actor_id, require_current: Callable[[], None]): ...
    def complete(self, request, *, invocation_id, artifact_ref, artifact_hash, require_current: Callable[[], None]): ...


class SemanticEvaluationArtifactPort(Protocol):
    def put(self, project_id: str, payload: dict) -> tuple[str, str]: ...
    def read(self, project_id: str, ref: str, digest: str) -> dict: ...


class SemanticRecallObservationPort(Protocol):
    def semantic_recall(self, project_id: str, invocation_id: str, *, verify_result: bool) -> ImageScreenedCandidatesReceipt: ...


class SemanticEvaluationApplicationService:
    def __init__(self, images, models: ModelExecutionProfileApplicationService, provider: SemanticModelPort,
                 repository: SemanticEvaluationRepositoryPort, artifacts: SemanticEvaluationArtifactPort, audit: LLMCallAuditPort):
        self.images, self.models, self.provider = images, models, provider
        self.repository, self.artifacts, self.audit = repository, artifacts, audit
        self.inputs = SemanticLinkInputApplicationService(images)
        self.decision_guard = None
        self.recall_observations: Optional[SemanticRecallObservationPort] = None

    def _prepare(self, request, *, historical=False):
        receipt = None
        if request.recall_invocation_id is not None:
            if self.recall_observations is None:
                raise RuntimeError("semantic recall observations are not configured")
            receipt = self.recall_observations.semantic_recall(request.project_id, request.recall_invocation_id,
                verify_result=not historical)
        return self.inputs.prepare(request.project_id, request.image_revision_id, request.target_object_id,
            relation=request.relation, subject_object_ids=tuple(request.subject_object_ids),
            expected_image_hash=request.expected_image_hash, recall_limit=request.recall_limit, recall_receipt=receipt)

    def _scope(self, project_id, *, exporting=False):
        scope = self.images.authorization.scope(project_id)
        if exporting and scope.effective_project_role not in {"project_admin", "platform_admin"}:
            raise SourceAccessDenied("model egress requires a project administrator")
        return scope

    def _screen(self, request):
        if self.decision_guard is None:
            raise RuntimeError("semantic review screening is not configured")
        return self.decision_guard.screen(request)

    def _preview(self, selection, prepared, model, screening):
        request = SemanticEvaluationRequest(**selection.model_dump(), input_digest=prepared.digest,
                                            model_config_digest=model.binding.config_digest, review_scope_digest=screening.digest)
        return SemanticPreview(request=request, provider=model.binding.provider, model_name=model.binding.model_name,
            destination=model.binding.base_url, source_binding_ids=sorted({item.binding_id for item in prepared.excerpts}),
            input_bytes=len(json.dumps(prepared.model_payload(), ensure_ascii=False).encode()), review_screening=list(screening.items))

    def preview(self, selection: SemanticSelection) -> SemanticPreview:
        scope = self._scope(selection.project_id, exporting=True)
        prepared = self._prepare(selection)
        screening = self._screen(selection)
        model = self.models.resolve(selection.model_config_id)
        result = self._preview(selection, prepared, model, screening)
        self.images.authorization.require_current(scope)
        return result

    async def evaluate(self, request: SemanticEvaluationRequest, *, invocation_id: str):
        scope = self._scope(request.project_id, exporting=True)
        saved = await asyncio.to_thread(self.repository.get, request.project_id, invocation_id)
        if saved is not None:
            if saved["request"] != request.model_dump():
                raise ImageRevisionIntegrityError("semantic invocation request changed")
            if saved.get("artifact_ref"):
                return await asyncio.to_thread(self.read, request.project_id, invocation_id)
            raise ValueError("semantic call was already reserved; unknown outcomes are not retried")
        prepared = await asyncio.to_thread(self._prepare, request)
        screening = await asyncio.to_thread(self._screen, request)
        if request.review_scope_digest != screening.digest:
            raise ImageRevisionIntegrityError("semantic review consent changed; preview and confirm again")
        screening.require_eligible()
        model = await asyncio.to_thread(self.models.resolve, request.model_config_id)
        if request.input_digest != prepared.digest or request.model_config_digest != model.binding.config_digest:
            raise ImageRevisionIntegrityError("semantic consent pins changed; preview and confirm again")
        selection = SemanticSelection.model_validate(request.model_dump(exclude={"input_digest", "model_config_digest", "review_scope_digest"}))
        preview = self._preview(selection, prepared, model, screening)
        def current():
            self.images.authorization.require_current(scope)
            self.decision_guard.require_current(screening)
            self.images.authorization.require_current(scope)
        await asyncio.to_thread(self.repository.reserve, request, preview, prepared, invocation_id=invocation_id,
                                actor_id=scope.actor_id, require_current=current)
        current()
        if (await asyncio.to_thread(self.models.resolve, request.model_config_id)).binding != model.binding:
            raise ImageRevisionIntegrityError("model changed after reservation; no source was sent")
        current()
        started = time.monotonic()
        reply, outcome = None, "error"
        try:
            reply = await asyncio.wait_for(self.provider.generate(prepared, model), timeout=SEMANTIC_TIMEOUT_SECONDS)
            evaluation = validate_semantic_output(prepared, reply.content)
            current()
            outcome = "success"
        finally:
            call = LLMCall(id=str(uuid4()), occurred_at=datetime.now(timezone.utc), route="chat", purpose="system_image.links.evaluate",
                provider=model.binding.provider, model_name=model.binding.model_name, selected_provider=model.binding.provider,
                selected_model_name=model.binding.model_name, runtime_mode="live", outcome=outcome,
                reason="semantic_output_validated" if outcome == "success" else "semantic_call_failed_or_interrupted",
                project_id=request.project_id, tool_invocation_id=invocation_id, prompt_id="nasus.semantic-link-judgment",
                prompt_version="v1", model_calls=1, request_hash=prepared.digest, response_hash=text_digest(reply.content) if reply else "",
                input_token_count=reply.input_tokens if reply else 0, output_token_count=reply.output_tokens if reply else 0,
                usage_source=reply.usage_source if reply else "none", latency_ms=int((time.monotonic() - started) * 1000))
            self.audit.persist_llm_call(call)
        payload = {"schema": SEMANTIC_REPORT_SCHEMA, "project_id": request.project_id, "invocation_id": invocation_id,
                   "request": request.model_dump(), "preview": preview.model_dump(), "model_output": reply.content,
                   "evaluation": asdict(evaluation), "evaluation_digest": evaluation.digest}
        current()
        ref, digest = await asyncio.to_thread(self.artifacts.put, request.project_id, payload)
        await asyncio.to_thread(self.repository.complete, request, invocation_id=invocation_id, artifact_ref=ref,
                                artifact_hash=digest, require_current=current)
        current()
        return self._view(request, prepared, evaluation, invocation_id, digest)

    @staticmethod
    def _view(request, prepared, evaluation, invocation_id, digest):
        fields = ("object_id", "revision_id", "source_revision_id", "evidence_id", "relative_path", "start_line", "end_line", "basis", "role", "field_index")
        return {"invocation_id": invocation_id, "artifact_hash": digest, "request": request.model_dump(),
                "evaluation": asdict(evaluation), "spans": [
                    {**{key: getattr(span, key) for key in fields}, "span_id": span.span_id, "text_hash": span.text_hash}
                    for span in prepared.excerpts]}

    def list_for_target(self, project_id, image_revision_id, target_object_id, relation, *, after_id="", limit=20):
        if (type(limit) is not int or not 1 <= limit <= 50 or not isinstance(after_id, str) or len(after_id) > 128
                or relation not in {"implements", "asserts"}):
            raise ValueError("invalid semantic history page")
        scope = self._scope(project_id)
        header, members = self.images.frozen_document_members(project_id, image_revision_id)
        if not any(member["object_id"] == target_object_id for member in members):
            raise KeyError("semantic target not found")
        rows = self.repository.list_for_target(project_id, image_revision_id, target_object_id, relation, after_id, limit + 1)
        self.images.authorization.require_current(scope)
        return {"project_id": project_id, "image_revision_id": image_revision_id, "image_artifact_hash": header.artifact_hash,
                "target_object_id": target_object_id, "relation": relation, "items": rows[:limit],
                "next_after_id": rows[limit - 1]["invocation_id"] if len(rows) > limit else None}

    def read(self, project_id, invocation_id):
        scope = self._scope(project_id)
        saved = self.repository.get(project_id, invocation_id)
        if saved is None or not saved.get("artifact_ref"):
            raise KeyError("semantic evaluation not found")
        request = SemanticEvaluationRequest.model_validate(saved["request"])
        prepared = self._prepare(request, historical=True) if request.recall_invocation_id else self._prepare(request)
        if request.input_digest != prepared.digest:
            raise ImageRevisionIntegrityError("semantic evaluation input no longer verifies")
        payload = self.artifacts.read(project_id, saved["artifact_ref"], saved["artifact_hash"])
        if (payload["request"] != request.model_dump() or payload["invocation_id"] != invocation_id
                or payload["preview"] != saved["preview"]):
            raise ImageRevisionIntegrityError("semantic evaluation scope mismatch")
        try:
            evaluation = validate_semantic_output(prepared, payload["model_output"])
        except (ValueError, TypeError):
            raise ImageRevisionIntegrityError("archived semantic output failed validation") from None
        if evaluation.digest != payload["evaluation_digest"] or snapshot_digest(asdict(evaluation)) != snapshot_digest(payload["evaluation"]):
            raise ImageRevisionIntegrityError("semantic evaluation result mismatch")
        self.images.authorization.require_current(scope)
        return self._view(request, prepared, evaluation, invocation_id, saved["artifact_hash"])
