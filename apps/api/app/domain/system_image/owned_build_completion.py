"""A fixed responsibility revision refines an assessment, never resolves gaps."""
from copy import deepcopy
from dataclasses import dataclass
import json

from .build_plan import BuildPlanIntegrityError
from .gap_ownership import GAP_FIELDS, GapResponsibility, report_gaps, validate_responsibilities
from .source_snapshots import snapshot_digest


@dataclass(frozen=True)
class CompletionOwnershipProof:
    completion_invocation_id: str
    completion_report_hash: str
    revision_id: str
    revision_hash: str
    assignments: tuple[GapResponsibility, ...]

    def __post_init__(self):
        if (any(type(value) is not str or not 1 <= len(value) <= 128 or any(ord(c) < 32 for c in value)
                for value in (self.completion_invocation_id, self.revision_id))
                or any(type(value) is not str or len(value) != 71 or not value.startswith("sha256:")
                       or any(c not in "0123456789abcdef" for c in value[7:])
                       for value in (self.completion_report_hash, self.revision_hash))):
            raise BuildPlanIntegrityError("Completion responsibility proof requires exact IDs and digests.")


def assess_owned_completion(original, proof: CompletionOwnershipProof):
    if (original.get("schema") != "nasus.image-build-completion.v2"
            or snapshot_digest(original) != proof.completion_report_hash
            or original.get("state") != "blocked" or original.get("delivery_kind") != "candidate_only"
            or any(original.get(key) is not False for key in
                   ("candidate_ready", "goal_completed", "publication_authorized", "execution_authorized"))):
        raise BuildPlanIntegrityError("Responsibilities must refine one exact immutable v2 assessment.")
    gaps = report_gaps(original)
    assignments = validate_responsibilities(gaps, proof.assignments)
    owners = {item.gap_id: item.owner_actor_id for item in assignments}
    report = deepcopy(original)
    report["schema"] = "nasus.image-build-completion.v3"
    report["ownership"] = {"completion_invocation_id": proof.completion_invocation_id,
        "completion_report_hash": proof.completion_report_hash, "revision_id": proof.revision_id,
        "revision_hash": proof.revision_hash, "assignment_count": len(assignments),
        "basis": "confirmed_revision_not_gap_resolution"}
    report["gaps"] = []
    for gap in original["gaps"]:
        if gap["code"] == "gap_ownership_unassigned":
            continue
        ident = "gap_" + snapshot_digest({key: gap[key] for key in GAP_FIELDS})[7:]
        report["gaps"].append({**gap, "gap_id": ident, "owner_actor_id": owners[ident],
            "ownership_status": "confirmed", "resolution_status": "unresolved"})
    report["blockers"] = [code for code in original["blockers"] if code != "gap_ownership_unassigned"]
    if not report["blockers"]:
        raise BuildPlanIntegrityError("Assigning responsibilities cannot establish candidate delivery readiness.")
    if len(json.dumps(report, ensure_ascii=False, allow_nan=False).encode()) > 65536:
        raise BuildPlanIntegrityError("Owned completion exceeds 64 KiB; no partial assessment is returned.")
    return report
