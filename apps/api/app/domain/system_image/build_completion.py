"""Evidence-based candidate assessment, never publication or execution authority."""
from dataclasses import asdict
import json

from .build_plan import BuildPlanIntegrityError
from .source_snapshots import snapshot_digest


COMPLETION_SCHEMA = "nasus.image-build-completion.v1"


def assess_build_completion(plan, review, scans, analyses, checkpoint, verified_evidence_count, *, require_build_lineage=False):
    if (review.image_artifact_hash is None or checkpoint["project_id"] != plan.intent.project_id
            or checkpoint["goal_template"] not in {"system_image_build", "system_image_investigation"}
            or checkpoint["status"] not in {"paused", "blocked"} or checkpoint.get("active_started_at") is not None):
        raise BuildPlanIntegrityError("Completion assessment requires a settled same-project build checkpoint.")
    expected = {item.source_revision_id: item for item in plan.intent.sources if item.status == "captured"}
    if len(scans) != len(expected) or {item["source_revision_id"] for item in scans} != set(expected):
        raise BuildPlanIntegrityError("Completion assessment must account for every captured source.")
    for scan in scans:
        source = expected[scan["source_revision_id"]]
        if (scan["binding_id"], scan["source_type"]) != (source.binding_id, source.source_type):
            raise BuildPlanIntegrityError("Completion source inventory differs from its fixed manifest.")
    if (type(verified_evidence_count) is not int or verified_evidence_count < 0
            or len({item["source_revision_id"] for item in analyses}) != len(analyses)
            or any(item["source_revision_id"] not in expected
                   or expected[item["source_revision_id"]].source_type != "code" for item in analyses)):
        raise BuildPlanIntegrityError("Invalid completion evidence or analysis pins.")
    gaps = [{**asdict(item), "owner_actor_id": None, "ownership_status": "unassigned"} for item in review.gaps]
    blockers = []

    def block(code, reason, action):
        blockers.append(code)
        gaps.append({"code": code, "blocks": "candidate_delivery", "reason": reason,
                     "required_action": action, "owner_actor_id": None, "ownership_status": "unassigned"})

    code_sources = [item for item in plan.intent.sources if item.source_type == "code"]
    if not code_sources or any(item.status != "captured" for item in code_sources):
        block("required_code_not_captured", "Required code has not been immutably captured.", "Capture the required code in a new reviewed manifest.")
    if any(not item["enumeration_complete"] for item in scans):
        block("source_inventory_incomplete", "Source enumeration is missing or incomplete.", "Capture an explicit complete inventory; do not infer it from member counts.")
    if any(item["failed_entries"] or item["unsupported_entries"] for item in scans):
        block("source_acquisition_gaps", "The acquisition inventory contains failed or unsupported entries.", "Resolve the acquisition gaps under a newly captured source revision.")
    if any(not item["file_bodies_verified"] for item in scans):
        block("full_source_bytes_unverified", "Inventory hashes and member evidence do not verify every archived file body.",
              "Verify all required source bytes before claiming complete snapshot delivery.")
    code_revisions = {item.source_revision_id for item in code_sources if item.status == "captured"}
    if {item["source_revision_id"] for item in analyses} != code_revisions:
        block("code_analysis_not_selected", "Not every code revision has an explicitly pinned analysis.", "Select a verified analysis for every fixed code source revision.")
    if any(item["failed"] or item["not_analyzed"] or item["projection_status"] != "complete" for item in analyses):
        block("code_analysis_partial", "At least one parser or provider projection remains incomplete or unknown.", "Inspect the fixed analysis diagnostics; do not report a partial graph as complete.")
    if (analyses and any(not item.get("build_lineage_verified", False) for item in analyses)) or (require_build_lineage and not analyses):
        block("analysis_build_lineage_unverified", "Selected analysis diagnostics are source-pinned, not attested outputs of this structural build.",
              "Pin the committed build's actual provider and analysis lineage before declaring structural completeness.")
    if review.inventory["legacy_members"] or review.inventory["code_members_without_evidence"]:
        block("unverified_image_members", "Legacy or unevidenced members remain in the candidate.", "Produce a new fully source-pinned candidate.")
    artifacts = [{"work_item_id": "structure", "artifact": "image_candidate", "state": "verified",
                  "artifact_hash": review.image_artifact_hash},
                 {"work_item_id": "review", "artifact": "build_completion_report", "state": "assessed_not_delivered"}]
    for work in plan.work_items:
        if work.work_item_id not in {"structure", "review"}:
            artifacts.append({"work_item_id": work.work_item_id, "artifact": work.output_artifact, "state": "unverified"})
            block("required_artifact_unverified", "A required plan capability has no verified completion artifact.",
                  "Verify the required capability output without borrowing structural consent.")
    # Existing counters do not attest retries, phase-wide tool spend, model cost,
    # or approval of every capability. Preserve that distinction in the report.
    budget = {"proposed_limits": asdict(plan.intent.budget),
              "goal_model_calls_used": checkpoint["model_calls_used"],
              "goal_thinking_tokens_used": checkpoint["thinking_tokens_used"],
              "goal_steps_completed": checkpoint["steps_completed"],
              "goal_active_runtime_ms": checkpoint.get("active_runtime_ms"),
              "active_runtime_accounting_available": checkpoint.get("active_runtime_ms") is not None,
              "cost_microusd": None, "full_plan_accounting_verified": False}
    block("full_plan_budget_unverified", "Current goal counters are not a cumulative all-capability spending ledger.",
          "Verify the original approvals, retries, phase-wide usage and cost before candidate delivery.")
    block("critical_conflicts_unverified", "No complete critical-conflict resolution assessment is pinned to this report.",
          "Inspect and resolve or explicitly block critical conflicts under the requested purpose.")
    if gaps:
        block("gap_ownership_unassigned", "Remaining gaps have recommendations but no confirmed owners.",
              "Assign owners through a governed decision; a read query must not assign another user.")
    readiness = {key: {"state": "unresolved", "coverage": None, "basis": "no_verified_purpose_assessment"}
                 for key in ("structure", "behavior", "traceability", "automation", "execution")}
    readiness["structure"] = {"state": "source_membership_verified_not_complete_coverage", "coverage": None,
                              "basis": "frozen_image_and_all_exact_member_evidence", "verified_evidence_count": verified_evidence_count}
    report = {"schema": COMPLETION_SCHEMA, "project_id": plan.intent.project_id,
              "plan_digest": plan.digest, "image_revision_id": review.image_revision_id,
              "image_artifact_hash": review.image_artifact_hash, "source_manifest_id": plan.intent.source_manifest_id,
              "source_manifest_hash": plan.intent.source_manifest_hash, "purpose": plan.intent.purpose,
              "delivery_kind": "candidate_only", "state": "blocked", "candidate_ready": False,
              "goal_completed": False, "publication_authorized": False, "execution_authorized": False,
              "required_artifacts": artifacts, "source_scans": sorted(scans, key=lambda item: item["source_revision_id"]),
              "code_analyses": sorted(analyses, key=lambda item: item["source_revision_id"]),
              "readiness": readiness, "budget": budget,
              "critical_conflicts": {"state": "unverified", "count": None},
              "gaps": gaps, "blockers": sorted(set(blockers))}
    if len(json.dumps(report, ensure_ascii=False, allow_nan=False).encode()) > 65536:
        raise BuildPlanIntegrityError("Completion assessment exceeds 64 KiB; no silent truncation is permitted.")
    return report


def completion_digest(report):
    return snapshot_digest(report)
