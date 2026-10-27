"""Independent reviewed test-design obligations, never observed code behavior."""
from .acceptance_specification import acceptance_digest


SCOPE_POLICY = "nasus.test-design-scope.v1"
SCOPE_SCHEMA = "nasus.test-design-scope-revision.v1"
SCOPE_TOOL = "quality.test_design_scope.review"
SCOPE_QUERY_TOOL = "query.quality.test_design_scope"


class TestDesignScopeChanged(ValueError):
    __test__ = False


class TestDesignScopeIntegrityError(ValueError):
    __test__ = False


def scope_identity(project_id, context_id):
    return "scope_" + acceptance_digest([project_id, context_id])[7:]


def validate_scope_contract(contract, context):
    """Keep every fixed requirement; extra obligations require explicit human authority."""
    constraints = context["required_constraints"]
    ids = {item["object_id"] for item in constraints}
    if not ids or len(ids) != len(constraints):
        raise ValueError("a scope requires a complete, unique requirement denominator")
    if not context.get("publication_pin") or any(
        item.get("oracle") is None or item["authority"].get("status") != "approved" for item in constraints
    ):
        raise ValueError("a scope requires published inputs and independently approved oracles")
    examples = contract["examples"]
    if len(examples) != len(ids) or {item["constraint_id"] for item in examples} != ids:
        raise ValueError("positive and negative examples must account for every AC and business rule")
    gaps = {item["id"]: item for item in contract["gaps"]}
    for example in examples:
        gap_id = example.get("negative_gap_id")
        if gap_id is not None and (gap_id not in gaps or example["constraint_id"] not in gaps[gap_id]["constraint_ids"]):
            raise ValueError("pending negative examples require a gap for the same constraint")
    evidence_ids = {eid for item in constraints for eid in item["evidence_ids"]}
    evidence_ids.update(eid for item in context["facts"] for eid in item["endpoint"]["evidence_ids"])
    obligations = []
    for category in ("risks", "permissions", "transitions", "invariants"):
        assessment = contract[category]
        if bool(assessment["items"]) != (assessment["applicability"] == "applicable"):
            raise ValueError("each scope dimension requires items or an explicit not-applicable assessment")
        for item in assessment["items"]:
            if not set(item["constraint_ids"]) or not set(item["constraint_ids"]).issubset(ids):
                raise ValueError("obligation refers to a requirement outside the fixed denominator")
            if not set(item["evidence_ids"]).issubset(evidence_ids):
                raise ValueError("obligation evidence is outside the fixed context")
            obligations.append(item["obligation_id"])
    if len(obligations) != len(set(obligations)):
        raise ValueError("obligation identifiers must be unique across scope dimensions")
    facts = {item["endpoint"]["object_id"] for item in context["facts"] if item["relation"] == "asserts"}
    if not set(contract["reused_case_ids"]).issubset(facts):
        raise ValueError("reused cases must be present in the pinned retrieval candidates")
    for item in (*contract["conflicts"], *contract["gaps"]):
        if not set(item["constraint_ids"]) or not set(item["constraint_ids"]).issubset(ids):
            raise ValueError("a gap or conflict must refer to fixed requirements")
    blockers = ["unresolved_conflict:" + item["id"] for item in contract["conflicts"] if item["resolution"] is None]
    blockers += ["explicit_gap:" + item["id"] for item in contract["gaps"]]
    return {"constraint_ids": sorted(ids), "obligation_ids": sorted(obligations), "blockers": blockers,
            "scope_complete": not blockers, "generation_authorized": False,
            "use_policy": "reviewed_scope_only_requires_separate_generation_preflight"}
