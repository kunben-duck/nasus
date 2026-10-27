"""Application-port specimens; real PG/Node/MinIO is exercised in plan API tests."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace, asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.run_plan_observation_receipts import RunPlanObservationReceiptAccess
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.platform.tool_receipt_access import require_receipt_access
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.quality_loop.run_plan_observation_records import (
    ObservationRecordRequest, ObservationRecordQuery, RunPlanObservationRecordApplicationService,
    OBSERVATION_RECORD_TOOL, OBSERVATION_RECORD_QUERY_TOOL,
)
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_observation_record import observation_record_metadata
from apps.api.app.domain.quality_loop.run_plan_observations import RunPlanObservationInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_run_plan_observation_archives import inputs
from apps.api.app.infrastructure.persistence.run_plan_observation_repository import RunPlanObservationRepository


class RegistrationSpecimen:
    def __init__(self):
        self.values, self.calls = {}, []

    def committed(self, request, *, actor_id, invocation_id, require_access):
        require_access()
        return self.values.get(invocation_id, {}).get("metadata")

    def record(self, request, archive, ref, metadata, *, require_access):
        require_access()
        self.calls.append(metadata["record_id"])
        self.values[metadata["invocation_id"]] = {"metadata": deepcopy(metadata), "artifact_ref": ref,
            "request": request.model_dump(mode="json")}
        return deepcopy(metadata)

    def read(self, project_id, record_id):
        return deepcopy(next(value for value in self.values.values()
            if value["metadata"]["project_id"] == project_id and value["metadata"]["record_id"] == record_id))


def record_inputs(*, unknown=False, empty=False):
    plan, entries, archive_service, artifacts, storage, access = inputs()
    storage.config.s3_enabled = True
    artifact = {"project_id": plan["project_id"], "run_plan_id": access.parent.run_plan_id, "plan": plan}
    access.parent = type(access.parent)(**{**access.parent.model_dump(mode="json"),
        "run_plan_artifact_hash": acceptance_digest(artifact)})
    if unknown:
        result = archive_service._result(entries[0]["result"])
        entries[0]["result"] = asdict(replace(result, status="error", artifacts=(), execution_receipt=None))
    saved = archive_service.archive(plan, [] if empty else entries, run_id="explicit-archive-attempt", timeout_ms=5000)
    request = ObservationRecordRequest(**access.parent.model_dump(mode="json"),
        observation_artifact_hash=saved["artifact_hash"], collection_digest=saved["summary"]["collection_digest"], run_id=saved["run_id"])
    view = {"artifact": artifact, "metadata": {**access.parent.model_dump(mode="json"), "artifact_hash": acceptance_digest(artifact)}}
    state = SimpleNamespace(allowed=True, depth=0, sessions=0, checks=0, role="qa_lead", case_count=len(plan["prepared"]["cases"]))

    def allowed():
        state.checks += 1
        if not state.allowed:
            raise SourceAccessDenied("explicit source revocation")

    def plan_read(project_id, run_plan_id):
        allowed()
        assert state.depth == 1
        assert (project_id, run_plan_id) == (plan["project_id"], artifact["run_plan_id"])
        return deepcopy(view)

    @contextmanager
    def session():
        assert state.depth == 0
        state.sessions += 1
        state.depth = 1
        try:
            yield
        finally:
            state.depth = 0

    def scope(project_id):
        allowed()
        return SimpleNamespace(actor_id="explicit-reviewer", effective_project_role=state.role)

    repo = RegistrationSpecimen()
    application = RunPlanObservationRecordApplicationService(SimpleNamespace(read=plan_read, verified_read_session=session),
        SimpleNamespace(scope=scope, require_current=lambda original: allowed()), archive_service.observations, artifacts, repo)
    return application, request, state, repo, storage


@pytest.mark.parametrize("unknown,empty", [(False, False), (True, False), (False, True)])
def test_record_preserves_complete_case_actions_oracles_and_zero_formal_coverage(unknown, empty):
    application, request, state, repo, _storage = record_inputs(unknown=unknown, empty=empty)
    metadata = application.record(request, invocation_id="explicit-record-command", recorded_at="2026-10-10T10:00:00+00:00")
    assert state.depth == 0 and state.sessions == 1
    assert metadata["case_count"] == len(metadata["members"]) == state.case_count
    assert metadata["outcome_unknown_case_count"] == int(unknown)
    assert metadata["no_result_case_count"] == (state.case_count if empty else 0)
    assert metadata["automated_count"] == metadata["executed_on_target_count"] == metadata["passed_count"] == 0
    assert metadata["execution_authorized"] is metadata["canonical_execution_committed"] is False
    view = application.read(request.project_id, metadata["record_id"])
    assert state.sessions == 2 and state.depth == 0
    assert view["metadata"] == metadata
    if not empty:
        assert all(member["actions"] and member["oracles"] for member in metadata["members"])
    replay = application.record(request, invocation_id="explicit-record-command", recorded_at="later-time-does-not-rewrite-history")
    assert replay == metadata and len(repo.calls) == 1 and state.sessions == 3
    receipt = application.receipt(request.project_id, metadata["record_id"])
    assert "members" not in receipt["metadata"] and "archive" not in receipt
    assert "artifact_ref" not in str(receipt) and "base_url" not in str(receipt)


@pytest.mark.parametrize("fault", ["run_id", "collection_digest", "observation_artifact_hash", "run_plan_artifact_hash"])
def test_record_cannot_rebind_any_confirmed_original_pin(fault):
    application, request, state, repo, _storage = record_inputs()
    values = request.model_dump(mode="json")
    values[fault] = "another-attempt" if fault == "run_id" else acceptance_digest("another-original-input")
    with pytest.raises(RunPlanObservationInvalid):
        application.record(ObservationRecordRequest.model_validate(values), invocation_id="explicit-command", recorded_at="now")
    assert repo.calls == [] and state.depth == 0


def test_record_role_revocation_and_private_bytes_corruption_fail_closed():
    application, request, state, repo, storage = record_inputs()
    state.role = "member"
    with pytest.raises(SourceAccessDenied):
        application.record(request, invocation_id="explicit-command", recorded_at="now")
    state.role = "qa_lead"
    state.allowed = False
    with pytest.raises(SourceAccessDenied):
        application.record(request, invocation_id="explicit-command", recorded_at="now")
    state.allowed = True
    ref = application.artifacts.reference(request.project_id, request.observation_artifact_hash)
    storage.objects[ref] += b" "
    with pytest.raises(RunPlanObservationInvalid):
        application.record(request, invocation_id="explicit-command", recorded_at="now")
    assert repo.calls == [] and state.depth == 0


def test_rehashed_summary_cannot_inflate_counts_or_claim_execution_authority():
    application, request, _state, _repo, _storage = record_inputs()
    with application._read_session():
        archive = application._read_archive(request, application.artifacts.reference(request.project_id, request.observation_artifact_hash))
    for fault in ("passed_observation_count", "execution_authorized"):
        changed = deepcopy(archive)
        if fault == "execution_authorized": changed[fault] = True
        else: changed["summary"][fault] += 1
        values = {**request.model_dump(mode="json"), "observation_artifact_hash": acceptance_digest(changed)}
        with pytest.raises(RunPlanObservationInvalid):
            observation_record_metadata(changed, values, record_id="record", invocation_id="command", actor_id="actor", recorded_at="now")


@pytest.mark.parametrize("field,value", [("artifact_ref", "s3://arbitrary-bucket/response.json"), ("raw_results", []), ("execution_authorized", True)])
def test_record_request_cannot_import_arbitrary_url_results_or_authority(field, value):
    _application, request, _state, _repo, _storage = record_inputs()
    with pytest.raises(ValueError):
        ObservationRecordRequest.model_validate({**request.model_dump(mode="json"), field: value})


def test_receipts_reauthorize_all_inputs_and_shared_broadcast_has_no_private_payload():
    application, request, state, _repo, _storage = record_inputs()
    policy = RunPlanObservationReceiptAccess(application)
    invocation = ToolInvocation(id="explicit-command", conversation_id="explicit-conversation", tool_id=OBSERVATION_RECORD_TOOL,
        input_payload=request.model_dump(mode="json"), status="running", summary="private status", created_at="now",
        result=ToolResult(invocation_id="explicit-command", status="completed", summary="private result"))
    policy.require_access(invocation)
    projected = policy.broadcast_view(invocation)
    assert projected.input_payload == {} and projected.result is None
    assert invocation.input_payload == request.model_dump(mode="json")
    state.allowed = False
    with pytest.raises(PlatformApplicationError) as exc:
        policy.require_batch_access((invocation,))
    assert exc.value.status_code == 403
    with pytest.raises(PlatformApplicationError):
        require_receipt_access(None, invocation)


@pytest.mark.parametrize("fault", [None, "missing_consent", "numeric_consent", "expired", "future", "naive",
    "actor", "completed", "other_tool", "request", "conversation_project"])
def test_observation_canonical_confirmation_cannot_inherit_plan_consent_or_rebind_scope(fault):
    """Command/session specimens test policy only, not PostgreSQL persistence."""
    _application, request, _state, _repo, _storage = record_inputs()
    actor = "explicit-reviewer"
    now = datetime.now(timezone.utc)
    command = SimpleNamespace(id="original-command", conversation_id="original-conversation", tool_id=OBSERVATION_RECORD_TOOL,
        status="running", input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
            "confirmed_at": now.isoformat(), "confirmed_actor_id": actor})
    conversation = SimpleNamespace(project_id=request.project_id)
    if fault == "missing_consent": command.input_payload.pop("confirmed_by_user")
    elif fault == "numeric_consent": command.input_payload["confirmed_by_user"] = 1
    elif fault == "expired": command.input_payload["confirmed_at"] = (now - timedelta(minutes=16)).isoformat()
    elif fault == "future": command.input_payload["confirmed_at"] = (now + timedelta(seconds=30)).isoformat()
    elif fault == "naive": command.input_payload["confirmed_at"] = now.replace(tzinfo=None).isoformat()
    elif fault == "actor": command.input_payload["confirmed_actor_id"] = "another-reviewer"
    elif fault == "completed": command.status = "completed"
    elif fault == "other_tool": command.tool_id = "quality.run_plan.prepare"
    elif fault == "request": command.input_payload["collection_digest"] = acceptance_digest("other-collection")
    elif fault == "conversation_project": conversation.project_id = "another-project"
    session = SimpleNamespace(scalar=lambda query: command, get=lambda model, ident: conversation)
    if fault:
        with pytest.raises(ValueError):
            RunPlanObservationRepository._canonical(session, request, command.id, actor)
    else:
        assert RunPlanObservationRepository._canonical(session, request, command.id, actor) is command
        command.status = "completed"
        command.input_payload["confirmed_at"] = (now - timedelta(days=1)).isoformat()
        assert RunPlanObservationRepository._canonical(session, request, command.id, actor, historical=True) is command
