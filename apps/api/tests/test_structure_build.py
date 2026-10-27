from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.api.app.application.system_image.build_plans import StoredBuildPlan
from apps.api.app.application.system_image.structure_builds import (
    StructureBuildApplicationService, StructureBuildInput, StructureBuildTarget,
)
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.image_revision import ImageRevisionSummary
from apps.api.tests.test_build_plan import manifest, plan


@pytest.fixture
def structural_work():
    proposal = plan()
    stored = StoredBuildPlan("plan", "project", proposal.digest, "now", proposal)
    plans = SimpleNamespace(read=Mock(return_value=stored), manifests=SimpleNamespace(get_manifest=Mock(return_value=manifest())),
        authorization=SimpleNamespace(scope=Mock(return_value=object()), require_current=Mock()))
    target = StructureBuildTarget("project", None, datetime.now(timezone.utc).isoformat())
    revision = ImageRevisionSummary("image", "project", "baseline", "manifest", manifest().content_hash,
        "sha256:" + "a" * 64, "sha256:" + "b" * 64, "nasus.image-candidate.v1", target.confirmed_at, 1, 1, 0)
    repository = SimpleNamespace(validate=Mock(return_value=target), completed=Mock(return_value=None))
    preparation = SimpleNamespace(prepare=Mock(return_value=SimpleNamespace(revision=revision)))
    service = StructureBuildApplicationService(plans, preparation, repository)
    request = StructureBuildInput(project_id="project", plan_id="plan", plan_digest=proposal.digest, target_baseline_id="baseline")
    return SimpleNamespace(service=service, request=request, plans=plans, repository=repository,
        preparation=preparation, revision=revision, target=target)


def test_structural_work_passes_fixed_manifest_and_commit_binding(structural_work):
    v = structural_work
    assert v.service.execute(v.request, invocation_id="inv") == v.revision
    args, kwargs = v.preparation.prepare.call_args
    assert args == (manifest(),)
    assert kwargs["baseline_id"] == "baseline" and kwargs["recorded_at"] == v.target.confirmed_at
    assert kwargs["build_commit"].binding.plan_digest == v.request.plan_digest
    assert kwargs["build_commit"].binding.invocation_id == "inv"
    kwargs["check_phase"]()
    kwargs["build_commit"].require_current()


def test_existing_artifact_replays_without_spending_more_extraction_time(structural_work):
    v = structural_work
    v.repository.completed.return_value = v.revision
    v.repository.validate.return_value = replace(v.target, confirmed_at="2000-01-01T00:00:00+00:00")
    assert v.service.execute(v.request, invocation_id="inv") == v.revision
    v.preparation.prepare.assert_not_called()
    assert v.plans.authorization.require_current.call_count >= 2


def test_expired_work_stops_before_reading_archived_bytes(structural_work):
    v = structural_work
    v.repository.validate.return_value = replace(v.target, confirmed_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    with pytest.raises(TimeoutError, match="time budget"):
        v.service.execute(v.request, invocation_id="inv")
    v.preparation.prepare.assert_not_called()


@pytest.mark.parametrize("changes", [{"project_id": "foreign"}, {"baseline_id": "foreign"},
    {"manifest_id": "different"}, {"manifest_hash": "wrong"}, {"status": "official"}, {"publication": "published"}])
@pytest.mark.parametrize("replay", [False, True])
def test_out_of_scope_or_published_adapter_result_is_never_accepted(structural_work, changes, replay):
    v = structural_work
    corrupt = replace(v.revision, **changes)
    if replay:
        v.repository.completed.return_value = corrupt
    else:
        v.preparation.prepare.return_value = SimpleNamespace(revision=corrupt)
    with pytest.raises(BuildPlanIntegrityError, match="confirmed inputs"):
        v.service.execute(v.request, invocation_id="inv")


def test_changed_manifest_or_confirmation_target_never_reaches_extraction(structural_work):
    v = structural_work
    v.plans.manifests.get_manifest.return_value = replace(manifest(), project_id="other")
    with pytest.raises(BuildPlanIntegrityError, match="inputs"):
        v.service.execute(v.request, invocation_id="inv")
    v.plans.manifests.get_manifest.return_value = manifest()
    v.repository.validate.side_effect = [v.target, replace(v.target, version_id="new-version")]
    with pytest.raises(BuildPlanIntegrityError, match="target changed"):
        v.service.execute(v.request, invocation_id="inv")
    v.preparation.prepare.assert_not_called()
