from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.system_image.build_authorizations import BuildAuthorizationInput
from apps.api.app.domain.system_image.build_authorization import ApprovedBuildBudget, BuildExecutionAuthorization, authorization_from_dict
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.tests.test_build_plan import plan


def envelope():
    return BuildExecutionAuthorization("authorization", "project", "goal", "conversation", "plan", plan().digest,
        "manifest", plan().intent.source_manifest_hash, "baseline", "version", "invocation", "user",
        datetime.now(timezone.utc).isoformat(), ApprovedBuildBudget(1, 0, 1200, 0))


def test_authorization_roundtrip_is_immutable_and_has_no_publication_or_model_authority():
    value = envelope()
    assert authorization_from_dict(asdict(value)) == value
    assert authorization_from_dict(asdict(value)).digest == value.digest
    assert value.publication_allowed is False and value.work_item_ids == ("structure",)
    value.budget.validate_plan(plan())
    assert replace(value, target_version_id="new-version").digest != value.digest


@pytest.mark.parametrize("changes", [{"max_tool_calls": 0}, {"max_tool_calls": True},
    {"max_active_seconds": 86401}, {"max_cost_microusd": -1}, {"max_model_calls": "0"}])
def test_authorized_budget_is_strict(changes):
    budget = {**asdict(envelope().budget), **changes}
    with pytest.raises(BuildPlanIntegrityError):
        ApprovedBuildBudget(**budget)
    with pytest.raises(ValidationError):
        BuildAuthorizationInput(project_id="p", plan_id="plan", plan_digest="hash", target_baseline_id="b", budget=budget)


@pytest.mark.parametrize("changes", [{"max_tool_calls": 81}, {"max_active_seconds": 1201},
    {"max_model_calls": 1}, {"max_cost_microusd": 1}])
def test_authorization_cannot_enlarge_proposal_or_enable_unbound_semantic_capability(changes):
    with pytest.raises(BuildPlanIntegrityError):
        replace(envelope().budget, **changes).validate_plan(plan())


def test_expired_or_future_confirmation_cannot_reserve_work():
    grant = envelope()
    now = datetime.fromisoformat(grant.confirmed_at)
    grant.require_time_available(now + timedelta(seconds=1200))
    for instant in (now - timedelta(seconds=1), now + timedelta(seconds=1201)):
        with pytest.raises(TimeoutError):
            grant.require_time_available(instant)


@pytest.mark.parametrize("changes", [{"publication_allowed": True}, {"work_item_ids": ("semantics",)},
    {"confirmed_at": "2026-09-17T00:00:00"}, {"policy_version": "unknown"}])
def test_execution_consent_cannot_claim_other_authority(changes):
    with pytest.raises(BuildPlanIntegrityError):
        replace(envelope(), **changes)


def test_budget_exhausted_during_extraction_requests_goal_review():
    from apps.api.app.application.platform.tool_handlers.structure_builds import StructureBuildToolHandler
    from apps.api.app.application.platform.tool_models import ToolInvocation
    results = []

    def expired(*args, **kwargs):
        raise TimeoutError("Approved time exhausted during extraction")

    async def emit(*args):
        results.append(args[-1])

    handler = StructureBuildToolHandler(SimpleNamespace(execute=expired), SimpleNamespace(emit_tool_status=emit),
        SimpleNamespace(require_invocation_project_scope=lambda invocation: None))
    asyncio.run(handler.handle(ToolInvocation(id="work", tool_id="system_image.build.structure", status="running",
        summary="Build", input_payload={"project_id": "p", "plan_id": "plan", "plan_digest": "digest", "target_baseline_id": "b"})))
    assert results[0].status == "failed" and results[0].requires_followup
    assert results[0].followup_reason == "build_execution_authorization_review"
