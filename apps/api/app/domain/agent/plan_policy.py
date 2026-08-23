from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from .runtime_models import ToolPlanStep


@dataclass(frozen=True)
class AgentPlanScope:
    conversation_id: str
    project_id: str | None = None
    version_id: str | None = None
    us_id: str | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class AgentToolContract:
    tool_id: str
    scope: Literal["central", "edge", "either"]
    required_context: tuple[str, ...] = ()


class AgentPlanPolicyViolation(ValueError):
    def __init__(
        self,
        code: str,
        summary: str,
        *,
        missing_context: tuple[str, ...] = (),
    ) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary
        self.missing_context = missing_context


class AgentPlanPolicy:
    """Validates and binds untrusted planner output to the active conversation scope."""

    _scope_keys = ("conversation_id", "project_id", "version_id", "us_id", "task_id")
    _required_context_aliases = {
        "project_name": ("project_name", "name"),
        "version_name": ("version_name", "name"),
    }
    _reserved_runtime_keys = {
        "agent_goal_id",
        "agent_loop_iteration_id",
        "agent_loop_attempt",
        "agent_autonomy_level",
        "approved_at",
        "approved_by",
        "approval_status",
        "confirmed_at",
        "confirmed_by",
        "confirmed_by_user",
        "goal_description",
        "goal_template",
        "idempotency_key",
        "policy_snapshot_id",
        "tool_plan_index",
        "tool_plan_reason",
    }

    def __init__(self, *, max_tool_steps: int = 12, max_input_bytes: int = 32_768) -> None:
        self.max_tool_steps = max_tool_steps
        self.max_input_bytes = max_input_bytes

    def bind_and_validate(
        self,
        steps: list[ToolPlanStep],
        *,
        contracts: list[AgentToolContract],
        scope: AgentPlanScope,
    ) -> list[ToolPlanStep]:
        if not steps:
            raise AgentPlanPolicyViolation("empty_plan", "The planner did not select an executable tool.")
        if len(steps) > self.max_tool_steps:
            raise AgentPlanPolicyViolation(
                "step_budget_exceeded",
                f"The planner selected {len(steps)} tools, above the limit of {self.max_tool_steps}.",
            )

        contract_by_id = {contract.tool_id: contract for contract in contracts}
        bound_steps: list[ToolPlanStep] = []
        fingerprints: set[str] = set()
        for step in steps:
            contract = contract_by_id.get(step.tool_id)
            if contract is None:
                raise AgentPlanPolicyViolation(
                    "unknown_tool",
                    f"The planner selected an unregistered tool: {step.tool_id}.",
                )
            target_scope = self._validated_target_scope(step, contract)
            input_payload = self._sanitize_payload(step.input_payload)
            self._bind_scope(input_payload, scope)
            self._validate_required_context(input_payload, contract)
            self._validate_payload_size(input_payload, step.tool_id)

            fingerprint = json.dumps(
                [step.tool_id, target_scope, input_payload],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            if fingerprint in fingerprints:
                raise AgentPlanPolicyViolation(
                    "duplicate_action",
                    f"The planner repeated the same {step.tool_id} action with identical input.",
                )
            fingerprints.add(fingerprint)
            bound_steps.append(
                ToolPlanStep(
                    tool_id=step.tool_id,
                    input_payload=input_payload,
                    target_scope=target_scope,
                    reason=step.reason,
                )
            )
        return bound_steps

    @staticmethod
    def validate_goal_completion_contract(
        goal_template: str,
        steps: list[ToolPlanStep],
    ) -> None:
        if goal_template not in {"quality_loop", "us.quality.complete"}:
            return
        if not steps or steps[-1].tool_id != "release.assess":
            raise AgentPlanPolicyViolation(
                "incomplete_goal_plan",
                (
                    f"{goal_template} must finish with release.assess so the Agent "
                    "cannot report completion before release readiness is evaluated."
                ),
                missing_context=("complete_quality_plan",),
            )

    @staticmethod
    def _validated_target_scope(
        step: ToolPlanStep,
        contract: AgentToolContract,
    ) -> Literal["central", "edge"]:
        if contract.scope == "central" and step.target_scope != "central":
            raise AgentPlanPolicyViolation(
                "invalid_target_scope",
                f"{step.tool_id} is a central-only tool and cannot target {step.target_scope}.",
            )
        if contract.scope == "edge" and step.target_scope != "edge":
            raise AgentPlanPolicyViolation(
                "invalid_target_scope",
                f"{step.tool_id} is an edge-only tool and cannot target {step.target_scope}.",
            )
        return step.target_scope

    def _sanitize_payload(self, raw_payload: dict) -> dict:
        if not isinstance(raw_payload, dict):
            raise AgentPlanPolicyViolation("invalid_input", "Tool input must be a JSON object.")
        return {
            str(key): value
            for key, value in raw_payload.items()
            if str(key) not in self._reserved_runtime_keys
        }

    def _bind_scope(self, payload: dict, scope: AgentPlanScope) -> None:
        scope_values = {
            "conversation_id": scope.conversation_id,
            "project_id": scope.project_id,
            "version_id": scope.version_id,
            "us_id": scope.us_id,
            "task_id": scope.task_id,
        }
        for key in self._scope_keys:
            authoritative_value = scope_values[key]
            proposed_value = payload.get(key)
            if authoritative_value and proposed_value and proposed_value != authoritative_value:
                raise AgentPlanPolicyViolation(
                    "scope_conflict",
                    (
                        f"The planner attempted to use {key}={proposed_value}, but the active "
                        f"conversation is bound to {authoritative_value}."
                    ),
                )
            if authoritative_value:
                payload[key] = authoritative_value

    def _validate_required_context(self, payload: dict, contract: AgentToolContract) -> None:
        missing: list[str] = []
        for required_key in contract.required_context:
            aliases = self._required_context_aliases.get(required_key, (required_key,))
            if not any(self._has_value(payload.get(alias)) for alias in aliases):
                missing.append(required_key)
        if missing:
            missing_context = tuple(dict.fromkeys(missing))
            raise AgentPlanPolicyViolation(
                "missing_context",
                (
                    f"{contract.tool_id} is missing required context: "
                    f"{', '.join(missing_context)}."
                ),
                missing_context=missing_context,
            )

    def _validate_payload_size(self, payload: dict, tool_id: str) -> None:
        try:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise AgentPlanPolicyViolation(
                "invalid_input",
                f"{tool_id} input is not JSON serializable.",
            ) from exc
        if len(encoded) > self.max_input_bytes:
            raise AgentPlanPolicyViolation(
                "input_too_large",
                f"{tool_id} input exceeds the {self.max_input_bytes}-byte planner limit.",
            )

    @staticmethod
    def _has_value(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, dict, tuple, set)):
            return bool(value)
        return True


__all__ = [
    "AgentPlanPolicy",
    "AgentPlanPolicyViolation",
    "AgentPlanScope",
    "AgentToolContract",
]
