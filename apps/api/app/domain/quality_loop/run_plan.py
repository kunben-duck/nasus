"""Immutable execution inputs; declarations are not native target evidence."""
from copy import deepcopy
import json

from .acceptance_specification import acceptance_digest
from .automation_scripts import script_http_protocol, validate_script_proposal, verify_script_input
from .http_bindings import HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA


RUN_PLAN_SCHEMA = "nasus.run-plan.v1"
RUN_PLAN_ARTIFACT_SCHEMA = "nasus.run-plan-artifact.v1"
RUN_PLAN_BINDING_SCHEMA = "nasus.run-plan.v2"
RUN_PLAN_BINDING_ARTIFACT_SCHEMA = "nasus.run-plan-artifact.v2"
RUN_PLAN_FIXTURE_SCHEMA = "nasus.run-plan.v3"
RUN_PLAN_FIXTURE_ARTIFACT_SCHEMA = "nasus.run-plan-artifact.v3"
RUN_PLAN_TOOL = "quality.run_plan.prepare"
RUN_PLAN_PREVIEW_TOOL = "query.quality.run_plan_preview"
MAX_RUN_PLAN_BYTES = 16 * 1024 * 1024


class RunPlanInvalid(ValueError):
    pass


class RunPlanChanged(ValueError):
    pass


class RunPlanIntegrityError(ValueError):
    pass


def run_plan_artifact_schema(policy):
    if policy == RUN_PLAN_SCHEMA:
        return RUN_PLAN_ARTIFACT_SCHEMA
    if policy == RUN_PLAN_BINDING_SCHEMA:
        return RUN_PLAN_BINDING_ARTIFACT_SCHEMA
    if policy == RUN_PLAN_FIXTURE_SCHEMA:
        return RUN_PLAN_FIXTURE_ARTIFACT_SCHEMA
    raise RunPlanInvalid("unsupported explicit RunPlan policy")


def compile_run_plan(draft, review, selection, sources):
    prepared, proposal = draft["result"]["prepared"], draft["result"]["proposal"]
    verify_script_input(prepared)
    protocol = script_http_protocol(proposal)
    policy = RUN_PLAN_FIXTURE_SCHEMA if protocol == HTTP_FIXTURE_RECEIPT_SCHEMA else RUN_PLAN_BINDING_SCHEMA if protocol == HTTP_BINDING_RECEIPT_SCHEMA else RUN_PLAN_SCHEMA
    if selection["policy_revision"] != policy:
        raise RunPlanInvalid("RunPlan policy must preserve the explicitly reviewed script protocol")
    validated = validate_script_proposal(prepared, {key: proposal[key] for key in ("input_digest", "scripts", "gaps")}, http_protocol=protocol)
    if validated != proposal:
        raise RunPlanIntegrityError("RunPlan script cannot alter original case steps or oracle bindings")
    meta, reviewed = draft["metadata"], review["revision"]
    if (selection["project_id"] != prepared["project_id"] or meta["project_id"] != prepared["project_id"]
            or selection["script_revision_id"] != meta["script_revision_id"]
            or selection["script_artifact_hash"] != meta["artifact_hash"]
            or selection["review_revision_id"] != reviewed["revision_id"]
            or selection["review_artifact_hash"] != reviewed["artifact_hash"]
            or reviewed["script_revision_id"] != meta["script_revision_id"]
            or reviewed["script_artifact_hash"] != meta["artifact_hash"]
            or reviewed["project_id"] != prepared["project_id"]
            or reviewed["status"] != "reviewed" or (review.get("assessment") or {}).get("review_complete") is not True
            or not proposal["scripts"] or proposal["gaps"]):
        raise RunPlanInvalid("RunPlan requires the exact complete independently reviewed script")
    cases = {case["case_id"]: case for case in prepared["cases"]}
    scripts = {script["case_id"]: script for script in proposal["scripts"]}
    fixtures = {fixture["case_id"]: fixture for fixture in selection["fixtures"]}
    if (set(cases) != set(prepared["selected_case_ids"]) or set(scripts) != set(cases)
            or len(proposal["scripts"]) != len(cases) or set(fixtures) != set(cases)
            or len(selection["fixtures"]) != len(cases)
            or any(fixture["preconditions_digest"] != acceptance_digest(cases[ident]["preconditions"])
                for ident, fixture in fixtures.items())):
        raise RunPlanInvalid("RunPlan must preserve every case, precondition and fixture declaration")
    if (sources["project_id"] != prepared["project_id"]
            or sources["image_revision_id"] != prepared["context_pin"]["image_revision_id"]
            or sources["image_artifact_hash"] != prepared["context_pin"]["image_artifact_hash"]):
        raise RunPlanIntegrityError("RunPlan source inventory differs from the original context")
    code = sorted(({"binding_id": member["binding_id"], "source_revision_id": member["source_revision_id"]}
        for member in sources["source_members"] if member["source_type"] == "code" and member["status"] == "captured"),
        key=lambda pin: pin["binding_id"])
    declared = selection["target_build"]["code_sources"]
    if not code or sorted(declared, key=lambda pin: pin["binding_id"]) != code:
        raise RunPlanInvalid("target declaration must bind the complete original captured code scope")
    value = {"schema": policy, "project_id": prepared["project_id"],
        "selection": deepcopy(selection), "source_pin": deepcopy(sources),
        "script_pin": {"script_revision_id": meta["script_revision_id"], "artifact_hash": meta["artifact_hash"],
            "proposal_hash": acceptance_digest(proposal), "input_digest": prepared["input_digest"]},
        "review_pin": {"revision_id": reviewed["revision_id"], "artifact_hash": reviewed["artifact_hash"],
            "request_hash": reviewed["request_hash"], "authority_actor": reviewed["authority_actor"]},
        "prepared": deepcopy(prepared), "proposal": deepcopy(proposal), "status": "prepared",
        "target_verification": "declared_not_native_verified", "execution_authorized": False,
        "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0,
        "remaining_gates": ["native_build_source_attestation", "native_environment_and_locator_verification",
            "fixture_setup_cleanup_verification", "independent_execution_authorization", "canonical_run_plan_execution"]}
    result = {**value, "plan_digest": acceptance_digest(value)}
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RUN_PLAN_BYTES:
        raise RunPlanInvalid("complete RunPlan exceeds its byte budget; never truncate steps or oracles")
    return result
