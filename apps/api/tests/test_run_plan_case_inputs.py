"""Original input/worker protocol specimens; no database, Docker or target execution."""
import base64
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.http_fixture_execution import HttpFixtureExecutionSelection
from apps.api.app.application.quality_loop.http_fixture_history import HttpFixtureHistoryItem
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService, HttpFixturePhaseRecord
from apps.api.app.application.quality_loop.run_plan_case_fixtures import RunPlanCaseFixtureApplicationService
from apps.api.app.application.quality_loop.run_plan_case_inputs import RunPlanCaseInputApplicationService, RunPlanCaseExecutionSelection
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_locator_evidence import compile_http_locator_evidence
from apps.api.app.domain.quality_loop.http_locator_record import LOCATOR_RECORD_SCHEMA, locator_record_identity, locator_record_metadata
from apps.api.app.domain.quality_loop.native_environment_health import HEALTH_PROBES, NativeEnvironmentHealthObservation
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from apps.api.app.domain.quality_loop.run_plan_case_execution import CASE_EXECUTE_TOOL, RunPlanCaseExecutionInvalid
from apps.api.app.domain.shared.native_build_source import byte_digest
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.tests.test_http_fixture_native_grants import native_grant
from apps.api.tests.test_http_fixtures import Runner, manifest
from apps.api.tests.test_owned_target_environment import spec
from apps.api.tests.test_run_plan_observations import http_plan
from apps.api.tests.test_run_plan_locators import inventory_for


def http_saved_inputs():
    plan = http_plan(base_url="http://127.0.0.1:8080")
    for declaration in plan["selection"]["fixtures"]:
        recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
        declaration["data_manifest_hash"] = acceptance_digest(recipe)
    first = plan["selection"]["fixtures"][0]
    recipe = {**manifest(), **{key: first[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
    plan["plan_digest"] = acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"})
    archive = {"project_id": plan["project_id"], "run_plan_id": "original-plan", "plan": plan}
    metadata = dict(project_id=plan["project_id"], run_plan_id="original-plan", artifact_hash=acceptance_digest(archive),
        plan_digest=plan["plan_digest"], **{key: plan["source_pin"][key] for key in ("image_revision_id", "manifest_id")})
    return None, None, recipe, {"metadata": metadata, "artifact": archive}


def health_observation(environment, *, target_up=True):
    inventory = deepcopy(environment["archive"]["observation"]["inventory"])
    members = {item["role"]: item for item in inventory["dependency_instances"]}
    members["target"] = inventory["target"]
    checks = []
    for role, body in (("pg", b"1\n"), ("redis", b"PONG\n"),
            ("target", b'{"status":"UP"}\n200' if target_up else b'{"status":"DOWN"}\n503')):
        checks.append(dict(role=role, probe=HEALTH_PROBES[role],
            **{key: members[role][key] for key in ("container_id", "image_id", "started_at")},
            response_base64=base64.b64encode(body).decode(), response_hash=byte_digest(body), byte_count=len(body)))
    return NativeEnvironmentHealthObservation(inventory, acceptance_digest(inventory), tuple(checks), datetime.now(timezone.utc).isoformat())


@pytest.fixture
def case_inputs(spec, monkeypatch):
    import apps.api.tests.test_http_fixture_native_grants as module
    monkeypatch.setattr(module, "saved_inputs", http_saved_inputs)
    v = native_grant.__wrapped__(spec)
    grant = v.service.issue(v.request, invocation_id="original-setup-consent")
    execution_selection = HttpFixtureExecutionSelection(project_id=v.request.project_id,
        grant_id=grant["record_id"], grant_digest=grant["grant_digest"], operation="setup")
    resolved = v.service.execution_inputs(execution_selection, live=False)
    command = HttpFixtureLifecycleApplicationService._command(resolved.scope, "setup", tuple(resolved.manifest["setup_steps"]))
    runner = Runner()
    wire = runner.execute_owned_http(command, environment_id=resolved.scope.environment_id,
        artifact_hash=resolved.scope.artifact_hash, inventory_hash=resolved.scope.inventory_hash, require_work=lambda: None)
    item = HttpFixtureHistoryItem(project_id=v.request.project_id, invocation_id="original-setup-command",
        tool_id="quality.http_fixture.execute", stage="execute", status="completed",
        request_digest=acceptance_digest(execution_selection.model_dump(mode="json")), recipe_id=v.request.recipe_id,
        recipe_artifact_hash=v.request.recipe_artifact_hash, run_plan_id=resolved.parent.run_plan_id,
        run_plan_artifact_hash=resolved.parent.run_plan_artifact_hash, case_id=resolved.scope.case_id,
        attempt_id=resolved.scope.attempt_id, operation="setup", original_execution_id="original-setup-command",
        grant_id=grant["record_id"], grant_digest=grant["grant_digest"])
    state = dict(item=item, phases=(("setup", HttpFixturePhaseRecord(command, wire)), ("cleanup:session", None)),
        private_reads=0, health_reads=0, target_up=True, journal_reads=0)
    plan = v.saved["artifact"]["plan"]
    items, input_cohort, phase_cohort = {item.invocation_id: item}, {
        resolved.selection.grant_id: resolved}, {resolved.scope.case_id: state["phases"]}
    for index, declaration in enumerate(plan["selection"]["fixtures"][1:], 1):
        recipe = {**manifest(), **{key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")}}
        scope = replace(resolved.scope, case_id=recipe["case_id"], data_manifest_hash=acceptance_digest(recipe))
        selected = resolved.selection.model_copy(update={"grant_id": "protocol-grant-" + str(index),
            "grant_digest": acceptance_digest(["protocol-grant", index])})
        consent = replace(resolved.consent, scope=scope, grant_id=selected.grant_id, grant_digest=selected.grant_digest)
        original = replace(resolved, scope=scope, selection=selected, consent=consent, manifest=recipe)
        input_cohort[selected.grant_id] = original
        setup_id = "original-setup-command-" + str(index)
        selected_item = item.model_copy(update={"invocation_id": setup_id, "original_execution_id": setup_id,
            "request_digest": acceptance_digest(selected.model_dump(mode="json")), "case_id": scope.case_id,
            "grant_id": selected.grant_id, "grant_digest": selected.grant_digest})
        items[setup_id] = selected_item
        native_command = HttpFixtureLifecycleApplicationService._command(scope, "setup", tuple(recipe["setup_steps"]))
        native_wire = runner.execute_owned_http(native_command, environment_id=scope.environment_id,
            artifact_hash=scope.artifact_hash, inventory_hash=scope.inventory_hash, require_work=lambda: None)
        phase_cohort[scope.case_id] = (("setup", HttpFixturePhaseRecord(native_command, native_wire)), ("cleanup:session", None))
    state["initial_request_count"] = len(runner.commands)

    def history_item(target):
        return state["item"] if target.invocation_id == item.invocation_id else items[target.invocation_id]

    def history(_inputs, *, require_current, original_setup, include_cleanup):
        require_current()
        selected_item = history_item(SimpleNamespace(invocation_id=original_setup.invocation_id))
        assert original_setup.request_digest == selected_item.request_digest and include_cleanup is True
        assert _inputs.scope.case_id == selected_item.case_id
        state["journal_reads"] += 1
        return deepcopy(state["phases"] if _inputs.scope.case_id == resolved.scope.case_id else phase_cohort[_inputs.scope.case_id])

    def fixture_inputs(selected, *, live):
        assert live is False and selected == input_cohort[selected.grant_id].selection
        return input_cohort[selected.grant_id]

    jobs = SimpleNamespace(grants=SimpleNamespace(execution_inputs=fixture_inputs), history=SimpleNamespace(read=history_item),
        execution=SimpleNamespace(runtimes=SimpleNamespace(history=history)))
    fixtures = RunPlanCaseFixtureApplicationService(jobs, OwnedHttpFixtureObservationVerifier())
    query = v.environment["archive"]["request"]
    binding = {"metadata": {**deepcopy(query), "binding_id": query["build_binding_id"],
        "artifact_hash": query["build_binding_artifact_hash"], "target_artifact_hash": resolved.scope.artifact_hash,
        **{key: v.saved["metadata"][key] for key in ("plan_digest", "image_revision_id", "manifest_id")}},
        "current_use": {"inputs_current": True}}
    port, _, _ = inventory_for(plan, java='import org.springframework.web.bind.annotation.*;\n'
        '@RestController class Controller { @GetMapping("/explicit-protocol-fixture") String read() { return "ok"; } }')
    inventory = port.inspect(plan, require_access=lambda: None)
    report = compile_http_locator_evidence(plan, inventory)
    assert report["summary"]["static_match"] == report["summary"]["locator_count"]
    locator_archive = dict(schema=LOCATOR_RECORD_SCHEMA, project_id=plan["project_id"],
        record_id=locator_record_identity("original-locator-command"), invocation_id="original-locator-command",
        actor_id="admin", recorded_at=datetime.now(timezone.utc).isoformat(),
        request={key: query[key] for key in ("project_id", "run_plan_id", "run_plan_artifact_hash")},
        parents={"plan_digest": plan["plan_digest"], **{key: plan["source_pin"][key] for key in
            ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")}}, report=report)
    locator = dict(metadata=locator_record_metadata(locator_archive), archive=locator_archive, historical_not_live=True)
    selection = RunPlanCaseExecutionSelection(**query, run_id="original-business-attempt", plan_digest=plan["plan_digest"],
        timeout_ms=10000, environment_record_id=v.environment["metadata"]["record_id"],
        environment_record_artifact_hash=v.environment["metadata"]["artifact_hash"],
        locator_record_id=locator["metadata"]["record_id"], locator_record_artifact_hash=locator["metadata"]["artifact_hash"],
        fixture_setups=[dict(case_id=entry.case_id, invocation_id=entry.invocation_id) for entry in items.values()])
    snapshot = dict(id="original-business-command", tool_id=CASE_EXECUTE_TOOL, status="running",
        input_payload={**selection.model_dump(mode="json"), "confirmed_by_user": True, "confirmed_actor_id": "admin",
            "confirmed_at": datetime.now(timezone.utc).isoformat()})

    def original(_project, _invocation, *, actor_id, require_current):
        require_current()
        return {"command": deepcopy(snapshot), "now": datetime.now(timezone.utc)}

    def original_inputs(request, *, current):
        assert type(current) is bool
        state["private_reads"] += 1
        if request.model_dump(mode="json") != query:
            raise RunPlanIntegrityError("wrong original query")
        if current and (not v.saved["current_use"]["inputs_current"] or not binding["current_use"]["inputs_current"]):
            raise RunPlanChanged("stale original inputs")
        return deepcopy(v.saved), deepcopy(binding)

    def health(request, *, require_work):
        require_work()
        state["health_reads"] += 1
        return {"request": request.model_dump(mode="json"), "observation": health_observation(v.environment, target_up=state["target_up"])}

    authorization = v.service.authorization
    service = RunPlanCaseInputApplicationService(SimpleNamespace(authorization=authorization, original_inputs=original_inputs),
        v.records, SimpleNamespace(read=lambda *_: deepcopy(locator)), fixtures, SimpleNamespace(inspect=health),
        SimpleNamespace(original_command=original))
    return SimpleNamespace(service=service, fixtures=fixtures, selection=selection, snapshot=snapshot, v=v, binding=binding,
        locator=locator, state=state, resolved=resolved, jobs=jobs, runner=runner, authority=authorization)


def test_producer_uses_all_original_records_and_instance_not_policy_hash(case_inputs):
    v = case_inputs
    before = deepcopy((v.v.saved, v.v.environment, v.locator, v.snapshot))
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    assert prepared.scope.inventory_hash == v.v.environment["metadata"]["inventory_hash"]
    assert prepared.scope.inventory_hash != v.v.environment["metadata"]["operator_policy_digest"]
    assert prepared.scope.actor_id == "admin" and prepared.plan == v.v.saved["artifact"]["plan"]
    assert prepared.scope.selection == v.selection.model_dump(mode="json")
    v.service.require_current(prepared)
    assert (v.v.saved, v.v.environment, v.locator, v.snapshot) == before
    assert v.state["health_reads"] == 2 and v.state["journal_reads"] == 4 * len(v.selection.fixture_setups)
    assert len(v.runner.commands) == v.state["initial_request_count"]  # Specimen construction only, never producer dispatch.


@pytest.mark.parametrize("field,value", [("tool_id", "quality.http_fixture.execute"), ("status", "completed"),
    ("id", "other-command"), ("confirmed_by_user", False), ("confirmed_actor_id", "other-actor"),
    ("confirmed_at", "2000-01-01T00:00:00+00:00"), ("run_id", "other-attempt")])
def test_unrelated_or_stale_business_command_rejected_before_private_inputs(case_inputs, field, value):
    v = case_inputs
    target = v.snapshot if field in {"tool_id", "status", "id"} else v.snapshot["input_payload"]
    target[field] = value
    with pytest.raises(RunPlanCaseExecutionInvalid):
        v.service.prepare(v.selection, invocation_id="original-business-command")
    assert v.state["private_reads"] == v.state["journal_reads"] == v.state["health_reads"] == 0


@pytest.mark.parametrize("fault", ["source_revoked", "actor", "permission_digest", "stale_plan", "stale_build",
    "command", "target_down", "environment_metadata", "locator_metadata", "modified_prepared_plan", "modified_scope"])
def test_worker_rechecks_original_dependencies_without_rebinding_attempt(case_inputs, fault):
    v = case_inputs
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    if fault == "source_revoked": v.v.state["revoked"] = True
    elif fault in {"actor", "permission_digest"}:
        old = v.authority.scope(v.selection.project_id)
        new = SimpleNamespace(**vars(old))
        if fault == "actor": new.actor_id = "other-admin"
        else: new.fingerprint = acceptance_digest("changed-source-permissions")
        v.authority.scope = lambda _: new
    elif fault == "stale_plan": v.v.saved["current_use"]["inputs_current"] = False
    elif fault == "stale_build": v.binding["current_use"]["inputs_current"] = False
    elif fault == "command": v.snapshot["input_payload"]["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    elif fault == "target_down": v.state["target_up"] = False
    elif fault == "environment_metadata": v.v.environment["metadata"]["inventory_hash"] = acceptance_digest("changed")
    elif fault == "locator_metadata": v.locator["metadata"]["inventory_hash"] = acceptance_digest("changed")
    elif fault == "modified_prepared_plan": prepared.plan["project_id"] = "another-project"
    else: prepared.scope.selection["run_id"] = "other-attempt"
    with pytest.raises((RunPlanCaseExecutionInvalid, RunPlanChanged, RunPlanIntegrityError, SourceAccessDenied)):
        v.service.require_current(prepared)
    assert len(v.runner.commands) == v.state["initial_request_count"]


@pytest.mark.parametrize("fault", ["unconfirmed", "not_setup", "cleanup", "missing_setup", "unknown_setup",
    "cleanup_claimed", "cleanup_completed", "incomplete_cleanup_inventory", "another_command", "wrong_wire"])
def test_case_fixture_reader_never_promotes_metadata_or_unknown_effects(case_inputs, fault):
    v = case_inputs
    item, phases = v.state["item"], v.state["phases"]
    if fault == "unconfirmed": v.state["item"] = item.model_copy(update={"status": "waiting_confirmation"})
    elif fault == "not_setup": v.state["item"] = item.model_copy(update={"stage": "grant"})
    elif fault == "cleanup": v.state["item"] = item.model_copy(update={"operation": "cleanup"})
    elif fault in {"missing_setup", "unknown_setup"}:
        v.state["phases"] = (("setup", None if fault == "missing_setup" else HttpFixturePhaseRecord(phases[0][1].command, None)), phases[1])
    elif fault.startswith("cleanup_"):
        v.state["phases"] = (phases[0], ("cleanup:session", HttpFixturePhaseRecord(phases[0][1].command,
            None if fault == "cleanup_claimed" else phases[0][1].execution)))
    elif fault == "incomplete_cleanup_inventory": v.state["phases"] = (phases[0],)
    elif fault == "another_command":
        command = deepcopy(phases[0][1].command)
        command.metadata["fixture_phase"] = "other-setup"
        v.state["phases"] = (("setup", HttpFixturePhaseRecord(command, phases[0][1].execution)), phases[1])
    else:
        wire = phases[0][1].execution
        wire = type(wire)(wire.result, wire.request_body + b" ", wire.result_body, wire.environment_id, wire.inventory_hash)
        v.state["phases"] = (("setup", HttpFixturePhaseRecord(phases[0][1].command, wire)), phases[1])
    with pytest.raises(ValueError):
        v.fixtures.read(v.selection.project_id, item.invocation_id, require_current=lambda: v.authority.require_current(v.resolved.access_scope))
    assert len(v.runner.commands) == v.state["initial_request_count"]


def test_fixture_reader_rejects_new_cleanup_during_original_read(case_inputs):
    v, count = case_inputs, 0
    original = v.jobs.execution.runtimes.history
    def history(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            v.state["phases"] = (v.state["phases"][0], ("cleanup:session", v.state["phases"][0][1]))
        return original(*args, **kwargs)
    v.jobs.execution.runtimes.history = history
    with pytest.raises(RunPlanCaseExecutionInvalid, match="changed"):
        v.fixtures.read(v.selection.project_id, v.state["item"].invocation_id, require_current=lambda: None)


@pytest.mark.parametrize("field,value", [("timeout_ms", True), ("timeout_ms", "10000"),
    ("fixture_setups", []), ("environment_fully_verified", True), ("business_coverage_verified", True)])
def test_execution_selection_is_complete_and_never_accepts_client_authority(case_inputs, field, value):
    payload = case_inputs.selection.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValueError): RunPlanCaseExecutionSelection.model_validate(payload)


@pytest.mark.parametrize("fault", ["missing", "reordered", "duplicate_case", "duplicate_command"])
def test_producer_cannot_skip_reorder_or_share_setup_across_original_cases(case_inputs, fault):
    v = case_inputs
    payload = v.selection.model_dump(mode="json")
    fixtures = payload["fixture_setups"]
    if fault == "missing": fixtures.pop()
    elif fault == "reordered": fixtures.reverse()
    elif fault == "duplicate_case": fixtures[-1]["case_id"] = fixtures[0]["case_id"]
    else: fixtures[-1]["invocation_id"] = fixtures[0]["invocation_id"]
    v.snapshot["input_payload"].update(payload)
    with pytest.raises(ValueError):
        selection = RunPlanCaseExecutionSelection.model_validate(payload)
        v.service.prepare(selection, invocation_id=v.snapshot["id"])
    assert v.state["journal_reads"] == v.state["health_reads"] == 0


@pytest.mark.parametrize("field", ["run_id", "build_binding_id", "environment_record_id", "locator_record_id", "case_id", "invocation_id"])
def test_invalid_original_ids_are_rejected_before_private_reads(case_inputs, field):
    v = case_inputs
    payload = v.selection.model_dump(mode="json")
    target = payload["fixture_setups"][0] if field in {"case_id", "invocation_id"} else payload
    target[field] = "invalid\x00identifier"
    with pytest.raises(ValueError): RunPlanCaseExecutionSelection.model_validate(payload)
    assert v.state["private_reads"] == v.state["journal_reads"] == v.state["health_reads"] == 0


@pytest.mark.parametrize("fault", ["case", "run_plan", "target", "inventory", "native_record", "manifest"])
def test_producer_cannot_mix_self_consistent_fixture_parent_records(case_inputs, fault):
    v = case_inputs
    original = v.fixtures.read
    def read(*args, **kwargs):
        proof = original(*args, **kwargs)
        if fault == "case": proof["scope"]["case_id"] = "other-case"
        elif fault == "run_plan": proof["parent"]["run_plan_id"] = "other-plan"
        elif fault == "target": proof["scope"]["artifact_hash"] = acceptance_digest("other-build")
        elif fault == "inventory": proof["native_environment"]["inventory_hash"] = acceptance_digest("other-instance")
        elif fault == "native_record": proof["native_environment"]["record_id"] = "other-record"
        else: proof["manifest"]["setup"] = ["different original declaration"]
        return proof
    v.fixtures.read = read
    with pytest.raises(ValueError): v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    assert v.state["health_reads"] == 0


@pytest.mark.parametrize("wrong_command", [False, True])
def test_readonly_original_journal_never_reacquires_project_write_lock(case_inputs, monkeypatch, wrong_command):
    from apps.api.app.application.quality_loop.http_fixture_commands import HttpFixtureCommandAuthority
    from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_CANONICAL_DISPATCH_SCHEMA
    from apps.api.app.infrastructure.persistence import http_fixture_journal_repository as module
    v = case_inputs
    authority = HttpFixtureCommandAuthority(invocation_id=v.state["item"].invocation_id,
        request_digest=v.state["item"].request_digest)
    parent = v.resolved.parent.model_dump(mode="json")
    command = v.state["phases"][0][1].command
    access = SimpleNamespace(require_scope=lambda _: parent)
    journal = module.PostgresHttpFixtureDispatchJournal(access, SimpleNamespace(), actor_id="admin")
    session = SimpleNamespace()
    @contextmanager
    def opened(): yield session
    monkeypatch.setattr(module, "session_scope", opened)
    monkeypatch.setattr(module.NativeBuildRepository, "_actor", staticmethod(lambda *_: None))
    monkeypatch.setattr(journal, "_parent", lambda *_: None)
    monkeypatch.setattr(journal, "_lock", lambda *_: pytest.fail("readonly guard must not reacquire a project write lock"))
    def expected(scope, phase, *, read_only):
        assert scope == v.resolved.scope and phase == "setup" and read_only is True
        return command
    monkeypatch.setattr(journal, "_expected", expected)
    pin = authority.model_dump(mode="json")
    if wrong_command: pin["invocation_id"] = "other-original-setup"
    reserved = {"schema": FIXTURE_CANONICAL_DISPATCH_SCHEMA, "canonical_command": {**pin, "intent_digest": acceptance_digest("intent")}}
    monkeypatch.setattr(journal, "_records", lambda *_: (reserved, None))
    if wrong_command:
        with pytest.raises(ValueError, match="another command"):
            journal.inspect(v.resolved.scope, "setup", original_command=authority, read_only=True)
    else:
        assert journal.inspect(v.resolved.scope, "setup", original_command=authority, read_only=True) == HttpFixturePhaseRecord(command, None)


def test_readonly_cleanup_resolution_propagates_read_mode_to_setup(case_inputs, monkeypatch):
    from apps.api.app.infrastructure.persistence import http_fixture_journal_repository as module
    v = case_inputs
    calls = []
    def inspect(scope, phase, *, read_only):
        calls.append((scope, phase, read_only))
        return v.state["phases"][0][1]
    access = SimpleNamespace(command=lambda *args, **kwargs: kwargs["setup_receipt"])
    journal = module.PostgresHttpFixtureDispatchJournal(access, SimpleNamespace(), actor_id="admin")
    monkeypatch.setattr(journal, "inspect", inspect)
    receipt = journal._expected(v.resolved.scope, "cleanup:session", read_only=True)
    assert receipt["bindings"] and calls == [(v.resolved.scope, "setup", True)]


def test_original_command_reader_uses_pg_time_but_never_takes_a_nested_write_lock(case_inputs, monkeypatch):
    from apps.api.app.infrastructure.persistence import run_plan_case_execution_repository as module
    from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
    v, now = case_inputs, datetime.now(timezone.utc)
    checks = []
    command = SimpleNamespace(**deepcopy(v.snapshot))
    def scalar(query):
        assert query._for_update_arg is None
        return command if query.column_descriptions[0].get("entity") is ToolInvocationRecord else now
    @contextmanager
    def opened(): yield SimpleNamespace(scalar=scalar, get=lambda *_: None)
    monkeypatch.setattr(module, "session_scope", opened)
    monkeypatch.setattr(module.TestDesignScopeRepository, "_lock", lambda *_: pytest.fail("read must not reacquire write lock"))
    monkeypatch.setattr(module.PostgresRunPlanCaseExecutionRepository, "_actor", staticmethod(lambda *_: checks.append("actor")))
    result = module.PostgresRunPlanCaseExecutionRepository().original_command(v.selection.project_id,
        v.snapshot["id"], actor_id="admin", require_current=lambda: checks.append("current"))
    assert result == {"command": v.snapshot, "now": now} and checks == ["current", "actor", "current", "actor"]
    result["command"]["input_payload"]["run_id"] = "mutated"
    assert command.input_payload["run_id"] == v.selection.run_id


def test_full_producer_worker_and_private_archive_keep_every_original_case(case_inputs):
    import asyncio
    from apps.api.app.application.quality_loop.run_plan_case_execution import RunPlanCaseExecutionApplicationService
    from apps.api.app.application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
    from apps.api.app.infrastructure.storage.run_plan_case_artifacts import RunPlanCaseArtifacts
    from apps.api.tests.test_run_plan_case_artifacts import Storage
    from apps.api.tests.test_run_plan_case_execution import Runner as BusinessRunner, Journal
    v, runner, journal, storage = case_inputs, BusinessRunner(), Journal(), Storage()
    worker = RunPlanCaseExecutionApplicationService(runner, OwnedHttpFixtureObservationVerifier(), journal, RunPlanCaseArtifacts(storage))
    application = RunPlanCaseApplicationService(v.service, worker)
    original = deepcopy(v.v.saved["artifact"]["plan"])
    result = asyncio.run(application.execute(v.selection, invocation_id=v.snapshot["id"]))
    assert result["state"]["state"] == "observed"
    assert len(runner.commands) == len(journal.claims) == len(journal.outcomes) == len(storage.writes) == len(original["prepared"]["cases"])
    assert [item["case_id"] for item in result["observations"]] == [item["case_id"] for item in original["prepared"]["cases"]]
    assert v.v.saved["artifact"]["plan"] == original
    assert result["state"]["business_coverage_verified"] is result["state"]["canonical_execution_committed"] is False
    assert result["state"]["executed_on_target_count"] == result["state"]["passed_count"] == 0


def test_composition_is_lazy_and_invalid_runner_config_does_not_reserve_case_work(case_inputs, monkeypatch):
    import asyncio
    from apps.api.app.infrastructure.runner import run_plan_case_runtime as module
    from apps.api.tests.test_run_plan_case_artifacts import Storage
    v = case_inputs
    monkeypatch.delenv("NASUS_HTTP_FIXTURE_NODE", raising=False)
    def runner(**kwargs):
        pytest.fail("composition must not instantiate optional target executable")
    monkeypatch.setattr(module, "ConfiguredOwnedTargetHttpRunner", runner)
    composed = module.compose_run_plan_cases(v.service.original_inputs, v.v.records,
        v.service.locators, v.jobs, v.service.health, Storage())
    assert composed.inputs.fixtures.jobs is v.jobs
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    calls = []
    def invalid(**kwargs):
        calls.append(kwargs)
        raise ValueError("target executable not configured")
    monkeypatch.setattr(module, "ConfiguredOwnedTargetHttpRunner", invalid)
    composed.execution.journal = SimpleNamespace(acquire=lambda *_args, **_kwargs: pytest.fail("bad config must not acquire case work"))
    with pytest.raises(ValueError, match="not configured"):
        asyncio.run(composed.execution.execute(prepared.plan, prepared.scope, require_current=lambda: calls.append("current")))
    assert calls == ["current", {"node_executable": ""}]


def test_input_preparation_does_not_block_event_loop_and_cancel_joins_without_dispatch():
    import asyncio
    from threading import Event
    from apps.api.app.application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
    entered, release, joined = Event(), Event(), Event()
    calls = []
    def prepare(*args, require_work, **kwargs):
        require_work()
        entered.set()
        release.wait(timeout=3)
        try: require_work()
        finally: joined.set()
        pytest.fail("cancelled preparation must not return execution inputs")
    async def execute(*args, **kwargs):
        calls.append("dispatch")
        pytest.fail("cancelled input preparation must not enter case worker")
    async def verify():
        application = RunPlanCaseApplicationService(SimpleNamespace(prepare=prepare), SimpleNamespace(execute=execute))
        task = asyncio.create_task(application.execute(None, invocation_id="original"))
        for _ in range(100):
            if entered.is_set(): break
            await asyncio.sleep(0.01)
        assert entered.is_set() and not task.done()
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done() and not joined.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert joined.is_set() and calls == []
    asyncio.run(verify())
