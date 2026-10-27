"""Canonical generation writes reviewable inventory, not approved coverage."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from apps.api.app.application.quality_loop.quality_models import USItem
from apps.api.app.infrastructure.persistence.quality_loop_repository import QualityLoopRepository
from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_refresh_api import read


STAGES = (
    ("quality.scope.generate", "scope", "scope_pack", "scenarios", "scope_items"),
    ("quality.scenario.generate", "scenarios", "scenario_set", "scenarios", "scenario_groups"),
    ("quality.plan.generate", "verification_plan", "verification_plan", "verification", "verification_priorities"),
    ("quality.case.generate", "cases", "case_set", "cases", "test_cases"),
    ("automation.generate", "automation", "automation_blueprint", "automation", "automation_scripts"),
    ("quality.change-doc.generate", "change_document", "change_document", "change_document", "change_deltas"),
)


def prepare_us(v):
    us = USItem(id="generation_observation_" + uuid4().hex, title="Explicit inventory protocol fixture",
        owner="QA", status="analysis", risk="low", progress=0, next_action="Inspect drafts")
    QualityLoopRepository().replace_us_items(v["project_id"], None, [us])
    v["invoke"]("system_image.context.materialize")
    return us


def assert_generation_inventory(v, us, stage):
    tool, step, part_type, lane_key, count_key = stage
    before = deepcopy(read(v))
    v["invoke"](tool, {"us_id": us.id})
    workspace = v["client"].get(f"/v1/projects/{v['project_id']}", headers=v["headers"])
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()
    part = next(part for part in body["quality_asset_pack"]["parts"] if part["part_type"] == part_type)
    assert part["status"] == "ready_for_review"
    assert next(lane for lane in body["asset_lanes"] if lane["id"].endswith("_lane_" + lane_key))["status"] == "ready_for_review"
    payload = part["structured_content"]
    after = read(v)
    metrics = next(item["metrics"] for item in after["metric_snapshots"]
        if item["us_id"] == us.id and item["metrics"].get("quality_loop_step") == step)
    collection = {"scenarios": "scenarios", "verification_plan": "priorities", "cases": "cases",
        "automation": "scripts", "change_document": "deltas"}.get(step)
    expected_count = len(payload[collection]) if collection else sum(len(payload[key]) for key in
        ("in_scope", "out_of_scope", "regression_targets", "risk_targets"))
    assert metrics[count_key] == expected_count > 0
    assert metrics["coverage_status"] == "unknown"
    assert metrics["measurement_basis"] == "generated_draft_inventory_not_quality_assessment"
    assert not {"scenario_coverage", "assertion_coverage", "automation_coverage", "regression_focus"}.intersection(metrics)
    assert after["sources"] == before["sources"] and after["source_manifest"] == before["source_manifest"]
    assert after["objects"] == before["objects"] and after["relationships"] == before["relationships"]
    profiles = SystemImageRepository().list_quality_profiles(v["project_id"])
    assert all(getattr(profile, field) is None for profile in profiles for field in
        ("risk_score", "coverage_score", "automation_feasibility", "release_score", "confidence"))
    assert not any(part["status"] == "approved" for part in body["quality_asset_pack"]["parts"])
    return {"stage": step, "observed_count": expected_count, "generation_mode": part["generation"]["mode"],
        "asset_status": part["status"], "coverage_status": metrics["coverage_status"]}


@pytest.mark.parametrize("stage", STAGES, ids=lambda stage: stage[1])
def test_canonical_generation_persists_actual_counts_without_approving_drafts(evidence_api, stage):
    v = evidence_api
    assert_generation_inventory(v, prepare_us(v), stage)


def test_exweb_generation_inventory_stays_unknown_after_all_legacy_steps(evidence_api, tmp_path):
    root = os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT")
    if not root:
        pytest.skip("explicit reviewed exweb Git export required")
    from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
    files, tree_hash, _ = read_git_tree(Path(root), AFTER)
    assert len(files) == 126
    exported = tmp_path / "fixed-exweb-generation-inventory"
    exported.mkdir()
    for name, content in files:
        path = exported / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    v = evidence_api
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(exported)}]})
    v["invoke"]("system_image.sources.ingest")
    us = prepare_us(v)
    observed = [assert_generation_inventory(v, us, stage) for stage in STAGES]
    assert all(item["generation_mode"] != "live" for item in observed), "This is a protocol fixture, not external model validation"
    v["invoke"]("release.assess", {"us_id": us.id})
    readiness = v["client"].get(f"/v1/projects/{v['project_id']}/release-readiness", headers=v["headers"]).json()
    assert readiness["evidence_summary"]["quality_assessment_unknown"] == 1 and readiness["blockers"] > 0
    assert any("quality assessment is unknown" in blocker for blocker in readiness["blocker_items"])
    workspace = v["client"].get(f"/v1/projects/{v['project_id']}", headers=v["headers"]).json()
    assert workspace["quality_asset_pack"]["status"] == "blocked"
    assert not any(part["status"] == "approved" for part in workspace["quality_asset_pack"]["parts"])
    conversation = v["client"].get(f"/v1/conversations/{v['conversation'].json()['id']}", headers=v["headers"])
    assert conversation.status_code == 200, conversation.text
    assert any(message["role"] == "assistant" and any("Release remains blocked." in block["text"]
        for block in message["blocks"]) for message in conversation.json()["messages"])
    report = os.getenv("EXWEB_GENERATION_INVENTORY_REPORT")
    if report:
        with Path(report).open("x") as output:
            json.dump({"schema": "nasus.exweb-generation-observation-truth.v1",
                "verified_at": datetime.now(timezone.utc).isoformat(), "repository": "https://github.com/kunben-duck/exweb.git",
                "commit": AFTER, "tree_hash": tree_hash, "exweb_file_count": 126,
                "additional_source": "isolated Orders code fixture", "us_basis": "explicit_protocol_fixture_not_maintainer_approval",
                "observations": observed, "automatically_approved_asset_count": 0,
                "invented_quality_coverage_absent": True, "quality_assessment_unknown": True,
                "release_blocked": True, "postgres_private_minio": True,
                "external_model_verified": False, "native_provider_verified": False,
                "target_execution_verified": False, "full_quality_closure_verified": False}, output, indent=2)
