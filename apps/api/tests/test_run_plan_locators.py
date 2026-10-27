"""Frozen-byte and query-port specimens, not native target or business gold."""
import asyncio
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.run_plan_locator_receipts import RunPlanLocatorReceiptAccess
from apps.api.app.application.platform.tool_handlers.run_plan_locators import RunPlanLocatorToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_receipt_access import require_receipt_access
from apps.api.app.application.quality_loop.run_plan_locators import (
    RunPlanLocatorApplicationService, RunPlanLocatorQuery, RUN_PLAN_LOCATOR_QUERY_TOOL,
)
from apps.api.app.domain.shared.native_build_source import FrozenNativeBuildSource, NativeBuildFile, NativeBuildSourcePin
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.automation_scripts import validate_script_proposal
from apps.api.app.domain.quality_loop.http_locator_evidence import compile_http_locator_evidence
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan, RunPlanIntegrityError, RunPlanInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.system_image.frozen_http_locators import FrozenHttpLocatorInventory
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_automation_scripts import script_output
from apps.api.tests.test_code_analysis import unit, routes
from apps.api.tests.test_http_binding_scripts import binding_script_output
from apps.api.tests.test_run_plans import plan_inputs


JAVA = '''import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("/api") class Controller {
  @GetMapping("/explicit-protocol-fixture") String read() { return "ok"; }
  @PostMapping("/sessions") String create() { return "ok"; }
  @GetMapping("/sessions/{sessionId}") String session() { return "ok"; }
}'''


def plan_fixture(*, protocol="v1", kind="http"):
    draft, review, sources, selection = plan_inputs()
    prepared = draft["result"]["prepared"]
    output = binding_script_output(prepared) if protocol == "v2" else script_output(prepared, kind=kind)
    if kind == "http":
        for script in output["scripts"]:
            for action in script["actions"]:
                if action["action"] == "request": action["path"] = "/api" + action["path"]
    proposal = validate_script_proposal(prepared, output, http_protocol="nasus.runner-http-execution." + protocol)
    draft["result"]["proposal"] = proposal
    if protocol == "v2":
        selection = selection.model_copy(update={"policy_revision": "nasus.run-plan.v2"})
    return compile_run_plan(draft, review, selection.model_dump(mode="json"), sources)


def frozen_source(plan, bodies):
    files = tuple(NativeBuildFile(path, body) for path, body in sorted(bodies.items()))
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.path.encode())
        digest.update(b"\0")
        digest.update(file.body)
    source = plan["selection"]["target_build"]["code_sources"][0]
    pin = NativeBuildSourcePin(**{key: plan["source_pin"][key] for key in (
        "project_id", "image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")}, **source,
        source_id="original-source", external_revision="explicit-fixed-specimen", content_hash="sha256:" + digest.hexdigest(),
        snapshot_manifest_hash=acceptance_digest("original-private-manifest"))
    return FrozenNativeBuildSource(pin, files)


def inventory_for(plan, java=JAVA, *, bodies=None):
    frozen = frozen_source(plan, bodies or {"Controller.java": java.encode(), "pom.xml": b"<project/>"})
    calls = []
    def read(**selection):
        calls.append(selection)
        assert all(selection[key] == getattr(frozen.pin, key) for key in selection)
        return frozen
    return FrozenHttpLocatorInventory(SimpleNamespace(read=read)), frozen, calls


@pytest.mark.parametrize("protocol", ["v1", "v2"])
def test_fixed_original_actions_match_route_spans_without_changing_cases_or_oracles(protocol):
    plan = plan_fixture(protocol=protocol)
    original = deepcopy(plan)
    port, source, calls = inventory_for(plan)
    inventory = port.inspect(plan, require_access=lambda: None)
    report = compile_http_locator_evidence(plan, inventory)
    count = sum(action["action"] == "request" for script in plan["proposal"]["scripts"] for action in script["actions"])
    assert report["summary"]["locator_count"] == report["summary"]["static_match"] == count
    assert len(calls) == 1 and plan == original
    assert len(inventory["sources"][0]["files"]) == len(source.files) == 2
    for item in report["locators"]:
        action = next(script for script in plan["proposal"]["scripts"] if script["case_id"] == item["case_id"])["actions"][item["action_index"]]
        assert item["action_digest"] == acceptance_digest(action)
        assert item["source_step_indices"] == action["source_step_indices"]
        candidate = item["candidates"][0]
        assert candidate["source_revision_id"] == source.pin.source_revision_id
        assert candidate["source_file_hash"] == source.files[0].metadata()["content_hash"]
        assert candidate["snippet_hash"].startswith("sha256:")
        assert {span["role"] for span in candidate["supporting_spans"]} == {"controller", "class_mapping"}
    assert not report["runtime_locators_verified"] and not report["execution_authorized"]
    assert report["passed_count"] == report["executed_on_target_count"] == report["automated_count"] == 0


@pytest.mark.parametrize("condition", ['params="mode=read"', 'headers="X-Mode=read"', 'consumes="application/json"',
    'produces="application/json"', 'version="1"'])
@pytest.mark.parametrize("at_class", [False, True])
def test_request_conditions_do_not_become_verified_locators_and_old_inventory_is_unchanged(condition, at_class):
    java = JAVA.replace('@RequestMapping("/api")', '@RequestMapping(path="/api", ' + condition + ')') if at_class else JAVA.replace(
        '@GetMapping("/explicit-protocol-fixture")', '@GetMapping(path="/explicit-protocol-fixture", ' + condition + ')')
    old = TreeSitterCodeIntelligenceAdapter().analyze([unit("Controller.java", java)])
    assert ("GET", "/api/explicit-protocol-fixture") in routes(old)
    plan = plan_fixture()
    port, _, _ = inventory_for(plan, java)
    report = compile_http_locator_evidence(plan, port.inspect(plan, require_access=lambda: None))
    assert report["summary"]["unresolved"] == report["summary"]["locator_count"]
    assert report["summary"]["static_match"] == 0


@pytest.mark.parametrize("path,method,state", [
    ("/api/sessions/123", "GET", "static_match"), ("/api/sessions/{{session}}", "GET", "static_match"),
    ("/sessions/123", "GET", "not_found"), ("/api/sessions/123/", "GET", "not_found"),
    ("/api/sessions", "GET", "not_found"), ("/api/sessions", "POST", "static_match"),
    ("/api/sessions/123?include=x", "GET", "static_match"), ("/api/sessions/123", "HEAD", "unresolved"),
    ("/api/sessions/%31", "GET", "unresolved"), ("/api/sessions/a;b", "GET", "unresolved"),
])
def test_method_path_matching_is_segment_exact_and_never_guesses_normalization(path, method, state):
    plan = plan_fixture()
    plan["proposal"]["scripts"][0]["actions"][0].update(path=path, method=method)
    plan["plan_digest"] = acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"})
    port, _, _ = inventory_for(plan)
    report = compile_http_locator_evidence(plan, port.inspect(plan, require_access=lambda: None))
    assert report["locators"][0]["status"] == state


def test_duplicate_declarations_are_ambiguous_not_a_fabricated_unique_route():
    plan = plan_fixture()
    port, _, _ = inventory_for(plan, bodies={"A.java": JAVA.encode(), "B.java": JAVA.replace("class Controller", "class Other").encode()})
    report = compile_http_locator_evidence(plan, port.inspect(plan, require_access=lambda: None))
    assert report["summary"]["ambiguous"] == report["summary"]["locator_count"]
    assert len(report["locators"][0]["candidates"]) == 2


@pytest.mark.parametrize("body", [b"class Broken {", b"// invalid utf8 \xff\nclass Controller {}", b"@own.RestController class Controller {}"])
def test_failed_or_foreign_annotations_cannot_manufacture_matches(body):
    plan = plan_fixture()
    port, _, _ = inventory_for(plan, bodies={"Controller.java": body})
    report = compile_http_locator_evidence(plan, port.inspect(plan, require_access=lambda: None))
    assert report["summary"]["static_match"] == 0 and not report["locators"][0]["candidates"]


def test_other_frameworks_and_browser_dom_are_explicit_gaps():
    plan = plan_fixture()
    port, _, _ = inventory_for(plan, bodies={"app.py": b"@app.get('/api/explicit-protocol-fixture')\ndef route():\n    return 'ok'\n"})
    report = compile_http_locator_evidence(plan, port.inspect(plan, require_access=lambda: None))
    assert report["summary"]["unsupported"] == report["summary"]["locator_count"]
    browser = plan_fixture(kind="browser")
    port, _, _ = inventory_for(browser)
    report = compile_http_locator_evidence(browser, port.inspect(browser, require_access=lambda: None))
    assert report["summary"]["unsupported"] == sum(len(script["actions"]) for script in browser["proposal"]["scripts"])


@pytest.mark.parametrize("fault", ["plan-hash", "inventory-hash", "source-roster", "image", "manifest", "source-revision", "file-hash", "file-status", "line"])
def test_rehashed_wrong_original_pins_or_evidence_are_rejected(fault):
    plan = plan_fixture()
    port, _, _ = inventory_for(plan)
    inventory = port.inspect(plan, require_access=lambda: None)
    item = inventory["sources"][0]
    if fault == "plan-hash": plan["plan_digest"] = acceptance_digest("wrong")
    elif fault == "source-roster": inventory["sources"] = []
    elif fault == "image": item["pin"]["image_artifact_hash"] = acceptance_digest("wrong")
    elif fault == "manifest": item["pin"]["manifest_id"] = "wrong"
    elif fault == "source-revision": item["pin"]["source_revision_id"] = "latest"
    elif fault == "file-hash": item["routes"][0]["source_file_hash"] = acceptance_digest("wrong")
    elif fault == "file-status": item["files"][0]["status"] = "failed"
    elif fault == "line": item["routes"][0]["start_line"] = True
    inventory["inventory_hash"] = acceptance_digest({key: value for key, value in inventory.items() if key != "inventory_hash"})
    if fault == "inventory-hash": inventory["inventory_hash"] = acceptance_digest("wrong")
    with pytest.raises(RunPlanIntegrityError): compile_http_locator_evidence(plan, inventory)


def test_complete_report_byte_bound_does_not_truncate(monkeypatch):
    import apps.api.app.domain.quality_loop.http_locator_evidence as policy
    plan = plan_fixture()
    port, _, _ = inventory_for(plan)
    monkeypatch.setattr(policy, "MAX_LOCATOR_REPORT_BYTES", 128)
    with pytest.raises(RunPlanInvalid, match="never truncate"):
        compile_http_locator_evidence(plan, port.inspect(plan, require_access=lambda: None))


@pytest.fixture
def state():
    plan = plan_fixture(protocol="v2")
    inventory, source, calls = inventory_for(plan)
    query = RunPlanLocatorQuery(project_id="p", run_plan_id="plan", run_plan_artifact_hash=acceptance_digest("saved-original-plan"))
    auth = SimpleNamespace(revoked=False)
    def current(scope=None):
        if auth.revoked: raise SourceAccessDenied("revoked")
    def scope(project):
        current()
        return SimpleNamespace(project_id=project, actor_id="actor")
    def read(project, ident):
        assert (project, ident) == ("p", "plan")
        return {"metadata": query.model_dump(mode="json") | {"artifact_hash": query.run_plan_artifact_hash},
            "artifact": {"plan": deepcopy(plan)}, "current_use": {"inputs_current": True}}
    service = RunPlanLocatorApplicationService(SimpleNamespace(read=read), SimpleNamespace(scope=scope, require_current=current), inventory)
    return SimpleNamespace(plan=plan, source=source, calls=calls, auth=auth, query=query, service=service)


def test_history_recompiles_original_inventory_not_the_current_parser_or_working_tree(state, monkeypatch):
    value = state.service.inspect(state.query)
    assert value["receipt"]["summary"]["static_match"] > 0 and len(state.calls) == 1
    monkeypatch.setattr(state.service.inventory, "inspect", lambda *args, **kwargs: pytest.fail("history reparsed source"))
    assert state.service.authorize_historical_receipt(state.query, value) == value
    assert len(state.calls) == 1
    state.auth.revoked = True
    with pytest.raises(SourceAccessDenied): state.service.authorize_historical_receipt(state.query, value)


@pytest.mark.parametrize("fault", ["query", "action", "report-hash", "count", "authority", "truthy-authority", "coverage", "extra"])
def test_historical_original_roster_and_metadata_cannot_be_rewritten(state, fault):
    value = state.service.inspect(state.query)
    if fault == "query": value["receipt"]["query"]["run_plan_artifact_hash"] = acceptance_digest("wrong")
    elif fault == "action": value["report"]["locators"][0]["action_digest"] = acceptance_digest("wrong")
    elif fault == "report-hash": value["receipt"]["report_hash"] = acceptance_digest("wrong")
    elif fault == "count": value["receipt"]["summary"]["static_match"] += 1
    elif fault == "authority": value["receipt"]["execution_authorized"] = True
    elif fault == "truthy-authority": value["receipt"]["execution_authorized"] = 0
    elif fault == "coverage": value["receipt"]["passed_count"] = 1
    elif fault == "extra": value["receipt"]["source_text"] = "untrusted"
    with pytest.raises((RunPlanIntegrityError, ValidationError)): state.service.authorize_historical_receipt(state.query, value)


def test_revocation_during_frozen_byte_read_prevents_result(state, monkeypatch):
    read = state.service.inventory.sources.read
    def revoked(**kwargs):
        result = read(**kwargs)
        state.auth.revoked = True
        return result
    monkeypatch.setattr(state.service.inventory.sources, "read", revoked)
    with pytest.raises(SourceAccessDenied): state.service.inspect(state.query)


def test_query_hash_is_exact_before_any_private_source_read(state):
    with pytest.raises(RunPlanIntegrityError):
        state.service.inspect(state.query.model_copy(update={"run_plan_artifact_hash": acceptance_digest("latest")}))
    assert not state.calls


def test_canonical_tool_receipt_is_private_and_reauthorized_without_rerunning_inventory(state):
    events = []
    async def emit(*args): events.append(args)
    access = SimpleNamespace(require_invocation_project_scope=lambda invocation: None)
    invocation = ToolInvocation(id="query", tool_id=RUN_PLAN_LOCATOR_QUERY_TOOL, tool_kind="query", scope="central",
        risk_level="low", confirmation_mode="none", status="running", summary="Static query specimen",
        input_payload=state.query.model_dump(mode="json"))
    asyncio.run(RunPlanLocatorToolHandler(state.service, SimpleNamespace(emit_tool_status=emit), access).handle(invocation))
    result = events[-1][-1]
    assert result.status == "completed" and result.run_plan_locators["report"]["locators"]
    invocation = invocation.model_copy(update={"status": "completed", "result": result})
    policy = RunPlanLocatorReceiptAccess(state.service)
    policy.require_access(invocation); policy.require_batch_access((invocation,))
    assert len(state.calls) == 1
    broadcast = policy.broadcast_view(invocation).model_dump(mode="json")
    assert broadcast["input_payload"] == {} and broadcast["result"] is None
    assert "Controller.java" not in str(broadcast) and "source_revision_id" not in str(broadcast)
    with pytest.raises(PlatformApplicationError): require_receipt_access(None, invocation)
    incomplete = invocation.model_copy(update={"status": "running"})
    with pytest.raises(PlatformApplicationError): policy.require_access(incomplete)
    state.auth.revoked = True
    with pytest.raises(PlatformApplicationError): policy.require_access(invocation)
