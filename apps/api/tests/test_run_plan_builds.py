"""Pure port/receipt specimens, not native Java or independently approved gold."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.run_plan_build_inputs import RunPlanBuildSelection, RunPlanBuildRequest
from apps.api.app.application.quality_loop.run_plan_builds import RunPlanBuildApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.native_build import NativeBuildRequest, NativeBuildOutput, build_receipt
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan, RunPlanChanged, RunPlanIntegrityError, RunPlanInvalid
from apps.api.app.domain.quality_loop.run_plan_build import compile_run_plan_build
from apps.api.app.domain.shared.native_build_source import NativeBuildSourcePin, FrozenNativeBuildSource, NativeBuildFile, byte_digest
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_native_build import protocol_jar
from apps.api.tests.test_run_plans import plan_inputs


def binding_inputs(*, multiple=False):
    draft, review, sources, selection = plan_inputs()
    if multiple:
        sources["source_members"].append({"binding_id": "second", "source_revision_id": "second-revision", "source_type": "code", "status": "captured"})
    artifact = protocol_jar()
    pom = b"<project>Binding protocol only.</project>"
    target = selection.target_build.model_dump(mode="json")
    target.update(artifact_name="app.jar", artifact_hash=byte_digest(artifact), build_definition_hash=byte_digest(pom),
        code_sources=[{key: member[key] for key in ("binding_id", "source_revision_id")}
            for member in sources["source_members"] if member["source_type"] == "code"])
    value = selection.model_dump(mode="json")
    value["target_build"] = target
    plan = compile_run_plan(draft, review, value, sources)
    archived = {"schema": "nasus.run-plan-artifact.v1", "project_id": "p", "run_plan_id": "plan", "plan": plan}
    view = {"artifact": archived, "metadata": {"artifact_hash": acceptance_digest(archived)}, "current_use": {"inputs_current": True}}
    builds = []
    for member in sources["source_members"]:
        if member["source_type"] != "code":
            continue
        pin = NativeBuildSourcePin(**{key: sources[key] for key in
            ("project_id", "image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")},
            binding_id=member["binding_id"], source_revision_id=member["source_revision_id"], source_id="source-" + member["binding_id"],
            external_revision="fixed", content_hash=byte_digest(b"pom.xml\0" + pom), snapshot_manifest_hash=byte_digest(b"snapshot"))
        request = NativeBuildRequest(FrozenNativeBuildSource(pin, (NativeBuildFile("pom.xml", pom),)), "target/app.jar")
        output = NativeBuildOutput(request.digest, artifact, b"Protocol only, not compiled.",
            {"image_id": byte_digest(b"image"), "java": "21", "maven": "3.9.11", "network": "none",
                "dependency_cache": "operator_read_only", "version_output_hash": byte_digest(b"protocol")}, {})
        receipt = build_receipt(request, output)
        ident = "native-" + member["binding_id"]
        metadata = {"project_id": "p", "invocation_id": ident, "build_id": "build-" + ident,
            "artifact_hash": acceptance_digest(["private-archive", ident]), "receipt_digest": acceptance_digest(receipt),
            "request_digest": request.digest, "artifact": receipt["artifact"], "execution_authorized": False}
        builds.append({"project_id": "p", "invocation_id": ident, "metadata": metadata, "receipt": receipt})
    selection = RunPlanBuildSelection(project_id="p", run_plan_id="plan", run_plan_artifact_hash=acceptance_digest(archived),
        native_builds=[{key: build["metadata"][key] for key in ("invocation_id", "build_id", "artifact_hash", "receipt_digest")} for build in builds],
        target_build_invocation_id=builds[0]["invocation_id"], reason="Independent original build binding protocol specimen")
    return view, selection, builds


def refresh_pins(view, selection, builds):
    plan = view["artifact"]["plan"]
    plan["plan_digest"] = acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"})
    view["metadata"]["artifact_hash"] = acceptance_digest(view["artifact"])
    selection["run_plan_artifact_hash"] = view["metadata"]["artifact_hash"]
    for build, reference in zip(builds, selection["native_builds"]):
        reference["receipt_digest"] = acceptance_digest(build["receipt"])
        if build["metadata"] is not None:
            build["metadata"]["receipt_digest"] = reference["receipt_digest"]


@pytest.mark.parametrize("multiple", [False, True])
def test_binding_preserves_complete_original_plan_and_all_build_pins_without_authority(multiple):
    view, selection, builds = binding_inputs(multiple=multiple)
    original = deepcopy((view, builds))
    binding = compile_run_plan_build(view, selection.model_dump(mode="json"), builds)
    assert (view, builds) == original
    assert len(binding["builds"]) == len(builds)
    assert binding["binding_digest"] == acceptance_digest({key: value for key, value in binding.items() if key != "binding_digest"})
    assert binding["native_build_source_attested"] is True and binding["execution_authorized"] is False
    assert binding["automated_count"] == binding["executed_on_target_count"] == binding["passed_count"] == 0
    assert "native_build_source_attestation" not in binding["remaining_gates"]
    assert "native_environment_and_locator_verification" in binding["remaining_gates"]
    assert "fixture_setup_cleanup_verification" in binding["remaining_gates"]
    assert not binding["reproducible_build_verified"] and not binding["dependency_supply_chain_verified"]


@pytest.mark.parametrize("fault", ["missing_source", "extra_source", "duplicate_source", "image", "manifest", "revision",
    "project", "archive_hash", "receipt_hash", "uncommitted", "truthy_verified", "execution", "passed", "truthy_zero",
    "jar_name", "jar_hash", "pom_hash", "runtime", "runtime_version", "tool", "tool_version", "network", "cache",
    "definition_missing", "target_missing", "plan_hash", "plan_artifact", "plan_authority", "request_digest"])
def test_binding_rejects_unpinned_incomplete_or_invented_target_evidence(fault):
    view, selection, builds = binding_inputs(multiple=True)
    value = selection.model_dump(mode="json")
    receipt = builds[0]["receipt"]
    target = view["artifact"]["plan"]["selection"]["target_build"]
    if fault == "missing_source": builds.pop(); value["native_builds"].pop()
    elif fault == "extra_source": builds.append(deepcopy(builds[0])); value["native_builds"].append(deepcopy(value["native_builds"][0]))
    elif fault == "duplicate_source": builds[1]["receipt"]["source"]["pin"].update(receipt["source"]["pin"])
    elif fault in {"image", "manifest", "revision", "project"}:
        key = {"image": "image_revision_id", "manifest": "manifest_id", "revision": "source_revision_id", "project": "project_id"}[fault]
        receipt["source"]["pin"][key] = "foreign"
    elif fault == "archive_hash": value["native_builds"][0]["artifact_hash"] = acceptance_digest("wrong archive")
    elif fault == "uncommitted": builds[0]["metadata"] = None
    elif fault == "truthy_verified": receipt["native_build_verified"] = "true"
    elif fault == "execution": receipt["execution_authorized"] = True
    elif fault == "passed": receipt["passed_count"] = 1
    elif fault == "truthy_zero": receipt["passed_count"] = False
    elif fault in {"jar_name", "jar_hash", "pom_hash", "runtime", "runtime_version", "tool", "tool_version"}:
        key = {"jar_name": "artifact_name", "jar_hash": "artifact_hash", "pom_hash": "build_definition_hash",
            "tool": "build_tool", "tool_version": "build_tool_version"}.get(fault, fault)
        target[key] = "different" if not key.endswith("hash") else acceptance_digest("different")
    elif fault in {"network", "cache"}: receipt["toolchain"]["network" if fault == "network" else "dependency_cache"] = "unsafe"
    elif fault == "definition_missing": receipt["source"]["files"] = []
    elif fault == "target_missing": value["target_build_invocation_id"] = "foreign"
    elif fault == "plan_authority": view["artifact"]["plan"]["execution_authorized"] = True
    elif fault == "request_digest": receipt["request_digest"] = acceptance_digest("different")
    refresh_pins(view, value, builds)
    if fault == "receipt_hash": value["native_builds"][0]["receipt_digest"] = acceptance_digest("wrong receipt")
    elif fault == "plan_hash": view["artifact"]["plan"]["plan_digest"] = acceptance_digest("wrong plan")
    elif fault == "plan_artifact": value["run_plan_artifact_hash"] = acceptance_digest("wrong artifact")
    with pytest.raises((RunPlanInvalid, RunPlanIntegrityError)):
        compile_run_plan_build(view, value, builds)


def test_binding_dto_rejects_duplicate_members_foreign_primary_and_execution_authority():
    _, selection, _ = binding_inputs()
    value = selection.model_dump(mode="json")
    for changed in ({**value, "native_builds": value["native_builds"] * 2}, {**value, "target_build_invocation_id": "foreign"},
            {**value, "execution_authorized": True}, {**value, "policy_revision": "unknown"}):
        with pytest.raises(ValidationError):
            RunPlanBuildSelection.model_validate(changed)


def test_binding_complete_byte_budget_never_truncates_sources(monkeypatch):
    import apps.api.app.domain.quality_loop.run_plan_build as policy
    view, selection, builds = binding_inputs(multiple=True)
    monkeypatch.setattr(policy, "MAX_RUN_PLAN_BUILD_BYTES", 128)
    with pytest.raises(RunPlanInvalid, match="no partial source"):
        compile_run_plan_build(view, selection.model_dump(mode="json"), builds)


def application():
    view, selection, builds = binding_inputs()
    actions, stored = [], {}
    class Authorization:
        revoked = False
        role = "qa_lead"
        fingerprint = acceptance_digest("access")
        def scope(self, project):
            self.require_current(None)
            return SimpleNamespace(actor_id="reviewer", fingerprint=self.fingerprint, effective_project_role=self.role)
        def require_current(self, access):
            if self.revoked:
                raise SourceAccessDenied("revoked")
    auth = Authorization()
    class Repository:
        def committed(self, request, *, actor_id, invocation_id, require_access):
            require_access()
            return stored.get("metadata")
        def record(self, request, payload, ref, digest, *, require_current):
            require_current()
            binding = payload["binding"]
            metadata = {key: payload[key] for key in ("binding_id", "project_id", "actor_id", "invocation_id", "recorded_at")}
            metadata.update({key: binding[key] for key in
                ("binding_digest", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "target_artifact_hash")})
            metadata.update({key: binding["source_pin"][key] for key in ("image_revision_id", "manifest_id")})
            metadata.update(artifact_hash=digest, request_hash=acceptance_digest(payload["request"]))
            stored.update(metadata=metadata, artifact_ref=ref, request=payload["request"], payload=deepcopy(payload))
            return metadata
        def read(self, project, ident): return stored
    class Artifacts:
        def put(self, project, payload):
            actions.append("put")
            return "private", acceptance_digest(payload)
        def read(self, *args):
            actions.append("private_read")
            return deepcopy(stored["payload"])
    def read_plan(*args):
        actions.append("source_read")
        auth.require_current(None)
        return deepcopy(view)
    def read_build(*args):
        actions.append("native_read")
        auth.require_current(None)
        return deepcopy(builds[0])
    service = RunPlanBuildApplicationService(SimpleNamespace(read=read_plan), SimpleNamespace(read=read_build), auth, Repository(), Artifacts())
    return service, view, selection, auth, actions, stored


def test_application_preview_is_readonly_history_is_reauthorized_and_withdrawal_never_rewrites_binding():
    service, view, selection, auth, actions, stored = application()
    preview = service.preview(selection)
    assert "put" not in actions and not preview["execution_authorized"]
    request = RunPlanBuildRequest.model_validate(preview["request"])
    metadata = service.bind(request, invocation_id="binding-command", recorded_at="2026-10-10T00:00:00+00:00")
    original = service.read("p", metadata["binding_id"])
    actions.clear()
    view["current_use"]["inputs_current"] = False
    historical = service.read("p", metadata["binding_id"])
    assert historical["artifact"] == original["artifact"] and not historical["current_use"]["inputs_current"]
    assert actions.index("native_read") < actions.index("private_read")
    assert service.bind(request, invocation_id="binding-command", recorded_at="later") == metadata
    with pytest.raises(RunPlanChanged): service.preview(selection)
    auth.revoked = True
    actions.clear()
    with pytest.raises(SourceAccessDenied): service.read("p", metadata["binding_id"])
    assert "private_read" not in actions


def test_application_changed_preview_corrupt_archive_and_nonreviewer_fail_closed():
    service, view, selection, auth, actions, stored = application()
    request = RunPlanBuildRequest.model_validate(service.preview(selection)["request"])
    auth.fingerprint = acceptance_digest("changed")
    with pytest.raises(RunPlanChanged): service.bind(request, invocation_id="command", recorded_at="now")
    assert "put" not in actions
    auth.role = "tester"
    with pytest.raises(SourceAccessDenied): service.bind(request, invocation_id="command", recorded_at="now")
    auth.role = "qa_lead"
    request = RunPlanBuildRequest.model_validate(service.preview(selection)["request"])
    metadata = service.bind(request, invocation_id="command", recorded_at="now")
    stored["payload"]["binding"]["execution_authorized"] = True
    with pytest.raises(RunPlanIntegrityError): service.read("p", metadata["binding_id"])


def test_build_binding_agent_fingerprint_changes_on_withdrawal_without_mutating_history():
    from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
    from apps.api.app.application.platform.tool_models import ToolResult
    service, view, selection, auth, actions, stored = application()
    preview = service.preview(selection)
    request = RunPlanBuildRequest.model_validate(preview["request"])
    metadata = service.bind(request, invocation_id="command", recorded_at="now")
    original = service.receipt("p", metadata["binding_id"])
    result = ToolResult(invocation_id="read", status="completed", summary="Original receipt", run_plan_build=original)
    fingerprint = observation_receipt_fingerprint(result)
    assert fingerprint is not None
    assert observation_receipt_fingerprint(result.model_copy(update={"run_plan_build": deepcopy(original)})) == fingerprint
    view["current_use"]["inputs_current"] = False
    current = service.receipt("p", metadata["binding_id"])
    assert current["metadata"] == original["metadata"]
    assert observation_receipt_fingerprint(result.model_copy(update={"run_plan_build": current})) != fingerprint
