"""Append-only plan phases retain old steps without treating them as active work."""
from dataclasses import asdict, dataclass
from typing import Optional

from .plan_policy import AgentPlanPolicyViolation
from .resume_checkpoint import AgentResumeCheckpoint
from .runtime_models import ToolPlanStep
from .image_plan_policy import validate_image_plan
from ..system_image.build_authorization import ApprovedBuildBudget
from ..system_image.image_revision import require_digest
from ..system_image.source_snapshots import snapshot_digest


PHASE_REF = "build_plan_phase:"
PHASE_POLICY = "nasus.agent-image-plan-phase.v1"
PHASE_PREPARED = "build_plan_phase_prepared"
COORDINATION_KEYS = frozenset({"goal_template", "goal_description", "tool_plan_index", "tool_plan_reason", "agent_loop_attempt"})


def active_phase_start(goal):
    refs = [ref[len(PHASE_REF):] for ref in getattr(goal, "target_refs", ()) if ref.startswith(PHASE_REF)]
    if not refs:
        return 0
    matches = [index for index, step in enumerate(goal.steps) if step.id == PHASE_REF + refs[0]]
    if len(refs) != 1 or len(matches) != 1:
        raise AgentPlanPolicyViolation("image_phase_marker_changed", "Active plan phase marker is missing or ambiguous.")
    return matches[0] + 1


def phase_target_refs(goal):
    start = active_phase_start(goal)
    if not start:
        return goal.target_refs
    marker = goal.steps[start - 1].tool_input_payload
    return [f"project:{goal.project_id}", f"build_plan:{marker.get('plan_id')}",
            f"source_manifest:{marker.get('source_manifest_id')}"]


def phase_contract(step):
    return {"id": step.id, "selected_tool_id": step.selected_tool_id,
            "input": {key: value for key, value in step.tool_input_payload.items() if key not in COORDINATION_KEYS}}


@dataclass(frozen=True)
class ImagePlanPhase:
    phase_id: str
    project_id: str
    goal_id: str
    root_plan_id: str
    revision_id: str
    revision_hash: str
    plan_id: str
    plan_digest: str
    source_manifest_id: str
    source_manifest_hash: str
    target_baseline_id: str
    target_version_id: Optional[str]
    parent_phase_id: Optional[str]
    parent_phase_hash: Optional[str]
    phase_number: int
    start_index: int
    prefix_hash: str
    contracts: tuple
    budget: ApprovedBuildBudget
    checkpoint: AgentResumeCheckpoint
    invocation_id: str
    created_at: str
    policy_version: str = PHASE_POLICY

    @property
    def digest(self):
        return snapshot_digest(asdict(self))

    def marker(self):
        return {"phase_id": self.phase_id, "phase_hash": self.digest, "plan_id": self.plan_id,
                "source_manifest_id": self.source_manifest_id}

    def require_valid(self):
        for value in (self.phase_id, self.project_id, self.goal_id, self.root_plan_id, self.revision_id,
                      self.plan_id, self.source_manifest_id, self.target_baseline_id, self.invocation_id):
            if type(value) is not str or not value or len(value) > 128 or any(ord(char) < 32 for char in value):
                raise AgentPlanPolicyViolation("image_phase_identity_changed", "Invalid plan phase identity.")
        for value in (self.revision_hash, self.plan_digest, self.source_manifest_hash, self.prefix_hash):
            require_digest(value)
        if self.parent_phase_hash is not None:
            require_digest(self.parent_phase_hash)
        for value in (self.parent_phase_id, self.target_version_id):
            if value is not None and (type(value) is not str or not value or len(value) > 128
                    or any(ord(char) < 32 for char in value)):
                raise AgentPlanPolicyViolation("image_phase_identity_changed", "Invalid optional plan phase identity.")
        if (self.policy_version != PHASE_POLICY or type(self.phase_number) is not int or not 1 <= self.phase_number <= 80
                or type(self.start_index) is not int or not 1 <= self.start_index <= 503
                or (self.parent_phase_id is None) != (self.parent_phase_hash is None)
                or (self.phase_number == 1) != (self.parent_phase_id is None)
                or self.checkpoint.goal_id != self.goal_id or self.checkpoint.project_id != self.project_id
                or len(self.contracts) != 7):
            raise AgentPlanPolicyViolation("image_phase_scope_changed", "Plan phase failed scope verification.")
        fixed = {"project_id": self.project_id, "plan_id": self.plan_id, "plan_digest": self.plan_digest,
                 "target_baseline_id": self.target_baseline_id}
        inputs = [("query.system_image.build_plans.read", {"project_id": self.project_id, "plan_id": self.plan_id}),
                  ("system_image.build.authorize", {**fixed, "budget": asdict(self.budget)}),
                  ("system_image.build.structure", fixed)]
        expected = []
        for number, (tool_id, payload) in enumerate(inputs, 1):
            expected.extend([{"id": f"phase_{self.phase_id}_act_{number}", "selected_tool_id": tool_id, "input": payload},
                             {"id": f"phase_{self.phase_id}_observe_{number}", "selected_tool_id": None, "input": {}}])
        expected.append({"id": f"phase_{self.phase_id}_decide", "selected_tool_id": None, "input": {}})
        if list(self.contracts) != expected:
            raise AgentPlanPolicyViolation("image_phase_work_changed", "Phase work differs from its independently confirmed contract.")


def verify_phase_chain(goal, phases):
    if not phases:
        if active_phase_start(goal) or any(step.id.startswith(PHASE_REF) for step in goal.steps):
            raise AgentPlanPolicyViolation("image_phase_receipt_missing", "Plan phase requires its durable activation receipt.")
        validate_image_plan([ToolPlanStep(step.selected_tool_id, step.tool_input_payload)
            for step in goal.steps if step.selected_tool_id], goal.target_refs)
        return 0
    if len(phases) > 80 or len(goal.steps) > 512 or len({step.id for step in goal.steps}) != len(goal.steps):
        raise AgentPlanPolicyViolation("image_phase_ledger_changed", "Plan phase history is invalid or oversized.")
    markers = [step.id for step in goal.steps if step.id.startswith(PHASE_REF)]
    if markers != [PHASE_REF + item.phase_id for item in phases]:
        raise AgentPlanPolicyViolation("image_phase_marker_changed", "Plan phase markers differ from the durable history.")
    previous = None
    for number, phase in enumerate(phases, 1):
        phase.require_valid()
        if (phase.project_id, phase.goal_id, phase.root_plan_id, phase.phase_number,
                phase.parent_phase_id, phase.parent_phase_hash) != (goal.project_id, goal.id, phases[0].root_plan_id,
                number, previous.phase_id if previous else None, previous.digest if previous else None):
            raise AgentPlanPolicyViolation("image_phase_ledger_changed", "Plan phase history is not its complete same-goal chain.")
        marker = goal.steps[phase.start_index] if phase.start_index < len(goal.steps) else None
        if (marker is None or marker.id != PHASE_REF + phase.phase_id or marker.selected_tool_id is not None
                or marker.status != "completed" or marker.tool_input_payload != phase.marker()
                or snapshot_digest([step.model_dump(mode="json") for step in goal.steps[:phase.start_index]]) != phase.prefix_hash):
            raise AgentPlanPolicyViolation("image_phase_history_changed", "Historical steps or activation marker changed.")
        end = phases[number].start_index if number < len(phases) else len(goal.steps)
        steps = goal.steps[phase.start_index + 1:end]
        by_id = {step.id: step for step in steps}
        if any(contract["id"] not in by_id or phase_contract(by_id[contract["id"]]) != contract for contract in phase.contracts):
            raise AgentPlanPolicyViolation("image_phase_work_changed", "Activated work changed its fixed inputs.")
        if ([step.id for step in steps[:6]] != [item["id"] for item in phase.contracts[:6]]
                or not steps or steps[-1].id != phase.contracts[-1]["id"]
                or any(steps[index].phase != "acting" for index in (0, 2, 4))):
            raise AgentPlanPolicyViolation("image_phase_work_changed", "Fixed phase work was reordered or detached from its observations.")
        validate_image_plan([ToolPlanStep(step.selected_tool_id, step.tool_input_payload)
            for step in steps if step.selected_tool_id], [f"project:{goal.project_id}", f"build_plan:{phase.plan_id}"])
        previous = phase
    if not {f"build_plan:{phases[0].root_plan_id}", PHASE_REF + phases[-1].phase_id} <= set(goal.target_refs):
        raise AgentPlanPolicyViolation("image_phase_scope_changed", "The original root or active phase reference changed.")
    if active_phase_start(goal) != phases[-1].start_index + 1:
        raise AgentPlanPolicyViolation("image_phase_scope_changed", "The active phase differs from the durable head.")
    root_steps = goal.steps[:phases[0].start_index]
    validate_image_plan([ToolPlanStep(step.selected_tool_id, step.tool_input_payload) for step in root_steps if step.selected_tool_id],
                        [ref for ref in goal.target_refs if not ref.startswith(PHASE_REF)])
    return phases[-1].start_index + 1
