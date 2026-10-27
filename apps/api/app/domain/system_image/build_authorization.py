"""Immutable, bounded execution consent. Publication is never implied."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from .build_plan import BuildPlanIntegrityError, InvestigationPlan
from .source_snapshots import snapshot_digest


AUTHORIZE_BUILD_TOOL = "system_image.build.authorize"
STRUCTURE_BUILD_TOOL = "system_image.build.structure"
AUTHORIZATION_POLICY = "nasus.image-build-authorization.v1"


@dataclass(frozen=True)
class ApprovedBuildBudget:
    max_tool_calls: int
    max_model_calls: int
    max_active_seconds: int
    max_cost_microusd: int

    def __post_init__(self):
        for name, lower, upper in (("max_tool_calls", 1, 1000), ("max_model_calls", 0, 1000),
                                    ("max_active_seconds", 1, 86400), ("max_cost_microusd", 0, 10**9)):
            if type(getattr(self, name)) is not int or not lower <= getattr(self, name) <= upper:
                raise BuildPlanIntegrityError("Invalid approved build budget.")

    def validate_plan(self, plan: InvestigationPlan):
        proposed = plan.intent.budget
        for name in ("max_tool_calls", "max_model_calls", "max_active_seconds"):
            if getattr(self, name) > getattr(proposed, name):
                raise BuildPlanIntegrityError("Execution consent cannot enlarge the proposed budget.")
        if proposed.max_cost_microusd is not None and self.max_cost_microusd > proposed.max_cost_microusd:
            raise BuildPlanIntegrityError("Execution consent cannot enlarge the proposed cost ceiling.")
        # Semantic execution also needs a separate model-egress capability.
        if self.max_model_calls or self.max_cost_microusd:
            raise BuildPlanIntegrityError("This executor cannot authorize model calls or model egress.")


@dataclass(frozen=True)
class BuildExecutionAuthorization:
    authorization_id: str
    project_id: str
    goal_id: str
    conversation_id: str
    plan_id: str
    plan_digest: str
    source_manifest_id: str
    source_manifest_hash: str
    target_baseline_id: str
    target_version_id: Optional[str]
    authorization_invocation_id: str
    authorized_by: str
    confirmed_at: str
    budget: ApprovedBuildBudget
    work_item_ids: tuple[str, ...] = ("structure",)
    policy_version: str = AUTHORIZATION_POLICY
    publication_allowed: bool = False

    def __post_init__(self):
        if (self.policy_version != AUTHORIZATION_POLICY or self.publication_allowed is not False
                or self.work_item_ids != ("structure",)):
            raise BuildPlanIntegrityError("Unsupported build execution authority.")
        try:
            if datetime.fromisoformat(self.confirmed_at).tzinfo is None:
                raise ValueError("missing timezone")
        except (TypeError, ValueError) as exc:
            raise BuildPlanIntegrityError("Execution consent requires a confirmation timestamp.") from exc

    @property
    def digest(self):
        return snapshot_digest(asdict(self))

    def require_time_available(self, now: Optional[datetime] = None):
        elapsed = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(self.confirmed_at)).total_seconds()
        if not 0 <= elapsed <= self.budget.max_active_seconds:
            raise TimeoutError("Approved build execution time has expired.")


def authorization_from_dict(payload: dict) -> BuildExecutionAuthorization:
    return BuildExecutionAuthorization(**{**payload, "budget": ApprovedBuildBudget(**payload["budget"]),
                                         "work_item_ids": tuple(payload["work_item_ids"])})
