"""Version-pinned context compilation; retrieval candidates never become oracles."""
import json

from .source_snapshots import snapshot_digest


CONTEXT_SCHEMA = "nasus.context-pack.v1"
CONTEXT_POLICY = "nasus.test-design-context.v1"
COMPILE_CONTEXT_TOOL = "system_image.context.compile"


class ContextPackIntegrityError(ValueError):
    pass


class ContextPackChanged(ValueError):
    pass


class ContextPublicationChanged(ContextPackChanged):
    pass


class ContextIndexChanged(ContextPackChanged):
    pass


class MandatoryContextTooLarge(ValueError):
    pass


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def budget_context(base, optional_facts, max_tokens):
    """Reserve all constraints first. UTF-8 bytes conservatively budget text, not provider framing."""
    if type(max_tokens) is not int or not 512 <= max_tokens <= 32768:
        raise ValueError("context budget must be between 512 and 32768")
    result = {**base, "facts": [], "budget": {"max_tokens": max_tokens,
        "measure": "utf8_bytes_upper_bound_not_provider_token_count", "used_upper_bound": 0, "omitted_optional_facts": len(optional_facts)}}
    def measure():
        for _ in range(8):
            size = len(canonical_bytes(result))
            if result["budget"]["used_upper_bound"] == size:
                return size
            result["budget"]["used_upper_bound"] = size
        raise ContextPackIntegrityError("context budget did not converge")
    if measure() > max_tokens:
        raise MandatoryContextTooLarge("Mandatory context exceeds budget; split scope or request a larger budget. No AC was discarded.")
    for fact in optional_facts:
        result["facts"].append(fact)
        result["budget"]["omitted_optional_facts"] -= 1
        if measure() > max_tokens:
            result["facts"].pop()
            result["budget"]["omitted_optional_facts"] += 1
            measure()
    if result["required_constraints"] != base["required_constraints"]:
        raise ContextPackIntegrityError("mandatory constraints changed during budgeting")
    return result


def context_metadata(payload, artifact_hash):
    context = payload["context"]
    return {key: payload[key] for key in ("context_id", "project_id", "image_revision_id", "image_artifact_hash",
        "input_digest", "invocation_id", "actor_id", "recorded_at", "policy_revision")} | {
        "artifact_hash": artifact_hash, "purpose": context["purpose"], "readiness": context["readiness"]["status"],
        "mandatory_count": len(context["required_constraints"]), "content_hash": snapshot_digest(context)}
