from typing import Literal, Optional, Protocol
import json

from .automation_inputs import AutomationInputSelection
from .test_design_output import Digest, Id, Text
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.automation_input import AutomationInputChanged
from ...domain.quality_loop.case_approval import (
    CASE_APPROVAL_SCHEMA, CASE_APPROVAL_POLICY, CaseApprovalChanged, CaseApprovalIntegrityError,
    case_approval_basis, case_approval_cohort,
)
from ...domain.quality_loop.test_design_mapping import TestDesignMappingChanged
from ...domain.quality_loop.test_design_scope import TestDesignScopeChanged
from ...domain.system_image.source_access import SourceAccessDenied


class CaseApprovalReviewInput(AutomationInputSelection):
    expected_input_digest: Digest
    expected_previous_revision_id: Optional[Id]
    decision: Literal["approve", "withdraw"]
    reason: Text
    policy_revision: Literal[CASE_APPROVAL_POLICY] = CASE_APPROVAL_POLICY

    def selection(self):
        return AutomationInputSelection(**{key: getattr(self, key) for key in AutomationInputSelection.model_fields})


class CaseApprovalRepositoryPort(Protocol):
    def history(self, project_id, cohort_id, through_revision_id=None): ...
    def archives(self, project_id, cohort_id): ...
    def get(self, project_id, revision_id): ...
    def committed(self, request, basis, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, ref, digest, *, require_current): ...


class CaseApprovalArtifactPort(Protocol):
    def put(self, project_id, payload): ...
    def read(self, project_id, ref, digest): ...


class CaseApprovalApplicationService:
    def __init__(self, inputs, authorization, repository: CaseApprovalRepositoryPort, artifacts: CaseApprovalArtifactPort):
        self.inputs, self.authorization, self.repository, self.artifacts = inputs, authorization, repository, artifacts

    def _basis(self, selection, *, historical=False):
        prepared = self.inputs.replay(selection) if historical else self.inputs.prepare(selection)
        return case_approval_basis(prepared)

    def preview(self, selection: AutomationInputSelection):
        selection = AutomationInputSelection.model_validate(selection.model_dump(mode="json"))
        access = self.authorization.scope(selection.project_id)
        prepared = self.inputs.replay(selection)
        basis = case_approval_basis(prepared)
        cohort = case_approval_cohort(basis)
        archives = self.repository.archives(selection.project_id, cohort)
        history = [revision for revision, _ in archives]
        for revision, ref in archives:
            self._verify_archive(selection.project_id, revision, ref)
        try:
            current = self._basis(selection) == basis
        except (AutomationInputChanged, TestDesignMappingChanged, TestDesignScopeChanged):
            current = False
        self.authorization.require_current(access)
        value = {"selection": selection.model_dump(mode="json"), "prepared": prepared, "basis": basis,
            "input_current": current, "cohort_id": cohort,
            "head": history[-1] if history else None, "history_count": len(history),
            "head_revision_id": history[-1]["revision_id"] if history else None,
            "can_review": access.effective_project_role in {"qa_lead", "project_admin", "platform_admin"},
            "execution_authorized": False, "business_coverage_verified": False}
        if len(json.dumps(value, ensure_ascii=False).encode()) > 512 * 1024:
            raise CaseApprovalIntegrityError("complete case admission preview exceeds its byte budget; no truncation")
        return value

    def review(self, request: CaseApprovalReviewInput, *, invocation_id, recorded_at):
        request = CaseApprovalReviewInput.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("case admission requires an independent project reviewer")
        require_access = lambda: self.authorization.require_current(access)
        # Recover the original fact without requiring its old input to be live again.
        basis = self._basis(request.selection(), historical=True)
        if basis["input_digest"] != request.expected_input_digest:
            raise CaseApprovalChanged("case admission input changed; inspect the complete selection again")
        prior = self.repository.committed(request, basis, actor_id=access.actor_id,
            invocation_id=invocation_id, require_access=require_access)
        if prior is not None:
            stored = self.read(request.project_id, prior["revision_id"])
            if stored["revision"] != prior or stored["basis"] != basis:
                raise CaseApprovalIntegrityError("case admission recovery lost its fixed original input")
            require_access()
            return prior
        historical = request.decision == "withdraw"
        if not historical and self._basis(request.selection()) != basis:
            raise CaseApprovalChanged("case admission dependencies changed before confirmation")
        payload = {"schema": CASE_APPROVAL_SCHEMA, "request": request.model_dump(mode="json"),
            "basis": basis, "project_id": request.project_id, "cohort_id": case_approval_cohort(basis),
            "authority_actor": access.actor_id, "invocation_id": invocation_id, "recorded_at": recorded_at}
        require_access()
        ref, digest = self.artifacts.put(request.project_id, payload)
        if acceptance_digest(payload) != digest:
            raise CaseApprovalIntegrityError("case admission artifact write mismatch")
        def require_current():
            if self._basis(request.selection(), historical=historical) != basis:
                raise CaseApprovalChanged("case admission dependencies changed during commit")
            require_access()
        result = self.repository.record(request, payload, ref, digest, require_current=require_current)
        require_access()
        return result

    def _verify_archive(self, project_id, revision, ref):
        payload = self.artifacts.read(project_id, ref, revision["artifact_hash"])
        try:
            request = CaseApprovalReviewInput.model_validate(payload["request"])
        except (ValueError, KeyError, TypeError) as error:
            raise CaseApprovalIntegrityError("case admission archive has an invalid original request") from error
        prepared = self.inputs.replay(request.selection())
        basis = case_approval_basis(prepared)
        if (payload.get("schema") != CASE_APPROVAL_SCHEMA or payload.get("project_id") != project_id
                or request.project_id != project_id or request.expected_input_digest != basis["input_digest"]
                or payload.get("basis") != basis or payload.get("cohort_id") != case_approval_cohort(basis)
                or acceptance_digest(payload) != revision["artifact_hash"]
                or acceptance_digest(request.model_dump(mode="json")) != revision["request_hash"]
                or revision["previous_revision_id"] != request.expected_previous_revision_id
                or revision["status"] != ("approved" if request.decision == "approve" else "withdrawn")
                or revision["project_id"] != project_id
                or revision["generation_id"] != basis["generation_pin"]["generation_id"]
                or revision["mapping_revision_id"] != request.mapping_revision_id
                or revision["input_digest"] != basis["input_digest"]
                or revision["case_count"] != len(basis["case_pins"])
                or any(payload.get(key) != revision[key] for key in ("authority_actor", "invocation_id", "recorded_at", "cohort_id"))):
            raise CaseApprovalIntegrityError("case admission archive differs from its complete fixed parents")
        return request, basis, prepared

    def read(self, project_id, revision_id):
        return self.read_with_inputs(project_id, revision_id)[0]

    def read_with_inputs(self, project_id, revision_id):
        """Return complete verified parents, without caching current authority."""
        access = self.authorization.scope(project_id)
        revision, ref = self.repository.get(project_id, revision_id)
        request, basis, prepared = self._verify_archive(project_id, revision, ref)
        archives = self.repository.archives(project_id, revision["cohort_id"])
        history = [item for item, _ in archives]
        if not any(item == revision for item in history):
            raise CaseApprovalIntegrityError("case admission revision is missing from its complete current history")
        for item, item_ref in archives:
            if item["revision_id"] != revision_id:
                self._verify_archive(project_id, item, item_ref)
        current = bool(history and history[-1]["revision_id"] == revision_id and revision["status"] == "approved")
        live_input = None
        if current:
            try:
                live_input = self.inputs.prepare(request.selection())
                current = case_approval_basis(live_input) == basis
            except (AutomationInputChanged, TestDesignMappingChanged, TestDesignScopeChanged):
                current = False
        if current:
            current = self.repository.history(project_id, revision["cohort_id"]) == history
        if not current:
            live_input = None
        self.authorization.require_current(access)
        value = {"revision": revision, "basis": basis, "historical_not_live": True,
            "current_use": {"case_admission_current": current, "generation_authorized": False,
                "execution_authorized": False, "business_coverage_verified": False}}
        return value, prepared, live_input

    def require_access(self, selection):
        access = self.authorization.scope(selection.project_id)
        self._basis(selection, historical=True)
        self.authorization.require_current(access)

    def resolve(self, project_id, revision_id, artifact_hash, prepared):
        value = self.read(project_id, revision_id)
        if value["revision"]["artifact_hash"] != artifact_hash or value["basis"] != case_approval_basis(prepared):
            raise CaseApprovalIntegrityError("case admission cannot substitute another case, oracle, mapping or input")
        if value["current_use"]["case_admission_current"] is not True:
            raise CaseApprovalChanged("case admission was withdrawn, superseded or lost current authority")
        return value
