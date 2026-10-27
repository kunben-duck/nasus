"""Independent case admission, never business truth or target execution authority."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from .acceptance_specification import acceptance_digest
from .automation_scripts import verify_script_input


CASE_APPROVAL_SCHEMA = "nasus.test-design-case-approval.v1"
CASE_APPROVAL_POLICY = "nasus.test-design-case-admission.v1"
CASE_APPROVAL_TOOL = "quality.test_design_cases.review"
CASE_APPROVAL_EVENT = "quality.test_design_cases.reviewed"


class CaseApprovalChanged(ValueError):
    pass


class CaseApprovalIntegrityError(ValueError):
    pass


def case_approval_basis(prepared):
    verify_script_input(prepared)
    cases = prepared["cases"]
    identities = prepared["selected_case_ids"]
    if (not cases or identities != sorted(set(identities))
            or [case["case_id"] for case in cases] != identities
            or len(prepared["obligations"]) != prepared["obligation_denominator"]
            or not prepared["required_constraints"]):
        raise CaseApprovalIntegrityError("case admission requires the complete fixed selection")
    return {"project_id": prepared["project_id"], "input_digest": prepared["input_digest"],
        **{key: deepcopy(prepared[key]) for key in ("context_pin", "scope_pin", "generation_pin", "mapping_pin")},
        "case_pins": [{"case_id": case["case_id"], "case_digest": acceptance_digest(case)} for case in cases],
        "obligation_pins": [{key: deepcopy(row[key]) for key in
            ("row_id", "oracle_digest", "selected_case_ids")} for row in prepared["obligations"]],
        "constraint_denominator": prepared["constraint_denominator"],
        "obligation_denominator": prepared["obligation_denominator"],
        "constraints_digest": acceptance_digest(prepared["required_constraints"]),
        "scope_contract_digest": acceptance_digest(prepared["scope_contract"])}


def case_approval_cohort(basis):
    identity = acceptance_digest({"project_id": basis["project_id"],
        "generation_id": basis["generation_pin"]["generation_id"],
        "case_ids": [item["case_id"] for item in basis["case_pins"]]})
    return str(uuid5(NAMESPACE_URL, CASE_APPROVAL_POLICY + ":" + identity))
