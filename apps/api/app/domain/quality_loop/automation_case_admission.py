"""Verify the exact independent admission, without granting execution authority."""
from .case_approval import CaseApprovalChanged, CaseApprovalIntegrityError, case_approval_basis, case_approval_cohort
from .acceptance_specification import acceptance_digest


def verify_automation_case_admission(prepared, value, revision_id, artifact_hash, *, current):
    basis = case_approval_basis(prepared)
    revision = value.get("revision", {}) if type(value) is dict else {}
    expected = {"revision_id": revision_id, "artifact_hash": artifact_hash, "status": "approved",
        "project_id": basis["project_id"], "generation_id": basis["generation_pin"]["generation_id"],
        "mapping_revision_id": basis["mapping_pin"]["revision_id"], "input_digest": basis["input_digest"],
        "cohort_id": case_approval_cohort(basis), "case_count": len(basis["case_pins"])}
    if (type(revision) is not dict or any(revision.get(key) != item for key, item in expected.items())
            or type(revision.get("case_count")) is not int or value.get("basis") != basis):
        raise CaseApprovalIntegrityError("automation must preserve its independently admitted cases and oracles")
    if current and value.get("current_use", {}).get("case_admission_current") is not True:
        raise CaseApprovalChanged("automation requires the current independent case admission")
    return {"revision_id": revision_id, "artifact_hash": artifact_hash, "basis_digest": acceptance_digest(basis)}
