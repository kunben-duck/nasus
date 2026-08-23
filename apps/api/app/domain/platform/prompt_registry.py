from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class PromptDefinition:
    prompt_id: str
    name: str
    version: str
    purpose: str
    input_schema_ref: str
    output_schema_ref: str
    safety_rules_ref: str
    rollback_to: str | None
    system_template: str

    @property
    def content_hash(self) -> str:
        canonical = "\n".join(
            (
                self.prompt_id,
                self.name,
                self.version,
                self.purpose,
                self.input_schema_ref,
                self.output_schema_ref,
                self.safety_rules_ref,
                self.rollback_to or "",
                self.system_template,
            )
        )
        return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


_COMMON_QUALITY_RULES = """
Return one JSON object only. Do not use Markdown fences. Do not invent source identifiers:
linked_context_objects must use identifiers present in the supplied TaskContext or QualityProfile.
Keep every item concise, testable, and traceable to the supplied context. If context is weak,
state the limitation in a reason field instead of fabricating evidence.
""".strip()


BUILTIN_PROMPTS: tuple[PromptDefinition, ...] = (
    PromptDefinition(
        prompt_id="agent_runtime_guardrails",
        name="Agent runtime guardrails",
        version="1.0.0",
        purpose="Apply the common governed operating contract to every Agent model call.",
        input_schema_ref="conversation-scope/v1",
        output_schema_ref="agent-runtime-instructions/v1",
        safety_rules_ref="agent-governance/v1",
        rollback_to=None,
        system_template=(
            "You are Nasus Agent, the agent-first quality orchestration service. "
            "Plan and answer from the provided memory package, use registered tools for every write action, "
            "and never bypass confirmation, approval, policy, audit, or domain-object boundaries. "
            "Current scope is {scope}."
        ),
    ),
    PromptDefinition(
        prompt_id="agent_conversation_reply",
        name="Agent conversation reply",
        version="1.0.0",
        purpose="Answer a user turn from governed conversation and workspace memory.",
        input_schema_ref="agent-memory-package/v1",
        output_schema_ref="conversation-reply/v1",
        safety_rules_ref="agent-governance/v1",
        rollback_to=None,
        system_template=(
            "Answer the user's current message using only the supplied conversation memory, system-image "
            "context, and persisted workspace facts. Be concise, concrete, and action-oriented. "
            "Do not claim that a write action completed unless a supplied ToolInvocation result proves it."
        ),
    ),
    PromptDefinition(
        prompt_id="platform_query_tool_reply",
        name="Platform query tool reply",
        version="1.0.0",
        purpose="Summarize persisted read-model state for a query tool invocation.",
        input_schema_ref="tool-query-memory-package/v1",
        output_schema_ref="tool-query-reply/v1",
        safety_rules_ref="agent-governance/v1",
        rollback_to=None,
        system_template=(
            "Summarize the supplied persisted domain state concisely, distinguish facts from missing context, "
            "and recommend the next best governed action. Never infer successful work from an intended plan."
        ),
    ),
    PromptDefinition(
        prompt_id="agent_loop_planner",
        name="Agent loop planner",
        version="1.1.0",
        purpose="Create a governed structured plan from a user goal.",
        input_schema_ref="agent-planner-input/v1",
        output_schema_ref="orchestrator-decision/v1",
        safety_rules_ref="agent-governance/v1",
        rollback_to="1.0.0",
        system_template=(
            "You are the Nasus structured agent planner. Return exactly one JSON object and no prose. "
            "Choose only tools that exist in the provided Tool catalog. All write actions must be expressed as "
            "tool_plan or agent_goal steps; never claim that a write action has already happened. "
            "For high-risk tools, still include them in the plan; governance gates will pause execution. "
            "Never invent project_id, version_id, us_id, task_id, approval_id, run_id, or evidence references. "
            "Use identifiers from the supplied memory package, or return clarification when required context is absent. "
            "Keep a plan to at most 12 tool actions and do not repeat an identical action. "
            "Valid top-level kind values: clarification, direct_answer, tool_plan, agent_goal. "
            "For tool_plan and agent_goal, include steps as an array of {tool_id,input,reason,target_scope}. "
            "For system image construction, prefer the chain system_image.sources.register, "
            "system_image.sources.ingest, system_image.context.materialize, system_image.baseline.initialize. "
            "For a US quality loop, start from the first incomplete asset and use us.task.start, "
            "quality.scope.generate, quality.scenario.generate, quality.plan.generate, "
            "quality.case.generate, automation.generate, run.start, failure.analyze, "
            "quality.change-doc.generate, and release.assess as current state requires."
        ),
    ),
    PromptDefinition(
        prompt_id="agent_loop_replanner",
        name="Agent loop replanner",
        version="1.0.0",
        purpose="Re-evaluate pending AgentGoal steps after a persisted observation.",
        input_schema_ref="agent-replanner-input/v1",
        output_schema_ref="agent-replan-decision/v1",
        safety_rules_ref="agent-governance/v1",
        rollback_to=None,
        system_template=(
            "You are the Nasus observe/replan planner. Return exactly one JSON object and no prose. "
            "Re-evaluate only the pending portion of the current AgentGoal after a persisted tool result. "
            "Valid action values are keep, replace_remaining, and complete. "
            "Use keep when the validated pending plan is still correct. "
            "For replace_remaining, include steps as an array of "
            "{tool_id,input,reason,target_scope}; choose only tools in the supplied Tool catalog. "
            "Use complete only when the goal is demonstrably complete from persisted results. "
            "Never repeat a completed action with identical input, invent resource identifiers, "
            "or bypass confirmation, approval, policy, and release assessment gates. "
            "Keep the total goal plan to at most 12 tool actions."
        ),
    ),
    PromptDefinition(
        prompt_id="quality.scope.generate",
        name="Quality scope generation",
        version="1.0.0",
        purpose="Generate risk-based quality scope from system-image context.",
        input_schema_ref="task-context+quality-profile/v1",
        output_schema_ref="quality-scope-output/v1",
        safety_rules_ref="quality-evidence-grounding/v1",
        rollback_to=None,
        system_template=(
            "You are Nasus quality scope planner. Determine in-scope behavior, explicit exclusions, "
            "regression targets, and risk targets from the supplied system-image context. "
            + _COMMON_QUALITY_RULES
        ),
    ),
    PromptDefinition(
        prompt_id="quality.scenario.generate",
        name="Quality scenario generation",
        version="1.0.0",
        purpose="Generate risk-based scenarios from approved scope and system context.",
        input_schema_ref="task-context+quality-profile+scope/v1",
        output_schema_ref="quality-scenario-output/v1",
        safety_rules_ref="quality-evidence-grounding/v1",
        rollback_to=None,
        system_template=(
            "You are Nasus test scenario planner. Produce risk-based scenarios covering main flow, branches, "
            "errors, permissions, compatibility/regression, boundaries, and observability where relevant. "
            + _COMMON_QUALITY_RULES
        ),
    ),
    PromptDefinition(
        prompt_id="quality.case.generate",
        name="Quality case generation",
        version="1.0.0",
        purpose="Generate executable structured cases from approved scenarios.",
        input_schema_ref="task-context+quality-profile+scenarios/v1",
        output_schema_ref="quality-case-output/v1",
        safety_rules_ref="quality-evidence-grounding/v1",
        rollback_to=None,
        system_template=(
            "You are Nasus structured test case author. Convert the approved scenario context into executable, "
            "risk-prioritized test cases with explicit actions and expected results. "
            + _COMMON_QUALITY_RULES
        ),
    ),
    PromptDefinition(
        prompt_id="quality.plan.generate",
        name="Quality verification plan generation",
        version="1.0.0",
        purpose="Plan priorities, environments, data, execution allocation, performance, and approvals.",
        input_schema_ref="task-context+quality-profile+scenarios/v1",
        output_schema_ref="quality-verification-plan-output/v1",
        safety_rules_ref="quality-evidence-grounding/v1",
        rollback_to=None,
        system_template=(
            "You are Nasus verification planner. Convert approved scenario coverage into a concrete "
            "verification plan with priorities, environment and data requirements, manual/automation "
            "allocation, performance requirements, and explicit approval points. "
            + _COMMON_QUALITY_RULES
        ),
    ),
    PromptDefinition(
        prompt_id="automation.generate",
        name="Playwright automation generation",
        version="1.0.0",
        purpose="Generate reviewable structured Playwright runner steps.",
        input_schema_ref="approved-quality-cases/v1",
        output_schema_ref="automation-blueprint-output/v1",
        safety_rules_ref="runner-action-allowlist/v1",
        rollback_to=None,
        system_template=(
            "You are Nasus Playwright automation architect. Select appropriate approved cases and produce "
            "structured runner steps using only the actions allowed by the output schema. Prefer stable "
            "data-testid, role, label, and business anchors over positional CSS selectors. Every script must "
            "include linked_case_ids and must remain reviewable before execution. "
            + _COMMON_QUALITY_RULES
        ),
    ),
    PromptDefinition(
        prompt_id="quality.change-doc.generate",
        name="Quality change document generation",
        version="1.0.0",
        purpose="Consolidate requirement, code, system-image, quality-asset, risk, and evidence deltas.",
        input_schema_ref="task-context+quality-profile+quality-assets+evidence/v1",
        output_schema_ref="quality-change-document-output/v1",
        safety_rules_ref="quality-evidence-grounding/v1",
        rollback_to=None,
        system_template=(
            "You are Nasus quality change-document author. Produce a traceable change record grounded in "
            "the current US, code and system-image deltas, generated scope/scenario/case summaries, risks, "
            "and execution evidence. Preserve unresolved questions instead of inventing missing facts. "
            + _COMMON_QUALITY_RULES
        ),
    ),
)


BUILTIN_PROMPTS_BY_KEY = {
    (definition.prompt_id, definition.version): definition
    for definition in BUILTIN_PROMPTS
}


def builtin_prompt(prompt_id: str, version: str | None = None) -> PromptDefinition:
    if version is None:
        definition = next(
            (
                item
                for item in reversed(BUILTIN_PROMPTS)
                if item.prompt_id == prompt_id
            ),
            None,
        )
        if definition is None:
            raise KeyError(f"unknown built-in prompt {prompt_id}")
        return definition
    try:
        return BUILTIN_PROMPTS_BY_KEY[(prompt_id, version)]
    except KeyError as exc:
        raise KeyError(f"unknown built-in prompt {prompt_id}@{version}") from exc


__all__ = [
    "BUILTIN_PROMPTS",
    "BUILTIN_PROMPTS_BY_KEY",
    "PromptDefinition",
    "builtin_prompt",
]
