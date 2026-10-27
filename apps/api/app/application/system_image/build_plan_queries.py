from __future__ import annotations

from dataclasses import asdict
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ...domain.system_image.build_plan import BuildPlanIntegrityError, InvestigationPlan, MAX_PLAN_BYTES
from ...domain.system_image.build_plan import TargetedBuildIntent
from .build_plans import BuildPlanApplicationService


READ_BUILD_PLAN_TOOL = "query.system_image.build_plans.read"


class BuildPlanReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: StrictStr = Field(min_length=1, max_length=128)
    plan_id: StrictStr = Field(min_length=1, max_length=128)


class BuildPlanReadReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["build_plan_read"] = "build_plan_read"
    request: BuildPlanReadInput
    plan_digest: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    source_manifest_id: StrictStr
    source_manifest_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    policy_version: StrictStr
    state: Literal["draft"] = "draft"
    authorization_state: Literal["not_granted"] = "not_granted"
    execution_ready: Literal[False] = False


class BuildPlanQueryApplicationService:
    """Replay immutable plans, never a current head or a growing artifact list."""

    def __init__(self, plans: BuildPlanApplicationService):
        self.plans = plans

    def execute(self, request: BuildPlanReadInput) -> BuildPlanReadReceipt:
        plan = self.plans.read(request.project_id, request.plan_id).proposal
        return self._receipt(request, plan)

    def expand(self, receipt: BuildPlanReadReceipt) -> InvestigationPlan:
        plan = self.plans.read(receipt.request.project_id, receipt.request.plan_id).proposal
        if self._receipt(receipt.request, plan) != receipt:
            raise BuildPlanIntegrityError("Build plan receipt does not match its fixed inputs.")
        return plan

    @staticmethod
    def _receipt(request: BuildPlanReadInput, plan: InvestigationPlan) -> BuildPlanReadReceipt:
        if len(json.dumps(asdict(plan), ensure_ascii=False).encode("utf-8")) > MAX_PLAN_BYTES:
            raise BuildPlanIntegrityError("Build plan exceeds the observation limit.")
        return BuildPlanReadReceipt(request=request, plan_digest=plan.digest,
            source_manifest_id=plan.intent.source_manifest_id, source_manifest_hash=plan.intent.source_manifest_hash,
            policy_version=plan.policy_version, state=plan.state,
            authorization_state=plan.authorization_state, execution_ready=plan.execution_ready)

    @staticmethod
    def describe(plan: InvestigationPlan, receipt: BuildPlanReadReceipt) -> dict:
        # User objectives, questions and source content are not implicit model egress.
        target = {"target": asdict(plan.intent.target), "scope_binding_ids": list(plan.intent.scope_binding_ids)} if isinstance(plan.intent, TargetedBuildIntent) else {}
        return {**receipt.model_dump(mode="json"), **target, "purpose": plan.intent.purpose,
            "mode": plan.intent.mode, "proposed_budget": asdict(plan.intent.budget),
            "sources": [asdict(source) for source in plan.intent.sources],
            "work_items": [{key: asdict(item)[key] for key in (
                "work_item_id", "capability", "proposed_tool_id", "binding_state", "source_binding_ids",
                "dependency_ids", "output_artifact", "max_attempts", "max_tool_calls", "max_model_calls", "failure_action")}
                for item in plan.work_items], "gap_codes": [gap.code for gap in plan.gaps]}
