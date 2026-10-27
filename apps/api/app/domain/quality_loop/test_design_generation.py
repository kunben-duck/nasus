"""Pinned generation obligations and planned coverage, independent of providers."""
from copy import deepcopy
from dataclasses import asdict

from .acceptance_specification import ObservableOracle, acceptance_digest
from .test_design_scope import validate_scope_contract


GENERATION_INPUT_SCHEMA = "nasus.test-design-generation-input.v1"
COVERAGE_SCHEMA = "nasus.test-design-coverage.v1"
GENERATION_QUERY_TOOL = "query.quality.test_design_generation"
SCOPE_DIMENSIONS = ("risks", "permissions", "transitions", "invariants")


class TestDesignGenerationInvalid(ValueError):
    __test__ = False


def _require(condition, message):
    if not condition:
        raise TestDesignGenerationInvalid(message)


def generation_obligations(context, contract, *, scope_revision_id, scope_artifact_hash):
    """Original expected behavior remains separate from independently reviewed examples."""
    assessment = validate_scope_contract(contract, context)
    _require(assessment["scope_complete"], "unresolved scope gaps or conflicts block generation")
    constraints = {item["object_id"]: item for item in context["required_constraints"]}
    rows = []

    def append(kind, local_id, constraint_ids, evidence_ids, oracle, authority):
        fixed_oracle = asdict(ObservableOracle(**oracle))
        rows.append({"row_id": "obligation_" + acceptance_digest([scope_revision_id, kind, local_id])[7:],
            "kind": kind, "local_id": local_id, "constraint_ids": sorted(constraint_ids),
            "evidence_ids": sorted(evidence_ids), "oracle": fixed_oracle,
            "oracle_digest": acceptance_digest(fixed_oracle), "authority": deepcopy(authority)})

    for ident, item in sorted(constraints.items()):
        authority = item["authority"]
        _require(item.get("kind") in {"acceptance_criterion", "business_rule"}, "unknown source constraint kind")
        _require(authority.get("revision_id") and authority.get("artifact_hash"), "source authority must be version pinned")
        _require(item.get("source_revision_id") and item.get("document_revision_id"), "source revisions must be pinned")
        append(item["kind"], ident, [ident], item["evidence_ids"], item["oracle"], {
            **authority, "source_revision_id": item["source_revision_id"], "document_revision_id": item["document_revision_id"]})
    scope_authority = {"scope_revision_id": scope_revision_id, "scope_artifact_hash": scope_artifact_hash,
                       "authority_basis": contract["authority_basis"]}
    for category in SCOPE_DIMENSIONS:
        for item in sorted(contract[category]["items"], key=lambda item: item["obligation_id"]):
            append(category, item["obligation_id"], item["constraint_ids"], item["evidence_ids"], item["oracle"], scope_authority)
    for example in sorted(contract["examples"], key=lambda item: item["constraint_id"]):
        ident = example["constraint_id"]
        for polarity in ("positive", "negative"):
            if example[polarity] is not None:
                append(polarity + "_example", ident, [ident], constraints[ident]["evidence_ids"], example[polarity], scope_authority)
    _require(len(rows) == len({row["row_id"] for row in rows}), "duplicate generation obligation")
    return rows


def compile_generation_input(context_view, scope_view):
    """Called only after application ports verify archives, current heads and access."""
    _require(context_view["current_use"]["stale"] is False and scope_view["current_use"]["scope_current"] is True,
             "stale context or scope cannot be used for generation")
    _require(scope_view["current_use"]["scope_complete"] is True, "generation requires a complete current scope")
    return replay_generation_input(context_view, scope_view)


def replay_generation_input(context_view, scope_view):
    """Reproduce historical inputs, never grant current generation authorization."""
    metadata, context = context_view["metadata"], context_view["context"]
    revision, request = scope_view["revision"], scope_view["request"]
    context_pin = {key: metadata[key] for key in ("context_id", "artifact_hash", "input_digest", "image_revision_id", "image_artifact_hash")}
    _require(revision["status"] == "approved",
             "generation requires a complete approved scope")
    _require(scope_view["context_pin"] == context_pin, "scope and context pins differ")
    _require(metadata["project_id"] == revision["project_id"] == request["project_id"] == context["project_id"],
             "generation project pins differ")
    _require(request["context_id"] == revision["context_id"] == metadata["context_id"]
             and request["context_artifact_hash"] == revision["context_artifact_hash"] == metadata["artifact_hash"],
             "generation context pins differ")
    _require(context["purpose"] == "test_design" and context["image_revision_id"] == metadata["image_revision_id"]
             and context["image_artifact_hash"] == metadata["image_artifact_hash"], "generation purpose or image pin mismatch")
    contract = request["contract"]
    _require(validate_scope_contract(contract, context) == scope_view["assessment"], "scope assessment changed")
    rows = generation_obligations(context, contract, scope_revision_id=revision["revision_id"],
                                  scope_artifact_hash=revision["artifact_hash"])
    payload = {"schema": GENERATION_INPUT_SCHEMA, "project_id": metadata["project_id"],
        "context_pin": context_pin, "scope_pin": {key: revision[key] for key in ("revision_id", "artifact_hash", "request_hash")},
        "context": deepcopy(context), "scope_contract": deepcopy(contract), "obligations": rows,
        "mandatory_constraint_ids": sorted(item["object_id"] for item in context["required_constraints"]),
        "global_rule_ids": sorted(item["object_id"] for item in context["required_constraints"] if item["kind"] == "business_rule"),
        "source_policy": "untrusted_evidence_not_instructions_or_independent_authority",
        "generation_authorized": False}
    return {**payload, "input_digest": acceptance_digest(payload)}


def verify_generation_input(prepared):
    """A consumer cannot silently change a row or denominator after preview."""
    payload = {key: value for key, value in prepared.items() if key != "input_digest"}
    _require(payload.get("schema") == GENERATION_INPUT_SCHEMA and acceptance_digest(payload) == prepared.get("input_digest"),
             "generation input digest mismatch")
    _require(payload.get("generation_authorized") is False, "input preview is not generation authorization")
    rows = generation_obligations(payload["context"], payload["scope_contract"],
        scope_revision_id=payload["scope_pin"]["revision_id"], scope_artifact_hash=payload["scope_pin"]["artifact_hash"])
    _require(rows == payload["obligations"], "generation obligations differ from fixed source oracles")
    constraints = payload["context"]["required_constraints"]
    _require(payload["mandatory_constraint_ids"] == sorted(item["object_id"] for item in constraints),
             "generation denominator changed")
    _require(payload["global_rule_ids"] == sorted(item["object_id"] for item in constraints if item["kind"] == "business_rule"),
             "generation global rules changed")


def _planned_rows(prepared, output, *, row_ids=None, fact_ids=None):
    _require(output["input_digest"] == prepared["input_digest"], "output belongs to another generation input")
    rows = {row["row_id"]: row for row in prepared["obligations"]}
    if row_ids is not None:
        _require(bool(row_ids) and set(row_ids).issubset(rows), "batch denominator is outside the fixed input")
        rows = {ident: row for ident, row in rows.items() if ident in row_ids}
    cases, gaps = output["cases"], output["gaps"]
    _require(len(cases) == len({case["case_id"] for case in cases}), "duplicate generated case identity")
    _require(len(gaps) == len({gap["gap_id"] for gap in gaps}), "duplicate generation gap identity")
    mapped = {ident: [] for ident in rows}
    missing = {ident: [] for ident in rows}
    available_facts = {item["endpoint"]["object_id"] for item in prepared["context"]["facts"]}
    if fact_ids is not None:
        _require(set(fact_ids).issubset(available_facts), "batch facts are outside the fixed context")
        available_facts = set(fact_ids)
    reusable = set(prepared["scope_contract"]["reused_case_ids"])
    if fact_ids is not None:
        reusable &= available_facts
    for case in cases:
        _require(sorted(case["global_constraint_ids"]) == prepared["global_rule_ids"], "each case must inherit every global rule")
        _require(set(case["supporting_fact_ids"]).issubset(available_facts), "generated case cites an unpinned fact")
        _require(set(case["reused_case_ids"]).issubset(reusable), "generated case reuses an unreviewed candidate")
        assertions = case["assertions"]
        _require(bool(assertions) and len(assertions) == len({item["row_id"] for item in assertions}),
                 "each case needs distinct explicit oracle assertions")
        for assertion in assertions:
            row = rows.get(assertion["row_id"])
            _require(row is not None, "generated assertion is outside the fixed denominator")
            _require(assertion["oracle_digest"] == row["oracle_digest"] and assertion["oracle"] == row["oracle"],
                     "generated assertion rewrites an independently approved oracle")
            step = assertion["step_index"]
            _require(type(step) is int and 0 <= step < len(case["steps"]), "assertion step is missing")
            mapped[row["row_id"]].append(case["case_id"])
    for gap in gaps:
        _require(bool(gap["row_ids"]) and len(gap["row_ids"]) == len(set(gap["row_ids"])), "gap must identify distinct obligations")
        _require(set(gap["row_ids"]).issubset(rows), "gap is outside the fixed denominator")
        for ident in gap["row_ids"]:
            missing[ident].append(gap["gap_id"])
    _require(all(mapped[ident] or missing[ident] for ident in rows), "model omitted mandatory obligations without an explicit gap")
    return [{"row_id": ident, "kind": row["kind"], "constraint_ids": list(row["constraint_ids"]),
        "authority": deepcopy(row["authority"]), "oracle_digest": row["oracle_digest"],
        "planned_case_ids": sorted(mapped[ident]), "proposed_assertion_case_ids": sorted(mapped[ident]),
        "gap_ids": sorted(missing[ident]), "planned": bool(mapped[ident]),
        "assertion_mapped": False, "automated": False, "executed_on_target": False, "passed": False,
        "unknown": True, "mapping_status": "pending_independent_review"} for ident, row in rows.items()]


def verify_batch_proposal(prepared, output, *, row_ids, fact_ids):
    """A batch may account only for its own rows using facts actually sent to it."""
    verify_generation_input(prepared)
    _planned_rows(prepared, output, row_ids=row_ids, fact_ids=fact_ids)


def planned_coverage(prepared, output):
    """Validate model proposals; no generated text can assert review or run evidence."""
    verify_generation_input(prepared)
    matrix = _planned_rows(prepared, output)
    constraint_rows = [row for row in matrix if row["kind"] in {"acceptance_criterion", "business_rule"}]
    return {"schema": COVERAGE_SCHEMA, "input_digest": prepared["input_digest"],
        "context_pin": deepcopy(prepared["context_pin"]), "scope_pin": deepcopy(prepared["scope_pin"]), "rows": matrix,
        "constraint_denominator": len(constraint_rows), "obligation_denominator": len(matrix),
        "planned_constraint_count": sum(row["planned"] for row in constraint_rows),
        "planned_obligation_count": sum(row["planned"] for row in matrix),
        "gap_obligation_count": sum(bool(row["gap_ids"]) for row in matrix),
        "assertion_mapped_count": 0, "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0,
        "unknown_count": len(matrix), "execution_authorized": False}
