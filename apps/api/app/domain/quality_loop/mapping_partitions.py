"""Lossless review partitions, not reviewer, oracle or execution authority."""
from copy import deepcopy
from hashlib import sha256
import re

from .acceptance_specification import acceptance_digest
from .test_design_mapping import TestDesignMappingInvalid, assess_verified_decisions


PLAN_SCHEMA = "nasus.test-design-mapping-plan.v1"
PART_SCHEMA = "nasus.test-design-mapping-part.v1"
PART_POLICY = "nasus.test-design-mapping-partition.v1"
PART_SIZE = 128
MAX_CASES = 64 * 512
MAX_CASE_ASSERTIONS = 256
MAX_ASSERTIONS = MAX_CASES * MAX_CASE_ASSERTIONS
MAX_PARTS = MAX_ASSERTIONS // PART_SIZE
PAIR_KEYS = {"case_id", "row_id", "step_index", "oracle_digest"}
DECISION_KEYS = PAIR_KEYS | {"decision", "reason"}


class MappingPartitionOutOfRange(TestDesignMappingInvalid):
    pass


def _identifier(value):
    if type(value) is not str or not 1 <= len(value) <= 128 or value != value.strip() or any(ord(c) < 32 for c in value):
        raise TestDesignMappingInvalid("invalid mapping partition identifier")


def _parts(proposal):
    cases = proposal.get("cases")
    if type(cases) is not list or len(cases) > MAX_CASES:
        raise TestDesignMappingInvalid("unsupported mapping case count; do not truncate")
    seen = set()
    for case in cases:
        _identifier(case.get("case_id"))
        if case["case_id"] in seen:
            raise TestDesignMappingInvalid("duplicate mapping case")
        seen.add(case["case_id"])
    rows = {row["row_id"]: row for row in proposal["coverage"]["rows"]}
    if len(rows) != len(proposal["coverage"]["rows"]):
        raise TestDesignMappingInvalid("duplicate coverage obligation")
    entries = []
    for case in sorted(cases, key=lambda item: item["case_id"]):
        assertions = case.get("assertions")
        if type(assertions) is not list or not 1 <= len(assertions) <= MAX_CASE_ASSERTIONS:
            raise TestDesignMappingInvalid("unsupported case assertion count; do not truncate")
        seen_rows = set()
        for item in assertions:
            _identifier(item.get("row_id"))
            row = rows.get(item["row_id"])
            if (item["row_id"] in seen_rows or row is None or type(item.get("step_index")) is not int
                    or not 0 <= item["step_index"] < len(case["steps"]) <= 64
                    or item.get("oracle_digest") != row["oracle_digest"]
                    or acceptance_digest(item["oracle"]) != item["oracle_digest"]):
                raise TestDesignMappingInvalid("partition must preserve the original obligation, step and oracle")
            seen_rows.add(item["row_id"])
        for item in sorted(assertions, key=lambda value: value["row_id"]):
            entries.append({"case_id": case["case_id"], **{key: item[key] for key in PAIR_KEYS - {"case_id"}}})
            if len(entries) == PART_SIZE:
                yield entries
                entries = []
    if entries:
        yield entries


def _part_digest(sequence, entries):
    return acceptance_digest({"sequence": sequence, "assertions": entries})


def prepare_mapping_partitions(proposal, generation_pin, previous_revision_id, *, sequence=None):
    """Hash all pairs while retaining at most one requested bounded page."""
    if sequence is not None and (type(sequence) is not int or not 0 <= sequence < MAX_PARTS):
        raise MappingPartitionOutOfRange("invalid mapping partition sequence")
    if set(generation_pin) != {"project_id", "generation_id", "artifact_hash", "context_pin", "scope_pin", "input_digest", "proposal_hash"}:
        raise TestDesignMappingInvalid("mapping partitions require complete generation provenance")
    for key in ("project_id", "generation_id"):
        _identifier(generation_pin[key])
    for key in ("artifact_hash", "input_digest", "proposal_hash"):
        if type(generation_pin[key]) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", generation_pin[key]) is None:
            raise TestDesignMappingInvalid("mapping partition pin requires a canonical digest")
    if generation_pin.get("proposal_hash") != acceptance_digest(proposal):
        raise TestDesignMappingInvalid("mapping partition proposal pin mismatch")
    if previous_revision_id is not None:
        _identifier(previous_revision_id)
    chain, selected, total, count = sha256(), None, 0, 0
    for ordinal, entries in enumerate(_parts(proposal)):
        digest = _part_digest(ordinal, entries)
        # Each fixed-size digest includes its sequence and the exact ordered pairs.
        chain.update(bytes.fromhex(digest[7:]))
        total += len(entries)
        count += 1
        if ordinal == sequence:
            selected = {"schema": PART_SCHEMA, "sequence": ordinal, "part_digest": digest,
                "assertions": entries, "execution_authorized": False}
    if sequence is not None and selected is None:
        raise MappingPartitionOutOfRange("mapping partition is outside this plan")
    body = {"schema": PLAN_SCHEMA, "policy_revision": PART_POLICY, "generation_pin": deepcopy(generation_pin),
        "expected_previous_revision_id": previous_revision_id, "case_count": len(proposal["cases"]),
        "assertion_count": total, "part_size": PART_SIZE, "part_count": count,
        "layout_digest": "sha256:" + chain.hexdigest(), "execution_authorized": False}
    plan = {**body, "plan_digest": acceptance_digest(body)}
    if selected is not None:
        selected["plan_digest"] = plan["plan_digest"]
    return plan, selected


def verify_partition_decisions(part, decisions):
    """A staged part may neither reorder nor omit its fixed assertion pairs."""
    if type(decisions) not in {list, tuple} or len(decisions) != len(part["assertions"]) or len(decisions) > PART_SIZE:
        raise TestDesignMappingInvalid("mapping partition requires every exact pair")
    for expected, item in zip(part["assertions"], decisions):
        if (type(item) is not dict or set(item) != DECISION_KEYS or type(item.get("step_index")) is not int
                or {key: item.get(key) for key in PAIR_KEYS} != expected
                or item.get("decision") not in {"accept", "reject", "defer"}
                or type(item.get("reason")) is not str or not item["reason"].strip() or len(item["reason"]) > 2000):
            raise TestDesignMappingInvalid("mapping partition decision must preserve the exact pair, step and oracle")
    return deepcopy(decisions)


def assess_partitioned_mappings(proposal, generation_pin, previous_revision_id, plan_digest, decision_parts):
    """Return an assessment only after every part, including the last, verifies."""
    plan, _ = prepare_mapping_partitions(proposal, generation_pin, previous_revision_id)
    if plan["plan_digest"] != plan_digest:
        raise TestDesignMappingInvalid("mapping partition plan changed")

    def verified():
        parts = iter(decision_parts)
        for sequence, entries in enumerate(_parts(proposal)):
            item = next(parts, None)
            digest = _part_digest(sequence, entries)
            if (type(item) is not dict or set(item) != {"sequence", "plan_digest", "part_digest", "decisions"}
                    or type(item.get("sequence")) is not int or item["sequence"] != sequence
                    or item.get("plan_digest") != plan_digest or item.get("part_digest") != digest):
                raise TestDesignMappingInvalid("mapping parts must be complete, pinned and ordered")
            yield from verify_partition_decisions({"assertions": entries}, item["decisions"])
        if next(parts, None) is not None:
            raise TestDesignMappingInvalid("mapping contains extra or repeated parts")

    return assess_verified_decisions(proposal, verified())
