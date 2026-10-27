"""Source enrichment is a new immutable proposal, never transferred consent."""
from dataclasses import asdict, dataclass
from typing import Optional

from ..agent.resume_checkpoint import AgentResumeCheckpoint
from .build_plan import BuildPlanIntegrityError, InvestigationPlan, TargetedBuildIntent, propose_build_plan
from .image_revision import require_digest
from .source_snapshots import CapturedSourceManifest, snapshot_digest


PLAN_REVISION_POLICY = "nasus.image-build-plan-revision.v1"
REVISION_PAUSE_REASONS = frozenset({"structural_candidate_review", "build_completion_review"})


def enriched_proposal(previous: InvestigationPlan, manifest: CapturedSourceManifest) -> InvestigationPlan:
    intent = previous.intent
    if manifest.project_id != intent.project_id or manifest.manifest_id == intent.source_manifest_id:
        raise BuildPlanIntegrityError("Enrichment requires a different manifest in the same project.")
    before = {item.binding_id: item for item in intent.sources}
    after = {item.binding_id: item for item in manifest.members}
    if len(after) != len(manifest.members) or not before.keys() <= after.keys():
        raise BuildPlanIntegrityError("Enrichment cannot remove or duplicate source bindings.")
    for binding_id, pin in before.items():
        current = after[binding_id]
        if current.source_type != pin.source_type or (pin.status == "captured" and current != pin):
            raise BuildPlanIntegrityError("Enrichment cannot replace an already captured revision.")
    additions = [item for key, item in after.items() if key not in before or item != before[key]]
    if not additions or any(item.status != "captured" for item in additions):
        raise BuildPlanIntegrityError("Enrichment needs newly captured sources, not pending placeholders.")
    if not any(item.source_type == "code" and item.status == "captured" for item in manifest.members):
        raise BuildPlanIntegrityError("A captured code source is required.")
    return propose_build_plan(manifest, objective=intent.objective, mode="enrich", purpose=intent.purpose,
                              budget=intent.budget, target=intent.target if isinstance(intent, TargetedBuildIntent) else None)


@dataclass(frozen=True)
class BuildPlanRevision:
    revision_id: str
    project_id: str
    goal_id: str
    root_plan_id: str
    from_plan_id: str
    from_plan_digest: str
    plan_id: str
    plan_digest: str
    source_manifest_id: str
    source_manifest_hash: str
    parent_revision_id: Optional[str]
    parent_revision_hash: Optional[str]
    revision_number: int
    checkpoint: AgentResumeCheckpoint
    invocation_id: str
    created_at: str
    policy_version: str = PLAN_REVISION_POLICY
    execution_authorized: bool = False
    publication_authorized: bool = False

    @property
    def digest(self):
        return snapshot_digest(asdict(self))

    def require_valid(self):
        for value in (self.revision_id, self.project_id, self.goal_id, self.root_plan_id,
                      self.from_plan_id, self.plan_id, self.source_manifest_id, self.invocation_id):
            if type(value) is not str or not value or len(value) > 128 or any(ord(char) < 32 for char in value):
                raise BuildPlanIntegrityError("Build plan revision has an invalid identity.")
        for value in (self.from_plan_digest, self.plan_digest, self.source_manifest_hash):
            require_digest(value)
        if self.parent_revision_hash is not None:
            require_digest(self.parent_revision_hash)
        if (self.policy_version != PLAN_REVISION_POLICY or self.execution_authorized is not False
                or self.publication_authorized is not False or not 1 <= self.revision_number <= 80
                or self.checkpoint.goal_id != self.goal_id or self.checkpoint.project_id != self.project_id
                or self.from_plan_id == self.plan_id
                or (self.revision_number == 1) != (self.parent_revision_id is None)
                or (self.parent_revision_id is None) != (self.parent_revision_hash is None)):
            raise BuildPlanIntegrityError("Build plan revision failed its fixed-scope verification.")
