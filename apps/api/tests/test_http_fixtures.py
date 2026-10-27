"""Protocol specimens, not target execution, durable PG claims or approved ACs."""
from copy import deepcopy
from dataclasses import replace
from threading import Lock

import pytest

from apps.api.app.application.quality_loop.http_fixtures import (
    HttpFixtureDispatchAlreadyClaimed, HttpFixtureLifecycleApplicationService, HttpFixtureOutcomeUnknown,
    HttpFixturePhaseRecord, HttpFixtureScope,
)
from apps.api.app.application.quality_loop.runner_port import OwnedTargetHttpExecution
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixtures import (
    HTTP_FIXTURE_SCHEMA, HttpFixtureInvalid, bind_run_plan_fixture, resolve_fixture_cleanup, validate_http_fixture_manifest,
)
from apps.api.app.domain.quality_loop.runner_observations import RunnerObservationInvalid
from apps.api.app.infrastructure.runner.adapters import HttpAutomationRunner
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.app.infrastructure.runner.request_wire import runner_request_body, runner_request_hash
from apps.api.tests.test_http_bindings import capture, oracle, request, specimen, wire


def manifest():
    return dict(schema=HTTP_FIXTURE_SCHEMA, case_id="fixture-case", preconditions_digest=acceptance_digest(["isolated test"]),
        setup=["Create a session in the owned target"], cleanup=["Close the exact session created by this attempt"],
        setup_steps=[request(), capture(), dict(action="assert_status", request_id="create", value="200"), oracle("create", "ACTIVE")],
        cleanup_groups={"session": [request("close", "/sessions/{{session}}/close"),
            dict(action="assert_status", request_id="close", value="200"), oracle("close", "CLOSED")]})


def scope(value=None):
    return HttpFixtureScope("fixture-project", "attempt-one", "fixture-case", acceptance_digest("fixed-parent"),
        acceptance_digest(value or manifest()), "owned-environment", acceptance_digest("original-build"),
        acceptance_digest("original-inventory"), 10000)


class Journal:
    """Explicit in-memory protocol double; production needs a durable journal."""
    def __init__(self):
        self.records, self.lock = {}, Lock()
        self.fail_commit = False

    def inspect(self, current, phase):
        return deepcopy(self.records.get(self.key(current, phase)))

    @staticmethod
    def key(current, phase):
        return (current.project_id, current.attempt_id, current.case_id, phase)

    def claim(self, current, phase, command, *, require_current):
        require_current()
        with self.lock:
            key = self.key(current, phase)
            if key in self.records:
                raise HttpFixtureDispatchAlreadyClaimed()
            self.records[key] = HttpFixturePhaseRecord(deepcopy(command), None)

    def complete(self, current, phase, command, execution, *, require_current):
        require_current()
        with self.lock:
            key = self.key(current, phase)
            assert self.records[key].command == command and self.records[key].execution is None
            if self.fail_commit:
                raise RuntimeError("original evidence commit failed")
            self.records[key] = HttpFixturePhaseRecord(deepcopy(command), deepcopy(execution))


class Runner:
    def __init__(self):
        self.commands, self.outputs = [], []
        self.failure = None
        self.payload = lambda command: specimen(command)

    def execute_owned_http(self, command, *, environment_id, artifact_hash, inventory_hash, require_work):
        require_work()
        self.commands.append(deepcopy(command))
        if self.failure:
            raise self.failure
        payload = self.payload(command)
        result = HttpAutomationRunner._result_from_payload(command, payload, request_hash=runner_request_hash(command))
        execution = OwnedTargetHttpExecution(result, runner_request_body(command), wire(payload), environment_id, inventory_hash)
        self.outputs.append(execution)
        require_work()
        return execution


def service():
    runner, journal = Runner(), Journal()
    return HttpFixtureLifecycleApplicationService(runner, journal, OwnedHttpFixtureObservationVerifier()), runner, journal


def test_complete_fixture_preserves_raw_bytes_binds_only_original_resource_and_replays_without_dispatch():
    app, runner, journal = service()
    value, current = manifest(), scope()
    original = deepcopy(value)
    prepared = app.prepare(current, value, require_work=lambda: None)
    cleaned = app.cleanup(current, value, require_work=lambda: None)
    assert prepared.receipt["bindings"][0]["value"] == "session_original"
    assert cleaned.cleanup_verified and not cleaned.baseline_restored
    assert not cleaned.business_coverage_verified and not cleaned.execution_authorized
    assert len(runner.commands) == 2 and runner.commands[1].steps[0]["path"] == "/sessions/session_original/close"
    assert value == original and runner.commands[1].steps[1:] == tuple(value["cleanup_groups"]["session"][1:])
    assert journal.inspect(current, "setup").execution.result_body == prepared.execution.result_body
    assert app.prepare(current, value, require_work=lambda: None) == prepared
    assert app.cleanup(current, value, require_work=lambda: None) == cleaned and len(runner.commands) == 2
    prepared.receipt["bindings"][0]["value"] = "caller-mutated"
    assert app.prepare(current, value, require_work=lambda: None).receipt["bindings"][0]["value"] == "session_original"


def test_failed_setup_oracle_keeps_resource_and_is_cleaned_without_rewriting_the_failure():
    app, runner, _ = service()
    value = manifest()
    value["setup_steps"][-1]["value_json"] = '"INDEPENDENT_EXPECTED"'
    runner.payload = lambda command: (specimen(command, states=["passed", "passed", "passed", "failed"], status="failed")
        if command.metadata["fixture_phase"] == "setup" else specimen(command))
    prepared = app.prepare(scope(value), value, require_work=lambda: None)
    cleaned = app.cleanup(scope(value), value, require_work=lambda: None)
    assert prepared.execution.result.status == "failed" and prepared.receipt["failed_assertion_count"] == 1
    assert cleaned.cleanup_verified and len(runner.commands) == 2
    assert runner.commands[0].steps[-1]["value_json"] == '"INDEPENDENT_EXPECTED"'


def test_partial_multi_resource_setup_cleans_known_resource_and_keeps_unknown_group_unresolved():
    app, runner, _ = service()
    value = manifest()
    value["setup_steps"][-1]["value_json"] = '"INDEPENDENT_EXPECTED"'
    value["setup_steps"].extend([request("create_two"), dict(action="capture_json", request_id="create_two", pointer="/sessionId", binding_id="second"),
        dict(action="assert_status", request_id="create_two", value="200")])
    value["cleanup_groups"]["second"] = deepcopy(value["cleanup_groups"]["session"])
    value["cleanup_groups"]["second"][0]["path"] = "/sessions/{{second}}/close"
    runner.payload = lambda command: (specimen(command, states=["passed", "passed", "passed", "failed", "not_executed", "not_executed", "not_executed"], status="failed")
        if command.metadata["fixture_phase"] == "setup" else specimen(command))
    app.prepare(scope(value), value, require_work=lambda: None)
    cleaned = app.cleanup(scope(value), value, require_work=lambda: None)
    assert not cleaned.cleanup_verified and cleaned.unresolved_bindings == ("second",)
    assert len(cleaned.phases) == 1 and len(runner.commands) == 2


@pytest.mark.parametrize("phase", ["setup", "cleanup:session"])
def test_unknown_transport_is_not_retried_even_after_new_service_instance(phase):
    app, runner, journal = service()
    value, current = manifest(), scope()
    if phase.startswith("cleanup"):
        app.prepare(current, value, require_work=lambda: None)
    runner.failure = TimeoutError("target may already have processed the original POST")
    if phase == "setup":
        with pytest.raises(HttpFixtureOutcomeUnknown): app.prepare(current, value, require_work=lambda: None)
    else:
        first = app.cleanup(current, value, require_work=lambda: None)
        assert not first.cleanup_verified and first.unknown_phases == (phase,)
    count = len(runner.commands)
    recovered = HttpFixtureLifecycleApplicationService(runner, journal, OwnedHttpFixtureObservationVerifier())
    if phase == "setup":
        with pytest.raises(HttpFixtureOutcomeUnknown): recovered.prepare(current, value, require_work=lambda: None)
        with pytest.raises(HttpFixtureOutcomeUnknown): recovered.cleanup(current, value, require_work=lambda: None)
    else:
        assert recovered.cleanup(current, value, require_work=lambda: None).unknown_phases == (phase,)
    assert len(runner.commands) == count


def test_failed_cleanup_oracle_is_not_success_and_is_not_automatically_reexecuted():
    app, runner, _ = service()
    value = manifest()
    value["cleanup_groups"]["session"][-1]["value_json"] = '"REMOVED"'
    runner.payload = lambda command: (specimen(command, states=["passed", "passed", "failed"], status="failed")
        if command.metadata["fixture_phase"].startswith("cleanup") else specimen(command))
    app.prepare(scope(value), value, require_work=lambda: None)
    first = app.cleanup(scope(value), value, require_work=lambda: None)
    assert not first.cleanup_verified and first.phases[0].execution.result.status == "failed"
    assert app.cleanup(scope(value), value, require_work=lambda: None) == first and len(runner.commands) == 2


def test_failed_evidence_commit_leaves_reserved_dispatch_and_cannot_repeat_mutation():
    app, runner, journal = service()
    journal.fail_commit = True
    with pytest.raises(RuntimeError, match="commit failed"):
        app.prepare(scope(), manifest(), require_work=lambda: None)
    journal.fail_commit = False
    with pytest.raises(HttpFixtureOutcomeUnknown): app.prepare(scope(), manifest(), require_work=lambda: None)
    assert len(runner.commands) == 1 and journal.inspect(scope(), "setup").execution is None


def test_live_authority_is_rechecked_on_saved_output_and_before_any_cleanup_dispatch():
    app, runner, _ = service()
    app.prepare(scope(), manifest(), require_work=lambda: None)
    def revoked():
        raise PermissionError("fixture authority withdrawn")
    with pytest.raises(PermissionError): app.prepare(scope(), manifest(), require_work=revoked)
    with pytest.raises(PermissionError): app.cleanup(scope(), manifest(), require_work=revoked)
    assert len(runner.commands) == 1


def test_concurrent_claim_does_not_dispatch_and_never_substitutes_a_fresh_attempt():
    app, runner, journal = service()
    journal.claim = lambda *args, **kwargs: (_ for _ in ()).throw(HttpFixtureDispatchAlreadyClaimed())
    with pytest.raises(HttpFixtureOutcomeUnknown): app.prepare(scope(), manifest(), require_work=lambda: None)
    assert not runner.commands


@pytest.mark.parametrize("field,value", [("request_body", b"{}"), ("result_body", b"{}"),
    ("result_body", b'{"status":"passed","status":"failed"}'), ("environment_id", "other"),
    ("inventory_hash", acceptance_digest("restarted-target"))])
def test_replay_checks_original_wire_output_and_owned_scope(field, value):
    app, runner, journal = service()
    app.prepare(scope(), manifest(), require_work=lambda: None)
    record = journal.records[journal.key(scope(), "setup")]
    journal.records[journal.key(scope(), "setup")] = replace(record, execution=replace(record.execution, **{field: value}))
    with pytest.raises(RunnerObservationInvalid): app.prepare(scope(), manifest(), require_work=lambda: None)
    assert len(runner.commands) == 1


@pytest.mark.parametrize("change", ["unknown_field", "missing_group", "foreign_binding", "literal_resource", "query_binding",
    "capture_after_oracle", "unbound_mutation", "no_status", "capture_in_cleanup", "unobserved_cleanup", "multiple_capture", "wrong_setup_type"])
def test_invalid_or_incomplete_recipes_are_refused_before_dispatch(change):
    value = manifest()
    if change == "unknown_field": value["execution_authorized"] = True
    if change == "missing_group": value["cleanup_groups"] = {}
    if change == "foreign_binding": value["cleanup_groups"]["session"][0]["path"] = "/sessions/{{other}}/close"
    if change == "literal_resource": value["cleanup_groups"]["session"][0]["path"] = "/sessions/foreign/close"
    if change == "query_binding": value["cleanup_groups"]["session"][0]["path"] = "/sessions?resource={{session}}"
    if change == "capture_after_oracle": value["setup_steps"][1], value["setup_steps"][2] = value["setup_steps"][2], value["setup_steps"][1]
    if change == "unbound_mutation": value["setup_steps"][0]["method"] = "DELETE"
    if change == "no_status": del value["setup_steps"][2]
    if change == "capture_in_cleanup": value["cleanup_groups"]["session"].append(capture())
    if change == "unobserved_cleanup": del value["cleanup_groups"]["session"][1]
    if change == "multiple_capture": value["setup_steps"].insert(2, capture(name="another"))
    if change == "wrong_setup_type": value["setup"] = "Create a session"
    app, runner, _ = service()
    with pytest.raises(HttpFixtureInvalid): app.prepare(scope(value), value, require_work=lambda: None)
    assert not runner.commands


def test_recipe_and_scope_cannot_be_edited_after_confirmation_or_cleanup_guess_resource_ids():
    app, runner, _ = service()
    value = manifest()
    value["setup_steps"][0]["body_json"] = '{"title":"changed"}'
    with pytest.raises(HttpFixtureInvalid): app.prepare(scope(), value, require_work=lambda: None)
    with pytest.raises(RunnerObservationInvalid): resolve_fixture_cleanup(manifest(), "session", "../foreign")
    with pytest.raises(HttpFixtureOutcomeUnknown): app.cleanup(scope(), manifest(), require_work=lambda: None)
    assert not runner.commands


def test_recipe_validation_returns_an_independent_copy():
    original = manifest()
    saved = validate_http_fixture_manifest(original)
    saved["setup_steps"][0]["path"] = "/changed"
    assert original["setup_steps"][0]["path"] == "/sessions"


@pytest.mark.parametrize("field,replacement", [("project_id", ""), ("attempt_id", "x\n"), ("case_id", "x" * 129),
    ("environment_id", None), ("parent_digest", "unfixed"), ("data_manifest_hash", True),
    ("artifact_hash", "sha256:" + "z" * 64), ("inventory_hash", []), ("timeout_ms", True), ("timeout_ms", 120001)])
def test_execution_scope_cannot_use_unfixed_or_unbounded_values(field, replacement):
    with pytest.raises(HttpFixtureInvalid): replace(scope(), **{field: replacement})


def test_deserialized_success_cannot_replace_original_failed_output():
    app, runner, journal = service()
    value = manifest()
    value["setup_steps"][-1]["value_json"] = '"INDEPENDENT_EXPECTED"'
    runner.payload = lambda command: specimen(command, states=["passed", "passed", "passed", "failed"], status="failed")
    app.prepare(scope(value), value, require_work=lambda: None)
    original = journal.records[journal.key(scope(value), "setup")]
    changed = replace(original.execution, result=replace(original.execution.result, status="passed"))
    journal.records[journal.key(scope(value), "setup")] = replace(original, execution=changed)
    with pytest.raises(RunnerObservationInvalid): app.prepare(scope(value), value, require_work=lambda: None)
    assert len(runner.commands) == 1


def test_complete_multi_resource_cleanup_is_independent_and_does_not_hide_another_group_failure():
    app, runner, _ = service()
    value = manifest()
    value["setup_steps"].extend([request("create_two"), dict(action="capture_json", request_id="create_two", pointer="/sessionId", binding_id="second"),
        dict(action="assert_status", request_id="create_two", value="200")])
    value["cleanup_groups"]["second"] = deepcopy(value["cleanup_groups"]["session"])
    value["cleanup_groups"]["second"][0]["path"] = "/sessions/{{second}}/close"
    value["cleanup_groups"]["session"][-1]["value_json"] = '"REMOVED"'
    runner.payload = lambda command: (specimen(command, states=["passed", "passed", "failed"], status="failed")
        if command.metadata["fixture_phase"] == "cleanup:session" else specimen(command))
    app.prepare(scope(value), value, require_work=lambda: None)
    cleaned = app.cleanup(scope(value), value, require_work=lambda: None)
    assert len(cleaned.phases) == 2 and not cleaned.cleanup_verified and not cleaned.unresolved_bindings
    assert [phase.execution.result.status for phase in cleaned.phases] == ["failed", "passed"]
    assert len(runner.commands) == 3


def test_owned_scope_callback_failure_leaves_dispatch_reserved_and_does_not_return_resource():
    app, runner, journal = service()
    def current():
        if runner.commands:
            raise PermissionError("authority changed during original POST")
    with pytest.raises(PermissionError): app.prepare(scope(), manifest(), require_work=current)
    assert len(runner.commands) == 1 and journal.inspect(scope(), "setup").execution is None
    with pytest.raises(HttpFixtureOutcomeUnknown): app.prepare(scope(), manifest(), require_work=lambda: None)
    assert len(runner.commands) == 1


def test_run_plan_binding_preserves_original_manifest_declaration_and_preconditions():
    from apps.api.tests.test_run_plans import plan_inputs
    from apps.api.app.domain.quality_loop.run_plan import compile_run_plan
    draft, review, sources, selection = plan_inputs()
    data = selection.model_dump(mode="json")
    declaration = data["fixtures"][0]
    value = manifest()
    value.update({key: declaration[key] for key in ("case_id", "preconditions_digest", "setup", "cleanup")})
    declaration["data_manifest_hash"] = acceptance_digest(value)
    plan = compile_run_plan(draft, review, data, sources)
    original = deepcopy(plan)
    pin = bind_run_plan_fixture(plan, value)
    assert pin["plan_digest"] == plan["plan_digest"] and pin["data_manifest_hash"] == acceptance_digest(value)
    assert pin["fixture_digest"] == acceptance_digest(declaration) and plan == original
    for key in ("case_id", "preconditions_digest", "setup", "cleanup"):
        changed = deepcopy(value)
        changed[key] = ["changed"] if type(changed[key]) is list else "other" if key == "case_id" else acceptance_digest("other")
        with pytest.raises(HttpFixtureInvalid): bind_run_plan_fixture(plan, changed)


@pytest.mark.parametrize("field,value", [("parent_digest", acceptance_digest("rebound-plan")),
    ("artifact_hash", acceptance_digest("different-build")), ("inventory_hash", acceptance_digest("restarted-cohort")),
    ("environment_id", "different-target"), ("timeout_ms", 12000)])
def test_same_attempt_cannot_change_scope_to_escape_a_reserved_unknown_mutation(field, value):
    app, runner, _ = service()
    runner.failure = TimeoutError("unknown original POST")
    with pytest.raises(HttpFixtureOutcomeUnknown): app.prepare(scope(), manifest(), require_work=lambda: None)
    with pytest.raises(HttpFixtureInvalid): app.prepare(replace(scope(), **{field: value}), manifest(), require_work=lambda: None)
    assert len(runner.commands) == 1


def test_same_attempt_cannot_change_manifest_to_redispatch_unknown_setup():
    app, runner, _ = service()
    runner.failure = TimeoutError("unknown original POST")
    with pytest.raises(HttpFixtureOutcomeUnknown): app.prepare(scope(), manifest(), require_work=lambda: None)
    value = manifest()
    value["setup_steps"][0]["body_json"] = '{"title":"changed-after-dispatch"}'
    with pytest.raises(HttpFixtureInvalid): app.prepare(scope(value), value, require_work=lambda: None)
    assert len(runner.commands) == 1
