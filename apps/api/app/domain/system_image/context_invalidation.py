"""Append-only stale facts; never rewrite historical knowledge or approvals."""
from dataclasses import asdict

from .context_pack import ContextPackChanged, ContextPackIntegrityError
from .derivation_impact import IMPACT_POLICY, MAX_DEPENDENCIES, validate_derivation_graph
from .source_snapshots import snapshot_digest


INVALIDATE_CONTEXT_TOOL = "system_image.context.invalidate"
INVALIDATION_POLICY = "nasus.context-invalidation.v1"


class ContextInvalidationChanged(ContextPackChanged):
    pass


class ContextInvalidationIntegrityError(ContextPackIntegrityError):
    pass


def invalidation_metadata(request, impact, *, invalidation_id, actor_id, invocation_id, recorded_at):
    value = asdict(impact)
    assessment = impact.assessment
    root = "context:" + request.context_id
    validate_derivation_graph(impact.dependencies, root)
    keys = tuple(sorted(node.key for node in impact.dependencies))
    if (request.expected_impact_hash != snapshot_digest(value)
            or any(getattr(impact, key) != getattr(request, key) for key in ("project_id", "context_id", "context_artifact_hash"))
            or impact.before.source_revision_id != request.before_revision_id
            or impact.after.source_revision_id != request.after_revision_id):
        raise ContextInvalidationChanged("fixed change impact changed; inspect and confirm again")
    if (not 1 <= len(keys) <= MAX_DEPENDENCIES or len(set(keys)) != len(keys) or root not in keys
            or assessment.dependency_count != len(keys) or assessment.affected_keys != keys
            or not assessment.reason_codes or not assessment.dependency_closure_complete
            or assessment.schema_version != IMPACT_POLICY or assessment.invalidation_applied
            or assessment.impact_complete or not impact.prospective_only or impact.new_dependencies_after_observation_included
            or (impact.before.project_id, impact.before.binding_id) != (request.project_id, impact.after.binding_id)
            or impact.after.project_id != request.project_id
            or assessment.generation_authorized or assessment.execution_authorized
            or assessment.graph_hash != snapshot_digest([asdict(node) for node in sorted(impact.dependencies, key=lambda n: n.key)])):
        raise ContextInvalidationIntegrityError("invalidation requires a complete affected fixed graph")
    return {"schema": INVALIDATION_POLICY, "invalidation_id": invalidation_id,
        "project_id": request.project_id, "context_id": request.context_id,
        "context_artifact_hash": request.context_artifact_hash,
        "request": request.model_dump(mode="json"), "request_hash": snapshot_digest(request.model_dump(mode="json")),
        "impact_hash": request.expected_impact_hash, "image_revision_id": impact.image_revision_id,
        "image_artifact_hash": impact.image_artifact_hash, "before": value["before"], "after": value["after"],
        "delta_hash": impact.delta_hash, "graph_hash": assessment.graph_hash,
        "query_scope_fingerprint": assessment.query_scope_fingerprint,
        "reason_codes": list(assessment.reason_codes), "dependency_count": len(keys),
        "authority_actor": actor_id, "invocation_id": invocation_id, "recorded_at": recorded_at,
        "invalidation_applied": True, "invalidation_scope": request.invalidation_scope, "impact_complete": False,
        "generation_authorized": False, "execution_authorized": False}
