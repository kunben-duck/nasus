"""Cumulative tool-work guardrails, not model-egress or execution consent."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .build_plan import BuildPlanIntegrityError
from .image_revision import require_digest
from .source_snapshots import snapshot_digest


class BuildToolBudgetExhausted(BuildPlanIntegrityError):
    pass


GOAL_BOUND_BUILD_CONTROLS = frozenset({
    "system_image.build.plan.revise", "system_image.build.plan.activate_revision",
})


@dataclass(frozen=True)
class BuildToolBudget:
    goal_id: str
    project_id: str
    conversation_id: str
    workflow_id: str | None
    max_tool_calls: int
    origin_digest: str
    origin_kind: str
    schema: str = "nasus.build-tool-budget.v1"

    def __post_init__(self):
        for value in (self.goal_id, self.project_id, self.conversation_id):
            if type(value) is not str or not value or len(value) > 128:
                raise BuildPlanIntegrityError("Invalid build tool budget scope.")
        if (type(self.max_tool_calls) is not int or not 1 <= self.max_tool_calls <= 1000
                or self.origin_kind not in {"saved_plan", "source_intent", "default_guardrail"}
                or self.schema != "nasus.build-tool-budget.v1"):
            raise BuildPlanIntegrityError("Invalid build tool budget policy.")
        require_digest(self.origin_digest)

    @property
    def digest(self):
        return snapshot_digest(asdict(self))

    def require_available(self, consumed):
        if type(consumed) is not int or not 0 <= consumed <= self.max_tool_calls:
            raise BuildPlanIntegrityError("Invalid cumulative tool consumption.")
        if consumed == self.max_tool_calls:
            raise BuildToolBudgetExhausted("The original goal's cumulative tool-work ceiling is exhausted.")


def consumption_payload(budget, *, invocation_id, tool_id, work_key, input_digest, sequence, previous_hash):
    budget.require_available(sequence - 1)
    require_digest(input_digest)
    require_digest(previous_hash)
    return {"schema": "nasus.build-tool-consumption.v1", "goal_id": budget.goal_id,
        "budget_hash": budget.digest, "invocation_id": invocation_id, "tool_id": tool_id,
        "work_key": work_key, "input_digest": input_digest, "sequence": sequence,
        "previous_hash": previous_hash, "tool_calls": 1}
