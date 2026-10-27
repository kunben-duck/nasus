from __future__ import annotations

from dataclasses import asdict
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from ...domain.quality_loop.acceptance_specification import (
    AC_POLICY, AC_SCHEMA, AcceptanceIntegrityError, ObservableOracle, acceptance_digest,
    acceptance_identity, require_authority_decision, StaleAcceptanceSpecification,
)
from ...domain.system_image.source_access import SourceAccessDenied


class AcceptanceSourcePort(Protocol):
    def inspect(self, project_id, image_revision_id, image_hash, object_id) -> dict: ...


class AcceptanceRepositoryPort(Protocol):
    def history(self, project_id, ac_id, through_revision_id=None): ...
    def get(self, project_id, revision_id): ...
    def committed(self, request, basis, *, actor_id, invocation_id, require_current): ...
    def record(self, request, basis, *, actor_id, invocation_id, recorded_at, artifact_ref, artifact_hash, require_current): ...


class AcceptanceArtifactPort(Protocol):
    def put(self, project_id, payload): ...
    def read(self, project_id, ref, digest): ...


class OracleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    preconditions: StrictStr = Field(min_length=1, max_length=2000)
    action: StrictStr = Field(min_length=1, max_length=2000)
    observation: StrictStr = Field(min_length=1, max_length=2000)
    expected_result: StrictStr = Field(min_length=1, max_length=2000)

    @field_validator("preconditions", "action", "observation", "expected_result")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("oracle fields must not be blank")
        return value


class AcceptanceReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    object_id: StrictStr = Field(min_length=1, max_length=128)
    basis_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_previous_revision_id: Optional[StrictStr] = Field(min_length=1, max_length=128)
    decision: Literal["approve", "withdraw"]
    oracle: Optional[OracleInput]
    authority_basis: Optional[Literal["user_confirmed_requirement"]]
    reason: StrictStr = Field(min_length=1, max_length=2000)
    policy_revision: Literal[AC_POLICY]

    @field_validator("reason")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("authority review requires a reason")
        return value


class AcceptanceQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    image_revision_id: StrictStr = Field(min_length=1, max_length=128)
    image_artifact_hash: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    object_id: StrictStr = Field(min_length=1, max_length=128)


class AcceptanceAuthorityReceipt(AcceptanceQueryInput):
    ac_id: StrictStr
    basis_digest: StrictStr = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    head_revision_id: Optional[StrictStr]
    head_artifact_hash: Optional[StrictStr]
    status: Literal["unapproved", "approved", "withdrawn"]
    policy_revision: Literal[AC_POLICY] = AC_POLICY
    applicability: Literal["exact_image_only"] = "exact_image_only"
    observation: Literal["query_time_not_live"] = "query_time_not_live"


class PinnedRequirementAuthorityService:
    """Shared source-proof/CAS protocol; concrete types keep AC and rule authority separate."""

    id_field = "ac_id"
    identity = staticmethod(acceptance_identity)
    policy = AC_POLICY
    schema = AC_SCHEMA
    review_input = AcceptanceReviewInput
    receipt_type = AcceptanceAuthorityReceipt
    required_basis = "user_confirmed_requirement"

    def __init__(self, sources: AcceptanceSourcePort, authorization, repository: AcceptanceRepositoryPort,
                 artifacts: AcceptanceArtifactPort):
        self.sources, self.authorization, self.repository, self.artifacts = sources, authorization, repository, artifacts

    def inspect(self, project_id, image_revision_id, image_hash, object_id):
        scope = self.authorization.scope(project_id)
        basis = self.sources.inspect(project_id, image_revision_id, image_hash, object_id)
        ac_id = self.identity(project_id, image_revision_id, object_id)
        history = self.repository.history(project_id, ac_id)
        head = history[-1] if history else None
        current = None
        if head:
            revision, ref = self.repository.get(project_id, head.revision_id)
            if revision != head:
                raise AcceptanceIntegrityError("acceptance inspection head mismatch")
            current = self._read_view(revision, basis, ref)
        if current:
            current = {key: value for key, value in current.items() if key != "basis"}
        result = {self.id_field: ac_id, "policy_revision": self.policy, "basis": basis, "basis_digest": acceptance_digest(basis),
                  "head": asdict(head) if head else None, "revision_count": len(history),
                  "current": current,
                  "can_review": scope.effective_project_role in {"qa_lead", "project_admin", "platform_admin"},
                  "applicability": "exact_image_only", "image_publication": "unchanged"}
        self.authorization.require_current(scope)
        return result

    def source_basis(self, project_id, image_revision_id, image_hash, object_id):
        return self.sources.inspect(project_id, image_revision_id, image_hash, object_id)

    def receipt(self, request: AcceptanceQueryInput):
        view = self.inspect(request.project_id, request.image_revision_id, request.image_artifact_hash, request.object_id)
        head = view["head"]
        return self.receipt_type(**request.model_dump(), **{self.id_field: view[self.id_field]}, basis_digest=view["basis_digest"],
            head_revision_id=head["revision_id"] if head else None, head_artifact_hash=head["artifact_hash"] if head else None,
            status=head["status"] if head else "unapproved")

    def verify_receipt(self, receipt: AcceptanceAuthorityReceipt):
        scope = self.authorization.scope(receipt.project_id)
        basis = self.sources.inspect(receipt.project_id, receipt.image_revision_id, receipt.image_artifact_hash, receipt.object_id)
        if (acceptance_digest(basis) != receipt.basis_digest
                or self.identity(receipt.project_id, receipt.image_revision_id, receipt.object_id) != getattr(receipt, self.id_field)):
            raise AcceptanceIntegrityError("acceptance observation source mismatch")
        if receipt.head_revision_id:
            view = self.read(receipt.project_id, receipt.head_revision_id)
            head = view["revision"]
            if (head[self.id_field] != getattr(receipt, self.id_field) or head["basis_digest"] != receipt.basis_digest
                    or head["artifact_hash"] != receipt.head_artifact_hash or head["status"] != receipt.status):
                raise AcceptanceIntegrityError("acceptance observation head mismatch")
        elif receipt.head_artifact_hash is not None or receipt.status != "unapproved":
            raise AcceptanceIntegrityError("unapproved observation cannot carry authority")
        self.authorization.require_current(scope)

    def review(self, request: AcceptanceReviewInput, *, invocation_id, recorded_at):
        request = self.review_input.model_validate(request.model_dump(mode="json"))
        scope = self.authorization.scope(request.project_id)
        if scope.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("acceptance authority review requires a project reviewer")
        basis = self.sources.inspect(request.project_id, request.image_revision_id, request.image_artifact_hash, request.object_id)
        if acceptance_digest(basis) != request.basis_digest:
            raise AcceptanceIntegrityError("acceptance source pins changed")
        current = lambda: self.authorization.require_current(scope)

        def replay():
            saved = self.repository.committed(request, basis, actor_id=scope.actor_id,
                                              invocation_id=invocation_id, require_current=current)
            if saved is not None:
                self._verify_review(saved, request, basis, scope.actor_id, invocation_id)
                current()
            return saved

        saved = replay()
        if saved is not None:
            return saved
        history = self.repository.history(request.project_id, self.identity(request.project_id, request.image_revision_id, request.object_id))
        head = history[-1] if history else None
        if (head.revision_id if head else None) != request.expected_previous_revision_id:
            # A concurrent retry may have committed after the first lookup.
            saved = replay()
            if saved is not None:
                return saved
            raise StaleAcceptanceSpecification("acceptance authority changed; inspect again")
        require_authority_decision(request.decision, ObservableOracle(**request.oracle.model_dump()) if request.oracle else None,
                                   request.authority_basis, head.status if head else None, required_basis=self.required_basis)
        payload = {"schema": self.schema, "project_id": request.project_id, "request": request.model_dump(mode="json"),
                   "basis": basis, "authority_actor": scope.actor_id, "invocation_id": invocation_id, "recorded_at": recorded_at}
        self.authorization.require_current(scope)
        ref, digest = self.artifacts.put(request.project_id, payload)
        if digest != acceptance_digest(payload):
            raise AcceptanceIntegrityError("acceptance artifact write mismatch")
        current()
        revision = self.repository.record(request, basis, actor_id=scope.actor_id, invocation_id=invocation_id,
            recorded_at=recorded_at, artifact_ref=ref, artifact_hash=digest, require_current=current)
        self._verify_review(revision, request, basis, scope.actor_id, invocation_id)
        current()
        return revision

    def _verify_review(self, revision, request, basis, actor_id, invocation_id):
        stored, ref = self.repository.get(request.project_id, revision.revision_id)
        if stored != revision or stored.authority_actor != actor_id or stored.invocation_id != invocation_id:
            raise AcceptanceIntegrityError("committed acceptance command mismatch")
        original = self._read_artifact(stored, basis, ref)
        if original != request:
            raise AcceptanceIntegrityError("committed acceptance request changed")

    def read(self, project_id, revision_id):
        scope = self.authorization.scope(project_id)
        revision, ref = self.repository.get(project_id, revision_id)
        basis = self.sources.inspect(project_id, revision.image_revision_id, revision.image_artifact_hash, revision.object_id)
        result = self._read_view(revision, basis, ref)
        self.authorization.require_current(scope)
        return result

    def _read_view(self, revision, basis, ref):
        if acceptance_digest(basis) != revision.basis_digest:
            raise AcceptanceIntegrityError("acceptance source proof changed")
        request = self._read_artifact(revision, basis, ref)
        return {"revision": asdict(revision), "basis": basis, "oracle": request.oracle.model_dump() if request.oracle else None,
                "authority_basis": request.authority_basis, "reason": request.reason, "historical_not_live": True}

    def _read_artifact(self, revision, basis, ref):
        payload = self.artifacts.read(revision.project_id, ref, revision.artifact_hash)
        request = self.review_input.model_validate(payload["request"])
        if (acceptance_digest(payload) != revision.artifact_hash or payload.get("schema") != self.schema
                or payload.get("project_id") != revision.project_id or payload.get("basis") != basis
                or payload.get("authority_actor") != revision.authority_actor or payload.get("invocation_id") != revision.invocation_id
                or payload.get("recorded_at") != revision.recorded_at
                or any(getattr(request, key) != getattr(revision, key) for key in (
                    "project_id", "image_revision_id", "image_artifact_hash", "object_id", "basis_digest", "policy_revision"))
                or request.expected_previous_revision_id != revision.previous_revision_id
                or revision.status != ("approved" if request.decision == "approve" else "withdrawn")):
            raise AcceptanceIntegrityError("acceptance artifact scope mismatch")
        require_authority_decision(request.decision, ObservableOracle(**request.oracle.model_dump()) if request.oracle else None,
                                   request.authority_basis, "approved" if revision.previous_revision_id else None, required_basis=self.required_basis)
        return request

    def resolve_oracle(self, project_id, image_revision_id, object_id, revision_id, artifact_hash):
        """A consumer pins a revision and rechecks withdrawal; historical reads are not authority gates."""
        scope = self.authorization.scope(project_id)
        value = self.read(project_id, revision_id)
        revision = value["revision"]
        if (revision["image_revision_id"] != image_revision_id or revision["object_id"] != object_id
                or revision["artifact_hash"] != artifact_hash or revision["status"] != "approved"):
            raise AcceptanceIntegrityError("oracle is not approved for this exact image and object")
        history = self.repository.history(project_id, revision[self.id_field])
        if not history or history[-1].revision_id != revision_id:
            raise StaleAcceptanceSpecification("oracle was superseded or withdrawn")
        self.authorization.require_current(scope)
        return value


class AcceptanceSpecificationApplicationService(PinnedRequirementAuthorityService):
    pass
