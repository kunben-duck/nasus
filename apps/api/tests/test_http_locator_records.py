"""Independent archive and byte-check contracts; sources/models are explicit specimens."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.http_locator_record_receipts import HttpLocatorRecordReceiptAccess
from apps.api.app.application.platform.tool_receipt_access import require_receipt_access
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.quality_loop.http_locator_records import HttpLocatorRecordApplicationService
from apps.api.app.application.quality_loop.run_plan_locators import RunPlanLocatorApplicationService, RunPlanLocatorQuery
from apps.api.app.application.quality_loop.environment_observation_records import EnvironmentRecordQuery
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_locator_record import (
    LOCATOR_RECORD_SCHEMA, LOCATOR_RECORD_TOOL, LOCATOR_RECORD_QUERY_TOOL, locator_record_identity,
    locator_record_metadata, validate_locator_archive,
)
from apps.api.app.domain.quality_loop.http_locator_evidence import compile_http_locator_evidence
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_run_plan_locators import JAVA, plan_fixture, inventory_for


def specimen(*, plan=None, java=JAVA):
    plan = plan if plan is not None else plan_fixture(protocol="v2")
    port, source, calls = inventory_for(plan, java)
    inventory = port.inspect(plan, require_access=lambda: None)
    query = RunPlanLocatorQuery(project_id=plan["project_id"], run_plan_id="original-plan", run_plan_artifact_hash=acceptance_digest("original-archive"))
    saved = {"metadata": query.model_dump(mode="json") | {"artifact_hash": query.run_plan_artifact_hash}, "artifact": {"plan": plan}}
    payload = {"schema": LOCATOR_RECORD_SCHEMA, "project_id": query.project_id, "record_id": locator_record_identity("command"),
        "invocation_id": "command", "actor_id": "reviewer", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "request": query.model_dump(mode="json"), "parents": {"plan_digest": plan["plan_digest"], **{key: plan["source_pin"][key]
            for key in ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")}},
        "report": compile_http_locator_evidence(plan, inventory)}
    return plan, port, source, calls, query, saved, payload


def test_record_retains_original_actions_gaps_and_never_upgrades_execution():
    plan, port, source, calls, query, saved, payload = specimen()
    metadata = validate_locator_archive(payload, query.model_dump(mode="json"), saved)
    assert metadata["source_bytes_verified"] is metadata["durable_locator_evidence_verified"] is True
    assert all(metadata[key] is False for key in ("runtime_locators_verified", "fixtures_verified", "execution_authorized", "business_coverage_verified"))
    assert metadata["automated_count"] == metadata["executed_on_target_count"] == metadata["passed_count"] == 0
    assert metadata["summary"] == payload["report"]["summary"]
    port.verify(plan, payload["report"]["inventory"], require_access=lambda: None)
    assert len(calls) == 2 and len(source.files) == 2


@pytest.mark.parametrize("field,value", [("schema", "wrong"), ("record_id", "foreign"), ("project_id", "foreign"),
    ("actor_id", ""), ("recorded_at", "2026-10-11T00:00:00"), ("recorded_at", None)])
def test_archive_scope_is_strict(field, value):
    *_, query, saved, payload = specimen()
    payload[field] = value
    with pytest.raises(RunPlanIntegrityError): validate_locator_archive(payload, query.model_dump(mode="json"), saved)


@pytest.mark.parametrize("field,value", [("execution_authorized", True), ("runtime_locators_verified", 0),
    ("business_coverage_verified", True), ("passed_count", 1), ("automated_count", False)])
def test_rehashed_archive_cannot_upgrade_authority(field, value):
    *_, query, saved, payload = specimen()
    payload["report"][field] = value
    payload["report"]["report_hash"] = acceptance_digest({key: value for key, value in payload["report"].items() if key != "report_hash"})
    with pytest.raises(RunPlanIntegrityError): validate_locator_archive(payload, query.model_dump(mode="json"), saved)


@pytest.mark.parametrize("mutation", ["file", "missing", "duplicate", "pin", "snippet", "support", "span", "bool_bytes"])
def test_history_verifies_original_bytes_not_only_self_consistent_hashes(mutation, monkeypatch):
    plan, port, source, calls, query, saved, payload = specimen()
    original = payload["report"]["inventory"]
    changed = deepcopy(original)
    item = changed["sources"][0]
    if mutation == "file": item["files"][0]["source_file_hash"] = acceptance_digest("forged-original")
    elif mutation == "missing": item["files"].pop()
    elif mutation == "duplicate": item["files"][1] = deepcopy(item["files"][0])
    elif mutation == "pin": item["pin"]["content_hash"] = acceptance_digest("forged-source")
    elif mutation == "snippet": item["routes"][0]["snippet_hash"] = acceptance_digest("forged-snippet")
    elif mutation == "support": item["routes"][0]["supporting_spans"][0]["snippet_hash"] = acceptance_digest("forged-class")
    elif mutation == "span": item["routes"][0]["end_line"] = 10000
    else: item["files"][0]["byte_count"] = True
    changed["inventory_hash"] = acceptance_digest({key: value for key, value in changed.items() if key != "inventory_hash"})
    monkeypatch.setattr(port, "inspect", lambda *a, **k: pytest.fail("history re-parsed source"))
    with pytest.raises(ValueError): port.verify(plan, changed, require_access=lambda: None)
    port.verify(plan, original, require_access=lambda: None)


def service_specimen(*, plan=None, java=JAVA):
    plan, port, source, calls, query, saved, payload = specimen(plan=plan, java=java)
    state = {"prior": None, "archives": {}, "denied": False, "parser_calls": 0, "commits": 0}
    def current(access):
        if state["denied"]: raise SourceAccessDenied("source denied")
    def read_plan(project, ident):
        current(None)
        assert project == query.project_id and ident == query.run_plan_id
        return deepcopy(saved)
    auth = SimpleNamespace(scope=lambda project: SimpleNamespace(actor_id="reviewer"), require_current=current)
    locator = RunPlanLocatorApplicationService(SimpleNamespace(read=read_plan), auth, port)
    original = port.inspect
    def inspect(*args, **kwargs):
        state["parser_calls"] += 1
        return original(*args, **kwargs)
    port.inspect = inspect
    def put(project, value):
        digest = acceptance_digest(value)
        state["archives"][digest] = deepcopy(value)
        return digest, digest
    artifacts = SimpleNamespace(put=put, read=lambda project, ref, digest: deepcopy(state["archives"][digest]))
    def committed(request, *, actor_id, invocation_id, require_access):
        assert request == query and actor_id == "reviewer" and invocation_id == "command"
        require_access()
        return deepcopy(state["prior"])
    def record(request, value, ref, metadata, *, require_access):
        require_access()
        state["prior"] = deepcopy(metadata)
        state["commits"] += 1
        return deepcopy(metadata)
    repository = SimpleNamespace(committed=committed, record=record, read=lambda project, ident: {
        "metadata": deepcopy(state["prior"]), "artifact_ref": state["prior"]["artifact_hash"], "request": query.model_dump(mode="json")})
    return HttpLocatorRecordApplicationService(locator, artifacts, repository), query, state


def test_application_archive_replay_and_receipt_never_reparse(monkeypatch):
    service, query, state = service_specimen()
    metadata = service.record(query, invocation_id="command", recorded_at=datetime.now(timezone.utc).isoformat())
    assert state["parser_calls"] == state["commits"] == 1
    monkeypatch.setattr(service.locators.inventory, "inspect", lambda *a, **k: pytest.fail("history parsed"))
    assert service.record(query, invocation_id="command", recorded_at="ignored-on-replay") == metadata
    view = service.read(query.project_id, metadata["record_id"])
    receipt = service.receipt(query.project_id, metadata["record_id"])
    service.authorize_receipts(((query, receipt), (EnvironmentRecordQuery(project_id=query.project_id, record_id=metadata["record_id"]), receipt)))
    assert view["archive"]["report"]["summary"] == metadata["summary"]
    assert state["commits"] == state["parser_calls"] == 1
    state["denied"] = True
    with pytest.raises(SourceAccessDenied): service.read(query.project_id, metadata["record_id"])


def test_actual_json_roundtrip_preserves_archive_digest_and_original_byte_checks(monkeypatch):
    service, query, state = service_specimen()
    original_read = service.artifacts.read
    monkeypatch.setattr(service.artifacts, "read", lambda *args: json.loads(json.dumps(original_read(*args))))
    metadata = service.record(query, invocation_id="command", recorded_at=datetime.now(timezone.utc).isoformat())
    original = state["archives"][metadata["artifact_hash"]]
    normalized = json.loads(json.dumps(original))
    assert normalized != original and acceptance_digest(normalized) == acceptance_digest(original)
    monkeypatch.setattr(service.locators.inventory, "inspect", lambda *a, **k: pytest.fail("JSON history re-parsed"))
    assert service.read(query.project_id, metadata["record_id"])["archive"] == normalized
    assert state["parser_calls"] == state["commits"] == 1


def test_rehashed_tool_receipt_cannot_replace_the_independent_archive():
    service, query, state = service_specimen()
    metadata = service.record(query, invocation_id="command", recorded_at=datetime.now(timezone.utc).isoformat())
    receipt = service.receipt(query.project_id, metadata["record_id"])
    receipt["metadata"]["report_hash"] = acceptance_digest("fabricated-tool-result")
    with pytest.raises(RunPlanIntegrityError): service.authorize_receipts(((query, receipt),))


@pytest.mark.parametrize("field,value", [("source_bytes_verified", 1), ("execution_authorized", 0), ("passed_count", False)])
def test_history_receipt_rejects_boolean_number_coercion(field, value):
    service, query, state = service_specimen()
    metadata = service.record(query, invocation_id="command", recorded_at=datetime.now(timezone.utc).isoformat())
    receipt = service.receipt(query.project_id, metadata["record_id"])
    receipt["metadata"][field] = value
    with pytest.raises(RunPlanIntegrityError): service.authorize_receipts(((query, receipt),))


@pytest.mark.parametrize("tool", [LOCATOR_RECORD_TOOL, LOCATOR_RECORD_QUERY_TOOL])
def test_missing_resource_authorizer_fails_closed_and_broadcasts_are_redacted(tool):
    service, query, state = service_specimen()
    metadata = service.record(query, invocation_id="command", recorded_at=datetime.now(timezone.utc).isoformat())
    receipt = service.receipt(query.project_id, metadata["record_id"])
    request = query.model_dump(mode="json") if tool == LOCATOR_RECORD_TOOL else {"project_id": query.project_id, "record_id": metadata["record_id"]}
    command = ToolInvocation(id="command", tool_id=tool, status="completed", summary="Explicit locator specimen", input_payload=request,
        result=ToolResult(invocation_id="command", status="completed", summary="Explicit locator specimen", run_plan_locator_record=receipt))
    with pytest.raises(PlatformApplicationError): require_receipt_access(None, command)
    access = HttpLocatorRecordReceiptAccess(service)
    access.require_access(command)
    assert access.broadcast_view(command).result is None and access.broadcast_view(command).input_payload == {}
