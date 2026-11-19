"""Live M3 replay. No specimen cases, native replies or execution receipts."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.model_settings import StudioSettings
from apps.api.app.application.system_image.context_pack_inputs import ContextPreviewInput
from apps.api.app.application.quality_loop.test_design_scope_inputs import TestDesignContract
from apps.api.app.application.quality_loop.generation_execution_inputs import GenerationExecutionSelection
from apps.api.app.domain.quality_loop.case_approval import CASE_APPROVAL_TOOL
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_requirement_realworld_live import test_realworld_live_review_clarification_independent_confirmation as review_m2
from apps.api.tests.test_requirement_reviews_api import command
from apps.api.tests.test_reference_links_api import candidate


def checked(v, tool, payload, *, reviewer=False):
    result = command(v, tool, payload, headers=v["member_headers"] if reviewer else v["headers"])
    assert result["status"] == "completed", result.get("summary")
    return result


def adopt_defect(v):
    before = v["client"].get(f"/v1/projects/{v['project_id']}/versions/{v['version']}/delivery", headers=v["headers"]).json()
    revisions = json.loads(os.environ["M3_REVISIONS"])
    assert before["code_revisions"][0]["commit_sha"] == revisions["original"]
    subprocess.run(["git", "-C", os.environ["M1_REALWORLD_REPOSITORY"], "update-ref", "refs/heads/nasus-m3-acceptance",
        revisions["defect"], revisions["original"]], check=True)
    for tool in ("system_image.sources.ingest", "system_image.context.materialize"):
        checked(v, tool, {"project_id": v["project_id"]})
    image = candidate(v)
    option = v["client"].get(f"/v1/projects/{v['project_id']}/versions/{v['version']}/delivery/image-options/{image['image_revision_id']}", headers=v["headers"])
    assert option.status_code == 200, option.text
    assert set(option.json()["request"]["code_commits"].values()) == {revisions["defect"]}
    done = checked(v, "quality.iteration_image.adopt", {**option.json()["request"],
        "reason": "Explicitly adopt the independently labelled injected ownership-check defect for M3 acceptance"})
    after = v["client"].get(f"/v1/projects/{v['project_id']}/versions/{v['version']}/delivery", headers=v["headers"]).json()
    assert before["baseline"] == after["baseline"] and after["iteration_image"]["adoption_id"]
    v["adoption_evidence"] = {"before": before, "after": after, "invocation_id": done["id"]}


def install_live_profile(v, monkeypatch):
    settings = StudioSettings.model_validate_json(os.environ["M2_LIVE_SETTINGS"])
    custom = settings.custom_model
    payload = {"model_route": "chat", "display_name": "M3 isolated live acceptance", "custom_provider_kind": custom.provider_kind,
        "custom_base_url": custom.base_url, "custom_model_name": custom.model_name, "custom_api_key": os.environ["M2_LIVE_KEY"]}
    response = v["client"].post("/v1/settings/model-configs/test", headers=v["headers"], json=payload)
    assert response.status_code == 200 and response.json()["ok"], "Actual live model connection test failed"
    saved = v["client"].post("/v1/settings/model-configs", headers=v["headers"], json={**payload, "test_token": response.json()["test_token"]})
    assert saved.status_code == 200, "Tested live model could not be saved"
    config = next(item for item in saved.json()["model_configurations"]["chat"]["configurations"] if item["display_name"] == payload["display_name"])
    tokenizer = Path(os.environ["M3_TOKENIZER"])
    policy = {"policy_id": "realworld-m3-deepseek-flash", "revision": "2026-11-16-peak-ceiling", "config_id": config["config_id"],
        "provider": custom.provider_kind, "model_name": custom.model_name, "base_url": custom.base_url.rstrip("/"),
        "currency": "USD", "context_tokens": 131072, "max_output_tokens": 32768,
        "input_nanos_per_token": 300, "output_nanos_per_token": 1200, "framing_tokens": 512,
        "tokenizer_kind": "huggingface_json", "tokenizer_id": "deepseek-ai/DeepSeek-V4.1-Flash-1017",
        "tokenizer_digest": "sha256:" + hashlib.sha256(tokenizer.read_bytes()).hexdigest()}
    path = tokenizer.with_name("model-policy.json")
    path.write_text(json.dumps({"schema": "nasus.generation-model-policies.v1", "profiles": [{"policy": policy, "tokenizer_path": tokenizer.name}]}))
    monkeypatch.setenv("NASUS_GENERATION_MODEL_POLICIES", str(path))
    return config, policy


def scope_for_article_edit(context):
    constraints = context["required_constraints"]
    permissions, risks, invariants, transitions = [], [], [], []
    # Copy confirmed oracles exactly. Dimensions describe their intent, not
    # additional expectations inferred from the intentionally defective target.
    for index, item in enumerate(constraints):
        oracle = item["oracle"]
        text = json.dumps(oracle, ensure_ascii=False)
        base = {"constraint_ids": [item["object_id"]], "evidence_ids": [], "oracle": oracle}
        denied = bool(re.search(r"\b(?:401|403)\b", text))
        missing = bool(re.search(r"\b404\b", text))
        if denied:
            permissions.append({**base, "obligation_id": f"permission-{index}", "actor": "Unauthenticated user" if "401" in text else "Authenticated non-author",
                "operation": "Update article", "resource": "Article owned by another user", "expected": "denied"})
            risks.append({**base, "obligation_id": f"risk-{index}", "boundary": "Unauthorized article mutation must be rejected"})
            invariants.append({**base, "obligation_id": f"unchanged-{index}", "invariant": "Rejected update preserves article data and author"})
        elif not missing:
            permissions.append({**base, "obligation_id": f"permission-{index}", "actor": "Authenticated article author",
                "operation": "Update article", "resource": "Own article", "expected": "allowed"})
            transitions.append({**base, "obligation_id": f"update-{index}", "from_state": "Existing article with original fields",
                "event": "Author submits confirmed valid update", "to_state": "Updated fields can be read back"})
    if not risks or not permissions or not invariants or not transitions:
        raise AssertionError("Confirmed review is missing author/denial dimensions; do not silently narrow M3 scope")
    return TestDesignContract.model_validate({"authority_basis": "user_confirmed_test_design_scope",
        **{name: {"applicability": "applicable", "rationale": "Explicit operator scope copies the independently confirmed US-001 oracle without changing its expected behavior.", "items": items}
           for name, items in (("risks", risks), ("permissions", permissions), ("transitions", transitions), ("invariants", invariants))},
        "examples": [{"constraint_id": item["object_id"], "positive": item["oracle"], "negative": None,
            "negative_not_applicable_reason": "Denial and nonexistent-article paths are independent confirmed AC in this same complete scope; no additional unspecified negative partition.",
            "negative_gap_id": None} for item in constraints], "reused_case_ids": [],
        "reuse_assessment": "Pinned historical authorization examples remain evidence; no unreviewed executable historical case is promoted.",
        "conflicts": [], "conflict_assessment": "Use fixed specification plus explicitly confirmed US-001, not the injected implementation behavior.", "gaps": []}).model_dump(mode="json")


def edit_and_review_live_cases(v, draft, record):
    """Review actual model output without replacing its expectations or claiming execution."""
    root = f"/v1/projects/{v['project_id']}/quality"
    def get(path, *, reviewer=False, params=None):
        response = v["client"].get(root + path, headers=v["member_headers"] if reviewer else v["headers"], params=params)
        assert response.status_code == 200, response.text
        return response.json()
    original = draft["result"]
    case = deepcopy(original["proposal"]["cases"][0])
    case["preconditions"].append("Use distinct per-case test accounts and article data in the isolated acceptance target.")
    edited = checked(v, "quality.test_design.cases.revise", {
        "project_id": v["project_id"], "generation_id": draft["metadata"]["generation_id"],
        "generation_artifact_hash": draft["metadata"]["artifact_hash"], "cases": [case],
        "reason": "Clarify per-case data isolation; keep every model-generated assertion and confirmed oracle unchanged"})
    record("case_revision_saved", edit_invocation_id=edited["id"])
    ident = next(ref.split(":", 1)[1] for ref in edited["result"]["object_refs"] if ref.startswith("test_design_result:"))
    child = get("/test-design-results/" + ident)
    parent = get("/test-design-results/" + draft["metadata"]["generation_id"])
    assert parent["result"] == original and not parent["current_use"]["scope_current"]
    assert child["result"]["proposal"]["cases"][0] == case
    assert child["result"]["author_ids"] == [v["owner"]["id"]]
    mappings = [{"case_id": item["case_id"], "row_id": assertion["row_id"],
        "step_index": assertion["step_index"], "oracle_digest": assertion["oracle_digest"],
        "decision": "accept", "reason": "Exact confirmed AC oracle preserved; independent mapping review, not target execution"}
        for item in child["result"]["proposal"]["cases"] for assertion in item["assertions"]]
    mapping_command = checked(v, "quality.test_design_mapping.review", {
        "project_id": v["project_id"], "generation_id": ident, "generation_artifact_hash": child["metadata"]["artifact_hash"],
        "expected_previous_revision_id": None, "decision": "review", "mappings": mappings,
        "reason": "Independent complete mapping review for actual live-model cases after immutable editing"}, reviewer=True)
    record("case_mapping_reviewed", mapping_invocation_id=mapping_command["id"])
    mapping = get(f"/test-design-results/{ident}/mapping-review", reviewer=True,
        params={"artifact_hash": child["metadata"]["artifact_hash"]})["head"]
    assert mapping["current_use"]["mapping_complete"] and mapping["current_use"]["mapping_current"]
    selection = {"mapping_revision_id": mapping["revision"]["revision_id"],
        "mapping_artifact_hash": mapping["revision"]["artifact_hash"],
        "case_ids": sorted(item["case_id"] for item in child["result"]["proposal"]["cases"])}
    params = [(key, selection[key]) for key in ("mapping_revision_id", "mapping_artifact_hash")]
    params += [("case_ids", item) for item in selection["case_ids"]]
    author_preview = get("/test-design-case-approvals/preview", params=params)
    preview = get("/test-design-case-approvals/preview", reviewer=True, params=params)
    assert not author_preview["can_review"] and preview["can_review"]
    request = {"project_id": v["project_id"], **selection,
        "expected_input_digest": preview["basis"]["input_digest"], "expected_previous_revision_id": None,
        "decision": "approve", "reason": "Independent admission of all live-model cases; execution remains separately authorized"}
    refused = command(v, CASE_APPROVAL_TOOL, request)
    assert refused["status"] == "failed", "The generator/editor must not approve their own cases"
    approved = checked(v, CASE_APPROVAL_TOOL, request, reviewer=True)
    record("case_admission_saved", approval_invocation_id=approved["id"])
    approval_id = approved["result"]["object_refs"][0].split(":", 1)[1]
    approval = get("/test-design-case-approvals/" + approval_id, reviewer=True)
    assert approval["current_use"]["case_admission_current"] and not approval["current_use"]["execution_authorized"]
    assert approval["revision"]["authority_actor"] == v["member"]["id"]
    return {"edit_invocation_id": edited["id"], "revision": child, "mapping_invocation_id": mapping_command["id"],
        "mapping": mapping, "approval_invocation_id": approved["id"], "approval": approval}


@pytest.mark.skipif(not os.getenv("M3_ACCEPTANCE_REPORT"), reason="Requires explicit live M3 acceptance opt-in")
def test_realworld_m3_live_chain(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    report = Path(os.environ["M3_ACCEPTANCE_REPORT"])
    evidence = {"schema": "nasus.realworld-m3-acceptance.v1", "status": "running", "full_m3_verified": False,
        "revisions": json.loads(os.environ["M3_REVISIONS"]), "injected_defect": True}
    def save(stage, **values):
        evidence.update(stage=stage, **values)
        report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    save("m1_m2")
    review_m2(v, tmp_path, monkeypatch, source_ref="refs/heads/nasus-m3-acceptance", after_m1=adopt_defect)
    reviewed = json.loads(Path(os.environ["M2_ACCEPTANCE_REPORT"]).read_text())
    save("confirmed_defect_image", adoption=v["adoption_evidence"], requirement=reviewed["final_review"], iteration=reviewed["iteration"])
    request = reviewed["final_review"]["test_design_context_request"]
    assert request is not None
    with actor_scope(UserProfile.model_validate(v["owner"])):
        preview = app.state.container.context_packs.preview(ContextPreviewInput.model_validate(request))
    done = checked(v, "system_image.context.compile", {**preview["request"], "expected_input_digest": preview["input_digest"]})
    ident = next(ref.split(":", 1)[1] for ref in done["result"]["object_refs"] if ref.startswith("context_pack:"))
    response = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/context-packs/{ident}", headers=v["headers"])
    assert response.status_code == 200, response.text
    context = response.json()
    assert context["context"]["required_constraints"] and not context["current_use"]["stale"]
    scope_command = checked(v, "quality.test_design_scope.review", {"project_id": v["project_id"], "context_id": ident,
        "context_artifact_hash": context["metadata"]["artifact_hash"], "expected_previous_revision_id": None, "decision": "approve",
        "contract": scope_for_article_edit(context["context"]), "reason": "Independent US-001 complete confirmed-AC scope review", "policy_revision": "nasus.test-design-scope.v1"}, reviewer=True)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        scope = app.state.container.test_design_scopes.inspect(v["project_id"], ident)["head"]["revision"]
    save("scope_approved", context=context, scope=scope, scope_invocation_id=scope_command["id"])
    config, policy = install_live_profile(v, monkeypatch)
    selection = GenerationExecutionSelection(project_id=v["project_id"], scope_revision_id=scope["revision_id"],
        scope_artifact_hash=scope["artifact_hash"], model_config_id=config["config_id"], budget={"currency": "USD", "max_calls": 8,
            "max_reserved_tokens": 2000000, "max_reserved_cost_nanos": 1000000000,
            "max_input_tokens_per_call": 98304, "max_output_tokens_per_call": 32768})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        generation = app.state.container.test_design_executor.preview(selection)
    save("generation_preview", generation=generation, model_policy=policy)
    from temporalio.client import Client
    from temporalio.worker import Worker
    from apps.api.app.infrastructure.config.agent_runtime_config import temporal_gateway_config_from_env
    from apps.api.app.infrastructure.workflow.generation_runtime import TemporalGenerationRuntime, build_generation_activities
    from apps.api.app.infrastructure.workflow.nasus_generation_workflow import NasusTestDesignGenerationWorkflow
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    async def generate():
        cfg = replace(temporal_gateway_config_from_env(), address=os.environ["TEST_TEMPORAL_ADDRESS"], task_queue="nasus-m3-" + uuid4().hex)
        client = await Client.connect(cfg.address, namespace=cfg.namespace)
        runtime = TemporalGenerationRuntime(cfg)
        monkeypatch.setattr(app.state.container.test_design_jobs, "workflow", runtime)
        async with Worker(client, task_queue=runtime.task_queue, workflows=[NasusTestDesignGenerationWorkflow], activities=build_generation_activities()):
            accepted = await asyncio.to_thread(command, v, "quality.test_design.generate", generation["request"])
            assert accepted["status"] in {"running", "completed"}, accepted.get("summary")
            save("generation_running", generation_invocation_id=accepted["id"])
            handle = client.get_workflow_handle("nasus-test-design-generation:" + accepted["id"])
            status = await asyncio.wait_for(handle.result(), 900)
            final = await asyncio.to_thread(v["client"].get, "/v1/tool-invocations/" + accepted["id"], headers=v["headers"])
            save("generation_finished", generation_command=final.json(), generation_workflow_status=status)
            assert status == "completed", final.json().get("summary")
            return final.json()
    generated = asyncio.run(generate())
    ident = next(ref.split(":", 1)[1] for ref in generated["result"]["object_refs"] if ref.startswith("test_design_result:"))
    draft = v["client"].get(f"/v1/projects/{v['project_id']}/quality/test-design-results/{ident}", headers=v["headers"]).json()
    save("model_cases_generated", draft=draft)
    assert draft["result"]["proposal"]["cases"] and not draft["result"]["proposal"]["gaps"]
    reviewed_cases = edit_and_review_live_cases(v, draft, save)
    save("model_cases_edited_and_reviewed", status="design_verified", full_m3_verified=False,
        case_review=reviewed_cases, remaining=["model_http_script_generation_and_independent_review", "controlled_authenticated_fixtures",
            "formal_defect_target_execution", "denial_readback", "cleanup_and_evidence"])
