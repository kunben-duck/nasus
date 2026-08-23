from __future__ import annotations

import pytest

from apps.api.app.domain.agent.plan_policy import (
    AgentPlanPolicy,
    AgentPlanPolicyViolation,
    AgentPlanScope,
    AgentToolContract,
)
from apps.api.app.domain.agent.runtime_models import ToolPlanStep


def contract(
    tool_id: str,
    *,
    scope: str = "central",
    required_context: tuple[str, ...] = (),
) -> AgentToolContract:
    return AgentToolContract(
        tool_id=tool_id,
        scope=scope,  # type: ignore[arg-type]
        required_context=required_context,
    )


def test_plan_policy_binds_authoritative_scope_and_strips_runtime_fields():
    policy = AgentPlanPolicy()
    steps = policy.bind_and_validate(
        [
            ToolPlanStep(
                tool_id="quality.case.generate",
                input_payload={
                    "agent_goal_id": "goal_forged",
                    "confirmed_by_user": True,
                },
                reason="Generate cases.",
            )
        ],
        contracts=[
            contract(
                "quality.case.generate",
                required_context=("project_id", "us_id"),
            )
        ],
        scope=AgentPlanScope(
            conversation_id="conv_1",
            project_id="proj_1",
            us_id="us_1",
        ),
    )

    assert steps[0].input_payload == {
        "conversation_id": "conv_1",
        "project_id": "proj_1",
        "us_id": "us_1",
    }


def test_plan_policy_rejects_cross_scope_resource_ids():
    policy = AgentPlanPolicy()

    with pytest.raises(AgentPlanPolicyViolation) as error:
        policy.bind_and_validate(
            [
                ToolPlanStep(
                    tool_id="release.assess",
                    input_payload={"project_id": "proj_other", "us_id": "us_1"},
                )
            ],
            contracts=[
                contract(
                    "release.assess",
                    required_context=("project_id", "us_id"),
                )
            ],
            scope=AgentPlanScope(
                conversation_id="conv_1",
                project_id="proj_1",
                us_id="us_1",
            ),
        )

    assert error.value.code == "scope_conflict"


def test_plan_policy_requires_tool_context_and_supports_name_aliases():
    policy = AgentPlanPolicy()
    create_steps = policy.bind_and_validate(
        [ToolPlanStep(tool_id="project.create", input_payload={"name": "Checkout"})],
        contracts=[contract("project.create", required_context=("project_name",))],
        scope=AgentPlanScope(conversation_id="conv_1"),
    )
    assert create_steps[0].input_payload["name"] == "Checkout"

    with pytest.raises(AgentPlanPolicyViolation) as error:
        policy.bind_and_validate(
            [ToolPlanStep(tool_id="run.start", input_payload={})],
            contracts=[contract("run.start", required_context=("project_id", "us_id"))],
            scope=AgentPlanScope(conversation_id="conv_1"),
        )
    assert error.value.code == "missing_context"
    assert error.value.missing_context == ("project_id", "us_id")


def test_plan_policy_rejects_duplicate_actions_and_excessive_plans():
    policy = AgentPlanPolicy(max_tool_steps=2)
    tool_contract = contract("query.dashboard.progress")

    with pytest.raises(AgentPlanPolicyViolation) as duplicate_error:
        policy.bind_and_validate(
            [
                ToolPlanStep(tool_id=tool_contract.tool_id, input_payload={}),
                ToolPlanStep(tool_id=tool_contract.tool_id, input_payload={}),
            ],
            contracts=[tool_contract],
            scope=AgentPlanScope(conversation_id="conv_1"),
        )
    assert duplicate_error.value.code == "duplicate_action"

    with pytest.raises(AgentPlanPolicyViolation) as budget_error:
        policy.bind_and_validate(
            [
                ToolPlanStep(tool_id=tool_contract.tool_id, input_payload={"page": index})
                for index in range(3)
            ],
            contracts=[tool_contract],
            scope=AgentPlanScope(conversation_id="conv_1"),
        )
    assert budget_error.value.code == "step_budget_exceeded"


def test_plan_policy_enforces_tool_target_scope():
    policy = AgentPlanPolicy()

    with pytest.raises(AgentPlanPolicyViolation) as error:
        policy.bind_and_validate(
            [
                ToolPlanStep(
                    tool_id="run.start",
                    input_payload={"project_id": "proj_1", "us_id": "us_1"},
                    target_scope="edge",
                )
            ],
            contracts=[
                contract(
                    "run.start",
                    required_context=("project_id", "us_id"),
                )
            ],
            scope=AgentPlanScope(
                conversation_id="conv_1",
                project_id="proj_1",
                us_id="us_1",
            ),
        )

    assert error.value.code == "invalid_target_scope"


def test_plan_policy_prevents_false_completion_of_full_quality_goal():
    policy = AgentPlanPolicy()
    with pytest.raises(AgentPlanPolicyViolation) as error:
        policy.validate_goal_completion_contract(
            "us.quality.complete",
            [
                ToolPlanStep(
                    tool_id="automation.generate",
                    input_payload={"project_id": "proj_1", "us_id": "us_1"},
                )
            ],
        )
    assert error.value.code == "incomplete_goal_plan"

    policy.validate_goal_completion_contract(
        "us.quality.complete",
        [
            ToolPlanStep(
                tool_id="run.start",
                input_payload={
                    "project_id": "proj_1",
                    "us_id": "us_1",
                    "base_url": "https://example.test",
                },
            ),
            ToolPlanStep(
                tool_id="release.assess",
                input_payload={"project_id": "proj_1", "us_id": "us_1"},
            ),
        ],
    )
