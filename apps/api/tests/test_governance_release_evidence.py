"""Approval grants permission; it cannot replace current release evidence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.governance import (
    GovernanceApplicationError,
    GovernanceApplicationService,
)
from apps.api.app.application.quality_loop.quality_models import ReleaseDecision
from apps.api.app.domain.quality_loop.release_decision import release_decision_status


class ReleaseWorkspace:
    def __init__(self, readiness):
        self.readiness = readiness
        self.decision = ReleaseDecision(id="decision", project_id="project", version_id="version",
            us_id="us", status="ready", score=90, rationale="Historical assessment",
            approval_ref="approval:approval", evidence_refs=["execution_evidence:previous"],
            created_at="2026-10-01T00:00:00Z")
        self.writes = []
        self.project = SimpleNamespace(system_image_status="candidate", progress=20, risk="medium")
        self.baseline = SimpleNamespace(id="official", kind="official", status="draft", updated_at="old")

    def resolve_project_id(self, invocation):
        return "project"

    def has_project(self, project_id):
        return project_id == "project"

    def require_project_access(self, project_id):
        assert project_id == "project"

    def get_approval(self, project_id, approval_id):
        assert (project_id, approval_id) == ("project", "approval")
        return SimpleNamespace(id="approval", status="approved")

    def find_release_decision(self, project_id, us_id, version_id):
        assert (project_id, us_id, version_id) == ("project", "us", "version")
        return self.decision.model_copy(deep=True)

    def get_release_readiness(self, version_id):
        assert version_id == "version"
        return self.readiness

    def list_execution_evidence(self, project_id):
        return [SimpleNamespace(id="current", us_id="us")]

    def save_release_decision(self, decision):
        self.writes.append("decision")
        self.decision = decision

    def list_baselines(self, project_id):
        return [deepcopy(self.baseline)]

    def replace_baselines(self, project_id, baselines):
        self.writes.append("baseline")
        self.baseline = baselines[0]

    def persist_system_image(self, project_id):
        self.writes.append("image")

    def get_project(self, project_id):
        return deepcopy(self.project)

    def save_project(self, project):
        self.writes.append("project")
        self.project = project


def readiness():
    return SimpleNamespace(version_id="version", score=90, blockers=0, approvals_open=0,
        pending_merge=0, evidence_summary={})


def invocation():
    return SimpleNamespace(input_payload={"project_id": "project", "version_id": "version",
        "us_id": "us", "approval_id": "approval"}, conversation_id=None)


@pytest.mark.parametrize("method", ["submit_release_decision", "promote_baseline"])
@pytest.mark.parametrize("state", ["unknown", "blocked", "missing"])
def test_stale_ready_decision_cannot_bypass_current_release_evidence(method, state):
    current = readiness()
    if state == "unknown":
        current.evidence_summary = {"quality_assessment_unknown": 1}
    elif state == "blocked":
        current.blockers = 1
    else:
        current = None
    workspace = ReleaseWorkspace(current)
    before = workspace.decision.model_copy(deep=True)
    with pytest.raises(GovernanceApplicationError, match="current release evidence"):
        getattr(GovernanceApplicationService(workspace), method)(invocation())
    assert not workspace.writes
    assert workspace.decision == before and workspace.baseline.status == "draft"


@pytest.mark.parametrize("method", ["submit_release_decision", "promote_baseline"])
def test_current_known_release_evidence_preserves_governance_path(method):
    workspace = ReleaseWorkspace(readiness())
    result = getattr(GovernanceApplicationService(workspace), method)(invocation())
    assert workspace.writes
    assert "approval:approval" in result.evidence_refs
    if method == "promote_baseline":
        assert workspace.baseline.status == "promoted"


def test_unknown_assessment_cannot_be_overridden_by_legacy_numeric_score():
    current = readiness()
    current.evidence_summary = {"quality_assessment_unknown": 1}
    assert release_decision_status(current, ["execution_evidence:current"]) == "blocked"


@pytest.mark.parametrize("score,approvals", [(70, 0), (90, 1)])
def test_conditional_decision_also_requires_execution_evidence(score, approvals):
    current = readiness()
    current.score, current.approvals_open = score, approvals
    assert release_decision_status(current, []) == "needs_evidence"
