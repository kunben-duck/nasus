"""Scoped static uncertainty; no runtime, business oracle or coverage authority."""
from copy import deepcopy
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.api.app.domain.quality_loop.http_locator_evidence import compile_http_locator_evidence
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan, RunPlanIntegrityError
from apps.api.tests import test_http_fixture_binding_scripts as scripts
from apps.api.tests.exweb_git_trees import AFTER, git_bytes, read_git_tree
from apps.api.tests.test_run_plan_locators import inventory_for, JAVA, plan_fixture


def scoped_plan(path="/api/sessions/{{session}}", method="GET"):
    original = scripts.fixture_script_output

    def output(prepared):
        value = original(prepared)
        for script in value["scripts"]:
            for action in script["actions"]:
                if action["action"] == "request":
                    action.update(path=path, method=method)
        return value

    with patch.object(scripts, "fixture_script_output", output):
        draft, review, sources, selection = scripts.fixture_plan_inputs()
    return compile_run_plan(draft, review, selection, sources)


def report_for(plan, *, java=JAVA, bodies=None):
    port, source, _ = inventory_for(plan, java, bodies=bodies)
    inventory = port.inspect(plan, require_access=lambda: None)
    original = deepcopy((plan, inventory))
    report = compile_http_locator_evidence(plan, inventory)
    assert (plan, inventory) == original
    return report, port, source


def test_unrelated_condition_retains_complete_evidence_without_blocking_a_disjoint_original_request():
    java = JAVA.replace('@PostMapping("/sessions")', '@PostMapping(path="/sessions",produces="application/json")')
    plan = scoped_plan()
    report, _, _ = report_for(plan, java=java)
    assert report["schema"] == "nasus.run-plan-http-locators.v2"
    assert report["policy"] == "nasus.http-locator-static-match.v2"
    assert report["inventory"]["schema"] == "nasus.frozen-http-route-inventory.v2"
    assert report["summary"]["static_match"] == report["summary"]["locator_count"] == len(plan["prepared"]["cases"])
    unresolved = [route for route in report["inventory"]["sources"][0]["routes"] if route["status"] == "unresolved"]
    assert len(unresolved) == 1 and unresolved[0]["unresolved_match_scope"] == [{"method": "POST", "route_path": "/api/sessions"}]
    assert report["runtime_locators_verified"] is report["business_coverage_verified"] is False
    assert report["automated_count"] == report["executed_on_target_count"] == report["passed_count"] == 0


@pytest.mark.parametrize("annotation,path,method,state", [
    ('@GetMapping(path="/elsewhere",produces="application/json")', "/api/sessions/{{session}}", "GET", "static_match"),
    ('@PostMapping(path="/sessions/{id}",headers="X-Mode=x")', "/api/sessions/{{session}}", "GET", "static_match"),
    ('@GetMapping(path="/sessions/{id}",headers="X-Mode=x")', "/api/sessions/{{session}}", "GET", "unresolved"),
    ('@GetMapping(path="/sessions/fixed",produces="application/json")', "/api/sessions/{{session}}", "GET", "unresolved"),
    ('@GetMapping(path="/sessions/fixed",produces="application/json")', "/api/sessions/another", "GET", "static_match"),
    ('@RequestMapping(path="/sessions/{id}",produces="application/json")', "/api/sessions/{{session}}", "GET", "unresolved"),
    ('@GetMapping(path=UNKNOWN,produces="application/json")', "/api/sessions/{{session}}", "GET", "unresolved"),
    ('@GetMapping(path="/sessions/{id:[0-9]+}",produces="application/json")', "/api/sessions/{{session}}", "GET", "unresolved"),
])
def test_uncertainty_is_excluded_only_by_verified_method_and_literal_segments(annotation, path, method, state):
    java = JAVA.replace('  @PostMapping("/sessions") String create() { return "ok"; }',
        '  ' + annotation + ' String conditional() { return "ok"; }')
    report, _, _ = report_for(scoped_plan(path, method), java=java)
    assert report["summary"][state] == report["summary"]["locator_count"]


def test_observed_literal_route_can_overlap_an_unresolved_fixture_value():
    java = JAVA.replace('  @PostMapping("/sessions") String create() { return "ok"; }',
        '  @GetMapping("/sessions/fixed") String fixed() { return "ok"; }')
    report, _, _ = report_for(scoped_plan(), java=java)
    assert report["summary"]["unresolved"] == report["summary"]["locator_count"]


def test_failed_java_remains_global_uncertainty_and_legacy_reports_keep_the_original_policy():
    condition = JAVA.replace('@PostMapping("/sessions")', '@PostMapping(path="/sessions",produces="application/json")')
    report, _, _ = report_for(scoped_plan(), bodies={"Controller.java": JAVA.encode(), "Broken.java": b"class Broken {"})
    assert report["summary"]["unresolved"] == report["summary"]["locator_count"]
    for protocol in ("v1", "v2"):
        report, _, _ = report_for(plan_fixture(protocol=protocol), java=condition)
        assert report["schema"] == "nasus.run-plan-http-locators.v1"
        assert report["policy"] == "nasus.http-locator-static-match.v1"
        assert report["inventory"]["schema"] == "nasus.frozen-http-route-inventory.v1"
        assert report["summary"]["unresolved"] == report["summary"]["locator_count"]
        assert all("unresolved_match_scope" not in route for route in report["inventory"]["sources"][0]["routes"])


@pytest.mark.parametrize("scope", [[], True, {}, [None], [{"method": "get", "route_path": "/api/elsewhere"}],
    [{"method": "GET", "route_path": "relative"}], [{"method": "GET", "route_path": "/" + "x" * 4096}],
    [{"method": "GET", "route_path": "/api/\x00"}], [{"method": "GET", "route_path": "/api/\x7f"}],
    [{"method": "GET", "route_path": "/a", "authority": True}],
    [{"method": "GET", "route_path": "/a"}] * 2,
    [{"method": "GET", "route_path": "/b"}, {"method": "GET", "route_path": "/a"}],
    [{"method": "GET", "route_path": "/" + str(i)} for i in range(65)],
])
def test_rehashed_invalid_uncertainty_scope_is_rejected(scope):
    plan = scoped_plan()
    java = JAVA.replace('@PostMapping("/sessions")', '@PostMapping(path="/sessions",produces="application/json")')
    report, _, _ = report_for(plan, java=java)
    inventory = deepcopy(report["inventory"])
    next(route for route in inventory["sources"][0]["routes"] if route["status"] == "unresolved")["unresolved_match_scope"] = scope
    inventory["inventory_hash"] = acceptance_digest({key: value for key, value in inventory.items() if key != "inventory_hash"})
    with pytest.raises(RunPlanIntegrityError): compile_http_locator_evidence(plan, inventory)


def test_scoped_inventory_requires_new_plan_and_legacy_history_retains_original_unknowns():
    plan = scoped_plan()
    java = JAVA.replace('@PostMapping("/sessions")', '@PostMapping(path="/sessions",produces="application/json")')
    report, _, _ = report_for(plan, java=java)
    with pytest.raises(RunPlanIntegrityError): compile_http_locator_evidence(plan_fixture(protocol="v2"), report["inventory"])
    old = deepcopy(report["inventory"])
    old.update(schema="nasus.frozen-http-route-inventory.v1", rule="java.import-resolved-http-locators.v1")
    for source in old["sources"]:
        for route in source["routes"]:
            route["rule"] = old["rule"]
            route.pop("unresolved_match_scope", None)
        for file in source["files"]:
            file["rules"] = [old["rule"] if item == report["inventory"]["rule"] else item for item in file["rules"]]
    old["inventory_hash"] = acceptance_digest({key: value for key, value in old.items() if key != "inventory_hash"})
    replay = compile_http_locator_evidence(plan, old)
    assert replay["policy"] == "nasus.http-locator-static-match.v1"
    assert replay["summary"]["unresolved"] == replay["summary"]["locator_count"]


def test_new_report_is_archived_once_and_replayed_with_original_scope_without_reparsing(monkeypatch):
    from datetime import datetime, timezone
    from apps.api.tests.test_http_locator_records import service_specimen
    from apps.api.app.domain.system_image.source_access import SourceAccessDenied
    java = JAVA.replace('@PostMapping("/sessions")', '@PostMapping(path="/sessions",produces="application/json")')
    service, query, state = service_specimen(plan=scoped_plan(), java=java)
    receipt = service.record(query, invocation_id="command", recorded_at=datetime.now(timezone.utc).isoformat())
    monkeypatch.setattr(service.locators.inventory, "inspect", lambda *a, **kw: pytest.fail("historical parser re-execution"))
    assert service.record(query, invocation_id="command", recorded_at="ignored") == receipt
    view = service.read(query.project_id, receipt["record_id"])
    assert view["archive"]["report"]["schema"] == "nasus.run-plan-http-locators.v2"
    assert view["archive"]["report"]["summary"]["static_match"] == receipt["summary"]["locator_count"]
    assert state["commits"] == state["parser_calls"] == 1
    assert receipt["execution_authorized"] is False and receipt["passed_count"] == 0
    state["denied"] = True
    with pytest.raises(SourceAccessDenied): service.read(query.project_id, receipt["record_id"])


@pytest.mark.skipif(not os.getenv("EXWEB_SOURCE_REFRESH_GIT_ROOT"), reason="explicit fixed original exweb cache required")
def test_all_original_exweb_files_keep_conditions_but_allow_disjoint_session_static_locators():
    root = Path(os.environ["EXWEB_SOURCE_REFRESH_GIT_ROOT"])
    before = git_bytes(root, "status", "--porcelain")
    files, _, _ = read_git_tree(root, AFTER)
    assert len(files) == 126 and before == b""
    plan = scoped_plan("/api/v1/finance/chat/sessions/{{session}}")
    original = deepcopy(plan)
    report, port, source = report_for(plan, bodies=dict(files))
    assert len(source.files) == len(report["inventory"]["sources"][0]["files"]) == 126
    assert report["summary"]["static_match"] == report["summary"]["locator_count"] == len(plan["prepared"]["cases"])
    unresolved = [route for route in report["inventory"]["sources"][0]["routes"] if route["status"] == "unresolved"]
    assert len(unresolved) == 6 and all(route["unresolved_match_scope"] for route in unresolved)
    assert all(item["candidates"][0]["route_path"] == "/api/v1/finance/chat/sessions/{sessionId}" for item in report["locators"])
    port.verify(plan, report["inventory"], require_access=lambda: None)
    assert plan == original and git_bytes(root, "status", "--porcelain") == before
