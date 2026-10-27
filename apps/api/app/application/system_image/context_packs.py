from typing import ContextManager, Protocol
from uuid import uuid4

from ...domain.system_image.context_pack import CONTEXT_SCHEMA, ContextPackChanged, ContextPackIntegrityError, ContextPublicationChanged, ContextIndexChanged, MandatoryContextTooLarge, context_metadata
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.context_authorities import archived_authority_pins
from ...domain.system_image.source_access import SourceAccessDenied
from .context_pack_inputs import ContextCompileInput, ContextPreviewInput, ContextReadInput, ContextListInput, ContextListReceipt, ContextPackReceipt, ContextAuthorityRegistrationInput, ContextAuthorityBackfillInput, ContextAuthorityBackfillReceipt, preview_request
from .source_access import SourceScopeAuthorizationPort


class ContextPackAuthorizationPort(SourceScopeAuthorizationPort, Protocol):
    def live_read_session(self) -> ContextManager[object]: ...


class ContextPackRepositoryPort(Protocol):
    def get(self, project_id, context_id): ...
    def verify_provenance(self, project_id, context_id): ...
    def verify_authorities(self, project_id, context_id, *, pins=None): ...
    def list(self, request): ...
    def committed(self, request, *, invocation_id, actor_id, require_access): ...
    def record(self, request, metadata, artifact_ref, *, authority_pins, require_current, require_access): ...
    def register_authorities(self, request, metadata, pins, *, invocation_id, actor_id, recorded_at, require_current): ...
    def pending_authority_registrations(self, project_id, *, after_id, limit): ...
    def stale_state(self, project_id, context_id, artifact_hash): ...


class ContextPackArtifactPort(Protocol):
    def put(self, project_id, payload): ...
    def read(self, project_id, ref, digest): ...


class ContextPackApplicationService:
    def __init__(self, sources, authorization: ContextPackAuthorizationPort, repository: ContextPackRepositoryPort, artifacts: ContextPackArtifactPort):
        self.sources, self.authorization, self.repository, self.artifacts = sources, authorization, repository, artifacts

    def _prepare(self, request, *, pinned=None):
        context, provenance = self.sources.prepare(request, pinned=pinned)
        value = {"request": request.model_dump(mode="json"), "context": context, "provenance": provenance}
        return {**value, "input_digest": snapshot_digest(value)}

    def preview(self, request: ContextPreviewInput):
        scope = self.authorization.scope(request.project_id)
        value = self._prepare(request)
        self.authorization.require_current(scope)
        return {key: value[key] for key in ("request", "input_digest", "context")}

    def receipt(self, request):
        if isinstance(request, ContextAuthorityBackfillInput):
            page = self.pending_authority_registrations(request.project_id, after_id=request.after_id, limit=request.limit)
            return ContextAuthorityBackfillReceipt(request=request, items=page["items"],
                page_digest=snapshot_digest(page), next_after_id=page["next_after_id"])
        if isinstance(request, ContextListInput):
            page = self.list(request)
            return ContextListReceipt(request=request, context_ids=[item["context_id"] for item in page["items"]],
                page_digest=snapshot_digest(page), next_after_id=page["next_after_id"])
        if isinstance(request, ContextPreviewInput):
            value = self.preview(request)
            return ContextPackReceipt(request=request, input_digest=value["input_digest"],
                image_revision_id=request.image_revision_id, image_artifact_hash=request.image_artifact_hash,
                readiness=value["context"]["readiness"]["status"], mandatory_count=len(value["context"]["required_constraints"]),
                observation="preview_requires_revalidation")
        value = self.read(request.project_id, request.context_id)
        metadata = value["metadata"]
        return ContextPackReceipt(request=request, **{k: metadata[k] for k in ("context_id", "input_digest", "image_revision_id",
            "image_artifact_hash", "artifact_hash", "readiness", "mandatory_count")}, observation="historical_not_live")

    def list(self, request: ContextListInput):
        scope = self.authorization.scope(request.project_id)
        self.sources.require_image(request)
        page = self.repository.list(request)
        self.authorization.require_current(scope)
        return {"request": request.model_dump(mode="json"), **page}

    def compile(self, request: ContextCompileInput, *, invocation_id, recorded_at):
        scope = self.authorization.scope(request.project_id)
        access = lambda: self.authorization.require_current(scope)
        prior = self.repository.committed(request, invocation_id=invocation_id, actor_id=scope.actor_id, require_access=access)
        if prior is not None:
            self._verify_stored(request.project_id, prior["context_id"], expected_request=request)
            access()
            return prior
        value = self._prepare(preview_request(request))
        if value["input_digest"] != request.expected_input_digest:
            raise ContextPackChanged("Context inputs changed; preview and confirm again")
        payload = {"schema": CONTEXT_SCHEMA, "context_id": str(uuid4()), "project_id": request.project_id,
            "image_revision_id": request.image_revision_id, "image_artifact_hash": request.image_artifact_hash,
            "policy_revision": request.policy_revision, "input_digest": value["input_digest"], "request": request.model_dump(mode="json"),
            "context": value["context"], "provenance": value["provenance"],
            "invocation_id": invocation_id, "actor_id": scope.actor_id, "recorded_at": recorded_at}
        access()
        ref, digest = self.artifacts.put(request.project_id, payload)
        if digest != snapshot_digest(payload):
            raise ContextPackIntegrityError("context artifact write mismatch")
        def require_current():
            if self._prepare(preview_request(request))["input_digest"] != request.expected_input_digest:
                raise ContextPackChanged("Context inputs changed before commit")
            access()
        result = self.repository.record(request, context_metadata(payload, digest), ref,
            authority_pins=archived_authority_pins(payload), require_current=require_current, require_access=access)
        # The commit callback just re-derived these inputs under the project lock.
        # Verify the stored bytes against them, rather than doing a third source
        # traversal. Recovery and later reads still independently replay history.
        self._verify_stored(request.project_id, result["context_id"], expected_request=request, prepared=value)
        access()
        return result

    def _verify_stored(self, project_id, context_id, *, expected_request=None, prepared=None, verify_authorities=True):
        metadata, ref = self.repository.get(project_id, context_id)
        payload = self.artifacts.read(project_id, ref, metadata["artifact_hash"])
        request = ContextCompileInput.model_validate(payload["request"])
        if (payload.get("schema") != CONTEXT_SCHEMA or payload.get("context_id") != context_id
                or payload.get("project_id") != project_id or request.project_id != project_id
                or context_metadata(payload, snapshot_digest(payload)) != metadata
                or any(payload[key] != getattr(request, key) for key in ("image_revision_id", "image_artifact_hash", "policy_revision"))
                or payload["input_digest"] != request.expected_input_digest
                or expected_request is not None and request != expected_request):
            raise ContextPackIntegrityError("context artifact scope mismatch")
        derivation = {"request": preview_request(request).model_dump(mode="json"), "context": payload["context"], "provenance": payload["provenance"]}
        if snapshot_digest(derivation) != payload["input_digest"]:
            raise ContextPackIntegrityError("stored context derivation digest mismatch")
        rebuilt = prepared if prepared is not None else self._prepare(preview_request(request), pinned=payload["provenance"])
        if rebuilt["input_digest"] != payload["input_digest"] or snapshot_digest(rebuilt["context"]) != snapshot_digest(payload["context"]):
            raise ContextPackIntegrityError("context differs from its immutable derivation")
        self.repository.verify_provenance(project_id, context_id)
        if verify_authorities:
            self.repository.verify_authorities(project_id, context_id, pins=archived_authority_pins(payload))
        return metadata, payload, request

    def register_authorities(self, request: ContextAuthorityRegistrationInput, *, invocation_id, recorded_at):
        scope = self.authorization.scope(request.project_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("historical context dependency registration requires a project reviewer")
        metadata, payload, _ = self._verify_stored(request.project_id, request.context_id, verify_authorities=False)
        if metadata["artifact_hash"] != request.artifact_hash:
            raise ContextPackIntegrityError("historical context registration digest mismatch")
        pins = archived_authority_pins(payload)
        def require_current():
            self.authorization.require_current(scope)
            current_metadata, current_payload, _ = self._verify_stored(request.project_id, request.context_id,
                verify_authorities=False)
            if current_metadata != metadata or archived_authority_pins(current_payload) != pins:
                raise ContextPackIntegrityError("historical context registration inputs changed")
            self.authorization.require_current(scope)
        value = self.repository.register_authorities(request, metadata, pins, invocation_id=invocation_id,
            actor_id=scope.actor_id, recorded_at=recorded_at, require_current=require_current)
        self.repository.verify_authorities(request.project_id, request.context_id, pins=pins)
        self.authorization.require_current(scope)
        return value

    def pending_authority_registrations(self, project_id, *, after_id="", limit=3):
        scope = self.authorization.scope(project_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("historical context dependency discovery requires a project reviewer")
        ContextAuthorityBackfillInput(project_id=project_id, after_id=after_id, limit=limit)
        if after_id:
            self._verify_stored(project_id, after_id, verify_authorities=False)
        rows = self.repository.pending_authority_registrations(project_id, after_id=after_id, limit=limit)
        items = []
        # Include look-ahead in authorization: never leak a private next cursor.
        for row in rows:
            metadata, _, _ = self._verify_stored(project_id, row["context_id"], verify_authorities=False)
            if metadata != row:
                raise ContextPackIntegrityError("historical context dependency index changed")
            items.append({"registration_request": ContextAuthorityRegistrationInput(project_id=project_id,
                context_id=metadata["context_id"], artifact_hash=metadata["artifact_hash"]).model_dump(mode="json"),
                "image_revision_id": metadata["image_revision_id"], "image_artifact_hash": metadata["image_artifact_hash"],
                "status": "requires_independent_confirmation"})
        self.authorization.require_current(scope)
        return {"items": items[:limit], "next_after_id": rows[limit - 1]["context_id"] if len(rows) > limit else None,
            "generation_authorized": False}

    def read(self, project_id, context_id):
        # Reuse only the transport: each authorization statement remains fresh.
        with self.authorization.live_read_session():
            return self._read_current(project_id, context_id)

    def _read_current(self, project_id, context_id):
        scope = self.authorization.scope(project_id)
        try:
            metadata, payload, request = self._verify_stored(project_id, context_id)
        except Exception:
            self.authorization.require_current(scope)
            raise
        try:
            current = self._prepare(preview_request(request))
            stale = current["input_digest"] != payload["input_digest"]
            reason = "inputs_changed" if stale else "draft_investigation_only"
        except MandatoryContextTooLarge:
            # A larger new oracle must not erase access to a verifiable historical
            # pack. ACL and integrity failures deliberately still propagate.
            stale, reason = True, "current_mandatory_context_over_budget"
        except ContextPublicationChanged:
            stale, reason = True, "published_image_head_changed"
        except ContextIndexChanged:
            stale, reason = True, "retrieval_model_configuration_changed"
        try:
            invalidation = self.repository.stale_state(project_id, context_id, metadata["artifact_hash"])
        except Exception:
            self.authorization.require_current(scope)
            raise
        if invalidation is not None:
            stale, reason = True, "source_change_invalidated"
        self.authorization.require_current(scope)
        current_use = {"stale": stale, "generation_authorized": False, "reason": reason}
        if invalidation is not None:
            current_use["invalidation_id"] = invalidation["invalidation_id"]
        return {"metadata": metadata, "context": payload["context"],
            "derivation": {"request": payload["request"], "input_digest": payload["input_digest"], "historical_not_live": True},
            "current_use": current_use}
