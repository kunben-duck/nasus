from typing import Protocol

from .test_design_scope_inputs import ScopeReceipt, ScopeReviewInput
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_scope import (
    SCOPE_SCHEMA, TestDesignScopeChanged, TestDesignScopeIntegrityError, scope_identity, validate_scope_contract,
)
from ...domain.system_image.source_access import SourceAccessDenied


class ScopeContextPort(Protocol):
    def read(self, project_id, context_id): ...


class ScopeRepositoryPort(Protocol):
    def history(self, project_id, scope_id, through_revision_id=None): ...
    def get(self, project_id, revision_id): ...
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, artifact_ref, artifact_hash, *, require_current): ...


class ScopeArtifactPort(Protocol):
    def put(self, project_id, payload): ...
    def read(self, project_id, ref, digest): ...


class TestDesignScopeApplicationService:
    __test__ = False

    def __init__(self, contexts: ScopeContextPort, authorization, repository: ScopeRepositoryPort, artifacts: ScopeArtifactPort):
        self.contexts, self.authorization, self.repository, self.artifacts = contexts, authorization, repository, artifacts

    def inspect(self, project_id, context_id):
        access = self.authorization.scope(project_id)
        ident = scope_identity(project_id, context_id)
        history = self.repository.history(project_id, ident)
        if history:
            # The head read already verifies the archived context and its current
            # dependencies. Reuse only that call's result, never a cached ACL.
            head, context = self._read_inputs(project_id, history[-1]["revision_id"])
            if head["revision"]["context_id"] != context_id:
                raise TestDesignScopeIntegrityError("scope history context mismatch")
        else:
            head, context = None, self.contexts.read(project_id, context_id)
        self.authorization.require_current(access)
        return {"scope_id": ident, "context_id": context_id, "context_artifact_hash": context["metadata"]["artifact_hash"],
                "head": head, "history": history, "context_current_use": context["current_use"],
                "can_review": access.effective_project_role in {"qa_lead", "project_admin", "platform_admin"}}

    def _context(self, request, *, current):
        value = self.contexts.read(request.project_id, request.context_id)
        if value["metadata"]["artifact_hash"] != request.context_artifact_hash:
            raise TestDesignScopeIntegrityError("scope context hash mismatch")
        if current and value["current_use"]["stale"]:
            raise TestDesignScopeChanged("context dependencies changed; compile a new context")
        return value

    def receipt(self, request):
        view = self.inspect(request.project_id, request.context_id)
        head = view["head"]["revision"] if view["head"] else None
        return ScopeReceipt(**request.model_dump(), scope_id=view["scope_id"], context_artifact_hash=view["context_artifact_hash"],
            head_revision_id=head["revision_id"] if head else None, head_artifact_hash=head["artifact_hash"] if head else None,
            status=head["status"] if head else "unreviewed", context_stale=view["context_current_use"]["stale"],
            scope_current=view["head"]["current_use"]["scope_current"] if head else False,
            scope_complete=view["head"]["current_use"]["scope_complete"] if head else False,
            blocker_count=len(view["head"]["assessment"]["blockers"]) if head and view["head"]["assessment"] else 0)

    def verify_receipt(self, receipt):
        from .test_design_scope_inputs import ScopeQueryInput
        current = self.receipt(ScopeQueryInput(project_id=receipt.project_id, context_id=receipt.context_id))
        if current != receipt:
            raise TestDesignScopeChanged("scope observation changed; query again")

    def review(self, request: ScopeReviewInput, *, invocation_id, recorded_at):
        request = ScopeReviewInput.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("test-design scope requires a project reviewer")
        require_access = lambda: self.authorization.require_current(access)
        prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id, require_access=require_access)
        if prior is not None:
            stored = self.read(request.project_id, prior["revision_id"])
            if stored["request"] != request.model_dump(mode="json"):
                raise TestDesignScopeIntegrityError("scope recovery request mismatch")
            require_access()
            return prior
        context = self._context(request, current=request.decision == "approve")
        contract = request.contract.model_dump(mode="json") if request.contract else None
        assessment = validate_scope_contract(contract, context["context"]) if contract else None
        payload = {"schema": SCOPE_SCHEMA, "project_id": request.project_id, "request": request.model_dump(mode="json"),
                   "context_pin": {k: context["metadata"][k] for k in ("context_id", "artifact_hash", "input_digest", "image_revision_id", "image_artifact_hash")},
                   "assessment": assessment, "authority_actor": access.actor_id, "invocation_id": invocation_id, "recorded_at": recorded_at}
        require_access()
        ref, digest = self.artifacts.put(request.project_id, payload)
        if acceptance_digest(payload) != digest:
            raise TestDesignScopeIntegrityError("scope artifact write mismatch")

        def require_current():
            # All authority/head/ACL writers share the repository's project lock.
            self._context(request, current=request.decision == "approve")
            require_access()

        result = self.repository.record(request, payload, ref, digest, require_current=require_current)
        require_access()
        return result

    def read(self, project_id, revision_id):
        return self._read_inputs(project_id, revision_id)[0]

    def _read_inputs(self, project_id, revision_id):
        access = self.authorization.scope(project_id)
        revision, ref = self.repository.get(project_id, revision_id)
        payload = self.artifacts.read(project_id, ref, revision["artifact_hash"])
        request = ScopeReviewInput.model_validate(payload["request"])
        if (acceptance_digest(payload) != revision["artifact_hash"] or payload.get("schema") != SCOPE_SCHEMA
                or request.project_id != project_id or payload.get("project_id") != project_id
                or acceptance_digest(request.model_dump(mode="json")) != revision["request_hash"]
                or any(payload.get(k) != revision[k] for k in ("authority_actor", "invocation_id", "recorded_at"))
                or request.context_id != revision["context_id"] or request.context_artifact_hash != revision["context_artifact_hash"]
                or request.expected_previous_revision_id != revision["previous_revision_id"]
                or revision["status"] != ("approved" if request.decision == "approve" else "withdrawn")):
            raise TestDesignScopeIntegrityError("scope artifact metadata mismatch")
        context = self._context(request, current=False)
        pin = {k: context["metadata"][k] for k in ("context_id", "artifact_hash", "input_digest", "image_revision_id", "image_artifact_hash")}
        assessment = validate_scope_contract(request.contract.model_dump(mode="json"), context["context"]) if request.contract else None
        if payload.get("context_pin") != pin or payload.get("assessment") != assessment:
            raise TestDesignScopeIntegrityError("scope derivation mismatch")
        history = self.repository.history(project_id, revision["scope_id"])
        current = (history[-1]["revision_id"] == revision_id and revision["status"] == "approved"
                   and not context["current_use"]["stale"])
        self.authorization.require_current(access)
        value = {"revision": revision, "request": request.model_dump(mode="json"), "context_pin": pin, "assessment": assessment,
                "historical_not_live": True, "current_use": {"scope_current": current,
                    "scope_complete": bool(current and assessment and assessment["scope_complete"]), "generation_authorized": False}}
        return value, context

    def resolve(self, project_id, revision_id, artifact_hash):
        return self.resolve_inputs(project_id, revision_id, artifact_hash)[0]

    def resolve_inputs(self, project_id, revision_id, artifact_hash):
        value, context = self.read_inputs(project_id, revision_id, artifact_hash)
        if not value["current_use"]["scope_current"]:
            raise TestDesignScopeChanged("scope or context was superseded or withdrawn")
        return value, context

    def read_inputs(self, project_id, revision_id, artifact_hash):
        value, context = self._read_inputs(project_id, revision_id)
        if value["revision"]["artifact_hash"] != artifact_hash:
            raise TestDesignScopeIntegrityError("scope consumer pin mismatch")
        return value, context
