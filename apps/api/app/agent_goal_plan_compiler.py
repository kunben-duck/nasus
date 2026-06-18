from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .agent_runtime_models import AgentGoalProposal, ToolPlanStep

if TYPE_CHECKING:
    from .models import AgentGoal
    from .store import ApplicationStore


@dataclass
class AgentGoalPlanCompiler:
    """Compiles high-level AgentGoal proposals into executable ToolPlanSteps.

    The compiler is deliberately outside the graph runtime: planning uses domain
    state and tool contracts, while the graph runtime only executes the compiled
    Think/Act/Observe/Decide steps.
    """

    store: "ApplicationStore"

    def compile_tool_plan(self, proposal: AgentGoalProposal) -> list[ToolPlanStep]:
        explicit_steps = self._explicit_steps(proposal)
        if explicit_steps:
            return self._validate_known_tools(explicit_steps)
        if proposal.goal_template == "system_image_build":
            project_id = self._project_id_from_proposal(proposal)
            return self._compile_system_image_plan_for_project(project_id)
        return []

    def compile_followup_tool_plan(self, goal: "AgentGoal") -> list[ToolPlanStep]:
        """Compile remaining tools after a paused goal receives missing context.

        Initial planning may intentionally stop at a follow-up tool, for example
        when a system-image goal first needs real source bindings from the user.
        Once the blocked tool succeeds, the graph runtime asks the compiler for a
        fresh state-aware plan and inserts the remaining canonical tool steps into
        the same AgentGoal.
        """

        if not self._is_system_image_goal(goal):
            return []
        return self._compile_system_image_plan_for_project(self._project_id_from_goal(goal))

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
        if not project_id or project_id not in self.store.projects:
            return []

        steps: list[ToolPlanStep] = []
        if self.store.system_image_service.source_binding_incomplete(project_id):
            return self._validate_known_tools(
                [
                    ToolPlanStep(
                        tool_id="system_image.sources.register",
                        input_payload={"project_id": project_id, "requires_source_binding": True},
                        reason="The system image requires code, historical US document, and historical test asset sources before ingestion.",
                    )
                ]
            )

        sources = self.store.raw_assets.get(project_id, [])
        all_sources_indexed = bool(sources) and all(source.ingestion_status == "indexed" for source in sources)
        has_context = bool(self.store.knowledge_objects.get(project_id)) and bool(
            self.store.context_relationships.get(project_id)
        ) and bool(self.store.quality_metric_snapshots.get(project_id))
        baseline_ready = any(
            baseline.kind == "official" and baseline.status == "ready"
            for baseline in self.store.baselines.get(project_id, [])
        )

        if not sources:
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
        known_tool_ids = {tool.tool_id for tool in self.store.tools}
        unknown_tool_ids = [step.tool_id for step in steps if step.tool_id not in known_tool_ids]
        if unknown_tool_ids:
            raise ValueError(f"AgentGoal plan referenced unknown tools: {', '.join(unknown_tool_ids)}")
        return steps
