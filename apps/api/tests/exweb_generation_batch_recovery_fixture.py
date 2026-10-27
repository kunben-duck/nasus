"""Exweb/PG/MinIO recovery evidence, with explicit internal reply/consent fixtures."""
import asyncio
from datetime import datetime, timezone
from threading import Event, Thread
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.application.quality_loop.generation_batch_executor import GenerationBatchExecutorApplicationService
from apps.api.app.application.quality_loop.generation_batch_ledger import batch_execution_request
from apps.api.app.application.quality_loop.generation_batch_receipts import GenerationBatchReceiptApplicationService
from apps.api.app.application.quality_loop.generation_batch_recovery import GenerationBatchRecoveryRequest
from apps.api.app.application.quality_loop.generation_batch_recovery_results import GenerationBatchRecoveryApplicationService
from apps.api.app.application.quality_loop.generation_batch_results import GenerationBatchResultApplicationService
from apps.api.app.application.quality_loop.generation_executor import NativeGenerationReply
from apps.api.app.application.quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL
from apps.api.app.application.quality_loop.generation_jobs import GenerationJobApplicationService
from apps.api.app.application.quality_loop.test_design_results import GENERATION_TOOL
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.generation_batch_recovery_models import GenerationBatchRecoveryResultRecord
from apps.api.app.infrastructure.persistence.generation_batch_recovery_repository import GenerationBatchRecoveryRepository
from apps.api.app.infrastructure.persistence.generation_batch_repository import GenerationBatchRepository
from apps.api.app.infrastructure.persistence.generation_batch_result_repository import GenerationBatchResultRepository
from apps.api.app.infrastructure.persistence.test_design_result_models import TestDesignResultRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.generation_batch_reply_artifacts import GenerationBatchReplyArtifacts
from apps.api.tests.test_generation_batches import responses_for


def verify_exweb_archived_batch_recovery(executor, jobs, selected, planned, storage):
    project_id = selected.project_id
    actor_id = executor.authorization.scope(project_id).actor_id
    request = batch_execution_request(planned)
    source_id, recovery_id = uuid4().hex, uuid4().hex
    replies = GenerationBatchReplyArtifacts(storage)
    receipts = GenerationBatchReceiptApplicationService(executor.batch_planning, executor.authorization,
        jobs.repository, GenerationBatchRepository(), replies)
    results = GenerationBatchResultApplicationService(receipts, GenerationBatchResultRepository(), executor.results.artifacts)
    recovery = GenerationBatchRecoveryApplicationService(executor.batch_planning, executor.authorization,
        GenerationBatchRecoveryRepository(), replies, executor.results.artifacts)
    recovering_jobs = GenerationJobApplicationService(executor, jobs.repository, None, batch_recovery=recovery)

    class NoProvider:
        async def generate(self, *args, **kwargs):
            raise AssertionError("archive recovery must never make a Provider request")

    previous_executor = getattr(executor, "batch_executor", None)
    executor.batch_executor = GenerationBatchExecutorApplicationService(receipts, NoProvider(), results=results)

    def command(ident, tool, payload):
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=ident, tool_id=tool, status="running",
                summary="Explicit internal recovery/consent fixture, NOT exweb author approval or public Tool dispatch",
                input_payload={**payload, "confirmed_by_user": True, "confirmed_actor_id": actor_id,
                    "confirmed_at": datetime.now(timezone.utc).isoformat()}))

    command(source_id, GENERATION_TOOL, request.model_dump(mode="json"))
    lease = jobs.repository.claim_lease(project_id, source_id, uuid4().hex)
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
    try:
        plan = receipts.reserve(request, lease=lease)
        responses = responses_for(planned.input, planned.plan)
        for sequence, (_, content) in enumerate(responses):
            receipts.claim(request, sequence, lease=lease)
            receipts.archive_reply(request, sequence, NativeGenerationReply(content, 100, 50, "provider"),
                lease=lease, latency_ms=5)
        assert not renewal_errors
        assert jobs.repository.finish(project_id, source_id, "failed",
            "Explicit all-replies-archived terminal fixture; no target executed.", lease=lease) == "failed"
        stopped.set()
        worker.join(10)
        jobs.repository.release_lease(lease)

        offer = recovering_jobs.read(project_id, source_id)
        assert offer["reply_archived"] and offer["generation_id"] is None
        assert not offer["provider_outcome_unknown"] and "artifact_ref" not in str(offer)
        pins = GenerationBatchRecoveryRequest.model_validate(offer["recovery_request"])
        assert len(pins.replies) == len(responses)
        command(recovery_id, GENERATION_RECOVER_TOOL, pins.model_dump(mode="json"))

        append = EventOutboxRepository.append
        def fail_outbox(self, event, **kwargs):
            if event.event_type == "quality.test_design.generated":
                raise RuntimeError("explicit exweb recovered-result outbox rollback fixture")
            return append(self, event, **kwargs)

        with patch.object(EventOutboxRepository, "append", fail_outbox):
            with pytest.raises(RuntimeError, match="outbox rollback fixture"):
                asyncio.run(recovering_jobs.run(recovery_id))
        assert jobs.repository.command(recovery_id)[1] == "running"
        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(TestDesignResultRecord).where(
                TestDesignResultRecord.invocation_id == source_id)) == 0
            assert session.scalar(select(func.count()).select_from(GenerationBatchRecoveryResultRecord).where(
                GenerationBatchRecoveryResultRecord.source_invocation_id == source_id)) == 0
        assert asyncio.run(recovering_jobs.run(recovery_id)) == "completed"
        assert asyncio.run(recovering_jobs.run(recovery_id)) == "completed"
        state = recovering_jobs.read(project_id, recovery_id)
        assert state["recovery_request"] is None and state["source_invocation_id"] == source_id
        view = executor.results.read(project_id, state["generation_id"])
        metadata = view["metadata"]
        assert metadata["schema"] == "nasus.test-design-result.v4"
        assert metadata["recovery_invocation_id"] == recovery_id
        assert len(metadata["call_ids"]) == len(responses)
        assert view["result"]["recovery_request"] == pins.model_dump(mode="json")
        assert view["result"]["proposal"]["coverage"]["obligation_denominator"] == len(planned.input["obligations"])
        assert view["result"]["proposal"]["coverage"]["executed_on_target_count"] == 0
        assert jobs.repository.command(source_id)[1] == "failed"
        stored = results.repository.get(project_id, metadata["generation_id"])
        assert stored["metadata"] == metadata
        assert stored["artifact_ref"].startswith("s3://")
        assert executor.results.artifacts.read(project_id, stored["artifact_ref"], metadata["artifact_hash"]) == view["result"]
        return {"metadata": metadata, "planning_digest": planned.digest, "batch_count": len(responses),
            "source_binding_count": len(request.execution.source_binding_ids),
            "estimated_input_tokens": plan.reservation.estimated_input_tokens,
            "minio_recovered_result_roundtrip_verified": True, "outbox_rollback_then_retry_verified": True,
            "new_recovery_command_verified": True, "source_failed_command_preserved": True,
            "native_provider_request_count": 0, "public_tool_dispatch_in_this_fixture": False,
            "temporal_execution_in_this_fixture": False,
            "reply_and_usage_source": "explicit_internal_fixture_not_external_provider_or_author_approval",
            "target_executed": False, "passed_count": 0}
    finally:
        stopped.set()
        worker.join(10)
        jobs.repository.release_lease(lease)
        executor.batch_executor = previous_executor
