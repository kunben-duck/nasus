from collections import Counter
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .test_design_output import Digest, Id, validate_test_design_output
from ...domain.quality_loop.test_design_generation import TestDesignGenerationInvalid, compile_generation_input, replay_generation_input


class GenerationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: Id
    scope_revision_id: Id
    scope_artifact_hash: Digest


class GenerationScopePort(Protocol):
    def resolve_inputs(self, project_id, revision_id, artifact_hash): ...
    def read_inputs(self, project_id, revision_id, artifact_hash): ...


class GenerationInputReceipt(GenerationSelection):
    input_digest: Digest
    context_id: Id
    context_artifact_hash: Digest
    image_revision_id: Id
    image_artifact_hash: Digest
    constraint_count: int = Field(strict=True, ge=1, le=256)
    global_rule_count: int = Field(strict=True, ge=0, le=256)
    obligation_count: int = Field(strict=True, ge=1, le=1792)
    observation: Literal["query_time_requires_revalidation"] = "query_time_requires_revalidation"
    generation_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False


class TestDesignGenerationApplicationService:
    """Preflight and result checking only; persistent, budgeted invocation is separate."""
    __test__ = False

    def __init__(self, scopes: GenerationScopePort):
        self.scopes = scopes

    def prepare(self, request: GenerationSelection):
        request = GenerationSelection.model_validate(request.model_dump(mode="json"))
        scope, context = self.scopes.resolve_inputs(request.project_id, request.scope_revision_id, request.scope_artifact_hash)
        if scope["revision"]["revision_id"] != request.scope_revision_id or scope["revision"]["artifact_hash"] != request.scope_artifact_hash:
            raise TestDesignGenerationInvalid("generation scope port returned different pins")
        if scope["revision"]["project_id"] != request.project_id:
            raise TestDesignGenerationInvalid("generation scope belongs to another project")
        return compile_generation_input(context, scope)

    def preview(self, request: GenerationSelection):
        prepared = self.prepare(request)
        return {"project_id": request.project_id, "input_digest": prepared["input_digest"],
            "context_pin": prepared["context_pin"], "scope_pin": prepared["scope_pin"],
            "constraint_count": len(prepared["mandatory_constraint_ids"]),
            "global_rule_count": len(prepared["global_rule_ids"]), "obligation_count": len(prepared["obligations"]),
            "obligations_by_kind": dict(Counter(row["kind"] for row in prepared["obligations"])),
            "generation_authorized": False, "execution_authorized": False,
            "remaining_gates": ["tested_model_binding", "model_egress_consent", "provider_token_budget",
                                "durable_generation_reservation", "atomic_cases_and_coverage_commit"]}

    def replay(self, request: GenerationSelection):
        request = GenerationSelection.model_validate(request.model_dump(mode="json"))
        scope, context = self.scopes.read_inputs(request.project_id, request.scope_revision_id, request.scope_artifact_hash)
        if (scope["revision"]["revision_id"] != request.scope_revision_id
                or scope["revision"]["artifact_hash"] != request.scope_artifact_hash
                or scope["revision"]["project_id"] != request.project_id):
            raise TestDesignGenerationInvalid("historical generation scope pins differ")
        return replay_generation_input(context, scope)

    def check_output(self, request: GenerationSelection, *, expected_input_digest, content):
        # Re-resolve both immutable inputs and current permissions/heads after the
        # model call. A preview digest is never a reusable authorization grant.
        prepared = self.prepare(request)
        if prepared["input_digest"] != expected_input_digest:
            raise TestDesignGenerationInvalid("generation input changed; discard the uncommitted proposal")
        return validate_test_design_output(prepared, content)

    def receipt(self, request: GenerationSelection):
        preview = self.preview(request)
        pin = preview["context_pin"]
        return GenerationInputReceipt(**request.model_dump(), context_id=pin["context_id"], context_artifact_hash=pin["artifact_hash"],
            image_revision_id=pin["image_revision_id"], image_artifact_hash=pin["image_artifact_hash"],
            **{key: preview[key] for key in ("input_digest", "constraint_count", "global_rule_count", "obligation_count")})

    def verify_receipt(self, receipt: GenerationInputReceipt):
        request = GenerationSelection.model_validate({key: getattr(receipt, key) for key in GenerationSelection.model_fields})
        if self.receipt(request) != receipt:
            raise TestDesignGenerationInvalid("generation input observation changed; query again")
