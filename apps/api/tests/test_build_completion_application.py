from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.build_completions import BuildCompletionApplicationService, BuildCompletionInput
from apps.api.app.application.system_image.source_deltas import SourceBodyVerification
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.source_delta import SourceDeltaSnapshot, SourceRevisionPin
from apps.api.app.domain.system_image.source_inventory import SourceInventoryEntry
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.agent_resume_fixtures import paused_goal
from apps.api.tests.test_build_completion import inputs
from apps.api.app.application.system_image.build_completions import CompletionOwnershipPin
from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint
from apps.api.app.domain.system_image.gap_ownership import GapResponsibility, report_gaps
from apps.api.app.domain.system_image.owned_build_completion import CompletionOwnershipProof
from dataclasses import asdict, replace


def bounded_completion(file_count, total_bytes):
    plan, review, _, _ = inputs()
    goal = paused_goal()
    goal.project_id, goal.pause_reason = "project", "build_completion_review"
    request = BuildCompletionInput(project_id="project", investigation_revision_id="investigation",
        investigation_revision_hash=snapshot_digest("investigation"), expected_goal=goal.model_dump(mode="json"))
    record = SimpleNamespace(revision_id=request.investigation_revision_id, revision_hash=request.investigation_revision_hash,
        request=SimpleNamespace(goal_id=goal.id, image_revision_id="image"), review=review)
    pin = SourceRevisionPin("project", "code", "revision", "code", "fixed", snapshot_digest("manifest"), snapshot_digest("bodies"))
    files = tuple(SourceInventoryEntry(f"{index:05}.py", "file", "included", "captured",
                  total_bytes if index == 0 else 0, snapshot_digest(str(index))) for index in range(file_count))
    snapshot = SourceDeltaSnapshot(pin, files, (), None)
    verified = []
    def verify(project_id, revision_id, expected):
        assert project_id == "project" and revision_id == "revision" and expected == snapshot
        verified.append(revision_id)
        return SourceBodyVerification(pin, file_count, total_bytes, snapshot_digest("verified"))
    images = SimpleNamespace(verified_read_session=lambda **kwargs: nullcontext(),
        frozen_snapshot=lambda *args: (None, {"members": []}), verify_evidence_selection=lambda *args: None)
    authorization = SimpleNamespace(scope=lambda project_id: "scope", require_current=lambda scope: None)
    investigations = SimpleNamespace(repository=SimpleNamespace(read=lambda *args: record, require_checkpoint=lambda checkpoint: None),
        read=lambda *args: record, require_access=lambda *args: SimpleNamespace(proposal=plan),
        plans=SimpleNamespace(authorization=authorization), images=images)
    sources = SimpleNamespace(snapshot=lambda *args: snapshot, verify_bodies=verify)
    return BuildCompletionApplicationService(investigations, sources, None), request, verified


@pytest.mark.parametrize("file_count,total_bytes", [(5001, 1), (1, 100 * 1024 * 1024 + 1)])
def test_complete_verification_bounds_reject_before_any_body_reads(file_count, total_bytes):
    application, request, verified = bounded_completion(file_count, total_bytes)
    with pytest.raises(BuildPlanIntegrityError, match="no partial report"):
        application.read(request)
    assert not verified


@pytest.mark.parametrize("file_count,total_bytes", [(5000, 1), (1, 100 * 1024 * 1024)])
def test_exact_verification_bounds_preserve_all_files_and_bytes(file_count, total_bytes):
    application, request, verified = bounded_completion(file_count, total_bytes)
    report = application.read(request)
    assert verified == ["revision"]
    assert report["state"] == "blocked" and not report["goal_completed"]
    assert report["source_scans"][0]["verified_file_count"] == file_count
    assert report["source_scans"][0]["verified_byte_count"] == total_bytes
    assert "full_source_bytes_unverified" not in report["blockers"]


@pytest.mark.parametrize("failure", [False, True])
def test_completion_keeps_the_live_read_transport_scoped_through_every_validation(failure):
    application, request, _ = bounded_completion(1, 2)
    calls = []
    @contextmanager
    def live_reads():
        calls.append("open")
        try:
            yield
        finally:
            calls.append("close")
    application.investigations.plans.authorization.live_read_session = live_reads
    original = application.sources.verify_bodies
    def verify(*args):
        assert calls == ["open"]
        if failure:
            raise BuildPlanIntegrityError("verification failed")
        return original(*args)
    application.sources.verify_bodies = verify
    if failure:
        with pytest.raises(BuildPlanIntegrityError, match="verification failed"):
            application.read(request)
    else:
        assert application.read(request)["state"] == "blocked"
    assert calls == ["open", "close"]


def owned_completion():
    application, request, verified = bounded_completion(1, 2)
    original = application.read(request)
    original.update(schema="nasus.image-build-completion.v2", build_lineages=[])
    assignments = tuple(GapResponsibility(gap["gap_id"], "owner", "Inspect this fixed unresolved gap") for gap in report_gaps(original))
    proof = CompletionOwnershipProof("original", snapshot_digest(original), "revision", snapshot_digest("revision"), assignments)
    pin = CompletionOwnershipPin(**{key: getattr(proof, key) for key in CompletionOwnershipPin.model_fields})
    request = BuildCompletionInput(**{**request.model_dump(), "analysis_policy": "committed_build", "ownership_pin": pin})
    calls = []
    def resolve(selected, checkpoint, *, require_current):
        assert selected == pin and checkpoint == request.expected_goal
        calls.append(require_current)
        return original, proof
    application.ownership = SimpleNamespace(resolve_completion=resolve)
    return application, request, verified, original, proof, calls


def test_owned_assessment_uses_the_fixed_original_observation_and_explicit_replay_mode():
    application, request, verified, original, _, calls = owned_completion()
    result = application.read(request)
    assert verified == ["revision"] and calls == [True]
    assert result["schema"] == "nasus.image-build-completion.v3"
    assert original["goal_checkpoint"] == asdict(AgentResumeCheckpoint.capture(request.expected_goal))
    assert application.read(request, require_checkpoint=False) == result
    assert calls == [True, False] and verified == ["revision"]


@pytest.mark.parametrize("damage", ["missing_port", "proof_pin", "investigation", "checkpoint", "source_body"])
def test_owned_assessment_never_trusts_a_mismatched_or_unavailable_application_proof(damage):
    application, request, _, original, proof, _ = owned_completion()
    if damage == "missing_port":
        application.ownership = None
    else:
        if damage == "proof_pin":
            proof = replace(proof, revision_hash=snapshot_digest("other"))
        elif damage == "investigation":
            original["investigation_revision_id"] = "other"
        elif damage == "checkpoint":
            original["goal_checkpoint"] = {**original["goal_checkpoint"], "digest": snapshot_digest("other")}
        elif damage == "source_body":
            application.ownership = SimpleNamespace(resolve_completion=lambda *args, **kwargs: (
                _ for _ in ()).throw(BuildPlanIntegrityError("Original archived source bytes changed")))
        if damage != "source_body":
            application.ownership = SimpleNamespace(resolve_completion=lambda *args, **kwargs: (original, proof))
    with pytest.raises(BuildPlanIntegrityError):
        application.read(request)
