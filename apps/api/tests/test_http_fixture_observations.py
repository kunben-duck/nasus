"""Production archive/domain use cases with explicit read ports, not target evidence."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.http_fixture_job_receipts import HttpFixtureJobReceiptAccess
from apps.api.app.application.platform.tool_handlers.http_fixture_jobs import HttpFixtureJobToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.quality_loop.http_fixture_history import HttpFixtureHistoryTarget
from apps.api.app.application.quality_loop.http_fixture_observations import HttpFixtureOriginalObservation
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_command import FALSE_AUTHORITIES, FIXTURE_JOB_TOOLS
from apps.api.app.domain.quality_loop.http_fixture_observation import FIXTURE_OBSERVATION_TOOL, HttpFixtureObservationChanged
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_http_fixture_history import history_specimen, native_grant, spec


@pytest.fixture
def observation_specimen(history_specimen, monkeypatch):
    v = history_specimen
    item = v.history.read(v.target).model_dump(mode="json")
    claim = "fixture_" + acceptance_digest([item["project_id"], item["attempt_id"], item["case_id"], "setup"]).removeprefix("sha256:")
    v.job = {"schema": "nasus.http-fixture-job.v1", "project_id": item["project_id"], "invocation_id": item["invocation_id"],
        "request_digest": item["request_digest"], "selection": {key: item[key] for key in ("project_id", "grant_id", "grant_digest", "operation")},
        "status": item["status"], "intent_digest": acceptance_digest("explicit-original-intent-port-double"),
        "phases": [{"phase": "setup", "claim_id": claim, "state": "not_dispatched"}],
        "cancellation_requested": False, "cancellation_delivered": False, **{key: False for key in FALSE_AUTHORITIES}}
    v.observation_reads = []
    def read(target):
        assert target.model_dump(mode="json") == v.target.model_dump(mode="json")
        v.observation_reads.append(HttpFixtureHistoryTarget.model_validate(target.model_dump(mode="json")))
        return deepcopy(v.job)
    monkeypatch.setattr(v.jobs, "read", read)
    v.observations = v.jobs.observations
    return v


def observed_phase(v, state="outcome_unknown", status="passed"):
    phase = v.job["phases"][0]
    phase.update(state=state, dispatch_digest=acceptance_digest("explicit-original-dispatch-port-double"))
    if state == "observed":
        phase.update(result_status=status, result_digest=acceptance_digest(["explicit-original-result-port-double", status]))


def test_original_observation_is_independent_of_local_session_and_never_renews_or_dispatches(observation_specimen):
    v = observation_specimen
    issued, calls = deepcopy(v.state["issued"]), len(v.commands.calls)
    result = v.observations.read(v.target)
    assert result.state == "not_dispatched" and result.job == v.job
    assert result.expected_phases[0].claim_id == v.job["phases"][0]["claim_id"]
    assert result.selected == result.execution and result.source_scope_digest == v.access.fingerprint
    assert v.observation_reads == [v.target] and v.state["issued"] == issued and v.state["live"] == 0
    assert len(v.commands.calls) == calls
    assert not any(token in str(result.model_dump(mode="json")) for token in
        ("idempotency_key", "input_payload", "artifact_ref", "base_url", "setup_steps"))
    for key in FALSE_AUTHORITIES: assert getattr(result, key) is False


@pytest.mark.parametrize("stage", ["grant", "execute"])
@pytest.mark.parametrize("status", ["pending", "waiting_confirmation", "waiting_approval"])
def test_unconfirmed_commands_remain_metadata_only_and_never_read_a_journal(observation_specimen, stage, status):
    v = observation_specimen
    ident = "001-grant" if stage == "grant" else v.target.invocation_id
    next(row for row in v.history_state["rows"] if row["command"]["id"] == ident)["command"]["status"] = status
    result = v.observations.read(HttpFixtureHistoryTarget(project_id=v.target.project_id, invocation_id=ident))
    assert result.state == ("not_execution" if stage == "grant" else "not_confirmed")
    assert result.job is None and result.expected_phases == () and not v.observation_reads


@pytest.mark.parametrize("status", ["running", "failed", "cancelled"])
def test_cancellation_and_failure_do_not_resolve_unknown_effects(observation_specimen, status):
    v = observation_specimen
    observed_phase(v)
    v.history_state["rows"][1]["command"]["status"] = status
    v.history_state["rows"][2]["execution"]["status"] = status
    v.job.update(status=status, cancellation_requested=status == "cancelled", cancellation_delivered=status == "cancelled")
    result = v.observations.read(HttpFixtureHistoryTarget(project_id=v.target.project_id, invocation_id="003-cancel"))
    assert result.state == "outcome_unknown" and result.job["phases"][0]["state"] == "outcome_unknown"
    assert result.execution.invocation_id == v.target.invocation_id and result.selected.stage == "cancel"
    assert result.business_coverage_verified is False and result.baseline_restored is False


@pytest.mark.parametrize("status", ["passed", "failed", "error", "timed_out"])
def test_observed_phase_preserves_real_result_status_without_business_coverage(observation_specimen, status):
    v = observation_specimen
    observed_phase(v, "observed", status)
    result = v.observations.read(v.target)
    assert result.state == "observed" and result.job["phases"][0]["result_status"] == status
    assert result.business_coverage_verified is False


@pytest.mark.parametrize("status", ["running", "failed", "cancelled"])
def test_prebinding_preparation_never_claims_a_target_observation(observation_specimen, status):
    v = observation_specimen
    v.history_state["rows"][1]["command"]["status"] = status
    v.job.update(schema="nasus.http-fixture-job.v2", status=status, intent_digest=None, phases=[],
        preparation_digest=acceptance_digest("original-preparation-port-double"), target_observation_verified=False,
        phase={"running": "preparing", "failed": "preparation_failed", "cancelled": "preparation_cancelled"}[status],
        cancellation_requested=status == "cancelled")
    result = v.observations.read(v.target)
    assert result.state == v.job["phase"] and result.job["target_observation_verified"] is False


@pytest.mark.parametrize("fault", ["schema", "project", "invocation", "request", "selection", "status", "intent", "missing_phase",
    "extra_phase", "claim", "phase_name", "unknown_result", "observed_no_result", "dispatch", "result", "result_status", "authority",
    "cancel_coercion", "cancel_without_request", "complete_unknown", "extra", "malformed_schema", "malformed_state"])
def test_original_observation_rejects_changed_or_partial_journal(observation_specimen, fault):
    v = observation_specimen
    observed_phase(v)
    p = v.job["phases"][0]
    if fault == "schema": v.job["schema"] = "invented"
    elif fault == "project": v.job["project_id"] = "other"
    elif fault == "invocation": v.job["invocation_id"] = "other"
    elif fault == "request": v.job["request_digest"] = acceptance_digest("other")
    elif fault == "selection": v.job["selection"]["operation"] = "cleanup"
    elif fault == "status": v.job["status"] = "failed"
    elif fault == "intent": v.job["intent_digest"] = None
    elif fault == "missing_phase": v.job["phases"] = []
    elif fault == "extra_phase": v.job["phases"].append(deepcopy(p))
    elif fault == "claim": p["claim_id"] = "fixture_" + "a" * 64
    elif fault == "phase_name": p["phase"] = "cleanup:other"
    elif fault == "unknown_result": p["result_digest"] = acceptance_digest("fabricated")
    elif fault == "observed_no_result": p["state"] = "observed"
    elif fault == "dispatch": p["dispatch_digest"] = "bad"
    elif fault == "result": observed_phase(v, "observed"); p["result_digest"] = "bad"
    elif fault == "result_status": observed_phase(v, "observed"); p["result_status"] = "completed"
    elif fault == "authority": v.job["business_coverage_verified"] = True
    elif fault == "cancel_coercion": v.job["cancellation_requested"] = 0
    elif fault == "cancel_without_request": v.job["cancellation_delivered"] = True
    elif fault == "complete_unknown": v.job["status"] = "completed"; v.history_state["rows"][1]["command"]["status"] = "completed"
    elif fault == "malformed_schema": v.job["schema"] = []
    elif fault == "malformed_state": p["state"] = {}
    else: v.job["target_url"] = "private"
    with pytest.raises(HttpFixtureInvalid): v.observations.read(v.target)
    assert v.state["live"] == 0


def test_concurrent_command_change_requires_same_id_reinspection_not_new_attempt(observation_specimen, monkeypatch):
    v = observation_specimen
    read = v.jobs.read
    def transition(target):
        value = read(target)
        v.history_state["rows"][1]["command"]["status"] = "failed"
        return value
    monkeypatch.setattr(v.jobs, "read", transition)
    with pytest.raises(HttpFixtureObservationChanged): v.observations.read(v.target)
    assert v.observation_reads == [v.target]


def test_acl_revocation_after_journal_read_hides_everything(observation_specimen, monkeypatch):
    v = observation_specimen
    read = v.jobs.read
    def revoked(target):
        value = read(target); v.state["revoked"] = True; return value
    monkeypatch.setattr(v.jobs, "read", revoked)
    with pytest.raises(SourceAccessDenied): v.observations.read(v.target)


def test_another_current_administrator_can_inspect_without_inheriting_original_consent(observation_specimen):
    v = observation_specimen
    issued = deepcopy(v.state["issued"])
    v.access.actor_id = "another-current-administrator"
    v.access.fingerprint = acceptance_digest("another-current-administrator-source-scope")
    result = v.observations.read(v.target)
    assert result.source_scope_digest == v.access.fingerprint
    assert result.execution.invocation_id == v.target.invocation_id and result.execution_authorized is False
    assert v.state["issued"] == issued and v.state["live"] == 0
    assert {item["actor_id"] for item in issued.values()} == {"admin"}


def test_reader_cannot_inspect_original_journal_even_when_creator_metadata_is_available(observation_specimen):
    v = observation_specimen
    v.access.effective_project_role = "qa_lead"
    with pytest.raises(SourceAccessDenied): v.observations.read(v.target)
    assert not v.observation_reads


def test_snapshot_cannot_replace_either_original_or_expected_phase_inventory(observation_specimen):
    v = observation_specimen
    original = v.observations.read(v.target).model_dump(mode="json")
    for fault in ("phase", "claim", "selected", "state", "extra", "missing"):
        value = deepcopy(original)
        if fault == "phase": value["expected_phases"][0]["phase"] = "another"
        elif fault == "claim": value["expected_phases"][0]["claim_id"] = "fixture_" + "a" * 64
        elif fault == "selected": value["selected"]["status"] = "failed"
        elif fault == "state": value["state"] = "observed"
        elif fault == "missing": del value["source_scope_digest"]
        else: value["input_payload"] = {}
        with pytest.raises(ValueError): HttpFixtureOriginalObservation.model_validate(value)


def test_canonical_observation_receipt_is_protected_and_rechecks_dynamic_journal(observation_specimen):
    v = observation_specimen
    invocation = ToolInvocation(id="original-journal-query", tool_id=FIXTURE_OBSERVATION_TOOL, status="pending", summary="",
        input_payload=v.target.model_dump(mode="json"))
    events = []
    async def emit(ident, status, summary, refs, result=None): events.append(result)
    asyncio.run(HttpFixtureJobToolHandler(v.jobs, SimpleNamespace(emit_tool_status=emit),
        SimpleNamespace(require_invocation_project_scope=lambda _: None)).handle(invocation))
    result = events[-1]
    assert result.status == "completed" and result.http_fixture_observation is not None
    assert result.http_fixture_job is None and result.http_fixture_history is None
    assert FIXTURE_OBSERVATION_TOOL in FIXTURE_JOB_TOOLS
    completed = invocation.model_copy(update={"status": "completed", "result": result})
    protector = HttpFixtureJobReceiptAccess(v.jobs)
    protector.require_access(completed)
    public = protector.broadcast_view(completed)
    assert public.input_payload == {} and public.result is None
    observed_phase(v)
    with pytest.raises(PlatformApplicationError) as changed: protector.require_access(completed)
    assert changed.value.status_code == 409


@pytest.mark.parametrize("field", FALSE_AUTHORITIES)
@pytest.mark.parametrize("value", [True, 0, 1, "false", None])
def test_observation_never_accepts_coerced_top_level_authority(observation_specimen, field, value):
    wire = observation_specimen.observations.read(observation_specimen.target).model_dump(mode="json")
    wire[field] = value
    with pytest.raises(ValueError): HttpFixtureOriginalObservation.model_validate(wire)


def test_cleanup_classification_preserves_every_resource_and_unknown_dominates(observation_specimen):
    from apps.api.app.domain.quality_loop.http_fixture_observation import classify_original_observation

    original = observation_specimen.observations.read(observation_specimen.target).model_dump(mode="json")
    execution = original["execution"]
    execution["operation"] = "cleanup"
    job = original["job"]
    job["selection"]["operation"] = "cleanup"
    pins = [{"phase": "cleanup:" + binding, "claim_id": "fixture_" + acceptance_digest(
        [execution["project_id"], execution["attempt_id"], execution["case_id"], "cleanup:" + binding]).removeprefix("sha256:")}
        for binding in ("first-resource", "second-resource")]
    job["phases"] = [{**pin, "state": "not_dispatched"} for pin in pins]
    assert classify_original_observation(execution, execution, pins, job) == "not_dispatched"
    job["phases"][0].update(state="observed", dispatch_digest=acceptance_digest("first-dispatch"),
        result_digest=acceptance_digest("first-result"), result_status="failed")
    assert classify_original_observation(execution, execution, pins, job) == "partially_observed"
    job["phases"][1].update(state="outcome_unknown", dispatch_digest=acceptance_digest("second-dispatch"))
    assert classify_original_observation(execution, execution, pins, job) == "outcome_unknown"
    job["phases"].reverse()
    with pytest.raises(HttpFixtureInvalid): classify_original_observation(execution, execution, pins, job)


@pytest.mark.parametrize("receipt", [None, {}, {"execution_authorized": True}])
def test_completed_query_cannot_omit_or_invent_original_journal(observation_specimen, receipt):
    v = observation_specimen
    invocation = ToolInvocation(id="query", tool_id=FIXTURE_OBSERVATION_TOOL, status="completed", summary="",
        input_payload=v.target.model_dump(mode="json"), result=ToolResult(invocation_id="query", status="completed", summary="",
            http_fixture_observation=receipt))
    with pytest.raises(ValueError): v.jobs.authorize_receipts((invocation,))


@pytest.mark.parametrize("field", ["http_fixture_job", "http_fixture_history"])
def test_original_journal_query_cannot_mix_an_unverified_operation_receipt(observation_specimen, field):
    v = observation_specimen
    receipt = v.observations.read(v.target).model_dump(mode="json")
    invocation = ToolInvocation(id="query", tool_id=FIXTURE_OBSERVATION_TOOL, status="completed", summary="",
        input_payload=v.target.model_dump(mode="json"), result=ToolResult(invocation_id="query", status="completed", summary="",
            http_fixture_observation=receipt, **{field: {"execution_authorized": True}}))
    with pytest.raises(HttpFixtureInvalid): v.jobs.authorize_receipts((invocation,))
