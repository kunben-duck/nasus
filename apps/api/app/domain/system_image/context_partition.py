"""Deterministic AC partitions. A bundle is an index, not one model prompt."""
from .context_pack import ContextPackIntegrityError, MandatoryContextTooLarge, budget_context
from .source_snapshots import snapshot_digest


PARTITION_POLICY = "nasus.test-design-context.v2"
RULE_AUTHORITY_POLICY = "nasus.test-design-context.v3"
PUBLISHED_CONTEXT_POLICY = "nasus.test-design-context.v4"
INDEXED_CONTEXT_POLICY = "nasus.test-design-context.v5"
BUNDLE_SCHEMA = "nasus.context-bundle.v1"
MAX_CONSTRAINTS = 256


def partition_context(base, optional_facts, max_tokens):
    if base.get("policy_version") not in {PARTITION_POLICY, RULE_AUTHORITY_POLICY, PUBLISHED_CONTEXT_POLICY, INDEXED_CONTEXT_POLICY} or base.get("purpose") != "test_design" or base.get("schema_version") != "nasus.context-pack.v1":
        raise ContextPackIntegrityError("context partition policy mismatch")
    constraints = base["required_constraints"]
    ids = [item["object_id"] for item in constraints]
    if len(set(ids)) != len(ids) or any(not ident for ident in ids):
        raise ContextPackIntegrityError("mandatory constraints must have distinct identities")
    if len(ids) > MAX_CONSTRAINTS:
        raise MandatoryContextTooLarge("Context exceeds the supported constraint count; no requirement was discarded")
    if any(item["kind"] not in {"acceptance_criterion", "business_rule"} for item in constraints):
        raise ContextPackIntegrityError("unknown mandatory constraint kind")
    if any(fact["target_object_id"] not in ids for fact in optional_facts):
        raise ContextPackIntegrityError("support candidate belongs to an unknown constraint")
    # Until rule applicability is separately approved, every source business rule
    # is global. Retrieval rank must never decide whether a rule is inherited.
    global_ids = [item["object_id"] for item in constraints if item["kind"] == "business_rule"]
    targets = [item["object_id"] for item in constraints if item["kind"] == "acceptance_criterion"]

    def compile_part(selected, facts):
        selected_ids = set(selected) | set(global_ids)
        required = [item for item in constraints if item["object_id"] in selected_ids]
        reasons = [reason for reason in base["readiness"]["reason_codes"]
                   if reason not in {"missing_requirements", "unapproved_mandatory_constraint"}]
        if not required:
            reasons.insert(0, "missing_requirements")
        elif any(item["oracle"] is None for item in required):
            reasons.insert(0, "unapproved_mandatory_constraint")
        part = {**base, "required_constraints": required,
            "partition": {"target_object_ids": list(selected), "global_constraint_ids": global_ids,
                "rule_inheritance": "all_source_business_rules"},
            "readiness": {"status": "blocked" if not required or any(item["oracle"] is None for item in required) else "partial",
                "reason_codes": reasons}}
        return budget_context(part, [fact for fact in facts if fact["target_object_id"] in selected_ids], max_tokens)

    groups, current = [], []
    # Validate indivisible global obligations before considering any target.
    compile_part([], [])
    for target in targets:
        try:
            compile_part([*current, target], optional_facts)
        except MandatoryContextTooLarge:
            if not current:
                raise MandatoryContextTooLarge("One AC with all global rules exceeds the budget; increase the budget. No constraint was truncated.")
            groups.append(current)
            current = [target]
            compile_part(current, optional_facts)
        else:
            current.append(target)
    if current or not groups:
        groups.append(current)
    parts = [compile_part(group, optional_facts) for group in groups]
    facts = {snapshot_digest(fact): fact for part in parts for fact in part["facts"]}
    all_optional = {snapshot_digest(fact) for fact in optional_facts}
    return {**base, "schema_version": BUNDLE_SCHEMA, "facts": list(facts.values()),
        "parts": [{"part_id": snapshot_digest(part), "context": part} for part in parts],
        "budget": {"max_tokens": max_tokens, "scope": "per_part",
            "measure": "utf8_bytes_upper_bound_not_provider_token_count",
            "used_upper_bound": max(part["budget"]["used_upper_bound"] for part in parts),
            "total_upper_bound": sum(part["budget"]["used_upper_bound"] for part in parts),
            "part_count": len(parts), "omitted_optional_facts": len(all_optional - set(facts))}}
