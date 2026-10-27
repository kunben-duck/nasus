"""Admission protocol specimens; not independent business gold or target runs."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.automation_inputs import AutomationInputSelection
from apps.api.app.application.quality_loop.case_approvals import CaseApprovalApplicationService, CaseApprovalReviewInput
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.automation_input import AutomationInputChanged, compile_automation_input
from apps.api.app.domain.quality_loop.case_approval import CaseApprovalChanged, CaseApprovalIntegrityError, case_approval_basis
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_automation_input import automation_inputs


def admission_ports():
    prepared = compile_automation_input(*automation_inputs())
    selection = AutomationInputSelection(project_id=prepared["project_id"],
        mapping_revision_id=prepared["mapping_pin"]["revision_id"],
        mapping_artifact_hash=prepared["mapping_pin"]["artifact_hash"], case_ids=tuple(prepared["selected_case_ids"]))
    state = SimpleNamespace(prepared=prepared, current=True, accessible=True, role="qa_lead", rows=[], archives={}, calls=[])
    def prepare(_selection):
        state.calls.append("current")
        if not state.current:
            raise AutomationInputChanged("withdrawn original mapping")
        return deepcopy(prepared)
    def replay(_selection):
        state.calls.append("historical")
        return deepcopy(prepared)
    def access(_scope):
        if not state.accessible:
            raise SourceAccessDenied("current source access revoked")
    def get(project, revision):
        row = next(row for row in state.rows if row["revision_id"] == revision)
        assert project == prepared["project_id"]
        return deepcopy(row), revision
    def committed(request, basis, *, actor_id, invocation_id, require_access):
        require_access()
        return next((deepcopy(row) for row in state.rows if row["invocation_id"] == invocation_id), None)
    def put(project, payload):
        assert project == prepared["project_id"]
        state.pending = deepcopy(payload)
        return "pending", acceptance_digest(payload)
    def read(project, ref, digest):
        payload = state.archives[ref]
        if acceptance_digest(payload) != digest:
            raise CaseApprovalIntegrityError("original approval archive digest mismatch")
        return deepcopy(payload)
    def record(request, payload, ref, digest, *, require_current):
        assert request.expected_previous_revision_id == (state.rows[-1]["revision_id"] if state.rows else None)
        require_current()
        basis = payload["basis"]
        row = {"revision_id": "r" + str(len(state.rows) + 1), "project_id": request.project_id,
            "generation_id": basis["generation_pin"]["generation_id"], "mapping_revision_id": request.mapping_revision_id,
            "cohort_id": payload["cohort_id"], "previous_revision_id": request.expected_previous_revision_id,
            "sequence": len(state.rows) + 1, "status": "approved" if request.decision == "approve" else "withdrawn",
            "artifact_hash": digest, "request_hash": acceptance_digest(request.model_dump(mode="json")),
            "input_digest": basis["input_digest"], "case_count": len(basis["case_pins"]),
            **{key: payload[key] for key in ("authority_actor", "invocation_id", "recorded_at")}}
        state.archives[row["revision_id"]] = deepcopy(payload)
        state.rows.append(row)
        return deepcopy(row)
    repository = SimpleNamespace(history=lambda *_: deepcopy(state.rows),
        archives=lambda *_: [(deepcopy(row), row["revision_id"]) for row in state.rows], get=get, committed=committed, record=record)
    authorization = SimpleNamespace(scope=lambda project: SimpleNamespace(project_id=project, actor_id="reviewer",
        effective_project_role=state.role), require_current=access)
    service = CaseApprovalApplicationService(SimpleNamespace(prepare=prepare, replay=replay), authorization,
        repository, SimpleNamespace(put=put, read=read))
    request = CaseApprovalReviewInput(**selection.model_dump(mode="json"), expected_input_digest=prepared["input_digest"],
        expected_previous_revision_id=None, decision="approve", reason="Independent review of exact original cases")
    return service, request, state


def approve(service, request):
    return service.review(request, invocation_id="command-1", recorded_at="2026-10-13T00:00:00+00:00")


def test_case_admission_preserves_complete_original_pins_and_never_grants_execution():
    service, request, state = admission_ports()
    original = deepcopy(state.prepared)
    view = service.preview(request.selection())
    assert view["head"] is None and view["history_count"] == 0 and view["can_review"]
    assert not view["execution_authorized"] and not view["business_coverage_verified"]
    row = approve(service, request)
    result = service.resolve(request.project_id, row["revision_id"], row["artifact_hash"], state.prepared)
    assert result["current_use"] == {"case_admission_current": True, "generation_authorized": False,
        "execution_authorized": False, "business_coverage_verified": False}
    assert result["basis"]["case_pins"] == [{"case_id": case["case_id"], "case_digest": acceptance_digest(case)}
        for case in original["cases"]]
    assert result["basis"]["constraint_denominator"] == 2 and result["basis"]["obligation_denominator"] == 7
    assert state.prepared == original


@pytest.mark.parametrize("role", ["viewer", "qa_engineer", "developer"])
def test_case_admission_requires_independent_reviewer(role):
    service, request, state = admission_ports()
    state.role = role
    assert not service.preview(request.selection())["can_review"]
    with pytest.raises(SourceAccessDenied):
        approve(service, request)
    assert not state.rows and not state.archives


def test_committed_approval_replays_without_reactivating_withdrawn_inputs():
    service, request, state = admission_ports()
    row = approve(service, request)
    state.current = False
    assert approve(service, request) == row and len(state.rows) == 1
    assert not service.read(request.project_id, row["revision_id"])["current_use"]["case_admission_current"]
    with pytest.raises(CaseApprovalChanged):
        service.resolve(request.project_id, row["revision_id"], row["artifact_hash"], state.prepared)
    with pytest.raises(AutomationInputChanged):
        service.review(request, invocation_id="new-command", recorded_at="2026-10-13T00:00:00+00:00")


def test_withdrawal_appends_without_mutating_old_case_or_approval():
    service, request, state = admission_ports()
    row = approve(service, request)
    original_archive = deepcopy(state.archives[row["revision_id"]])
    state.current = False
    withdrawn = service.review(request.model_copy(update={"decision": "withdraw", "expected_previous_revision_id": row["revision_id"]}),
        invocation_id="command-2", recorded_at="2026-10-13T00:01:00+00:00")
    assert withdrawn["status"] == "withdrawn" and withdrawn["sequence"] == 2
    assert state.archives[row["revision_id"]] == original_archive
    assert not service.read(request.project_id, row["revision_id"])["current_use"]["case_admission_current"]
    assert not service.read(request.project_id, withdrawn["revision_id"])["current_use"]["case_admission_current"]


@pytest.mark.parametrize("field,value", [("case_count", 0), ("generation_id", "other"),
    ("mapping_revision_id", "other"), ("input_digest", "sha256:" + "a" * 64), ("project_id", "other")])
def test_archive_cannot_substitute_metadata_parents(field, value):
    service, request, state = admission_ports()
    row = approve(service, request)
    state.rows[0][field] = value
    with pytest.raises(CaseApprovalIntegrityError):
        service.read(request.project_id, row["revision_id"])


def test_last_source_access_check_prevents_partial_approval():
    service, request, state = admission_ports()
    put = service.artifacts.put
    def revoke(project, payload):
        value = put(project, payload)
        state.accessible = False
        return value
    service.artifacts.put = revoke
    with pytest.raises(SourceAccessDenied):
        approve(service, request)
    assert not state.rows


def test_source_withdrawal_blocks_history_and_committed_recovery():
    service, request, state = admission_ports()
    row = approve(service, request)
    state.accessible = False
    for operation in (lambda: approve(service, request), lambda: service.read(request.project_id, row["revision_id"])):
        with pytest.raises(SourceAccessDenied):
            operation()


def test_new_head_cannot_hide_missing_or_corrupt_predecessor_archive():
    service, request, state = admission_ports()
    row = approve(service, request)
    service.review(request.model_copy(update={"decision": "withdraw", "expected_previous_revision_id": row["revision_id"]}),
        invocation_id="command-2", recorded_at="2026-10-13T00:01:00+00:00")
    state.archives[row["revision_id"]]["request"]["reason"] = "Changed original approval"
    for operation in (lambda: service.preview(request.selection()), lambda: service.read(request.project_id, "r2")):
        with pytest.raises(CaseApprovalIntegrityError):
            operation()


@pytest.mark.parametrize("fault", ["digest", "authority", "missing_case", "missing_obligation"])
def test_basis_rejects_unverified_or_incomplete_input(fault):
    prepared = compile_automation_input(*automation_inputs())
    if fault == "digest": prepared["input_digest"] = "sha256:" + "0" * 64
    elif fault == "authority": prepared["execution_authorized"] = True
    elif fault == "missing_case": prepared["cases"].pop()
    else: prepared["obligations"].pop()
    if fault != "digest":
        prepared["input_digest"] = acceptance_digest({key: value for key, value in prepared.items() if key != "input_digest"})
    with pytest.raises(ValueError):
        case_approval_basis(prepared)
