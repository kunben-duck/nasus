"""Real exweb/PG/MinIO receipts with explicit, non-provider reply fixtures."""
from datetime import datetime, timezone
from threading import Event, Thread
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.application.quality_loop.generation_batch_ledger import batch_execution_request
from apps.api.app.application.quality_loop.generation_batch_receipts import GenerationBatchReceiptApplicationService
from apps.api.app.application.quality_loop.generation_batch_results import GenerationBatchResultApplicationService
from apps.api.app.application.quality_loop.generation_executor import GenerationOutcomeUnknown, NativeGenerationReply
from apps.api.app.application.quality_loop.test_design_results import GENERATION_TOOL
from apps.api.app.infrastructure.persistence.db_models import LLMCallRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.generation_batch_repository import GenerationBatchRepository
from apps.api.app.infrastructure.persistence.generation_batch_result_repository import GenerationBatchResultRepository
from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignResultRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.generation_batch_reply_artifacts import GenerationBatchReplyArtifacts
from apps.api.tests.test_generation_batches import responses_for


def verify_exweb_batch_ledger(executor, jobs, selected, planned, storage):
    project_id = selected.project_id
    actor_id = executor.authorization.scope(project_id).actor_id
    request = batch_execution_request(planned)
    invocation_id = uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation_id, tool_id=GENERATION_TOOL, status="running",
            summary="Internal batch ledger fixture, NOT external generation or exweb author approval",
            input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
                "confirmed_actor_id": actor_id, "confirmed_at": datetime.now(timezone.utc).isoformat()}))
    lease = jobs.repository.claim_lease(project_id, invocation_id, uuid4().hex)
    stopped, renewal_errors = Event(), []

    def heartbeat():
        while not stopped.wait(5):
            try:
                jobs.repository.renew_lease(lease)
            except Exception as exc:
                renewal_errors.append(exc)
                return

    worker = Thread(target=heartbeat, daemon=True)
    worker.start()
    receipts = GenerationBatchReceiptApplicationService(executor.batch_planning, executor.authorization,
        jobs.repository, GenerationBatchRepository(), GenerationBatchReplyArtifacts(storage))
    try:
        plan = receipts.reserve(request, lease=lease)
        assert receipts.reserve(request, lease=lease) == plan
        responses = responses_for(planned.input, planned.plan)
        for sequence, (_, content) in enumerate(responses):
            receipts.claim(request, sequence, lease=lease)
            with pytest.raises(GenerationOutcomeUnknown):
                receipts.claim(request, sequence, lease=lease)
            receipts.archive_reply(request, sequence, NativeGenerationReply(content, 100, 50, "provider"),
                lease=lease, latency_ms=5)
        replay = receipts.read(request, lease=lease)
        assert replay["responses"] == responses
        assert all(item["artifact_ref"].startswith("s3://") for item in replay["replies"])
        assert replay["budget"]["claimed_calls"] == replay["budget"]["archived_calls"] == len(responses)
        assert replay["budget"]["unknown_calls"] == 0 and not replay["budget"]["reservation_released"]
        checked = executor.batch_planning.check_outputs(selected, expected_planning_digest=planned.digest,
            responses=replay["responses"])
        coverage = checked["proposal"]["coverage"]
        assert coverage["constraint_denominator"] == 2 and coverage["obligation_denominator"] == 8
        assert coverage["passed_count"] == coverage["executed_on_target_count"] == 0
        with session_scope() as session:
            calls = session.scalars(select(LLMCallRecord).where(LLMCallRecord.tool_invocation_id == invocation_id)).all()
            assert len(calls) == len(responses)
            assert all(call.prompt_version == "batch-v1" and call.model_calls == 1 for call in calls)
            assert session.scalar(select(func.count()).select_from(TestDesignResultRecord).where(
                TestDesignResultRecord.invocation_id == invocation_id)) == 0
        assert not renewal_errors
        results = GenerationBatchResultApplicationService(receipts, GenerationBatchResultRepository(), executor.results.artifacts)
        metadata = results.commit(request, lease=lease)
        assert results.commit(request, lease=lease) == metadata
        stored = results.repository.get(project_id, metadata["generation_id"])
        assert stored["artifact_ref"].startswith("s3://") and metadata["call_id"] is None
        result = executor.results.read(project_id, metadata["generation_id"])
        assert result["result"]["schema"] == "nasus.test-design-result.v3"
        assert result["result"]["proposal"]["coverage"] == coverage
        assert jobs.repository.finish(project_id, invocation_id, "completed",
            "Explicit fixture aggregate archived; NOT external model or target validation.", lease=lease) == "completed"
        assert executor.results.read(project_id, metadata["generation_id"])["result"] == result["result"]
        return {"planning_digest": planned.digest, "batch_count": len(responses),
            "source_binding_count": len(request.execution.source_binding_ids),
            "estimated_input_tokens": plan.reservation.estimated_input_tokens,
            "minio_private_reply_roundtrip_verified": True, "individual_call_audits_verified": True,
            "duplicate_call_claim_rejected": True, "complete_original_obligations_verified": True,
            "native_provider_request_count": 0, "aggregate_result_committed": True, "metadata": metadata,
            "minio_aggregate_roundtrip_verified": True, "aggregate_replay_without_egress_verified": True,
            "multi_call_execution_enabled": False, "temporal_execution_in_this_fixture": False,
            "reply_and_usage_source": "explicit_fixture_not_external_provider_or_author_approval",
            "target_executed": False, "passed_count": 0}
    finally:
        stopped.set()
        worker.join(10)
        jobs.repository.release_lease(lease)
