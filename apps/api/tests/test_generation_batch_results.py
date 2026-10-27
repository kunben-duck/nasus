"""Versioned aggregate contract fixtures, not external model or PG proof."""
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

from apps.api.app.application.quality_loop.generation_batch_ledger import batch_call_request_hash, validate_batch_reply, batch_reservation, batch_execution_preview
from apps.api.app.application.quality_loop.generation_batch_planning import merge_batch_proposals, PreparedGenerationBatchPlan, batch_messages
from apps.api.app.application.quality_loop.generation_batch_results import validate_batch_result
from apps.api.app.application.quality_loop.test_design_results import BATCH_RESULT_SCHEMA, TestDesignResultIntegrityError, response_digest
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.tests.test_generation_batch_ledger import prepared_ledger, reply_payload
from apps.api.tests.test_generation_batches import responses_for


def result_fixture(prepared=None):
    prepared = prepared or prepared_ledger()[0]
    plan = batch_reservation(prepared, invocation_id="command", actor_id="actor")
    responses = responses_for(prepared.input, prepared.plan)
    merged = merge_batch_proposals(prepared.input, prepared.plan, responses, aggregate=True)
    objects, proofs = {}, []
    for sequence, (_, content) in enumerate(responses):
        _, body = reply_payload(plan, sequence)
        claim = {"project_id": plan.project_id, "invocation_id": plan.invocation_id, "sequence": sequence,
            "batch_digest": plan.batches[sequence].batch_digest, "call_id": f"native:{sequence}",
            "request_hash": batch_call_request_hash(plan, sequence), "reserved_at": "2026-10-03T00:00:00+00:00"}
        body.update(content=content, call_id=claim["call_id"])
        receipt = {**validate_batch_reply(plan, sequence, claim, body), "artifact_ref": f"private:{sequence}", "artifact_hash": acceptance_digest(body)}
        objects[receipt["artifact_ref"]] = body
        audit = {"id": claim["call_id"], "request_hash": claim["request_hash"], "response_hash": receipt["response_hash"],
            "provider": plan.model_binding.provider, "model_name": plan.model_binding.model_name,
            "input_tokens": 100, "output_tokens": 50, "usage_source": "provider", "occurred_at": claim["reserved_at"]}
        proofs.append({"claim": claim, "reply": receipt, "audit": audit})
    payload = {"schema": BATCH_RESULT_SCHEMA, "project_id": plan.project_id,
        "generation_id": str(uuid5(NAMESPACE_URL, "nasus:test-design:" + plan.invocation_id)),
        "invocation_id": plan.invocation_id, "actor_id": plan.actor_id, "request": plan.request.model_dump(mode="json"),
        "context_pin": prepared.input["context_pin"], "scope_pin": prepared.input["scope_pin"],
        "model_binding": plan.model_binding.model_dump(mode="json"), "reservation": plan.model_dump(mode="json"),
        "batch_plan": prepared.plan, "calls": proofs, "proposal": merged["proposal"], "provenance": merged["provenance"],
        "merged_output_hash": response_digest(merged["merged_content"]), "status": "draft",
        "mapping_status": "pending_independent_review", "execution_authorized": False}
    return prepared, plan, payload, objects, SimpleNamespace(read=lambda project, ref, digest: deepcopy(objects[ref]))


def public_result_fixture(context_view=None, scope_view=None, *, recovery_invocation_id=None):
    """Explicit protocol fixture for Portal; never persists or sends a model request."""
    from apps.api.app.domain.quality_loop.test_design_generation import compile_generation_input
    from apps.api.app.domain.quality_loop.test_design_scope import validate_scope_contract
    from apps.api.tests.test_generation_batches import divided_plan
    template, original = prepared_ledger()
    if context_view is not None:
        input_ = compile_generation_input(context_view, scope_view)
        batches, reserved, counts, limits = divided_plan(input_)
        selection = {"project_id": input_["project_id"], "scope_revision_id": input_["scope_pin"]["revision_id"],
            "scope_artifact_hash": input_["scope_pin"]["artifact_hash"], "model_config_id": original.model_binding.config_id,
            "budget": limits.model_dump(mode="json")}
        planning = {**{key: template.preview[key] for key in ("schema", "model_binding", "policy", "source_binding_ids", "source_scope_digest")},
            "selection": selection, "plan_digest": batches["plan_digest"], "reservation": reserved,
            "messages_hashes": [acceptance_digest(list(batch_messages(batch))) for batch in batches["batches"]]}
        digest = acceptance_digest(planning)
        preview = {**planning, "planning_digest": digest, "input_digest": input_["input_digest"],
            "batches": [{"batch_digest": batch["batch_digest"], "sequence": index, "estimated_input_tokens": counts[index]}
                for index, batch in enumerate(batches["batches"])]}
        template = PreparedGenerationBatchPlan(digest, preview, input_, batches)
    prepared, plan, private, _, _ = result_fixture(template)
    if recovery_invocation_id is not None:
        from apps.api.app.application.quality_loop.generation_batch_recovery import batch_recovery_request
        from apps.api.app.application.quality_loop.test_design_results import RECOVERED_BATCH_RESULT_SCHEMA
        private.update(schema=RECOVERED_BATCH_RESULT_SCHEMA, recovery_invocation_id=recovery_invocation_id,
            recovery_request=batch_recovery_request(plan, prepared.input, prepared.plan, private["calls"]).model_dump(mode="json"))
    metadata = {"schema": private["schema"], "project_id": plan.project_id, "generation_id": private["generation_id"],
        "scope_revision_id": plan.request.scope_revision_id, "invocation_id": plan.invocation_id, "call_id": None,
        "call_ids": [item["claim"]["call_id"] for item in private["calls"]], "batch_count": len(plan.batches),
        "plan_digest": plan.plan_digest, "status": "draft", "artifact_hash": acceptance_digest(private),
        "case_count": len(private["proposal"]["cases"]), "gap_count": len(private["proposal"]["gaps"])}
    if recovery_invocation_id is not None:
        metadata["recovery_invocation_id"] = recovery_invocation_id
    public = deepcopy(private)
    for proof in public["calls"]:
        proof["reply"].pop("artifact_ref")
    view = {"metadata": metadata, "result": public, "historical_not_live": True,
        "current_use": {"scope_current": True, "mapping_approved": False, "execution_authorized": False},
        "view_schema": "nasus.test-design-result-view.v4" if recovery_invocation_id is not None else "nasus.test-design-result-view.v3"}
    view["view_hash"] = acceptance_digest(view)
    scope = scope_view or {"revision": {**prepared.input["scope_pin"], "project_id": plan.project_id},
        "context_pin": prepared.input["context_pin"], "request": {"contract": prepared.input["scope_contract"]},
        "assessment": validate_scope_contract(prepared.input["scope_contract"], prepared.input["context"])}
    return {"archive": view, "scope": scope, "preview": batch_execution_preview(prepared), "job": {"project_id": plan.project_id,
        "generation_id": metadata["generation_id"], "source_invocation_id": plan.invocation_id,
        "invocation_id": recovery_invocation_id or plan.invocation_id}}


def test_v3_result_reconstructs_all_native_responses_full_denominator_and_case_lineage():
    prepared, plan, payload, _, artifacts = result_fixture()
    assert validate_batch_result(prepared.input, payload, artifacts) == plan
    assert len(payload["calls"]) == 3 and "call" not in payload and "raw_output" not in payload
    coverage = payload["proposal"]["coverage"]
    assert coverage["obligation_denominator"] == len(prepared.input["obligations"])
    assert coverage["assertion_mapped_count"] == coverage["executed_on_target_count"] == coverage["passed_count"] == 0
    assert len({proof["audit"]["request_hash"] for proof in payload["calls"]}) == 3
    assert {case_id for batch in payload["provenance"] for case_id in batch["case_id_map"].values()} == {case["case_id"] for case in payload["proposal"]["cases"]}


@pytest.mark.parametrize("mutation", ["missing_call", "duplicate_call", "request_hash", "response_hash", "native_body", "plan",
    "oracle", "coverage", "case_lineage", "output_hash", "authority", "single_call", "model", "generation_id", "malformed_proof", "extra_secret", "boolean_usage"])
def test_v3_result_rejects_partial_foreign_corrupt_or_authoritative_aggregates(mutation):
    prepared, _, payload, objects, artifacts = result_fixture()
    if mutation == "missing_call":
        payload["calls"].pop()
    elif mutation == "duplicate_call":
        payload["calls"][1] = deepcopy(payload["calls"][0])
    elif mutation == "request_hash":
        payload["calls"][0]["audit"]["request_hash"] = acceptance_digest("fake single aggregate call")
    elif mutation == "response_hash":
        payload["calls"][0]["audit"]["response_hash"] = acceptance_digest("different reply")
    elif mutation == "native_body":
        objects["private:0"]["content"] += " "
    elif mutation == "plan":
        payload["batch_plan"]["batches"].pop()
    elif mutation == "oracle":
        payload["proposal"]["cases"][0]["assertions"][0]["oracle"]["expected_value"] = "fabricated"
    elif mutation == "coverage":
        payload["proposal"]["coverage"]["passed_count"] = 1
    elif mutation == "case_lineage":
        payload["provenance"][0]["case_id_map"] = {}
    elif mutation == "output_hash":
        payload["merged_output_hash"] = acceptance_digest("different merge")
    elif mutation == "authority":
        payload["execution_authorized"] = True
    elif mutation == "single_call":
        payload["call"] = payload["calls"][0]["audit"]
    elif mutation == "model":
        payload["model_binding"]["model_name"] = "fallback is prohibited"
    elif mutation == "malformed_proof":
        payload["calls"][0]["reply"].pop("usage")
    elif mutation == "extra_secret":
        payload["calls"][0]["audit"]["api_key"] = "never allowed"
    elif mutation == "boolean_usage":
        payload["calls"][0]["audit"]["input_tokens"] = True
    else:
        payload["generation_id"] = "foreign"
    with pytest.raises(ValueError):
        validate_batch_result(prepared.input, payload, artifacts)


def test_versioned_aggregate_does_not_truncate_valid_multi_call_output_to_single_call_limits():
    prepared, _ = prepared_ledger()
    responses = responses_for(prepared.input, prepared.plan)
    # Each native response stays within its own 512-case/1 MiB contract.
    enlarged = []
    for ident, content in responses:
        output = json.loads(content)
        original = deepcopy(output["cases"])
        output["cases"] = []
        for index in range(180):
            case = deepcopy(original[index % len(original)])
            case["case_id"] = f"independent-local:{index}"
            output["cases"].append(case)
        enlarged.append((ident, json.dumps(output)))
    with pytest.raises(ValueError):
        merge_batch_proposals(prepared.input, prepared.plan, enlarged)
    merged = merge_batch_proposals(prepared.input, prepared.plan, enlarged, aggregate=True)
    assert len(merged["proposal"]["cases"]) == 540
    assert merged["proposal"]["coverage"]["obligation_denominator"] == len(prepared.input["obligations"])
    assert merged["proposal"]["coverage"]["passed_count"] == 0
