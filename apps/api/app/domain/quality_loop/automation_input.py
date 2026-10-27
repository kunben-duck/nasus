"""Carry independently reviewed case/oracle pins into automation preparation."""
from copy import deepcopy
import json

from .acceptance_specification import acceptance_digest
from .test_design_generation import planned_coverage, verify_generation_input


AUTOMATION_INPUT_SCHEMA = "nasus.automation-input-preview.v1"
MAX_AUTOMATION_INPUT_BYTES = 256 * 1024
MAX_AUTOMATION_CASES = 512


class AutomationInputInvalid(ValueError):
    pass


class AutomationInputChanged(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise AutomationInputInvalid(message)


def compile_automation_input(prepared, result, mapping, case_ids):
    if (result["current_use"]["scope_current"] is not True
            or mapping["current_use"]["mapping_current"] is not True):
        raise AutomationInputChanged("automation input dependencies are no longer current")
    _require(mapping["current_use"]["mapping_complete"] is True,
        "automation preparation requires a complete independent mapping review")
    return replay_automation_input(prepared, result, mapping, case_ids)


def replay_automation_input(prepared, result, mapping, case_ids):
    """Rebuild original input, without treating historical approvals as current."""
    verify_generation_input(prepared)
    _require(type(case_ids) is tuple and 1 <= len(case_ids) <= MAX_AUTOMATION_CASES
        and all(type(ident) is str and 1 <= len(ident) <= 128 for ident in case_ids)
        and len(case_ids) == len(set(case_ids)), "select distinct explicit case identities")
    _require(mapping["assessment"]["mapping_complete"] is True,
        "automation preparation requires a complete independent mapping review")
    metadata, draft, revision = result["metadata"], result["result"], mapping["revision"]
    project = prepared["project_id"]
    _require(project == metadata["project_id"] == revision["project_id"]
        and revision["status"] == "reviewed" and draft["status"] == "draft",
        "automation input project or review status mismatch")
    generation_pin = {"generation_id": metadata["generation_id"], "artifact_hash": metadata["artifact_hash"],
        "context_pin": draft["context_pin"], "scope_pin": draft["scope_pin"],
        "input_digest": draft["request"]["input_digest"], "proposal_hash": acceptance_digest(draft["proposal"])}
    _require(mapping["generation_pin"] == generation_pin
        and generation_pin["context_pin"] == prepared["context_pin"]
        and generation_pin["scope_pin"] == prepared["scope_pin"]
        and generation_pin["input_digest"] == prepared["input_digest"],
        "automation dependencies must preserve the exact generation, scope and context")
    proposal = draft["proposal"]
    coverage = planned_coverage(prepared, {"input_digest": prepared["input_digest"],
        "cases": proposal["cases"], "gaps": proposal["gaps"]})
    _require(coverage == proposal["coverage"], "automation draft coverage differs from its fixed obligations")
    reviewed = mapping["assessment"]
    selected = set(case_ids)
    cases = {case["case_id"]: case for case in proposal["cases"]}
    _require(selected.issubset(cases) and selected.issubset(reviewed["accepted_case_ids"]),
        "every selected case requires independently accepted assertions")
    rows = reviewed["coverage"]["rows"]
    _require(len(rows) == len(prepared["obligations"])
        and {row["row_id"] for row in rows} == {row["row_id"] for row in prepared["obligations"]},
        "automation review cannot change the obligation denominator")
    obligations = []
    by_row = {row["row_id"]: row for row in rows}
    for obligation in prepared["obligations"]:
        row = by_row[obligation["row_id"]]
        linked = sorted(selected.intersection(row["accepted_case_ids"]))
        _require(linked and not row["gap_ids"] and row["oracle_digest"] == obligation["oracle_digest"],
            "selected cases must retain every mandatory obligation and its approved oracle")
        _require(not any(row[key] for key in ("automated", "executed_on_target", "passed"))
            and row["unknown"] is True, "mapping review cannot grant automation or execution evidence")
        for ident in linked:
            assertion = next((item for item in cases[ident]["assertions"] if item["row_id"] == obligation["row_id"]), None)
            _require(assertion is not None and assertion["oracle"] == obligation["oracle"]
                and assertion["oracle_digest"] == obligation["oracle_digest"],
                "reviewed case assertion does not preserve the original oracle")
        obligations.append({**deepcopy(obligation), "selected_case_ids": linked})
    payload = {"schema": AUTOMATION_INPUT_SCHEMA, "purpose": "automation", "project_id": project,
        "context_pin": deepcopy(prepared["context_pin"]), "scope_pin": deepcopy(prepared["scope_pin"]),
        "generation_pin": deepcopy(generation_pin),
        "mapping_pin": {key: revision[key] for key in ("revision_id", "artifact_hash", "request_hash")},
        "selected_case_ids": sorted(selected), "cases": [deepcopy(cases[ident]) for ident in sorted(selected)],
        "required_constraints": deepcopy(prepared["context"]["required_constraints"]),
        "scope_contract": deepcopy(prepared["scope_contract"]), "obligations": obligations,
        "supporting_facts": deepcopy(prepared["context"]["facts"]),
        "constraint_denominator": coverage["constraint_denominator"], "obligation_denominator": len(obligations),
        "readiness": {"status": "blocked", "reason_codes": ["automation_environment_not_bound",
            "api_or_dom_locator_evidence_not_bound", "fixture_setup_cleanup_not_bound",
            "model_budget_not_bound", "script_generation_and_independent_review_required"]},
        "source_policy": "untrusted_evidence_not_instructions_or_independent_authority",
        "generation_authorized": False, "execution_authorized": False,
        "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0}
    value = {**payload, "input_digest": acceptance_digest(payload)}
    _require(len(json.dumps(value, ensure_ascii=False).encode("utf-8")) <= MAX_AUTOMATION_INPUT_BYTES,
        "mandatory automation input exceeds 256 KiB; no silent truncation is allowed")
    return value
