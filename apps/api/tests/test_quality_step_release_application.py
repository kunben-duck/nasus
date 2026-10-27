"""Release conversation guidance must agree with the domain state transition."""
import asyncio
from unittest.mock import Mock

import pytest

from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.application.quality_loop.quality_models import ReleaseReadiness
from apps.api.app.application.quality_loop.quality_steps import QualityStepCompletionApplicationService


@pytest.mark.parametrize("changes, blocked", [
    ({"score": 79}, True),
    ({"score": 59}, True),
    ({"approvals_open": 1}, True),
    ({"pending_merge": 1}, True),
    ({"blockers": 1}, True),
    ({"status": "Needs additional release evidence"}, True),
    ({"evidence_summary": {"quality_assessment_unknown": 1}}, True),
    ({"score": 80}, False),
    ({"score": 100}, False),
])
def test_release_guidance_and_all_updates_use_the_same_original_assessment(changes, blocked):
    assessment = ReleaseReadiness(**{
        "version_id": "version-original", "status": "Ready for release review", "score": 90,
        "blockers": 0, "approvals_open": 0, "pending_merge": 0,
        "execution_health": "Original observed execution", "summary": "Original assessment",
        "evidence_summary": {"quality_assessment_unknown": 0}, **changes,
    })
    before = assessment.model_dump()
    scope = Mock(spec=["resolve_scope", "query_keys_for"])
    scope.resolve_scope.return_value = ("project", "us-original")
    scope.query_keys_for.return_value = [["project", "project"]]
    refresh = Mock(spec=["refresh_project"])
    progress = Mock(spec=["ensure_asset_lanes", "update_lane", "touch_us"])
    packs = Mock(spec=["upsert_part"])
    packs.upsert_part.return_value = ["asset:original"]
    readiness = Mock(spec=["upsert_release_readiness"])
    readiness.upsert_release_readiness.return_value = assessment
    metrics = Mock(spec=["record_quality_image_update"])
    metrics.record_quality_image_update.return_value = ["metric:original"]
    execution = Mock(spec=["evidence_refs_for_us"])
    execution.evidence_refs_for_us.return_value = ["execution_evidence:original"]
    generator = Mock(spec=["generate"])
    service = QualityStepCompletionApplicationService(
        read_model_refresh=refresh, context_queries=Mock(spec=[]), scope_queries=scope,
        asset_progress=progress, asset_packs=packs, release_readiness=readiness,
        quality_image_updates=metrics, run_execution=execution, quality_generator=generator,
    )
    invocation = ToolInvocation(id="invocation", tool_id="release.assess", status="running",
        summary="Assessing", input_payload={"project_id": "project", "us_id": "us-original"})
    result = asyncio.run(service.complete_quality_step(invocation, step="release"))

    assert result is not None
    assert ("Release remains blocked" in result.assistant_message) is blocked
    assert ("ready for human release review" in result.assistant_message) is (not blocked)
    assert ("approval.request" in result.next_tools) is (not blocked)
    expected_status = "blocked" if blocked else "completed"
    progress.update_lane.assert_called_once_with("project", "us-original", "release",
        status=expected_status, summary=(assessment.summary if blocked else
            "Release readiness score is complete. Formal ReleaseDecision still requires approval."))
    progress.touch_us.assert_called_once_with("project", "us-original",
        progress=70 if blocked else 92, status="blocked" if blocked else "release_ready",
        next_action="Resolve release evidence gaps" if blocked else "Request release approval")
    assert packs.upsert_part.call_args.kwargs["status"] == expected_status
    assert packs.upsert_part.call_args.kwargs["evidence_refs"] == ["execution_evidence:original"]
    update = metrics.record_quality_image_update.call_args.kwargs
    assert update["metrics"]["release_score"] == assessment.score
    assert update["evidence_refs"] == [
        "release_readiness:version-original", "execution_evidence:original", "us:us-original"]
    assert result.evidence_refs == ["execution_evidence:original"]
    readiness.upsert_release_readiness.assert_called_once_with("project", "us-original")
    refresh.refresh_project.assert_called_once_with("project")
    generator.generate.assert_not_called()
    assert assessment.model_dump() == before
