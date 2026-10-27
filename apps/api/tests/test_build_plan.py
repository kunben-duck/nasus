from dataclasses import asdict, replace
import json

import pytest
from pydantic import ValidationError

from apps.api.app.application.system_image.build_plans import BuildPlanInput
from apps.api.app.domain.system_image.build_plan import (
    BuildBudgetProposal, BuildPlanIntegrityError, decode_build_plan, propose_build_plan,
    BuildTarget, TargetedBuildIntent, TARGETED_PLAN_POLICY,
)
from apps.api.app.domain.system_image.source_snapshots import CapturedSourceManifest, SourceManifestMember, snapshot_digest


def manifest(*members):
    members = tuple(sorted(members or (SourceManifestMember("code", "code", "revision", "captured"),), key=lambda m: m.binding_id))
    return CapturedSourceManifest("manifest", "project", snapshot_digest([asdict(m) for m in members]), "now", members)


def plan(inputs=None, **kwargs):
    return propose_build_plan(inputs or manifest(), objective="Understand the fixed repository", mode="initialize",
                              purpose="structure", budget=BuildBudgetProposal(), **kwargs)


def test_plan_is_deterministic_source_pinned_and_not_an_execution_grant():
    first = plan()
    assert plan() == first
    assert decode_build_plan(json.loads(json.dumps(asdict(first)))) == first
    assert first.digest == decode_build_plan(asdict(first)).digest
    assert first.intent.sources == manifest().members
    assert not first.execution_ready and first.authorization_state == "not_granted"
    assert first.work_items[-1].dependency_ids == ("structure",)
    gaps = {gap.code: gap.blocks for gap in first.gaps}
    assert "captured_code_required" not in gaps
    assert gaps["us_doc_unavailable"] == "business_acceptance"
    assert gaps["test_asset_unavailable"] == "test_reuse"
    assert all(work.binding_state != "ready" for work in first.work_items)
    assert first.work_items[0].proposed_tool_id == "system_image.build.structure"
    assert first.work_items[0].binding_state == "requires_confirmation"


def test_legacy_plan_digest_and_unbound_work_remain_readable():
    current = plan()
    legacy = replace(current, policy_version="nasus.image-investigation-plan.v1", work_items=(
        replace(current.work_items[0], proposed_tool_id="system_image.context.materialize", binding_state="requires_pinned_executor"),
        *current.work_items[1:]))
    assert decode_build_plan(asdict(legacy)).digest == legacy.digest
    assert legacy.digest != current.digest


def test_optional_failed_input_does_not_block_structure_but_required_code_does():
    code = SourceManifestMember("code", "code", "r", "captured")
    doc = SourceManifestMember("doc", "us_doc", None, "failed")
    assert not any(g.blocks == "structure" for g in plan(manifest(code, doc)).gaps)
    for inputs in (manifest(doc), manifest(replace(code, source_revision_id=None, status="pending"))):
        assert any(g.code == "captured_code_required" for g in plan(inputs).gaps)


def test_semantics_proposal_requires_capabilities_and_does_not_invent_oracles():
    result = propose_build_plan(manifest(), objective="Compare requirements and tests", mode="enrich", purpose="traceability",
                                budget=BuildBudgetProposal())
    assert result.work_items[-1].dependency_ids == ("structure", "semantics")
    assert result.work_items[1].proposed_tool_id is None
    assert {g.code for g in result.gaps} >= {"semantic_investigation_required", "cost_ceiling_required"}


@pytest.mark.parametrize("field,value", [("max_tool_calls", 0), ("max_model_calls", True), ("max_active_seconds", 86401),
    ("max_cost_microusd", -1), ("max_cost_microusd", 1.5), ("max_tool_calls", "80")])
def test_budget_bounds_are_strict(field, value):
    with pytest.raises(ValueError):
        BuildBudgetProposal(**{field: value})
    with pytest.raises(ValidationError):
        BuildPlanInput(project_id="p", source_manifest_id="m", objective="x", budget={field: value})


@pytest.mark.parametrize("change", [{"execution_ready": True}, {"state": "completed"}, {"authorization_state": "approved"}])
def test_draft_cannot_claim_execution_or_publication(change):
    with pytest.raises(ValueError):
        replace(plan(), **change)


@pytest.mark.parametrize("change", [{"dependency_ids": ("review",)}, {"source_binding_ids": ("outside",)},
    {"proposed_tool_id": "run.start"}, {"max_attempts": True}, {"max_model_calls": 31},
    {"question": 42}, {"acceptance_conditions": (False,)}, {"output_artifact": ""}, {"source_binding_ids": ("code", "code")}])
def test_invalid_dag_tools_and_source_scope_are_rejected(change):
    first = plan()
    with pytest.raises(ValueError):
        replace(first, work_items=(replace(first.work_items[0], **change), *first.work_items[1:]))


def test_plan_cannot_exceed_budget_or_accept_corrupt_manifest():
    with pytest.raises(ValueError, match="budget"):
        replace(plan(), intent=replace(plan().intent, budget=BuildBudgetProposal(max_tool_calls=1)))
    with pytest.raises(BuildPlanIntegrityError):
        plan(replace(manifest(), content_hash="wrong"))
    with pytest.raises(BuildPlanIntegrityError):
        plan(manifest(SourceManifestMember("code", "code", "wrong", "failed")))
    payload = asdict(plan())
    payload["unknown"] = "not canonical"
    with pytest.raises(BuildPlanIntegrityError):
        decode_build_plan(payload)


def test_targeted_intent_preserves_source_scope_and_legacy_serialization():
    target = BuildTarget("project", "baseline", None, None, None)
    fixed = plan(target=target)
    assert fixed.policy_version == TARGETED_PLAN_POLICY
    assert isinstance(fixed.intent, TargetedBuildIntent)
    assert fixed.intent.expected_head_status == "resolved"
    assert fixed.intent.scope_binding_ids == ("code",)
    assert decode_build_plan(json.loads(json.dumps(asdict(fixed)))) == fixed
    assert "target" not in asdict(plan())["intent"]
    assert "scope_binding_ids" not in asdict(plan())["intent"]
    assert fixed.digest != plan().digest
    assert not fixed.execution_ready and fixed.authorization_state == "not_granted"
    assert "publication_approval_required" in {gap.code for gap in fixed.gaps}
    from apps.api.app.domain.system_image.build_plan_revisions import enriched_proposal
    enriched = enriched_proposal(fixed, replace(manifest(*fixed.intent.sources,
        SourceManifestMember("doc", "us_doc", "d1", "captured")), manifest_id="enriched"))
    assert enriched.intent.target == target and enriched.intent.scope_binding_ids == ("code", "doc")


@pytest.mark.parametrize("change", [{"target": None}, {"scope_binding_ids": ("other",)},
    {"expected_head_status": "unresolved"}, {"expected_head": "another"},
    {"target": BuildTarget("other", "baseline", None, None, None)}])
def test_targeted_intent_rejects_unresolved_or_rebound_scope(change):
    with pytest.raises(BuildPlanIntegrityError):
        replace(plan(target=BuildTarget("project", "baseline", None, None, None)).intent, **change)


@pytest.mark.parametrize("values", [dict(expected_head_id="head", expected_head_hash=None),
    dict(expected_head_id=None, expected_head_hash="sha256:" + "a" * 64),
    dict(expected_head_id="head", expected_head_hash="unverified"), dict(target_version_id=""),
    dict(target_baseline_id=""), dict(project_id="project\nsecret"), dict(target_baseline_id="baseline\x00"),
    dict(target_version_id="version\rsecret"), dict(expected_head_id="head\tsecret", expected_head_hash="sha256:" + "a" * 64)])
def test_target_fields_require_explicit_canonical_pins(values):
    with pytest.raises(BuildPlanIntegrityError):
        BuildTarget(**{**dict(project_id="project", target_baseline_id="baseline", target_version_id=None,
            expected_head_id=None, expected_head_hash=None), **values})
