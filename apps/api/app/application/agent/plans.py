from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from .ports import AgentPlanStatePort
from ...domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep
from ...domain.agent.image_plan_policy import is_pinned_image_plan, validate_image_plan
from ...domain.agent.plan_policy import AgentPlanPolicyViolation
from .image_investigation_plans import AgentInvestigationPlanPort
from .build_intent_entries import AgentBuildIntentEntryPort, DIGEST_REF
from .natural_build_entries import REQUEST_REF
from .source_build_wait import WAIT_REF, WAIT_TOOL
from ...domain.agent.image_plan_phases import active_phase_start, phase_target_refs

if TYPE_CHECKING:
    from .agent_models import AgentGoal


class AgentImagePhasePort(Protocol):
    def verify_goal(self, goal: "AgentGoal") -> int: ...


@dataclass
class AgentGoalPlanCompiler:
    """Compiles high-level AgentGoal proposals into executable ToolPlanSteps.

    The compiler is deliberately outside the graph runtime: planning uses domain
    state and tool contracts, while the graph runtime only executes the compiled
    Think/Act/Observe/Decide steps.
    """

    state: AgentPlanStatePort
    investigations: AgentInvestigationPlanPort | None = None
    image_phases: AgentImagePhasePort | None = None
    build_intents: AgentBuildIntentEntryPort | None = None

    def validate_goal_plan(self, goal: "AgentGoal", extra_steps: list[ToolPlanStep] | None = None) -> None:
        start = active_phase_start(goal)
        if not start and any(ref.startswith((REQUEST_REF, WAIT_REF)) for ref in goal.target_refs):
            if self.build_intents is None:
                raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
            self.build_intents.validate_preparation_goal(goal)
        if start:
            if self.image_phases is None or self.image_phases.verify_goal(goal) != start:
                raise AgentPlanPolicyViolation("image_phase_receipt_missing", "A phased goal requires its authoritative activation ledger.")
        elif any(step.id.startswith("build_plan_phase:") for step in goal.steps):
            raise AgentPlanPolicyViolation("image_phase_marker_changed", "A phase marker has no active phase reference.")
        steps = [ToolPlanStep(step.selected_tool_id, step.tool_input_payload)
                 for step in goal.steps[start:] if step.selected_tool_id]
        validate_image_plan([*steps, *(extra_steps or [])], phase_target_refs(goal))

    def compile_tool_plan(self, proposal: AgentGoalProposal) -> list[ToolPlanStep]:
        explicit_steps = self._explicit_steps(proposal)
        if any(ref.startswith((DIGEST_REF, REQUEST_REF, WAIT_REF)) for ref in proposal.target_refs):
            if self.build_intents is None or explicit_steps:
                raise AgentPlanPolicyViolation("saved_build_intent_steps_changed", "Saved-intent entries use the canonical compiler, not caller-provided steps.")
            generated = self.build_intents.compile(proposal)
            if not generated:
                raise AgentPlanPolicyViolation("saved_build_intent_unavailable", "The saved intent could not be compiled.")
            validate_image_plan(generated, proposal.target_refs)
            return self._validate_known_tools(generated)
        context_steps = []
        if any(key in proposal.initial_tool_input for key in ("plan_id", "source_manifest_id", "image_revision_id")):
            context_steps = [ToolPlanStep("system_image.build.plan", proposal.initial_tool_input)]
        validate_image_plan([*context_steps, *explicit_steps], proposal.target_refs)
        if explicit_steps:
            return self._validate_known_tools(explicit_steps)
        if is_pinned_image_plan(context_steps, proposal.target_refs) or proposal.goal_template == "system_image_investigation":
            raise AgentPlanPolicyViolation("pinned_image_steps_required", "Read the saved plan and provide explicit fixed-input work; mutable state planning is not allowed.")
        if proposal.goal_template == "system_image_build":
            project_id = self._project_id_from_proposal(proposal)
            return self._compile_system_image_plan_for_project(project_id)
        return []

    def compile_preparation_continuation(self, goal, invocation):
        if (invocation.tool_id != "system_image.build.plan"
                or not any(ref.startswith(REQUEST_REF) for ref in goal.target_refs)):
            return None
        if self.build_intents is None:
            raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
        refs, steps = self.build_intents.preparation_continuation(goal, invocation)
        self.validate_goal_plan(goal.model_copy(update={"target_refs": refs}), steps)
        return refs, self._validate_known_tools(steps)

    def compile_source_input_continuation(self, goal):
        if (not any(ref.startswith(WAIT_REF) for ref in goal.target_refs)
                or any(ref.startswith(REQUEST_REF) for ref in goal.target_refs)):
            return None
        if self.build_intents is None:
            raise AgentPlanPolicyViolation("build_preparation_unavailable", "Build preparation is unavailable.")
        self.validate_goal_plan(goal)
        refs, steps = self.build_intents.source_input_continuation(goal)
        original = [ToolPlanStep(step.selected_tool_id, step.tool_input_payload)
                    for step in goal.steps if step.selected_tool_id]
        if len(original) != 1 or original[0].tool_id != WAIT_TOOL:
            raise AgentPlanPolicyViolation("build_input_wait_scope_changed", "The original waiting command changed.")
        validate_image_plan([*original, *steps], refs)
        return refs, self._validate_known_tools(steps)

    def compile_followup_tool_plan(self, goal: "AgentGoal") -> list[ToolPlanStep]:
        """Compile remaining tools after a paused goal receives missing context.

        Initial planning may intentionally stop at a follow-up tool, for example
        when a system-image goal first needs real source bindings from the user.
        Once the blocked tool succeeds, the graph runtime asks the compiler for a
        fresh state-aware plan and inserts the remaining canonical tool steps into
        the same AgentGoal.
        """

        if self.investigations is not None:
            self.validate_goal_plan(goal)
            proposed = self.investigations.followup(goal)
            if proposed:
                self.validate_goal_plan(goal, proposed)
                return self._validate_known_tools(proposed)
        steps = [ToolPlanStep(tool_id=step.selected_tool_id, input_payload=step.tool_input_payload)
                 for step in goal.steps[active_phase_start(goal):] if step.selected_tool_id]
        if is_pinned_image_plan(steps, phase_target_refs(goal)) or goal.goal_template == "system_image_investigation":
            return []
        if not self._is_system_image_goal(goal):
            return []
        return self._compile_system_image_plan_for_project(self._project_id_from_goal(goal))

    def compile_structure_continuation(self, goal: "AgentGoal") -> list[ToolPlanStep]:
        if self.investigations is None:
            return []
        self.validate_goal_plan(goal)
        proposed = self.investigations.after_structure(goal)
        self.validate_goal_plan(goal, proposed)
        return self._validate_known_tools(proposed)

    def compile_reference_continuation(self, goal: "AgentGoal") -> list[ToolPlanStep]:
        if self.investigations is None:
            return []
        self.validate_goal_plan(goal)
        proposed = self.investigations.after_reference(goal)
        self.validate_goal_plan(goal, proposed)
        return self._validate_known_tools(proposed)

    def _explicit_steps(self, proposal: AgentGoalProposal) -> list[ToolPlanStep]:
        if proposal.planned_tools:
            return proposal.planned_tools
        if proposal.initial_tool_id is None:
            return []
        return [
            ToolPlanStep(
                tool_id=proposal.initial_tool_id,
                input_payload=proposal.initial_tool_input,
            )
        ]

    def _compile_system_image_plan_for_project(self, project_id: str | None) -> list[ToolPlanStep]:
        if not project_id or not self.state.project_exists(project_id):
            return []

        steps: list[ToolPlanStep] = []
        if self.state.source_binding_incomplete(project_id):
            return self._validate_known_tools(
                [
                    ToolPlanStep(
                        tool_id="system_image.sources.register",
                        input_payload={"project_id": project_id, "requires_source_binding": True},
                        reason=(
                            "The system image requires a code source before ingestion. Historical US documents "
                            "and test assets are optional enrichment sources."
                        ),
                    )
                ]
            )

        source_statuses = self.state.source_ingestion_statuses(project_id)
        all_sources_indexed = bool(source_statuses) and all(status == "indexed" for status in source_statuses)
        has_context = self.state.has_materialized_context(project_id)
        baseline_ready = self.state.has_ready_official_baseline(project_id)

        if not source_statuses:
            steps.append(
                ToolPlanStep(
                    tool_id="system_image.sources.register",
                    input_payload={"project_id": project_id},
                    reason="No system image source groups are registered yet.",
                )
            )
        if not all_sources_indexed:
            steps.append(
                ToolPlanStep(
                    tool_id="system_image.sources.ingest",
                    input_payload={"project_id": project_id},
                    reason="Registered source groups are not fully indexed.",
                )
            )
        if not has_context:
            steps.append(
                ToolPlanStep(
                    tool_id="system_image.context.materialize",
                    input_payload={"project_id": project_id},
                    reason="The project does not yet have materialized context objects, relationships, and metrics.",
                )
            )
        if not baseline_ready:
            steps.append(
                ToolPlanStep(
                    tool_id="system_image.baseline.initialize",
                    input_payload={"project_id": project_id},
                    reason="The Official System Image baseline is not ready.",
                )
            )
        return self._validate_known_tools(steps)

    def _project_id_from_proposal(self, proposal: AgentGoalProposal) -> str | None:
        for payload in self._proposal_payloads(proposal):
            project_id = payload.get("project_id")
            if isinstance(project_id, str) and project_id:
                return project_id
        for target_ref in proposal.target_refs:
            if target_ref.startswith("project:"):
                return target_ref.split(":", 1)[1]
        for query_key in proposal.query_keys:
            if len(query_key) >= 2 and query_key[0] in {"project", "system-image", "knowledge"}:
                return query_key[1]
        return None

    @staticmethod
    def _proposal_payloads(proposal: AgentGoalProposal) -> list[dict[str, Any]]:
        payloads = [proposal.initial_tool_input]
        payloads.extend(step.input_payload for step in proposal.planned_tools)
        return payloads

    @staticmethod
    def _is_system_image_goal(goal: "AgentGoal") -> bool:
        if any(step.tool_input_payload.get("goal_template") == "system_image_build" for step in goal.steps):
            return True
        return "system image" in goal.title.lower() or "system image" in goal.summary.lower()

    @staticmethod
    def _project_id_from_goal(goal: "AgentGoal") -> str | None:
        if goal.project_id:
            return goal.project_id
        for step in goal.steps:
            project_id = step.tool_input_payload.get("project_id")
            if isinstance(project_id, str) and project_id:
                return project_id
        return None

    def _validate_known_tools(self, steps: list[ToolPlanStep]) -> list[ToolPlanStep]:
        known_tool_ids = self.state.known_tool_ids()
        unknown_tool_ids = [step.tool_id for step in steps if step.tool_id not in known_tool_ids]
        if unknown_tool_ids:
            raise ValueError(f"AgentGoal plan referenced unknown tools: {', '.join(unknown_tool_ids)}")
        return steps


__all__ = ["AgentGoalPlanCompiler"]
