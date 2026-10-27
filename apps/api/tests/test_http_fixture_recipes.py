"""Domain/application specimens; not original target execution or production ACL proof."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.http_fixture_recipe_receipts import HttpFixtureRecipeReceiptAccess
from apps.api.app.application.platform.tool_handlers.http_fixture_recipes import HttpFixtureRecipeToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_receipt_access import require_receipt_access
from apps.api.app.application.platform.tool_test_design_scope import ToolTestDesignScopeObservationApplicationService
from apps.api.app.application.quality_loop.environment_observation_records import EnvironmentRecordQuery
from apps.api.app.application.quality_loop.http_fixture_recipes import HttpFixtureRecipeApplicationService, HttpFixtureRecipeRequest
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_recipe import (
    RECIPE_SCHEMA, RECIPE_TOOL, RECIPE_QUERY_TOOL, RECIPE_FALSE_AUTHORITIES, RECIPE_ZERO_COUNTS, RECIPE_EVENT_FIELDS,
    recipe_identity, recipe_metadata, validate_recipe_archive,
)
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.storage.http_fixture_recipe_artifacts import HttpFixtureRecipeArtifacts
from apps.api.app.infrastructure.persistence.http_fixture_recipe_repository import HttpFixtureRecipeRepository
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceManifestRecord
from apps.api.app.infrastructure.persistence.run_plan_models import RunPlanRecord
from apps.api.app.infrastructure.persistence.run_plan_repository import RunPlanRepository
from apps.api.tests.test_http_fixture_journal_access import saved_inputs


def specimen():
    _, _, manifest, saved = saved_inputs()
    request = HttpFixtureRecipeRequest(project_id=saved["metadata"]["project_id"], run_plan_id=saved["metadata"]["run_plan_id"],
        run_plan_artifact_hash=saved["metadata"]["artifact_hash"], manifest=manifest)
    plan = saved["artifact"]["plan"]
    payload = {"schema": RECIPE_SCHEMA, "project_id": request.project_id, "record_id": recipe_identity("command"),
        "invocation_id": "command", "actor_id": "reviewer", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "request": request.model_dump(mode="json"), "parents": {"plan_digest": plan["plan_digest"], **{key: plan["source_pin"][key]
            for key in ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")}},
        "fixture_digest": acceptance_digest(plan["selection"]["fixtures"][0])}
    return request, saved, payload


def test_complete_recipe_binds_original_declaration_and_cannot_grant_execution():
    request, saved, payload = specimen()
    original = deepcopy(saved)
    metadata = validate_recipe_archive(payload, request.model_dump(mode="json"), saved)
    assert metadata["data_manifest_hash"] == acceptance_digest(request.manifest)
    assert metadata["recipe_bytes_verified"] is metadata["historical_not_live"] is True
    assert all(metadata[key] is False for key in RECIPE_FALSE_AUTHORITIES)
    assert all(type(metadata[key]) is int and metadata[key] == 0 for key in RECIPE_ZERO_COUNTS)
    assert saved == original and "manifest" not in metadata
    assert validate_recipe_archive(json.loads(json.dumps(payload)), request.model_dump(mode="json"), saved) == metadata


def test_fact_broadcast_is_opaque_without_case_identity_or_private_definition_hash():
    assert set(RECIPE_EVENT_FIELDS) == {"project_id", "record_id", "run_plan_id", "status"}


@pytest.mark.parametrize("key,value", [("schema", "wrong"), ("record_id", "foreign"), ("project_id", "foreign"),
    ("actor_id", ""), ("recorded_at", None), ("recorded_at", "2026-10-12T00:00:00"), ("fixture_digest", "bad"),
    ("execution_authorized", True), ("passed_count", 1)])
def test_archive_scope_and_additional_authority_are_rejected(key, value):
    request, saved, payload = specimen()
    payload[key] = value
    with pytest.raises(ValueError): validate_recipe_archive(payload, request.model_dump(mode="json"), saved)


@pytest.mark.parametrize("key", ["project_id", "run_plan_id", "run_plan_artifact_hash", "fixture_digest",
    "image_revision_id", "plan_digest", "manifest_hash", "oracle", "setup", "cleanup", "resource"])
def test_self_consistent_new_hashes_cannot_rebind_original_input(key):
    request, saved, payload = specimen()
    if key in {"project_id", "run_plan_id", "run_plan_artifact_hash"}:
        payload["request"][key] = acceptance_digest("another") if key.endswith("hash") else "another"
    elif key == "fixture_digest": payload[key] = acceptance_digest("another")
    elif key in {"image_revision_id", "plan_digest", "manifest_hash"}:
        payload["parents"][key] = "another" if key.endswith("id") else acceptance_digest("another")
    elif key == "oracle": payload["request"]["manifest"]["setup_steps"][-1]["value_json"] = '"OTHER"'
    elif key in {"setup", "cleanup"}: payload["request"]["manifest"][key] = ["Different original declaration"]
    else: payload["request"]["manifest"]["cleanup_groups"]["session"][0]["path"] = "/sessions/foreign/close"
    with pytest.raises(ValueError): validate_recipe_archive(payload, payload["request"], saved)


def test_valid_plan_wrapped_in_another_project_is_rejected():
    request, saved, payload = specimen()
    saved["artifact"]["project_id"] = "foreign"
    digest = acceptance_digest(saved["artifact"])
    saved["metadata"]["artifact_hash"] = digest
    payload["request"]["run_plan_artifact_hash"] = digest
    with pytest.raises(RunPlanIntegrityError): validate_recipe_archive(payload, payload["request"], saved)


def service_specimen():
    request, saved, _ = specimen()
    state = {"archives": {}, "prior": None, "commits": 0, "writes": 0, "denied": False, "role": "qa_lead"}
    def current(_access):
        if state["denied"]: raise SourceAccessDenied("source revoked")
    def read_plan(project, ident):
        current(None)
        assert (project, ident) == (request.project_id, request.run_plan_id)
        return deepcopy(saved)
    auth = SimpleNamespace(scope=lambda project: SimpleNamespace(actor_id="reviewer", effective_project_role=state["role"]),
        require_current=current)
    plans = SimpleNamespace(read=read_plan, authorization=auth)
    def put(project, payload):
        state["writes"] += 1
        digest = acceptance_digest(payload)
        state["archives"][digest] = deepcopy(payload)
        return "s3://private/" + digest, digest
    artifacts = SimpleNamespace(put=put, read=lambda project, ref, digest: deepcopy(state["archives"][digest]))
    def committed(value, *, actor_id, invocation_id, require_access):
        assert value == request and actor_id == "reviewer" and invocation_id == "command"
        require_access()
        return deepcopy(state["prior"])
    def record(value, payload, ref, metadata, *, require_access):
        require_access()
        state["prior"], state["ref"] = deepcopy(metadata), ref
        state["commits"] += 1
        return deepcopy(metadata)
    repository = SimpleNamespace(committed=committed, record=record, read=lambda project, ident: {
        "metadata": deepcopy(state["prior"]), "artifact_ref": state["ref"], "request": request.model_dump(mode="json")})
    return HttpFixtureRecipeApplicationService(plans, artifacts, repository), request, state


def registered_specimen():
    service, request, state = service_specimen()
    metadata = service.record(request, invocation_id="command", recorded_at=datetime.now(timezone.utc).isoformat())
    return service, request, state, metadata


def test_replay_restores_original_archive_without_second_write_or_dispatch():
    service, request, state, metadata = registered_specimen()
    assert service.record(request, invocation_id="command", recorded_at="ignored historical time") == metadata
    assert service.read(request.project_id, metadata["record_id"])["archive"]["request"]["manifest"] == request.manifest
    receipt = service.receipt(request.project_id, metadata["record_id"])
    service.authorize_receipts(((request, receipt), (EnvironmentRecordQuery(project_id=request.project_id,
        record_id=metadata["record_id"]), receipt)))
    assert state["writes"] == state["commits"] == 1
    assert not hasattr(service, "runner")


def test_combined_read_returns_the_exact_verified_plan_without_another_traversal(monkeypatch):
    service, request, state, metadata = registered_specimen()
    read, calls = service.plans.read, []
    def observed(*args):
        value = read(*args)
        calls.append(value)
        return value
    monkeypatch.setattr(service.plans, "read", observed)
    view, parent = service.read_with_plan(request.project_id, metadata["record_id"])
    assert len(calls) == 1 and parent is calls[0]
    assert view["metadata"] == metadata and view["archive"]["request"] == request.model_dump(mode="json")
    parent["metadata"]["artifact_hash"] = acceptance_digest("consumer mutation")
    next_view, next_parent = service.read_with_plan(request.project_id, metadata["record_id"])
    assert len(calls) == 2 and next_parent["metadata"]["artifact_hash"] == request.run_plan_artifact_hash
    assert next_view == view and state["writes"] == state["commits"] == 1
    state["denied"] = True
    with pytest.raises(SourceAccessDenied): service.read_with_plan(request.project_id, metadata["record_id"])


def test_combined_read_cannot_return_a_parent_for_a_damaged_private_recipe():
    service, request, state, metadata = registered_specimen()
    state["archives"][metadata["artifact_hash"]]["fixture_digest"] = acceptance_digest("damaged")
    with pytest.raises(RunPlanIntegrityError): service.read_with_plan(request.project_id, metadata["record_id"])


@pytest.mark.parametrize("role", ["viewer", "tester", "unknown"])
def test_non_reviewers_cannot_register_or_read_original_recipes(role):
    service, request, state, metadata = registered_specimen()
    state["role"] = role
    with pytest.raises(SourceAccessDenied): service.record(request, invocation_id="command", recorded_at="ignored")
    with pytest.raises(SourceAccessDenied): service.read(request.project_id, metadata["record_id"])
    assert state["writes"] == state["commits"] == 1


def test_revoked_source_is_checked_before_private_bytes(monkeypatch):
    service, request, state, metadata = registered_specimen()
    state["denied"] = True
    monkeypatch.setattr(service.artifacts, "read", lambda *a: pytest.fail("read before current source access"))
    with pytest.raises(SourceAccessDenied): service.read(request.project_id, metadata["record_id"])


def test_revocation_after_archive_does_not_commit_recipe(monkeypatch):
    service, request, state = service_specimen()
    put = service.artifacts.put
    def revoke(*args):
        result = put(*args)
        state["denied"] = True
        return result
    monkeypatch.setattr(service.artifacts, "put", revoke)
    with pytest.raises(SourceAccessDenied): service.record(request, invocation_id="command", recorded_at=datetime.now(timezone.utc).isoformat())
    assert state["writes"] == 1 and state["commits"] == 0 and state["prior"] is None


@pytest.mark.parametrize("key,value", [("recipe_bytes_verified", 1), ("execution_authorized", 0), ("passed_count", False),
    ("data_manifest_hash", acceptance_digest("forged"))])
def test_rehashed_metadata_or_receipt_cannot_replace_original_archive(key, value):
    service, request, state, metadata = registered_specimen()
    receipt = service.receipt(request.project_id, metadata["record_id"])
    receipt["metadata"][key] = value
    with pytest.raises(RunPlanIntegrityError): service.authorize_receipts(((request, receipt),))
    state["prior"][key] = value
    with pytest.raises(RunPlanIntegrityError): service.read(request.project_id, metadata["record_id"])


@pytest.mark.parametrize("tool", [RECIPE_TOOL, RECIPE_QUERY_TOOL])
def test_resource_authorizer_is_required_and_sse_does_not_expose_recipe(tool):
    service, request, state, metadata = registered_specimen()
    payload = request.model_dump(mode="json") if tool == RECIPE_TOOL else {"project_id": request.project_id, "record_id": metadata["record_id"]}
    command = ToolInvocation(id="command", tool_id=tool, status="completed", summary="Private definition", input_payload=payload,
        result=ToolResult(invocation_id="command", status="completed", summary="Private recipe",
            http_fixture_recipe=service.receipt(request.project_id, metadata["record_id"])))
    with pytest.raises(PlatformApplicationError): require_receipt_access(None, command)
    policy = HttpFixtureRecipeReceiptAccess(service)
    policy.require_access(command)
    broadcast = policy.broadcast_view(command)
    assert broadcast.result is None and broadcast.input_payload == {} and "manifest" not in broadcast.summary


def test_agent_query_reauthorizes_original_receipt_and_rejects_another_project():
    service, request, state, metadata = registered_specimen()
    receipt = service.receipt(request.project_id, metadata["record_id"])
    command = ToolInvocation(id="query", tool_id=RECIPE_QUERY_TOOL, status="completed", summary="Original recipe",
        input_payload={"project_id": request.project_id, "record_id": metadata["record_id"]},
        result=ToolResult(invocation_id="query", status="completed", summary="Original recipe", http_fixture_recipe=receipt))
    observer = ToolTestDesignScopeObservationApplicationService(SimpleNamespace(get_tool_invocation=lambda _: command), None,
        SimpleNamespace(require_invocation_project_scope=lambda _: None), http_fixture_recipes=service)
    assert observer.describe("query", request.project_id) == receipt
    with pytest.raises(PlatformApplicationError): observer.describe("query", "foreign")
    state["denied"] = True
    with pytest.raises(SourceAccessDenied): observer.describe("query", request.project_id)


def test_canonical_storage_rejects_local_fallback_without_reading_or_writing():
    storage = SimpleNamespace(config=SimpleNamespace(s3_enabled=False),
        put_bytes=lambda *a, **k: pytest.fail("local write"), get_bytes=lambda *a, **k: pytest.fail("local read"))
    artifacts = HttpFixtureRecipeArtifacts(storage)
    with pytest.raises(RunPlanIntegrityError): artifacts.put("project", {})
    with pytest.raises(RunPlanIntegrityError): artifacts.read("project", "s3://private/entry", acceptance_digest("entry"))
    storage.config.s3_enabled = True
    with pytest.raises(RunPlanIntegrityError): artifacts.read("project", "local-object://private/entry", acceptance_digest("entry"))


def test_repository_resolves_original_source_hashes_without_rewriting_plan_metadata(monkeypatch):
    request, saved, _ = specimen()
    pin = saved["artifact"]["plan"]["source_pin"]
    original = {"image_revision_id": pin["image_revision_id"], "manifest_id": pin["manifest_id"],
        "plan_digest": saved["artifact"]["plan"]["plan_digest"]}
    plan = SimpleNamespace(project_id=request.project_id, artifact_hash=request.run_plan_artifact_hash)
    image = SimpleNamespace(project_id=request.project_id, manifest_id=pin["manifest_id"], artifact_hash=pin["image_artifact_hash"])
    manifest = SimpleNamespace(project_id=request.project_id, content_hash=pin["manifest_hash"])
    rows = {RunPlanRecord: plan, ImageRevisionRecord: image, SourceManifestRecord: manifest}
    monkeypatch.setattr(RunPlanRepository, "_verify", lambda session, row: deepcopy(original))
    session = SimpleNamespace(get=lambda model, key: rows.get(model))
    assert HttpFixtureRecipeRepository._parents(session, request) == {**original,
        "image_artifact_hash": pin["image_artifact_hash"], "manifest_hash": pin["manifest_hash"]}
    assert set(original) == {"image_revision_id", "manifest_id", "plan_digest"}
    image.manifest_id = "another-original-manifest"
    with pytest.raises(RunPlanIntegrityError): HttpFixtureRecipeRepository._parents(session, request)
    image.manifest_id = pin["manifest_id"]
    rows[SourceManifestRecord] = None
    with pytest.raises(RunPlanIntegrityError): HttpFixtureRecipeRepository._parents(session, request)


def test_handler_returns_metadata_only_and_failures_do_not_expose_input():
    service, request, state = service_specimen()
    events = []
    async def emit(*args): events.append(args)
    handler = HttpFixtureRecipeToolHandler(service, SimpleNamespace(emit_tool_status=emit),
        SimpleNamespace(require_invocation_project_scope=lambda _: None))
    command = ToolInvocation(id="command", tool_id=RECIPE_TOOL, status="running", input_payload=request.model_dump(mode="json"), summary="Registration")
    asyncio.run(handler.handle(command))
    result = events[-1][-1]
    assert result.status == "completed" and '"manifest":' not in result.model_dump_json() and "setup_steps" not in result.model_dump_json()
    assert result.http_fixture_recipe["metadata"]["execution_authorized"] is False
    state["denied"] = True
    asyncio.run(handler.handle(command))
    assert events[-1][-1].status == "failed" and events[-1][-1].http_fixture_recipe is None
