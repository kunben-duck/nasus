"""Consent protocol specimens, not actual target dispatch or production ACL proof."""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.http_fixture_grant_receipts import HttpFixtureGrantReceiptAccess
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_receipt_access import require_receipt_access
from apps.api.app.application.quality_loop.environment_observation_records import EnvironmentRecordQuery
from apps.api.app.application.quality_loop.http_fixture_grants import HttpFixtureGrantApplicationService, HttpFixtureGrantRequest
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_grant import (
    GRANT_SCHEMA, GRANT_TOOL, GRANT_QUERY_TOOL, GRANT_SECONDS, GRANT_EVENT_FIELDS, grant_identity, grant_metadata,
)
from apps.api.app.domain.quality_loop.http_fixture_recipe import validate_recipe_archive
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_http_fixture_recipes import specimen


def grant_specimen():
    recipe_request, plan, recipe = specimen()
    plan["current_use"] = {"inputs_current": True}
    metadata = validate_recipe_archive(recipe, recipe_request.model_dump(mode="json"), plan)
    request = HttpFixtureGrantRequest(project_id=metadata["project_id"], recipe_id=metadata["record_id"],
        recipe_artifact_hash=metadata["artifact_hash"], attempt_id="attempt", operation="setup", timeout_ms=30000)
    state = {"role": "project_admin", "actor": "admin", "denied": False, "current": True,
        "source_scope": acceptance_digest("acl"), "grants": {}, "live_calls": [], "issues": 0, "expired": False}

    def current(_access):
        if state["denied"]:
            raise SourceAccessDenied("source revoked")
        if _access is not None and (_access.actor_id != state["actor"] or _access.fingerprint != state["source_scope"]):
            raise SourceAccessDenied("original source scope changed")

    def read_recipe(project, ident):
        current(None)
        assert (project, ident) == (request.project_id, request.recipe_id)
        return {"metadata": deepcopy(metadata), "archive": deepcopy(recipe), "historical_not_live": True}

    def read_plan(project, ident):
        current(None)
        assert (project, ident) == (recipe_request.project_id, recipe_request.run_plan_id)
        value = deepcopy(plan)
        value["current_use"]["inputs_current"] = state["current"]
        if "base_url" in state:
            value["artifact"]["plan"]["selection"]["environment"]["base_url"] = state["base_url"]
        return value

    auth = SimpleNamespace(scope=lambda project: SimpleNamespace(actor_id=state["actor"],
        effective_project_role=state["role"], fingerprint=state["source_scope"]), require_current=current)
    recipes = SimpleNamespace(read=read_recipe, authorization=auth,
        plans=SimpleNamespace(read=read_plan), verified_read_session=nullcontext)

    def issue(value, scope, source_scope_digest, *, actor_id, invocation_id, require_access):
        require_access()
        ident = grant_identity(invocation_id)
        if ident in state["grants"]:
            return grant_metadata(state["grants"][ident])
        issued = datetime.now(timezone.utc)
        payload = {"schema": GRANT_SCHEMA, "project_id": value.project_id, "record_id": ident,
            "invocation_id": invocation_id, "actor_id": actor_id, "recorded_at": issued.isoformat(),
            "expires_at": (issued + timedelta(seconds=GRANT_SECONDS)).isoformat(), "request": value.model_dump(mode="json"),
            "scope": asdict(scope), "source_scope_digest": source_scope_digest}
        require_access()
        state["grants"][ident] = payload
        state["issues"] += 1
        return grant_metadata(payload)

    def live(project, ident, **kwargs):
        state["live_calls"].append((project, ident, kwargs))
        if state["expired"]:
            raise PermissionError("original grant expired")
        assert state["grants"][ident]["actor_id"] == kwargs["actor_id"]

    repository = SimpleNamespace(issue=issue, read=lambda project, ident: deepcopy(state["grants"][ident]), require_live=live)
    service = HttpFixtureGrantApplicationService(recipes, repository)
    value = service.issue(request, invocation_id="grant-command")
    return service, request, state, value


def test_original_scoped_permission_is_neither_execution_nor_fixture_evidence():
    service, request, state, metadata = grant_specimen()
    assert metadata["scope_permission_recorded"] is True
    assert all(metadata[key] is False for key in ("execution_authorized", "canonical_execution_committed",
        "fixtures_verified", "business_coverage_verified", "baseline_restored"))
    assert all(type(metadata[key]) is int and metadata[key] == 0 for key in ("automated_count", "executed_on_target_count", "passed_count"))
    assert set(GRANT_EVENT_FIELDS) == {"project_id", "record_id", "status"}
    scope = HttpFixtureScope(**metadata["scope"])
    assert service.require_operation(request.project_id, metadata["record_id"], scope, "setup") == metadata
    assert len(state["live_calls"]) == 1
    assert not hasattr(service, "runner")


def test_combined_recipe_parent_is_reused_but_each_operation_checks_fresh_inputs(monkeypatch):
    service, request, state, metadata = grant_specimen()
    recipe_read, plan_read, calls = service.recipes.read, service.recipes.plans.read, []
    def combined(project, ident):
        recipe = recipe_read(project, ident)
        parent = plan_read(project, recipe["archive"]["request"]["run_plan_id"])
        calls.append(parent)
        return recipe, parent
    monkeypatch.setattr(service.recipes, "read_with_plan", combined, raising=False)
    monkeypatch.setattr(service.recipes, "read", lambda *args: pytest.fail("duplicate recipe read"))
    monkeypatch.setattr(service.recipes.plans, "read", lambda *args: pytest.fail("duplicate verified parent read"))
    scope = HttpFixtureScope(**metadata["scope"])
    assert service.require_operation(request.project_id, metadata["record_id"], scope, "setup") == metadata
    assert len(calls) == 1 and len(state["live_calls"]) == 1
    state["current"] = False
    with pytest.raises(RunPlanChanged): service.require_operation(request.project_id, metadata["record_id"], scope, "setup")
    assert len(calls) == 2 and len(state["live_calls"]) == 1
    state["denied"] = True
    with pytest.raises(SourceAccessDenied): service.read(request.project_id, metadata["record_id"])


@pytest.mark.parametrize("field", ["project_id", "run_plan_id", "artifact_hash"])
def test_combined_reader_cannot_substitute_a_different_original_plan(monkeypatch, field):
    service, request, state, metadata = grant_specimen()
    recipe = service.recipes.read(request.project_id, request.recipe_id)
    parent = service.recipes.plans.read(request.project_id, recipe["archive"]["request"]["run_plan_id"])
    parent["metadata"][field] = acceptance_digest("other") if field.endswith("hash") else "other"
    monkeypatch.setattr(service.recipes, "read_with_plan", lambda *args: (deepcopy(recipe), deepcopy(parent)), raising=False)
    with pytest.raises(RunPlanIntegrityError): service.read(request.project_id, metadata["record_id"])
    assert not state["live_calls"]


@pytest.mark.parametrize("failure", [None, "initial", "history", "current", "expiry", "final"])
def test_operation_read_scope_covers_all_gates_and_always_closes(monkeypatch, failure):
    service, request, state, metadata = grant_specimen()
    depth, gates = [0], []
    @contextmanager
    def verified():
        depth[0] += 1
        try:
            yield
        finally:
            depth[0] -= 1
    monkeypatch.setattr(service.recipes, "verified_read_session", verified)
    original_scope, original_read, original_plan, original_live = (
        service.authorization.scope, service.repository.read, service.recipes.plans.read, service.repository.require_live)
    def gate(name, action):
        def checked(*args, **kwargs):
            assert depth[0] > 0
            gates.append(name)
            if failure == name:
                raise RuntimeError("explicit " + name + " failure")
            return action(*args, **kwargs)
        return checked
    monkeypatch.setattr(service.authorization, "scope", gate("initial", original_scope))
    monkeypatch.setattr(service.repository, "read", gate("history", original_read))
    monkeypatch.setattr(service.recipes.plans, "read", gate("current", original_plan))
    def live(*args, **kwargs):
        result = original_live(*args, **kwargs)
        if failure == "final": state["denied"] = True
        return result
    monkeypatch.setattr(service.repository, "require_live", gate("expiry", live))
    scope = HttpFixtureScope(**metadata["scope"])
    if failure is None:
        assert service.require_operation(request.project_id, metadata["record_id"], scope, "setup") == metadata
    else:
        with pytest.raises(SourceAccessDenied if failure == "final" else RuntimeError):
            service.require_operation(request.project_id, metadata["record_id"], scope, "setup")
    assert depth[0] == 0 and gates
    assert state["issues"] == 1


@pytest.mark.parametrize("key,value", [("operation", "both"), ("timeout_ms", True), ("timeout_ms", 999),
    ("timeout_ms", 120001), ("attempt_id", "\n"), ("recipe_artifact_hash", "bad"), ("approved", True)])
def test_unbounded_or_combined_consent_request_rejected(key, value):
    _, request, _, _ = grant_specimen()
    data = request.model_dump(mode="json")
    data[key] = value
    with pytest.raises(ValueError): HttpFixtureGrantRequest.model_validate(data)


@pytest.mark.parametrize("key,value", [("schema", "bad"), ("record_id", "foreign"), ("actor_id", ""),
    ("recorded_at", "2026-10-12T00:00:00"), ("expires_at", "2099-10-12T00:00:00+00:00"),
    ("source_scope_digest", "bad"), ("execution_authorized", True), ("passed_count", 1)])
def test_rehashed_authority_or_unbounded_lifetime_rejected(key, value):
    _, _, state, metadata = grant_specimen()
    payload = deepcopy(state["grants"][metadata["record_id"]])
    payload[key] = value
    with pytest.raises(ValueError): grant_metadata(payload)


@pytest.mark.parametrize("change", ["cleanup", "actor", "source", "attempt", "timeout", "environment", "build", "inventory"])
def test_independent_operation_actor_and_complete_scope_cannot_be_reused(change):
    service, request, state, metadata = grant_specimen()
    scope = HttpFixtureScope(**metadata["scope"])
    operation = "setup"
    if change == "cleanup": operation = "cleanup"
    elif change == "actor": state["actor"] = "other-admin"
    elif change == "source": state["source_scope"] = acceptance_digest("different policy")
    elif change == "attempt": scope = replace(scope, attempt_id="other-attempt")
    elif change == "timeout": scope = replace(scope, timeout_ms=1000)
    elif change == "environment": scope = replace(scope, environment_id="other-env")
    elif change == "build": scope = replace(scope, artifact_hash=acceptance_digest("different build"))
    else: scope = replace(scope, inventory_hash=acceptance_digest("different inventory"))
    with pytest.raises(SourceAccessDenied): service.require_operation(request.project_id, metadata["record_id"], scope, operation)
    assert not state["live_calls"]


def test_expiry_retains_history_without_renewal_or_new_issue():
    service, request, state, metadata = grant_specimen()
    state["expired"] = True
    assert service.read(request.project_id, metadata["record_id"])["metadata"] == metadata
    with pytest.raises(PermissionError):
        service.require_operation(request.project_id, metadata["record_id"], HttpFixtureScope(**metadata["scope"]), "setup")
    assert service.issue(request, invocation_id="grant-command") == metadata and state["issues"] == 1


@pytest.mark.parametrize("key,value", [("environment_id", "foreign"), ("artifact_hash", acceptance_digest("different")),
    ("inventory_hash", acceptance_digest("foreign inventory")), ("case_id", "foreign-case"),
    ("parent_digest", acceptance_digest("other plan")), ("data_manifest_hash", acceptance_digest("other manifest"))])
def test_recomputed_grant_digest_cannot_rebind_original_private_recipe_or_target(key, value):
    service, request, state, metadata = grant_specimen()
    state["grants"][metadata["record_id"]]["scope"][key] = value
    with pytest.raises(RunPlanIntegrityError): service.read(request.project_id, metadata["record_id"])
    assert not state["live_calls"] and state["issues"] == 1


def test_source_revocation_blocks_history_and_live_permission_without_repository_live_check():
    service, request, state, metadata = grant_specimen()
    state["denied"] = True
    with pytest.raises(SourceAccessDenied): service.read(request.project_id, metadata["record_id"])
    with pytest.raises(SourceAccessDenied):
        service.require_operation(request.project_id, metadata["record_id"], HttpFixtureScope(**metadata["scope"]), "setup")
    assert not state["live_calls"]


@pytest.mark.parametrize("url", ["http://127.0.0.1:19876", "http://localhost:8080", "http://remote.invalid:8080", "https://127.0.0.1:8080"])
def test_other_target_declaration_cannot_obtain_this_owned_protocol_consent(url):
    service, request, state, metadata = grant_specimen()
    state["base_url"] = url
    with pytest.raises(RunPlanIntegrityError): service.issue(request, invocation_id="other-command")
    with pytest.raises(RunPlanIntegrityError):
        service.require_operation(request.project_id, metadata["record_id"], HttpFixtureScope(**metadata["scope"]), "setup")
    assert state["issues"] == 1 and not state["live_calls"]


def test_stale_inputs_block_new_setup_but_not_independent_original_cleanup_permission():
    service, request, state, metadata = grant_specimen()
    state["current"] = False
    assert service.read(request.project_id, metadata["record_id"])["metadata"] == metadata
    with pytest.raises(RunPlanChanged): service.issue(request, invocation_id="new-setup")
    with pytest.raises(RunPlanChanged):
        service.require_operation(request.project_id, metadata["record_id"], HttpFixtureScope(**metadata["scope"]), "setup")
    cleanup = request.model_copy(update={"operation": "cleanup"})
    permitted = service.issue(cleanup, invocation_id="separate-cleanup")
    assert permitted["operation"] == "cleanup" and permitted["scope_digest"] == metadata["scope_digest"]
    assert service.require_operation(request.project_id, permitted["record_id"], HttpFixtureScope(**permitted["scope"]), "cleanup") == permitted
    assert state["issues"] == 2


@pytest.mark.parametrize("role", ["qa_lead", "tester", "viewer"])
def test_reviewer_or_lower_has_no_operation_consent_authority(role):
    service, request, state, metadata = grant_specimen()
    state["role"] = role
    with pytest.raises(SourceAccessDenied): service.read(request.project_id, metadata["record_id"])
    with pytest.raises(SourceAccessDenied): service.issue(request, invocation_id="other")


@pytest.mark.parametrize("key,value", [("scope_permission_recorded", 1), ("execution_authorized", 0), ("passed_count", False)])
def test_receipt_rehash_cannot_promote_consent_to_live_authority(key, value):
    service, request, _, metadata = grant_specimen()
    receipt = service.read(request.project_id, metadata["record_id"])
    service.authorize_receipts(((request, receipt),))
    receipt["metadata"][key] = value
    with pytest.raises(RunPlanIntegrityError): service.authorize_receipts(((request, receipt),))


@pytest.mark.parametrize("tool", [GRANT_TOOL, GRANT_QUERY_TOOL])
def test_receipt_access_required_and_broadcast_has_no_scope_or_consent(tool):
    service, request, state, metadata = grant_specimen()
    payload = request.model_dump(mode="json") if tool == GRANT_TOOL else {"project_id": request.project_id, "record_id": metadata["record_id"]}
    invocation = ToolInvocation(id="grant-command", tool_id=tool, status="completed", summary="Private scope",
        input_payload=payload, result=ToolResult(invocation_id="grant-command", status="completed", summary="Private grant",
            http_fixture_grant=service.read(request.project_id, metadata["record_id"])))
    with pytest.raises(PlatformApplicationError): require_receipt_access(None, invocation)
    policy = HttpFixtureGrantReceiptAccess(service)
    policy.require_access(invocation)
    broadcast = policy.broadcast_view(invocation)
    assert broadcast.result is None and broadcast.input_payload == {} and "inventory" not in broadcast.summary
    state["denied"] = True
    with pytest.raises(PlatformApplicationError): policy.require_access(invocation)
