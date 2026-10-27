"""Explicit application/inspector protocol specimens, not real Docker or PG evidence."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.http_fixture_grants import HttpFixtureGrantApplicationService, HttpFixtureGrantRequest
from apps.api.app.application.quality_loop.http_fixture_journal_access import NativeSavedRunPlanHttpFixtureAccess, SavedRunPlanHttpFixtureAccess
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.application.quality_loop.run_plan_observation_archives import RunPlanObservationArchiveParent
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_SCHEMA, environment_record_metadata, record_identity
from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_SCHEMA, NATIVE_GRANT_SCHEMA, GRANT_SECONDS, grant_identity, grant_metadata
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_PARENT_FIELDS, RECIPE_SCHEMA, recipe_identity, validate_recipe_archive
from apps.api.app.domain.quality_loop.http_fixture_target import native_fixture_environment
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from apps.api.app.infrastructure.persistence.http_fixture_native_grant_models import HttpFixtureNativeGrantRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.environment_observation_models import EnvironmentObservationRecord
from apps.api.app.infrastructure.persistence.environment_observation_repository import EnvironmentObservationRepository
from apps.api.app.infrastructure.persistence.http_fixture_grant_repository import HttpFixtureGrantRepository
from apps.api.tests.test_http_fixture_journal_access import saved_inputs
from apps.api.tests.test_owned_target_environment import Commands, spec


@pytest.fixture
def native_grant(spec):
    _, _, manifest, saved = saved_inputs()
    owned = replace(spec, project_id=saved["metadata"]["project_id"])
    plan = saved["artifact"]["plan"]
    selection = plan["selection"]
    selection["environment"].update(kind="local", environment_id=owned.environment_id, inventory_hash=owned.digest)
    plan["plan_digest"] = acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"})
    saved["metadata"].update(plan_digest=plan["plan_digest"], artifact_hash=acceptance_digest(saved["artifact"]))
    saved["current_use"] = {"inputs_current": True}
    commands = Commands(owned)
    commands.body = selection["target_build"]["artifact_hash"][7:].encode() + b"  /app/target.jar\n"
    observed = OwnedTargetEnvironmentInspector(owned, command=commands).inspect(selection["target_build"]["artifact_hash"], require_work=lambda: None)
    now = datetime.now(timezone.utc).isoformat()
    environment = {"schema": ENVIRONMENT_RECORD_SCHEMA, "project_id": plan["project_id"],
        "record_id": record_identity("environment-command"), "invocation_id": "environment-command", "actor_id": "admin",
        "recorded_at": now, "request": {"project_id": plan["project_id"], "run_plan_id": saved["metadata"]["run_plan_id"],
            "run_plan_artifact_hash": saved["metadata"]["artifact_hash"], "build_binding_id": "protocol-binding",
            "build_binding_artifact_hash": acceptance_digest("protocol-binding")},
        "parents": {"plan_digest": plan["plan_digest"], **{key: plan["source_pin"][key] for key in ("image_revision_id", "manifest_id")},
            "environment_id": owned.environment_id, "operator_policy_digest": owned.digest,
            "target_artifact_hash": selection["target_build"]["artifact_hash"]},
        "observation": {"inventory": observed.inventory, "inventory_hash": observed.inventory_hash, "observed_at": observed.observed_at}}
    view = {"archive": environment, "metadata": environment_record_metadata(environment), "historical_not_live": True}
    recipe = {"schema": RECIPE_SCHEMA, "project_id": plan["project_id"], "record_id": recipe_identity("recipe-command"),
        "invocation_id": "recipe-command", "actor_id": "admin", "recorded_at": now,
        "request": {"project_id": plan["project_id"], "run_plan_id": saved["metadata"]["run_plan_id"],
            "run_plan_artifact_hash": saved["metadata"]["artifact_hash"], "manifest": manifest},
        "parents": {"plan_digest": plan["plan_digest"], **{key: plan["source_pin"][key] for key in RECIPE_PARENT_FIELDS if key != "plan_digest"}},
        "fixture_digest": acceptance_digest(selection["fixtures"][0])}
    recipe_metadata = validate_recipe_archive(recipe, recipe["request"], saved)
    state = {"revoked": False, "issued": {}, "reads": 0, "live": 0}
    access = SimpleNamespace(actor_id="admin", effective_project_role="project_admin", fingerprint=acceptance_digest("source-acl"))
    def current(_):
        if state["revoked"]:
            raise SourceAccessDenied("explicit source revocation")
    def environment_read(project, ident):
        current(access)
        assert (project, ident) == (plan["project_id"], environment["record_id"])
        state["reads"] += 1
        return deepcopy(view)
    records = SimpleNamespace(read=environment_read)
    plans = SimpleNamespace(read=lambda *args: deepcopy(saved), verified_read_session=nullcontext)
    recipes = SimpleNamespace(plans=plans, authorization=SimpleNamespace(scope=lambda _: access, require_current=current),
        read=lambda *args: {"archive": deepcopy(recipe), "metadata": deepcopy(recipe_metadata)}, verified_read_session=nullcontext)
    def issue(request, scope, source_scope_digest, *, actor_id, invocation_id, require_access, native_environment=None):
        require_access()
        issued = datetime.now(timezone.utc)
        payload = {"schema": NATIVE_GRANT_SCHEMA if native_environment else GRANT_SCHEMA, "project_id": request.project_id,
            "record_id": grant_identity(invocation_id), "invocation_id": invocation_id, "actor_id": actor_id,
            "recorded_at": issued.isoformat(), "expires_at": (issued + timedelta(seconds=GRANT_SECONDS)).isoformat(),
            "request": request.model_dump(mode="json"), "scope": asdict(scope), "source_scope_digest": source_scope_digest}
        if native_environment:
            payload["native_environment"] = deepcopy(native_environment)
        state["issued"][payload["record_id"]] = payload
        return grant_metadata(payload)
    def live(*args, **kwargs):
        state["live"] += 1
        current(access)
    repository = SimpleNamespace(issue=issue, read=lambda project, ident: deepcopy(state["issued"][ident]), require_live=live)
    service = HttpFixtureGrantApplicationService(recipes, repository, environment_records=records)
    request = HttpFixtureGrantRequest(project_id=plan["project_id"], recipe_id=recipe_metadata["record_id"],
        recipe_artifact_hash=recipe_metadata["artifact_hash"], attempt_id="native-attempt", operation="setup", timeout_ms=10000,
        policy_revision=NATIVE_GRANT_SCHEMA, environment_record_id=view["metadata"]["record_id"],
        environment_record_artifact_hash=view["metadata"]["artifact_hash"])
    return SimpleNamespace(service=service, request=request, saved=saved, manifest=manifest, environment=view,
        plans=plans, records=records, commands=commands, state=state)


def test_native_consent_and_journal_use_the_instance_hash_not_the_operator_policy(native_grant):
    v = native_grant
    old = deepcopy((v.saved, v.environment, v.manifest))
    calls = len(v.commands.calls)
    value = v.service.issue(v.request, invocation_id="native-consent-command")
    scope = HttpFixtureScope(**value["scope"])
    assert value["schema"] == NATIVE_GRANT_SCHEMA
    assert scope.inventory_hash == v.environment["metadata"]["inventory_hash"]
    assert scope.inventory_hash != value["native_environment"]["operator_policy_digest"]
    assert v.service.require_operation(scope.project_id, value["record_id"], scope, "setup") == value
    parent = RunPlanObservationArchiveParent(project_id=scope.project_id, run_plan_id=v.saved["metadata"]["run_plan_id"],
        run_plan_artifact_hash=v.saved["metadata"]["artifact_hash"], plan_digest=scope.parent_digest)
    native = NativeSavedRunPlanHttpFixtureAccess(v.plans, parent, v.manifest, v.records, value["native_environment"])
    assert native.require_scope(scope) == parent.model_dump(mode="json")
    assert native.command(scope, "setup").metadata["fixture_scope"]["inventory_hash"] == scope.inventory_hash
    assert native.command(scope, "cleanup:session", setup_receipt={"bindings": [{"binding_id": "session", "value": "original_id"}]}).steps[0]["path"] == "/sessions/original_id/close"
    with pytest.raises(HttpFixtureInvalid): SavedRunPlanHttpFixtureAccess(v.plans, parent, v.manifest).require_scope(scope)
    assert len(v.commands.calls) == calls and (v.saved, v.environment, v.manifest) == old
    assert all(value[key] is False for key in ("execution_authorized", "canonical_execution_committed", "fixtures_verified", "business_coverage_verified"))


def native_journal_access(v):
    value = v.service.issue(v.request, invocation_id="parent-port-consent")
    scope = HttpFixtureScope(**value["scope"])
    parent = RunPlanObservationArchiveParent(project_id=scope.project_id,
        run_plan_id=v.saved["metadata"]["run_plan_id"], run_plan_artifact_hash=v.saved["metadata"]["artifact_hash"],
        plan_digest=scope.parent_digest)
    return NativeSavedRunPlanHttpFixtureAccess(v.plans, parent, v.manifest, v.records, value["native_environment"]), scope, parent


def test_native_journal_reuses_only_the_complete_verified_environment_parent(native_grant, monkeypatch):
    v = native_grant
    access, scope, parent = native_journal_access(v)
    old = deepcopy((v.saved, v.environment, v.manifest))
    calls = []
    def read_with_plan(project, record):
        calls.append((project, record))
        if v.state["revoked"]:
            raise SourceAccessDenied("explicit current revocation")
        return deepcopy(v.environment), deepcopy(v.saved)
    monkeypatch.setattr(v.records, "read_with_plan", read_with_plan, raising=False)
    monkeypatch.setattr(v.plans, "read", lambda *_: pytest.fail("verified parent must not be expanded a second time"))
    monkeypatch.setattr(v.records, "read", lambda *_: pytest.fail("same environment must not be expanded twice"))
    assert access.require_scope(scope) == parent.model_dump(mode="json")
    assert len(calls) == 1 and (v.saved, v.environment, v.manifest) == old
    assert access.require_scope(scope) == parent.model_dump(mode="json") and len(calls) == 2
    v.state["revoked"] = True
    with pytest.raises(SourceAccessDenied):
        access.require_scope(scope)
    assert len(calls) == 3 and v.state["live"] == 0


@pytest.mark.parametrize("fault", ["parent-project", "parent-id", "parent-hash", "parent-body", "environment-pin",
    "missing-environment", "non-dict-parent", "malformed-pair"])
def test_native_journal_parent_port_cannot_substitute_original_scope(native_grant, monkeypatch, fault):
    v = native_grant
    access, scope, _ = native_journal_access(v)
    view, plan = deepcopy(v.environment), deepcopy(v.saved)
    if fault == "parent-project": plan["metadata"]["project_id"] = "different"
    elif fault == "parent-id": plan["metadata"]["run_plan_id"] = "different"
    elif fault == "parent-hash": plan["metadata"]["artifact_hash"] = acceptance_digest("different")
    elif fault == "parent-body": plan["artifact"]["plan"]["selection"]["environment"]["base_url"] = "https://outside.invalid"
    elif fault == "environment-pin": view["metadata"]["inventory_hash"] = acceptance_digest("different")
    elif fault == "missing-environment": view = None
    elif fault == "non-dict-parent": plan = []
    pair = (view,) if fault == "malformed-pair" else (view, plan)
    monkeypatch.setattr(v.records, "read_with_plan", lambda *_: pair, raising=False)
    monkeypatch.setattr(v.records, "read", lambda *_: pytest.fail("broken paired port must not fall back"))
    with pytest.raises(HttpFixtureInvalid):
        access.require_scope(scope)


@pytest.mark.parametrize("error", [SourceAccessDenied("private original source fault"), RuntimeError("private storage fault")])
def test_native_journal_parent_port_fault_is_not_replaced_by_another_reader(native_grant, monkeypatch, error):
    v = native_grant
    access, scope, _ = native_journal_access(v)
    def failed(*args):
        raise error
    monkeypatch.setattr(v.records, "read_with_plan", failed, raising=False)
    monkeypatch.setattr(v.plans, "read", lambda *_: pytest.fail("fault cannot trigger another parent read"))
    monkeypatch.setattr(v.records, "read", lambda *_: pytest.fail("fault cannot trigger legacy fallback"))
    with pytest.raises(type(error)) as raised:
        access.require_scope(scope)
    assert raised.value is error and v.state["live"] == 0


@pytest.mark.parametrize("field", ["environment_record_id", "environment_record_artifact_hash", "policy_revision"])
def test_native_consent_requires_explicit_complete_versioned_input(native_grant, field):
    payload = native_grant.request.model_dump(mode="json")
    payload.pop(field)
    with pytest.raises(ValueError): HttpFixtureGrantRequest.model_validate(payload)


def test_legacy_wire_and_payload_are_unchanged_and_never_read_native_inventory(native_grant):
    v = native_grant
    payload = {key: value for key, value in v.request.model_dump(mode="json").items()
        if key not in {"environment_record_id", "environment_record_artifact_hash", "policy_revision"}}
    request = HttpFixtureGrantRequest.model_validate(payload)
    assert request.model_dump(mode="json") == payload
    value = v.service.issue(request, invocation_id="legacy-command")
    assert value["schema"] == GRANT_SCHEMA and "native_environment" not in value
    assert value["scope"]["inventory_hash"] == v.saved["artifact"]["plan"]["selection"]["environment"]["inventory_hash"]
    assert v.state["reads"] == 0


@pytest.mark.parametrize("change", ["policy", "inventory", "project", "plan", "image", "manifest", "build", "authority", "extra"])
def test_self_consistent_environment_cannot_rebind_original_fixture_parents(native_grant, change):
    v = native_grant
    view = deepcopy(v.environment)
    if change == "policy": view["archive"]["parents"]["operator_policy_digest"] = acceptance_digest("other policy")
    elif change == "inventory": view["archive"]["observation"]["inventory_hash"] = acceptance_digest("other instance")
    elif change == "project": view["archive"]["project_id"] = "other-project"
    elif change == "plan": view["archive"]["request"]["run_plan_id"] = "other-plan"
    elif change in {"image", "manifest"}: view["archive"]["parents"][change + "_revision_id" if change == "image" else "manifest_id"] = "other"
    elif change == "build": view["archive"]["parents"]["target_artifact_hash"] = acceptance_digest("other jar")
    elif change == "authority": view["metadata"]["durable_native_observation_verified"] = 1
    else: view["metadata"]["execution_permitted"] = True
    with pytest.raises(RunPlanIntegrityError): native_fixture_environment(v.saved, v.manifest, view)


@pytest.mark.parametrize("change", ["schema", "request-version", "record", "archive", "inventory", "policy", "extra"])
def test_native_grant_bytes_cannot_downgrade_or_omit_original_inventory(native_grant, change):
    v = native_grant
    value = v.service.issue(v.request, invocation_id="native-consent-command")
    payload = deepcopy(v.state["issued"][value["record_id"]])
    if change == "schema": payload["schema"] = GRANT_SCHEMA
    elif change == "request-version": payload["request"].pop("policy_revision")
    elif change == "record": payload["native_environment"]["record_id"] = "other"
    elif change == "archive": payload["native_environment"]["artifact_hash"] = acceptance_digest("other")
    elif change == "inventory": payload["native_environment"]["inventory_hash"] = acceptance_digest("other")
    elif change == "policy": payload["native_environment"]["operator_policy_digest"] = "invalid"
    else: payload["native_environment"]["execution_authorized"] = True
    with pytest.raises(RunPlanIntegrityError): grant_metadata(payload)


def test_native_reader_missing_or_revoked_does_not_fall_back_to_a_policy_scope(native_grant):
    v = native_grant
    v.service.environment_records = None
    with pytest.raises(RunPlanIntegrityError): v.service.issue(v.request, invocation_id="missing")
    assert not v.state["issued"]
    v.service.environment_records = v.records
    v.state["revoked"] = True
    with pytest.raises(SourceAccessDenied): v.service.issue(v.request, invocation_id="revoked")
    assert not v.state["issued"]


@pytest.mark.parametrize("mutation", [None, "missing", "project", "grant", "environment", "inventory", "policy", "extra", "downgrade"])
def test_registered_native_grant_requires_its_original_append_only_parent_binding(native_grant, monkeypatch, mutation):
    v = native_grant
    metadata = v.service.issue(v.request, invocation_id="original-native-command")
    expected = HttpFixtureGrantRepository._native_binding_value(metadata)
    payload = deepcopy(expected)
    columns = {column.name for column in HttpFixtureNativeGrantRecord.__table__.columns} - {"payload", "content_hash"}
    if mutation == "project": payload["project_id"] = "other"
    elif mutation == "grant": payload["grant_digest"] = acceptance_digest("other")
    elif mutation == "environment": payload["environment_record_id"] = "other"
    elif mutation in {"inventory", "policy"}: payload["inventory_hash" if mutation == "inventory" else "operator_policy_digest"] = acceptance_digest("other")
    elif mutation == "extra": payload["execution_authorized"] = True
    row = HttpFixtureNativeGrantRecord(**{key: payload[key] for key in columns}, payload=payload, content_hash=acceptance_digest(payload))
    session = SimpleNamespace(get=lambda model, ident: None if mutation == "missing" else row)
    monkeypatch.setattr(HttpFixtureGrantRepository, "_native_parent", staticmethod(lambda *args: metadata["native_environment"]))
    value = deepcopy(metadata)
    if mutation == "downgrade": value["schema"] = GRANT_SCHEMA
    if mutation is None:
        HttpFixtureGrantRepository._verify_native_binding(session, value, v.request, {})
    else:
        with pytest.raises(RunPlanIntegrityError): HttpFixtureGrantRepository._verify_native_binding(session, value, v.request, {})


@pytest.mark.parametrize("mutation", [None, "missing-result", "command", "status", "object", "int-flag", "inventory", "authority", "project", "plan"])
def test_native_environment_parent_requires_its_exact_completed_receipt(native_grant, monkeypatch, mutation):
    v = native_grant
    metadata = deepcopy(v.environment["metadata"])
    parent = {key: metadata[key] for key in ("run_plan_id", "run_plan_artifact_hash", "plan_digest", "image_revision_id", "manifest_id")}
    row = SimpleNamespace(project_id=metadata["project_id"], record_id=metadata["record_id"],
        artifact_hash=metadata["artifact_hash"], invocation_id=metadata["invocation_id"])
    result = {"invocation_id": row.invocation_id, "status": "completed",
        "object_refs": ["run_plan_environment:" + row.record_id],
        "run_plan_environment_record": {"metadata": deepcopy(metadata), "historical_not_live": True}}
    command = SimpleNamespace(status="completed", result_payload=result)
    if mutation == "missing-result": command.result_payload = None
    elif mutation == "command": result["invocation_id"] = "another"
    elif mutation == "status": command.status = "running"
    elif mutation == "object": result["object_refs"] = ["run_plan_environment:another"]
    elif mutation == "int-flag": result["run_plan_environment_record"]["historical_not_live"] = 1
    elif mutation == "inventory": result["run_plan_environment_record"]["metadata"]["inventory_hash"] = acceptance_digest("another")
    elif mutation == "authority": result["run_plan_environment_record"]["metadata"]["execution_authorized"] = True
    elif mutation == "project": row.project_id = "another"
    elif mutation == "plan": parent["run_plan_artifact_hash"] = acceptance_digest("another")
    def get(model, ident):
        if model is EnvironmentObservationRecord:
            assert ident == row.record_id
            return row
        assert model is ToolInvocationRecord and ident == row.invocation_id
        return command
    # Only the SQL transport/parent verifier are doubles; the grant receipt gate is real.
    monkeypatch.setattr(EnvironmentObservationRepository, "_verify", classmethod(lambda cls, *args: metadata))
    if mutation is None:
        value = HttpFixtureGrantRepository._native_parent(SimpleNamespace(get=get), v.request, parent)
        assert value == {key: metadata[key] for key in ("record_id", "artifact_hash", "inventory_hash", "operator_policy_digest")}
    else:
        with pytest.raises(RunPlanIntegrityError): HttpFixtureGrantRepository._native_parent(SimpleNamespace(get=get), v.request, parent)
