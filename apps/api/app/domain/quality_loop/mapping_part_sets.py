"""Commit to every exact private part; a commitment itself grants no authority."""
from hashlib import sha256
import re

from .acceptance_specification import acceptance_digest
from .mapping_partitions import MAX_PARTS
from .test_design_mapping import TestDesignMappingInvalid


PART_SET_SCHEMA = "nasus.test-design-mapping-part-set.v1"
PARTITIONED_MAPPING_SCHEMA = "nasus.test-design-mapping-review.v2"
FINALIZE_TOOL = "quality.test_design_mapping.finalize"
FINALIZE_POLICY = "nasus.test-design-mapping.v2"
MEMBER_KEYS = {"sequence", "part_revision_id", "artifact_hash", "request_hash", "part_digest"}


def part_member(metadata):
    return {key: metadata[key] for key in MEMBER_KEYS}


def part_set_commitment(plan, actor_id, members):
    count = plan["part_count"]
    if type(count) is not int or not 1 <= count <= MAX_PARTS:
        raise TestDesignMappingInvalid("final mapping requires a nonempty bounded plan")
    if type(actor_id) is not str or not 1 <= len(actor_id) <= 128:
        raise TestDesignMappingInvalid("mapping set requires its independent reviewer")
    chain, seen, total = sha256(), set(), 0
    for item in members:
        if (type(item) is not dict or set(item) != MEMBER_KEYS or type(item["sequence"]) is not int
                or item["sequence"] != total or total >= count
                or type(item["part_revision_id"]) is not str or not 1 <= len(item["part_revision_id"]) <= 128
                or item["part_revision_id"] in seen
                or any(type(item[key]) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", item[key]) is None
                    for key in ("artifact_hash", "request_hash", "part_digest"))):
            raise TestDesignMappingInvalid("mapping set must contain every distinct exact part in order")
        seen.add(item["part_revision_id"])
        chain.update(bytes.fromhex(acceptance_digest(item)[7:]))
        total += 1
    if total != count:
        raise TestDesignMappingInvalid("mapping set is incomplete; do not approve a subset")
    body = {"schema": PART_SET_SCHEMA, "plan_digest": plan["plan_digest"], "authority_actor": actor_id,
        "part_count": total, "assertion_count": plan["assertion_count"], "members_digest": "sha256:" + chain.hexdigest()}
    return {**body, "part_set_digest": acceptance_digest(body)}
