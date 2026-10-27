"""A losing creator must not launch a second graph for the winning goal."""
import asyncio
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal, AgentGoalCreateRequest
from apps.api.app.application.agent.lifecycle import AgentGoalLifecycleApplicationService
from apps.api.app.domain.agent.goal_creation import ActiveAgentGoalExists
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.tests.test_saved_build_intent_entries import entries


@pytest.mark.parametrize("entry", ["manual", "proposal"])
@pytest.mark.parametrize("winner_scope", ["same", "different", "extra", "duplicate"])
def test_lost_creation_claim_reauthorizes_winner_without_starting_another_graph(entry, winner_scope):
    compiler, plans, proposal, reads = entries()
    winner = AgentGoal(id="winner", conversation_id="conversation", project_id="project",
        title="Original", summary="Fixed", status="pending", steps=[], target_refs=list(proposal.target_refs))
    if winner_scope == "different": winner.target_refs[1] = "build_plan:other"
    if winner_scope == "extra": winner.target_refs.append("image_revision:other")
    if winner_scope == "duplicate": winner.target_refs.append("project:project")
    effects, starts = [], []

    async def message(*args, **kwargs):
        effects.append(("message", kwargs))

    async def start(*args):
        starts.append(args)
        raise ActiveAgentGoalExists(winner.id)

    state = SimpleNamespace(list_goals_for_conversation=lambda _: [], get_goal=lambda ident: winner,
        record_goal_audit=lambda *args, **kwargs: effects.append(("audit", kwargs)),
        append_assistant_message=message)
    lifecycle = AgentGoalLifecycleApplicationService(state, SimpleNamespace(start_goal=start), build_intents=compiler)
    payload = AgentGoalCreateRequest(conversation_id="conversation", project_id="project", title="Saved", summary="Fixed",
        goal_template=proposal.goal_template, target_refs=proposal.target_refs)
    call = lifecycle.create_manual_goal(payload) if entry == "manual" else lifecycle.start_from_proposal("conversation", proposal)
    if winner_scope == "same":
        assert asyncio.run(call) is winner
        assert len([effect for effect in effects if effect[0] == "audit"]) == 1
    else:
        with pytest.raises(AgentPlanPolicyViolation, match="Another active goal"):
            asyncio.run(call)
        assert effects == []
    assert len(starts) == 1
    assert reads == [("project", "plan")]


@pytest.mark.parametrize("change", ["revoked", "target"])
def test_lost_creation_claim_does_not_bypass_current_source_or_target_checks(change):
    compiler, plans, proposal, _ = entries()
    winner = AgentGoal(id="winner", conversation_id="conversation", project_id="project",
        title="Original", summary="Fixed", status="pending", steps=[], target_refs=list(proposal.target_refs))

    async def start(*args):
        if change == "revoked": plans.allowed = False
        else: plans.current = False
        raise ActiveAgentGoalExists(winner.id)

    state = SimpleNamespace(list_goals_for_conversation=lambda _: [], get_goal=lambda _: winner,
        record_goal_audit=lambda *args, **kwargs: pytest.fail("Rejected claim must have no reuse effects"))
    lifecycle = AgentGoalLifecycleApplicationService(state, SimpleNamespace(start_goal=start), build_intents=compiler)
    with pytest.raises(AgentPlanPolicyViolation):
        asyncio.run(lifecycle.start_from_proposal("conversation", proposal))


def test_existing_ambiguous_controllers_cannot_bypass_the_creation_guard():
    compiler, _, proposal, _ = entries()
    first = AgentGoal(id="first", conversation_id="conversation", project_id="project", status="paused",
        title="First", summary="Fixed", steps=[], target_refs=list(proposal.target_refs))
    second = first.model_copy(update={"id": "second"})
    state = SimpleNamespace(list_goals_for_conversation=lambda _: [first, second],
        record_goal_audit=lambda *args, **kwargs: pytest.fail("Do not choose an ambiguous controller"))
    lifecycle = AgentGoalLifecycleApplicationService(state, SimpleNamespace(), build_intents=compiler)
    with pytest.raises(AgentPlanPolicyViolation) as conflict:
        asyncio.run(lifecycle.start_from_proposal("conversation", proposal))
    assert conflict.value.code == "active_agent_goal_ambiguous"
