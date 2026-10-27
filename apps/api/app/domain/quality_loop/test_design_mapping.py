"""Independent assertion review, never execution or business-oracle authority."""
from copy import deepcopy


MAPPING_SCHEMA = "nasus.test-design-mapping-review.v1"
MAPPING_POLICY = "nasus.test-design-mapping.v1"
MAPPING_TOOL = "quality.test_design_mapping.review"
MAPPING_QUERY_TOOL = "query.quality.test_design_mapping"


class TestDesignMappingInvalid(ValueError):
    __test__ = False


class TestDesignMappingChanged(ValueError):
    __test__ = False


class TestDesignMappingIntegrityError(ValueError):
    __test__ = False


def assess_mappings(proposal, mappings):
    """Every proposed pair is reviewed exactly once against its frozen step/oracle."""
    expected = {(case["case_id"], assertion["row_id"]): assertion
                for case in proposal["cases"] for assertion in case["assertions"]}
    decisions = {}
    for item in mappings:
        key = (item["case_id"], item["row_id"])
        assertion = expected.get(key)
        if (key in decisions or assertion is None or item["step_index"] != assertion["step_index"]
                or type(item["step_index"]) is not int or item["oracle_digest"] != assertion["oracle_digest"]
                or item["decision"] not in {"accept", "reject", "defer"}
                or not isinstance(item["reason"], str) or not item["reason"].strip()):
            raise TestDesignMappingInvalid("review must preserve each exact case, obligation, step and oracle")
        decisions[key] = item["decision"]
    if decisions.keys() != expected.keys():
        raise TestDesignMappingInvalid("review must account for every proposed assertion without omission")

    return assess_verified_decisions(proposal, (
        {"case_id": case, "row_id": ident, "decision": decision}
        for (case, ident), decision in decisions.items()))


def assess_verified_decisions(proposal, decisions):
    """Reduce fully verified pairs; callers must reject omissions and duplicates."""
    by_row, incomplete_cases = {}, set()
    counts = {"accept": 0, "reject": 0, "defer": 0}
    for item in decisions:
        case, ident, decision = item["case_id"], item["row_id"], item["decision"]
        by_row.setdefault(ident, {"accept": [], "reject": [], "defer": []})[decision].append(case)
        counts[decision] += 1
        if decision != "accept":
            incomplete_cases.add(case)

    coverage = deepcopy(proposal["coverage"])
    for row in coverage["rows"]:
        for decision, field in (("accept", "accepted_case_ids"), ("reject", "rejected_case_ids"), ("defer", "deferred_case_ids")):
            row[field] = sorted(by_row.get(row["row_id"], {}).get(decision, []))
        row["assertion_mapped"] = bool(row["accepted_case_ids"])
        row["mapping_status"] = "reviewed"
        # Oracle mapping proves intent, not automation, target observation or pass.
        row.update(automated=False, executed_on_target=False, passed=False, unknown=True)
    coverage.update(schema="nasus.reviewed-test-design-coverage.v1",
        assertion_mapped_count=sum(row["assertion_mapped"] for row in coverage["rows"]),
        automated_count=0, executed_on_target_count=0, passed_count=0,
        unknown_count=len(coverage["rows"]), execution_authorized=False)
    accepted_cases = sorted(case["case_id"] for case in proposal["cases"] if case["case_id"] not in incomplete_cases)
    return {"coverage": coverage, "accepted_case_ids": accepted_cases,
        "accepted_assertion_count": counts["accept"],
        "rejected_assertion_count": counts["reject"],
        "deferred_assertion_count": counts["defer"],
        "mapping_complete": bool(coverage["rows"] and all(row["assertion_mapped"] and not row["gap_ids"]
            for row in coverage["rows"])), "execution_authorized": False}
