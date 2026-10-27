"""Exact original build attestation, without environment or execution authority."""
from copy import deepcopy
from pathlib import PurePosixPath
import json

from .acceptance_specification import acceptance_digest
from .native_build import NATIVE_BUILD_SCHEMA, NATIVE_BUILD_ADAPTER
from .run_plan import RUN_PLAN_SCHEMA, RUN_PLAN_BINDING_SCHEMA, RUN_PLAN_FIXTURE_SCHEMA, run_plan_artifact_schema, RunPlanInvalid, RunPlanIntegrityError


RUN_PLAN_BUILD_SCHEMA = "nasus.run-plan-build.v1"
RUN_PLAN_BUILD_ARTIFACT_SCHEMA = "nasus.run-plan-build-artifact.v1"
RUN_PLAN_BUILD_TOOL = "quality.run_plan.bind_native_build"
RUN_PLAN_BUILD_PREVIEW_TOOL = "query.quality.run_plan_build_preview"
RUN_PLAN_BUILD_QUERY_TOOL = "query.quality.run_plan_build"
MAX_RUN_PLAN_BUILD_BYTES = 4 * 1024 * 1024


def compile_run_plan_build(view, selection, builds):
    artifact, metadata = view["artifact"], view["metadata"]
    plan, source = artifact["plan"], artifact["plan"]["source_pin"]
    unsigned = {key: value for key, value in plan.items() if key != "plan_digest"}
    if (plan.get("schema") not in {RUN_PLAN_SCHEMA, RUN_PLAN_BINDING_SCHEMA, RUN_PLAN_FIXTURE_SCHEMA}
            or plan.get("schema") != plan.get("selection", {}).get("policy_revision")
            or artifact.get("schema") != run_plan_artifact_schema(plan["schema"])
            or acceptance_digest(unsigned) != plan.get("plan_digest")
            or artifact.get("project_id") != selection["project_id"]
            or artifact.get("run_plan_id") != selection["run_plan_id"]
            or metadata.get("artifact_hash") != selection["run_plan_artifact_hash"]
            or acceptance_digest(artifact) != selection["run_plan_artifact_hash"]
            or plan.get("status") != "prepared" or plan.get("execution_authorized") is not False
            or any(type(plan.get(key)) is not int or plan[key] != 0 for key in
                ("automated_count", "executed_on_target_count", "passed_count"))):
        raise RunPlanIntegrityError("build binding requires the original immutable RunPlan")
    expected = {member["binding_id"]: member["source_revision_id"] for member in source["source_members"]
        if member["source_type"] == "code" and member["status"] == "captured"}
    declared = plan["selection"]["target_build"]
    if (not expected or len(builds) != len(expected) or len(selection["native_builds"]) != len(builds)
            or {pin["binding_id"]: pin["source_revision_id"] for pin in declared["code_sources"]} != expected):
        raise RunPlanInvalid("build binding must attest the complete original captured code scope")
    references = {item["invocation_id"]: item for item in selection["native_builds"]}
    if len(references) != len(builds):
        raise RunPlanInvalid("each original native build must appear exactly once")
    members, observed = [], set()
    target = None
    for build in builds:
        result, receipt = build.get("metadata"), build.get("receipt")
        ref = references.get(build.get("invocation_id"))
        if (not isinstance(result, dict) or not isinstance(receipt, dict) or ref is None
                or build.get("project_id") != selection["project_id"]
                or result.get("project_id") != selection["project_id"] or result.get("execution_authorized") is not False
                or any(result.get(key) != ref[key] for key in ("invocation_id", "build_id", "artifact_hash", "receipt_digest"))
                or acceptance_digest(receipt) != ref["receipt_digest"]
                or receipt.get("schema") != NATIVE_BUILD_SCHEMA or receipt.get("adapter") != NATIVE_BUILD_ADAPTER
                or receipt.get("native_build_verified") is not True or receipt.get("execution_authorized") is not False
                or any(type(receipt.get(key)) is not int or receipt[key] != 0 for key in
                    ("executed_on_target_count", "passed_count"))
                or result.get("request_digest") != receipt.get("request_digest")
                or result.get("artifact") != receipt.get("artifact")):
            raise RunPlanIntegrityError("build binding requires a verified original committed archive")
        pin = receipt["source"]["pin"]
        if (any(pin.get(key) != source[key] for key in
                ("project_id", "image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash"))
                or pin.get("binding_id") in observed or expected.get(pin.get("binding_id")) != pin.get("source_revision_id")):
            raise RunPlanInvalid("native build source differs from the original complete image scope")
        observed.add(pin["binding_id"])
        files = receipt["source"]["files"]
        definitions = [item for item in files if item["path"] == "pom.xml"]
        toolchain = receipt["toolchain"]
        if (len(definitions) != 1 or toolchain.get("java") != "21" or toolchain.get("maven") != "3.9.11"
                or toolchain.get("network") != "none" or toolchain.get("dependency_cache") != "operator_read_only"):
            raise RunPlanInvalid("unsupported native build definition or toolchain")
        member = {**deepcopy(ref), "source_pin": deepcopy(pin), "request_digest": receipt["request_digest"],
            "source_files_digest": acceptance_digest(files), "build_definition_hash": definitions[0]["content_hash"],
            "artifact": deepcopy(receipt["artifact"]), "toolchain": deepcopy(toolchain)}
        members.append(member)
        if ref["invocation_id"] == selection["target_build_invocation_id"]:
            target = member
    if observed != set(expected) or target is None:
        raise RunPlanInvalid("all code sources and an explicit primary target build are required")
    if (PurePosixPath(target["artifact"]["path"]).name != declared["artifact_name"]
            or target["artifact"]["content_hash"] != declared["artifact_hash"]
            or target["build_definition_hash"] != declared["build_definition_hash"]
            or (declared["runtime"], declared["runtime_version"], declared["build_tool"], declared["build_tool_version"])
                != ("Java", "21", "Maven", "3.9.11")):
        raise RunPlanInvalid("primary build must match the original artifact, root pom and toolchain declarations")
    value = {"schema": RUN_PLAN_BUILD_SCHEMA, "project_id": selection["project_id"],
        "selection": deepcopy(selection), "run_plan_id": selection["run_plan_id"],
        "run_plan_artifact_hash": selection["run_plan_artifact_hash"], "plan_digest": plan["plan_digest"],
        "source_pin": {key: source[key] for key in
            ("project_id", "image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")},
        "builds": sorted(members, key=lambda item: item["source_pin"]["binding_id"]),
        "target_build_invocation_id": selection["target_build_invocation_id"],
        "target_artifact_hash": target["artifact"]["content_hash"], "native_build_source_attested": True,
        "source_file_modes_attested": False,
        "execution_authorized": False, "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0,
        "reproducible_build_verified": False, "dependency_supply_chain_verified": False,
        "remaining_gates": [gate for gate in plan["remaining_gates"] if gate != "native_build_source_attestation"]}
    result = {**value, "binding_digest": acceptance_digest(value)}
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RUN_PLAN_BUILD_BYTES:
        raise RunPlanInvalid("complete build binding exceeds its byte budget; no partial source scope is accepted")
    return result
