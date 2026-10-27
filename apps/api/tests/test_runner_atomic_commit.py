"""Atomic execution facts on the disposable PostgreSQL database, not SQLite."""
from copy import deepcopy
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from apps.api.app.application.quality_loop.quality_models import ExecutionEvidence, RunDetail
from apps.api.app.infrastructure.persistence.database import get_database_url
from apps.api.app.infrastructure.persistence.quality_loop_repository import QualityLoopRepository
from apps.api.app.infrastructure.quality_loop import LegacyQualityRunWorkspace, SQLAlchemyQualityRunWorkspace


@pytest.fixture(params=["production", "compatibility"])
def execution_workspace(request):
    if not get_database_url().startswith("postgresql"):
        pytest.skip("requires disposable PostgreSQL")
    repository = QualityLoopRepository()
    state = SimpleNamespace(us_items={}, run_details={}, runs={}, execution_evidence={})
    lock = RLock()
    workspace = SQLAlchemyQualityRunWorkspace(repository)
    if request.param == "compatibility":
        workspace = LegacyQualityRunWorkspace(state, SimpleNamespace(mutation_guard=lambda: lock,
            quality_loop_repository=repository))
    return workspace, repository, state


def execution(project, *, ident=None):
    ident = ident or uuid4().hex
    run = RunDetail(id="run-" + ident, status="passed", channel="web_runner", title="Local fixture",
        summary="Observed fixture assertion, not business coverage", started_at="2026-10-10T00:00:00Z",
        failure_summary="", healing_status="not_required",
        us_id="fixture-us-" + project, runner_job_id="job-" + ident,
        target_base_url="http://127.0.0.1:12345", task_context_id="original-context",
        execution_plan=[{"action": "assert_text", "selector": "h1", "text": "fixture"}],
        execution_timeout_ms=1000, automation_script_id="explicit-fixture-script",
        evidence=["s3://private-test/" + ident])
    evidence = [ExecutionEvidence(id="evidence-" + ident, project_id=project, run_id=run.id,
        us_id=run.us_id, evidence_type="report", storage_ref=run.evidence[0],
        content_hash="sha256:" + "a" * 64, producer="web_runner", captured_at="2026-10-10T00:00:01Z")]
    return run, evidence


def test_atomic_commit_preserves_peer_facts_and_exact_retry(execution_workspace):
    workspace, repository, _ = execution_workspace
    project = "atomic-" + uuid4().hex
    peer, peer_evidence = execution(project)
    run, evidence = execution(project)
    repository.commit_run_execution(project, peer, peer_evidence)
    workspace.commit_run_execution(project, run, evidence)
    workspace.commit_run_execution(project, deepcopy(run), deepcopy(evidence))
    fresh = QualityLoopRepository()
    assert fresh.get_run_detail(project, run.id).model_dump() == run.model_dump()
    assert {item.id for item in fresh.list_run_details(project)} == {peer.id, run.id}
    assert {item.id for item in fresh.list_execution_evidence(project)} == {peer_evidence[0].id, evidence[0].id}


def test_late_evidence_insert_failure_rolls_back_run_without_changing_projections(execution_workspace):
    workspace, repository, state = execution_workspace
    project = "atomic-" + uuid4().hex
    peer, peer_evidence = execution(project)
    repository.commit_run_execution(project, peer, peer_evidence)
    run, evidence = execution(project)
    evidence[0].id = peer_evidence[0].id
    original = deepcopy(state.__dict__)
    with pytest.raises(IntegrityError):
        workspace.commit_run_execution(project, run, evidence)
    assert state.__dict__ == original
    fresh = QualityLoopRepository()
    assert fresh.get_run_detail(project, run.id) is None
    assert [item.id for item in fresh.list_execution_evidence(project)] == [peer_evidence[0].id]
    assert fresh.get_run_detail(project, peer.id).model_dump() == peer.model_dump()


@pytest.mark.parametrize("changed", ["project", "run", "us", "refs", "duplicate", "empty"])
def test_atomic_commit_rejects_incomplete_or_cross_scope_evidence(execution_workspace, changed):
    workspace, repository, state = execution_workspace
    project = "atomic-" + uuid4().hex
    run, evidence = execution(project)
    if changed == "project": evidence[0].project_id = "another-project"
    if changed == "run": evidence[0].run_id = "another-run"
    if changed == "us": evidence[0].us_id = "another-us"
    if changed == "refs": run.evidence = []
    if changed == "duplicate": evidence.append(deepcopy(evidence[0]))
    if changed == "empty": evidence.clear()
    with pytest.raises(ValueError, match="complete run scope"):
        workspace.commit_run_execution(project, run, evidence)
    assert repository.get_run_detail(project, run.id) is None
    assert repository.list_execution_evidence(project) == []
    assert not state.run_details and not state.runs and not state.execution_evidence


@pytest.mark.parametrize("changed", ["run", "evidence", "project"])
def test_committed_execution_cannot_be_overwritten_or_rebound(execution_workspace, changed):
    workspace, repository, state = execution_workspace
    project = "atomic-" + uuid4().hex
    run, evidence = execution(project)
    workspace.commit_run_execution(project, run, evidence)
    original = deepcopy(state.__dict__)
    attempted_run, attempted_evidence = deepcopy(run), deepcopy(evidence)
    requested_project = project
    if changed == "run": attempted_run.execution_plan[0]["text"] = "different oracle"
    if changed == "evidence": attempted_evidence[0].content_hash = "sha256:" + "b" * 64
    if changed == "project":
        requested_project = "another-project"
        attempted_evidence[0].project_id = requested_project
    with pytest.raises(ValueError, match="different facts"):
        workspace.commit_run_execution(requested_project, attempted_run, attempted_evidence)
    assert state.__dict__ == original
    assert repository.get_run_detail(project, run.id).model_dump() == run.model_dump()
    assert repository.list_execution_evidence(project)[0].model_dump() == evidence[0].model_dump()
