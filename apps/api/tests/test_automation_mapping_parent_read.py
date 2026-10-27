"""Operation-local verified parents; these specimens are not native business gold."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.automation_inputs import AutomationInputApplicationService, AutomationInputSelection
from apps.api.app.application.quality_loop.test_design_mappings import TestDesignMappingApplicationService
from apps.api.app.domain.quality_loop.automation_input import AutomationInputChanged, AutomationInputInvalid, compile_automation_input, replay_automation_input
from apps.api.app.domain.quality_loop.test_design_mapping import TestDesignMappingChanged, TestDesignMappingIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_automation_input import automation_inputs


def parent_ports():
    prepared, result, mapping, ids = automation_inputs()
    seen = []
    def duplicate(*_args):
        raise AssertionError("the already verified result must not be read again")
    def historical(project, revision):
        assert (project, revision) == ("p", "m")
        seen.append("history-parent")
        return deepcopy(mapping), deepcopy(result)
    def current(project, revision, digest):
        assert digest == mapping["revision"]["artifact_hash"]
        value = historical(project, revision)
        seen[-1] = "current-parent"
        return value
    def generation(mode):
        def read(selection):
            assert selection.project_id == "p" and selection.scope_revision_id == prepared["scope_pin"]["revision_id"]
            assert selection.scope_artifact_hash == prepared["scope_pin"]["artifact_hash"]
            seen.append(mode)
            return deepcopy(prepared)
        return read
    mappings = SimpleNamespace(read=duplicate, resolve=duplicate,
        read_with_result=historical, resolve_with_result=current)
    authorization = SimpleNamespace(scope=lambda project: SimpleNamespace(project_id=project),
        require_current=lambda access: seen.append("access"))
    service = AutomationInputApplicationService(mappings, SimpleNamespace(read=duplicate),
        SimpleNamespace(prepare=generation("prepare"), replay=generation("replay")), authorization)
    request = AutomationInputSelection(project_id="p", mapping_revision_id="m",
        mapping_artifact_hash=mapping["revision"]["artifact_hash"], case_ids=ids)
    return service, request, prepared, result, mapping, seen


@pytest.mark.parametrize("historical", [False, True])
def test_automation_reuses_verified_mapping_parent_but_keeps_all_generation_and_final_checks(historical):
    service, request, prepared, result, mapping, seen = parent_ports()
    if historical:
        actual = service.replay(request)
        assert actual == replay_automation_input(prepared, result, mapping, request.case_ids)
        assert seen == ["history-parent", "replay", "access"]
    else:
        actual = service.prepare(request)
        assert actual == compile_automation_input(prepared, result, mapping, request.case_ids)
        assert seen == ["current-parent", "prepare", "current-parent", "prepare", "access"]
    assert not actual["generation_authorized"] and not actual["execution_authorized"]
    assert actual["automated_count"] == actual["executed_on_target_count"] == actual["passed_count"] == 0
    service.prepare(request)
    assert seen[-5:] == ["current-parent", "prepare", "current-parent", "prepare", "access"]


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("fault", ["project", "generation", "scope", "oracle", "denominator", "hash"])
def test_parent_cannot_substitute_fixed_case_scope_or_source_oracle(historical, fault):
    service, request, _, result, mapping, _ = parent_ports()
    if fault == "project": result["metadata"]["project_id"] = "another"
    elif fault == "generation": result["metadata"]["generation_id"] = "another"
    elif fault == "scope": result["result"]["scope_pin"]["artifact_hash"] = "sha256:" + "a" * 64
    elif fault == "oracle": result["result"]["proposal"]["cases"][0]["assertions"][0]["oracle_digest"] = "sha256:" + "a" * 64
    elif fault == "denominator": result["result"]["proposal"]["coverage"]["rows"].pop()
    else: mapping["revision"]["artifact_hash"] = "sha256:" + "a" * 64
    service.mappings.read_with_result = lambda *_: (deepcopy(mapping), deepcopy(result))
    service.mappings.resolve_with_result = service.mappings.read_with_result
    with pytest.raises(AutomationInputInvalid):
        (service.replay if historical else service.prepare)(request)


@pytest.mark.parametrize("fault", ["mapping", "generation", "access"])
@pytest.mark.parametrize("historical", [False, True])
def test_failures_do_not_fall_back_to_duplicate_reader_or_return_partial_result(fault, historical):
    service, request, _, _, _, _ = parent_ports()
    def denied(*_args):
        raise SourceAccessDenied("explicit current source withdrawal")
    if fault == "mapping":
        setattr(service.mappings, "read_with_result" if historical else "resolve_with_result", denied)
    elif fault == "generation":
        setattr(service.generation, "replay" if historical else "prepare", denied)
    else: service.authorization.require_current = denied
    with pytest.raises(SourceAccessDenied):
        (service.replay if historical else service.prepare)(request)


@pytest.mark.parametrize("stage", ["parent", "generation"])
def test_second_compilation_still_rechecks_mutable_authority_after_case_collection(stage):
    service, request, _, _, _, _ = parent_ports()
    port = service.mappings if stage == "parent" else service.generation
    name = "resolve_with_result" if stage == "parent" else "prepare"
    original, calls = getattr(port, name), []
    def withdrawn(*args):
        calls.append(True)
        if len(calls) == 2:
            raise AutomationInputChanged("original authority withdrawn during collection")
        return original(*args)
    setattr(port, name, withdrawn)
    with pytest.raises(AutomationInputChanged): service.prepare(request)
    assert len(calls) == 2


@pytest.mark.parametrize("current", [False, True])
def test_mapping_parent_port_preserves_public_view_and_selected_hash(monkeypatch, current):
    _, result, mapping, _ = automation_inputs()
    service = TestDesignMappingApplicationService(None, None, None, None)
    calls = []
    def verified(project, revision):
        calls.append((project, revision))
        return deepcopy(mapping), deepcopy(result)
    monkeypatch.setattr(service, "_read_inputs", verified)
    view, parent = (service.resolve_with_result("p", "m", mapping["revision"]["artifact_hash"]) if current else
        service.read_with_result("p", "m"))
    assert view == mapping and parent == result and calls == [("p", "m")]
    assert service.read("p", "m") == view
    assert service.resolve("p", "m", mapping["revision"]["artifact_hash"]) == view
    with pytest.raises(TestDesignMappingIntegrityError): service.resolve_with_result("p", "m", "sha256:" + "a" * 64)
    mapping["current_use"]["mapping_current"] = False
    with pytest.raises(TestDesignMappingChanged):
        service.resolve_with_result("p", "m", mapping["revision"]["artifact_hash"])
    historical, _ = service.read_with_result("p", "m")
    assert historical["current_use"]["mapping_current"] is False
