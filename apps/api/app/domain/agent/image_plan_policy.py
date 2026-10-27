"""Keep immutable investigation work out of the legacy mutable-image pipeline."""

from __future__ import annotations

from typing import Sequence

from .plan_policy import AgentPlanPolicyViolation
from .runtime_models import ToolPlanStep


MUTABLE_IMAGE_TOOLS = frozenset({
    "system_image.sources.register", "system_image.sources.ingest", "system_image.context.materialize",
    "system_image.baseline.initialize", "baseline.promote",
})
PINNED_IMAGE_TOOLS = frozenset({"system_image.build.plan", "system_image.build.authorize", "system_image.build.structure",
    "system_image.build.investigate", "query.system_image.build_investigations.read",
    "query.system_image.build_plans.read", "system_image.links.propose_references", "query.system_image.references.read",
    "system_image.links.review", "query.system_image.links.decisions", "system_image.revisions.freeze_links"})
BUILD_GOAL_TEMPLATES = frozenset({"system_image_build", "system_image_investigation"})


def is_pinned_image_plan(steps: Sequence[ToolPlanStep], target_refs: Sequence[str] = ()) -> bool:
    return (any(ref.startswith(("build_plan:", "source_manifest:", "image_revision:", "image_reference_proposal:", "build_source_wait_digest:")) for ref in target_refs)
            or any(step.tool_id in PINNED_IMAGE_TOOLS or step.tool_id.startswith("query.system_image.revisions.")
                   or (step.tool_id.startswith("system_image.") and any(key in step.input_payload for key in (
                       "plan_id", "source_manifest_id", "image_revision_id"))) for step in steps))


def validate_image_plan(steps: Sequence[ToolPlanStep], target_refs: Sequence[str] = ()) -> None:
    if not is_pinned_image_plan(steps, target_refs):
        return
    if any(step.tool_id in MUTABLE_IMAGE_TOOLS for step in steps):
        raise AgentPlanPolicyViolation("pinned_image_mutation", "Pinned investigation cannot recapture inputs or initialize/promote a mutable baseline.")
    if any(step.tool_id == "system_image.build.authorize" for step in steps):
        # Investigation still reaches its own canonical confirmation gate; it
        # never reserves work against the structural-only authorization.
        allowed = {"system_image.build.authorize", "system_image.build.structure", "query.system_image.build_plans.read",
                   "system_image.build.investigate", "query.system_image.revisions.read",
                   "query.system_image.revisions.document", "query.system_image.build_investigations.read"}
        reference_tools = {"system_image.links.propose_references", "query.system_image.references.read"}
        references = [index for index, step in enumerate(steps) if step.tool_id in reference_tools]
        if references:
            investigations = [index for index, step in enumerate(steps) if step.tool_id == "system_image.build.investigate"]
            structures = [index for index, step in enumerate(steps) if step.tool_id == "system_image.build.structure"]
            if not investigations or not structures or not max(structures) < min(investigations) < min(references):
                raise AgentPlanPolicyViolation("build_authorization_capability", "Reference work must follow independent investigation, not structural consent.")
            allowed.update(reference_tools)
        if any(ref.startswith("build_request_digest:") for ref in target_refs):
            preparations = [step for step in steps if step.tool_id == "system_image.build.plan"]
            if len(preparations) != 1 or steps.index(preparations[0]) >= next(
                    index for index, step in enumerate(steps) if step.tool_id == "system_image.build.authorize"):
                raise AgentPlanPolicyViolation("build_preparation_scope_changed", "Only the original plan preparation may precede structural consent.")
            allowed.add("system_image.build.plan")
        if any(ref.startswith("build_source_wait_digest:") for ref in target_refs):
            waiting = [step for step in steps if step.tool_id == "query.system_image.status"]
            if (len(waiting) != 1 or "build_input_request" not in waiting[0].input_payload
                    or not any(step.tool_id == "system_image.build.plan" for step in steps)
                    or steps.index(waiting[0]) >= next(index for index, step in enumerate(steps)
                        if step.tool_id == "system_image.build.plan")):
                raise AgentPlanPolicyViolation("build_input_wait_scope_changed", "Only the original input-status read may precede plan preparation.")
            allowed.add("query.system_image.status")
        if any(step.tool_id not in allowed for step in steps):
            raise AgentPlanPolicyViolation("build_authorization_capability", "This build consent covers deterministic structure only; additional capabilities need separate authorization.")
    for key in ("project_id", "plan_id", "plan_digest", "source_manifest_id", "target_baseline_id",
                "image_revision_id", "image_artifact_hash"):
        values = [step.input_payload[key] for step in steps if key in step.input_payload]
        ref_prefix = {"project_id": "project:", "plan_id": "build_plan:", "source_manifest_id": "source_manifest:"}.get(key)
        if ref_prefix:
            values.extend(ref[len(ref_prefix):] for ref in target_refs if ref.startswith(ref_prefix))
        if any(not isinstance(value, str) or not value for value in values) or len(set(values)) > 1:
            raise AgentPlanPolicyViolation("pinned_image_scope_changed", "Pinned investigation scope cannot change during execution.")
