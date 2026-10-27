"""Commit validated generation proposals, not business approval or run evidence.

The caller is a budgeted, confirmed generation executor. There is deliberately
no public endpoint for importing arbitrary model output or coverage claims.
"""
import hashlib
from dataclasses import asdict
from typing import Optional, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import model_serializer

from .test_design_generation import GenerationSelection
from .test_design_review_queries import ReviewDraftListInput, ReviewDraftListReceipt
from .generation_execution_inputs import GenerationExecutionConsent
from .test_design_output import Digest, Id, validate_test_design_output
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_generation import replay_generation_input, TestDesignGenerationInvalid


RESULT_SCHEMA = "nasus.test-design-result.v1"
RECOVERED_RESULT_SCHEMA = "nasus.test-design-result.v2"
BATCH_RESULT_SCHEMA = "nasus.test-design-result.v3"
RECOVERED_BATCH_RESULT_SCHEMA = "nasus.test-design-result.v4"
GENERATION_TOOL = "quality.test_design.generate"


class TestDesignResultIntegrityError(ValueError):
    __test__ = False


class GenerationResultRequest(GenerationSelection):
    input_digest: Digest
    model_config_id: Id
    model_config_digest: Digest
    execution: Optional[GenerationExecutionConsent] = None

    @model_serializer(mode="wrap")
    def legacy_request(self, handler):
        value = handler(self)
        if value.get("execution") is None:
            value.pop("execution", None)
        return value

    def selection(self):
        return GenerationSelection(**{k: getattr(self, k) for k in GenerationSelection.model_fields})


class GenerationResultRepositoryPort(Protocol):
    def by_invocation(self, project_id, invocation_id): ...
    def get(self, project_id, generation_id): ...
    def list_metadata(self, request: ReviewDraftListInput): ...
    def verify_call(self, request, invocation_id, actor_id, call_id, response_hash, binding, *, authority_invocation_id=None): ...
    def require_recovery(self, request, invocation_id, actor_id, authority_invocation_id): ...
    def verify_recovery_history(self, payload): ...
    def verify_batch_history(self, payload): ...
    def record(self, request, payload, ref, digest, *, require_current): ...


def response_digest(content):
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


class TestDesignResultApplicationService:
    __test__ = False

    def __init__(self, generation, authorization, profiles, repository: GenerationResultRepositoryPort, artifacts, *, batch_replies=None):
        self.generation, self.authorization, self.profiles = generation, authorization, profiles
        self.repository, self.artifacts = repository, artifacts
        self.batch_replies = batch_replies

    def _binding(self, request):
        binding = self.profiles.resolve(request.model_config_id, route="chat").binding
        if binding.config_id != request.model_config_id or binding.config_digest != request.model_config_digest:
            raise TestDesignGenerationInvalid("generation model configuration changed")
        return asdict(binding)

    def list_for_review(self, request: ReviewDraftListInput):
        request = ReviewDraftListInput.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise PermissionError("draft discovery requires a current project reviewer")
        # Verify the cursor and look-ahead too: neither pagination nor counts
        # may reveal an archive whose source access has been revoked.
        if request.after_id:
            self.read(request.project_id, request.after_id)
        rows = self.repository.list_metadata(request)
        if len(rows) > request.limit + 1:
            raise TestDesignResultIntegrityError("draft discovery exceeds its page budget")
        items = []
        previous = request.after_id
        for metadata in rows:
            ident = metadata["generation_id"]
            if metadata["project_id"] != request.project_id or ident <= previous:
                raise TestDesignResultIntegrityError("draft discovery order or scope mismatch")
            value = self.read(request.project_id, ident)
            if value["metadata"] != metadata:
                raise TestDesignResultIntegrityError("draft discovery archive changed")
            items.append({"metadata": metadata, "context_pin": value["result"]["context_pin"],
                          "scope_pin": value["result"]["scope_pin"]})
            previous = ident
        more = len(items) > request.limit
        items = items[:request.limit]
        self.authorization.require_current(access)
        return {"request": request.model_dump(mode="json"), "items": items,
                "next_after_id": items[-1]["metadata"]["generation_id"] if more else None,
                "can_review": True, "generation_authorized": False, "execution_authorized": False}

    def review_receipt(self, request: ReviewDraftListInput):
        page = self.list_for_review(request)
        return ReviewDraftListReceipt(request=request,
            generation_ids=tuple(item["metadata"]["generation_id"] for item in page["items"]),
            page_digest=acceptance_digest(page), next_after_id=page["next_after_id"])

    def verify_review_receipt(self, receipt: ReviewDraftListReceipt):
        receipt = ReviewDraftListReceipt.model_validate(receipt.model_dump(mode="json"))
        if self.review_receipt(receipt.request) != receipt:
            raise TestDesignResultIntegrityError("review draft observation changed; inspect again")

    def commit(self, request: GenerationResultRequest, *, invocation_id, call_id, content, authority_invocation_id=None, require_work=None):
        request = GenerationResultRequest.model_validate(request.model_dump(mode="json"))
        if require_work:
            require_work()
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"project_admin", "platform_admin"}:
            raise PermissionError("model-derived generation requires a project administrator")
        if type(content) is not str or len(content.encode()) > 1024 * 1024:
            raise TestDesignGenerationInvalid("generation output exceeds the content budget")
        digest = response_digest(content)
        if authority_invocation_id is not None:
            self.repository.require_recovery(request, invocation_id, access.actor_id, authority_invocation_id)
        prior = self.repository.by_invocation(request.project_id, invocation_id)
        if prior is not None:
            view = self.read(request.project_id, prior["generation_id"])
            payload = view["result"]
            if (payload["request"] != request.model_dump(mode="json") or payload["actor_id"] != access.actor_id
                    or payload["call"]["id"] != call_id or payload["call"]["response_hash"] != digest):
                raise TestDesignResultIntegrityError("generation invocation already has a different result")
            self.authorization.require_current(access)
            if require_work:
                require_work()
            return view["metadata"]

        prepared = self.generation.prepare(request.selection())
        if prepared["input_digest"] != request.input_digest:
            raise TestDesignGenerationInvalid("generation input changed")
        proposal = validate_test_design_output(prepared, content)
        binding = self._binding(request)
        authority = {"authority_invocation_id": authority_invocation_id} if authority_invocation_id else {}
        call = self.repository.verify_call(request, invocation_id, access.actor_id, call_id, digest, binding, **authority)
        payload = {"schema": RESULT_SCHEMA, "project_id": request.project_id,
            "generation_id": str(uuid5(NAMESPACE_URL, "nasus:test-design:" + invocation_id)),
            "invocation_id": invocation_id, "actor_id": access.actor_id, "request": request.model_dump(mode="json"),
            "context_pin": prepared["context_pin"], "scope_pin": prepared["scope_pin"], "model_binding": binding,
            "call": call, "raw_output": content, "proposal": proposal, "status": "draft",
            "mapping_status": "pending_independent_review", "execution_authorized": False}
        if authority_invocation_id is not None:
            payload.update(schema=RECOVERED_RESULT_SCHEMA, recovery_invocation_id=authority_invocation_id)
        self.authorization.require_current(access)
        ref, artifact_hash = self.artifacts.put(request.project_id, payload)
        if acceptance_digest(payload) != artifact_hash:
            raise TestDesignResultIntegrityError("generation artifact write mismatch")

        def require_current():
            # The repository holds the same project/ACL locks as authority writers.
            if require_work:
                require_work()
            fresh = self.generation.prepare(request.selection())
            if fresh["input_digest"] != request.input_digest or self._binding(request) != binding:
                raise TestDesignGenerationInvalid("generation dependencies changed before commit")
            self.authorization.require_current(access)
            if require_work:
                require_work()

        result = self.repository.record(request, payload, ref, artifact_hash, require_current=require_current)
        self.authorization.require_current(access)
        return result

    def read(self, project_id, generation_id):
        access = self.authorization.scope(project_id)
        stored = self.repository.get(project_id, generation_id)
        metadata = stored["metadata"]
        payload = self.artifacts.read(project_id, stored["artifact_ref"], metadata["artifact_hash"])
        if payload.get("schema") in {BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA}:
            from .generation_batch_results import read_batch_result
            return read_batch_result(self, access, stored, payload, project_id, generation_id)
        if (acceptance_digest(payload) != metadata["artifact_hash"] or payload.get("schema") not in {RESULT_SCHEMA, RECOVERED_RESULT_SCHEMA}
                or payload.get("project_id") != project_id or payload.get("generation_id") != generation_id
                or payload.get("invocation_id") != metadata["invocation_id"]
                or payload.get("call", {}).get("id") != metadata["call_id"]
                or payload.get("status") != "draft" or payload.get("mapping_status") != "pending_independent_review"
                or payload.get("execution_authorized") is not False):
            raise TestDesignResultIntegrityError("generation artifact metadata mismatch")
        if payload["schema"] == RECOVERED_RESULT_SCHEMA:
            if payload.get("recovery_invocation_id") != metadata.get("recovery_invocation_id"):
                raise TestDesignResultIntegrityError("generation recovery provenance mismatch")
            self.repository.verify_recovery_history(payload)
        elif "recovery_invocation_id" in payload or "recovery_invocation_id" in metadata:
            raise TestDesignResultIntegrityError("legacy generation cannot acquire recovery authority")
        request = GenerationResultRequest.model_validate(payload["request"])
        if request.project_id != project_id or request.scope_revision_id != metadata["scope_revision_id"]:
            raise TestDesignResultIntegrityError("generation request scope mismatch")
        scope, context = self.generation.scopes.read_inputs(project_id, request.scope_revision_id, request.scope_artifact_hash)
        prepared = replay_generation_input(context, scope)
        if (prepared["input_digest"] != request.input_digest or payload["context_pin"] != prepared["context_pin"]
                or payload["scope_pin"] != prepared["scope_pin"]
                or response_digest(payload["raw_output"]) != payload["call"]["response_hash"]
                or acceptance_digest(request.model_dump(mode="json")) != payload["call"]["request_hash"]
                or payload["model_binding"]["config_id"] != request.model_config_id
                or payload["model_binding"]["config_digest"] != request.model_config_digest):
            raise TestDesignResultIntegrityError("generation provenance mismatch")
        proposal = validate_test_design_output(prepared, payload["raw_output"])
        if (payload["proposal"] != proposal or stored["coverage"] != proposal["coverage"]
                or stored["cases"] != sorted(proposal["cases"], key=lambda case: case["case_id"])
                or metadata["case_count"] != len(proposal["cases"]) or metadata["gap_count"] != len(proposal["gaps"])):
            raise TestDesignResultIntegrityError("persisted cases and coverage differ from the archived proposal")
        self.authorization.require_current(access)
        return {"metadata": metadata, "result": payload, "historical_not_live": True,
                "current_use": {"scope_current": scope["current_use"]["scope_current"],
                    "mapping_approved": False, "execution_authorized": False}}

    def read_public(self, project_id, generation_id):
        value = self.read(project_id, generation_id)
        if value["result"]["schema"] in {BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA}:
            from copy import deepcopy
            value = deepcopy(value)
            for proof in value["result"]["calls"]:
                proof["reply"].pop("artifact_ref")
            # The archive hash pins the private artifact. The public view has
            # its own digest because native storage locations are not exposed.
            version = "v4" if value["result"]["schema"] == RECOVERED_BATCH_RESULT_SCHEMA else "v3"
            value["view_schema"] = "nasus.test-design-result-view." + version
            value["view_hash"] = acceptance_digest(value)
        return value
