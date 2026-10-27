from dataclasses import asdict

import pytest

from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.build_tool_budget import BuildToolBudget, BuildToolBudgetExhausted, consumption_payload
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_tool_invocation_runtime_ports import build_runtime, tool_definition
from apps.api.app.application.platform.tool_models import ToolInvocationRequest


def budget(limit=2):
    return BuildToolBudget("goal", "project", "conversation", "workflow", limit,
        snapshot_digest({"original": "intent"}), "source_intent")


@pytest.mark.parametrize("limit", [0, -1, 1001, True, "80"])
def test_invalid_tool_guardrails_are_rejected(limit):
    with pytest.raises(BuildPlanIntegrityError):
        budget(limit)


def test_cumulative_ceiling_is_not_a_capability_grant():
    original = budget()
    original.require_available(0)
    original.require_available(1)
    with pytest.raises(BuildToolBudgetExhausted):
        original.require_available(2)
    with pytest.raises(BuildPlanIntegrityError):
        original.require_available(3)
    assert "model_calls" not in asdict(original) and "publication_allowed" not in asdict(original)


def test_each_consumption_binds_the_prior_receipt_and_original_budget():
    original = budget()
    first = consumption_payload(original, invocation_id="tool1", tool_id="query.one", work_key="one",
        input_digest=snapshot_digest({"input": 1}), sequence=1, previous_hash=original.digest)
    second = consumption_payload(original, invocation_id="tool2", tool_id="query.two", work_key="two",
        input_digest=snapshot_digest({"input": 2}), sequence=2, previous_hash=snapshot_digest(first))
    assert first["budget_hash"] == second["budget_hash"] == original.digest
    assert second["previous_hash"] == snapshot_digest(first)
    with pytest.raises(BuildToolBudgetExhausted):
        consumption_payload(original, invocation_id="tool3", tool_id="query.three", work_key="three",
            input_digest=snapshot_digest({}), sequence=3, previous_hash=snapshot_digest(second))


@pytest.mark.parametrize("failure", [BuildToolBudgetExhausted, BuildPlanIntegrityError])
def test_canonical_runtime_denies_before_handler_dispatch(failure):
    import asyncio
    runtime, _, audit, _, _, handled = build_runtime(tool=tool_definition())

    class Budgets:
        def reserve_tool_work(self, invocation):
            raise failure("Do not expose a private provider secret")

    runtime._work_budgets = Budgets()
    result = asyncio.run(runtime.create(ToolInvocationRequest(tool_id="quality.test.execute")))
    assert result.status == "failed" and not handled
    assert result.result.followup_reason == "build_tool_budget_review"
    assert "secret" not in result.summary
    assert audit.events[-1].action == "tool.invocation.budget_denied"


def test_confirmation_and_replay_do_not_consume_tool_work_twice():
    import asyncio
    runtime, _, _, _, _, handled = build_runtime(tool=tool_definition(confirmation_mode="user_confirm"))
    reserved = []

    class Budgets:
        def reserve_tool_work(self, invocation):
            reserved.append(invocation.id)
            return True

    runtime._work_budgets = Budgets()
    request = ToolInvocationRequest(tool_id="quality.test.execute", idempotency_key="original-command")
    pending = asyncio.run(runtime.create(request))
    assert pending.status == "waiting_confirmation" and not reserved
    complete = asyncio.run(runtime.confirm(pending.id))
    assert asyncio.run(runtime.create(request)).id == complete.id
    assert asyncio.run(runtime.confirm(complete.id)).id == complete.id
    assert reserved == handled == [complete.id]
