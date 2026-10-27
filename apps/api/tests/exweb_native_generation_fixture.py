"""Exweb + real tokenizer/PG/MinIO, with explicit native HTTP response fixtures."""
import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx

from apps.api.app.application.quality_loop.generation_executor import GenerationExecutorApplicationService
from apps.api.app.application.quality_loop.generation_execution_inputs import GenerationExecutionSelection
from apps.api.app.application.quality_loop.generation_jobs import GenerationJobApplicationService
from apps.api.app.application.quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL, GenerationRecoveryRequest, GenerationHistoryRequest
from apps.api.app.application.quality_loop.test_design_results import GenerationResultRequest, GENERATION_TOOL
from apps.api.app.application.system_image.generation_sources import ImageGenerationSourceInventory
from apps.api.app.infrastructure.llm.generation_token_budget import LocalGenerationTokenCounter, tiktoken_policy_digest
from apps.api.app.infrastructure.llm.test_design_model import HTTPTestDesignModel
from apps.api.app.infrastructure.persistence.generation_execution_repository import GenerationExecutionRepository
from apps.api.app.infrastructure.persistence.generation_job_repository import GenerationJobRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.generation_reply_artifacts import GenerationReplyArtifacts
from apps.api.tests.test_generation_executor import budget, policy
from apps.api.tests.test_semantic_link_model import native_reply
from apps.api.tests.test_test_design_generation import case_output
from apps.api.tests.test_generation_batches import responses_for
from apps.api.tests.exweb_generation_batch_fixture import verify_exweb_batch_ledger
from apps.api.tests.exweb_generation_batch_recovery_fixture import verify_exweb_archived_batch_recovery


def verify_exweb_native_generation(results, selection, authorization, profiles, config, images, storage):
    import tiktoken
    binding = profiles.resolve(config.config_id).binding
    operator_policy = policy(binding, tokenizer_digest=tiktoken_policy_digest("cl100k_base"))
    encoding = tiktoken.get_encoding("cl100k_base")
    counter = LocalGenerationTokenCounter(operator_policy, lambda text: encoding.encode(text, disallowed_special=()))
    calls = []
    def handle(request):
        calls.append(request)
        prepared = json.loads(json.loads(request.content)["messages"][-1]["content"])
        return httpx.Response(200, json=native_reply(binding.provider, json.dumps(case_output(prepared))))
    service = GenerationExecutorApplicationService(results.generation, results, profiles,
        SimpleNamespace(resolve=lambda model: counter), authorization, ImageGenerationSourceInventory(images),
        HTTPTestDesignModel(transport=httpx.MockTransport(handle)), GenerationExecutionRepository(), GenerationReplyArtifacts(storage))
    selected = GenerationExecutionSelection(**selection.model_dump(mode="json"), model_config_id=config.config_id, budget=budget())
    preview = service.preview(selected)
    assert not calls and "source_fields" not in json.dumps(preview)
    planned = service.batch_planning.prepare(selected)
    checked = service.batch_planning.check_outputs(selected, expected_planning_digest=planned.digest,
        responses=responses_for(planned.input, planned.plan))
    assert planned.preview["input_digest"] == preview["request"]["input_digest"]
    assert planned.preview["source_binding_ids"] == preview["request"]["execution"]["source_binding_ids"]
    assert len(planned.plan["batches"]) == 1 and len(planned.input["obligations"]) == 8
    assert checked["proposal"]["coverage"]["constraint_denominator"] == 2
    assert checked["proposal"]["coverage"]["obligation_denominator"] == 8
    assert checked["proposal"]["coverage"]["passed_count"] == 0 and not calls
    request = GenerationResultRequest.model_validate(preview["request"])
    invocation_id = uuid4().hex
    actor_id = authorization.scope(selection.project_id).actor_id
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation_id, tool_id=GENERATION_TOOL, status="running",
            summary="Native transport fixture, not external exweb model or author validation",
            input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True, "confirmed_actor_id": actor_id,
                "confirmed_at": datetime.now(timezone.utc).isoformat()}))
    jobs = GenerationJobApplicationService(service, GenerationJobRepository(), None)
    record = results.repository.record
    def first_failure(*args, **kwargs):
        raise RuntimeError("explicit exweb draft commit failure fixture")
    results.repository.record = first_failure
    try:
        try:
            asyncio.run(jobs.run(invocation_id))
        except RuntimeError as exc:
            assert "draft commit failure fixture" in str(exc)
        else:
            raise AssertionError("fixture must fail after archiving the native reply")
    finally:
        results.repository.record = record
    assert asyncio.run(jobs.fail(invocation_id)) == "failed"
    state = jobs.read(selection.project_id, invocation_id)
    recovery = GenerationRecoveryRequest.model_validate(state["recovery_request"])
    recovery_id = uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=recovery_id, tool_id=GENERATION_RECOVER_TOOL, status="running",
            summary="Explicit canonical recovery authority fixture, NOT exweb maintainer approval",
            input_payload={**recovery.model_dump(mode="json"), "confirmed_by_user": True, "confirmed_actor_id": actor_id,
                "confirmed_at": datetime.now(timezone.utc).isoformat()}))
    assert asyncio.run(jobs.run(recovery_id)) == "completed"
    metadata = results.repository.by_invocation(selection.project_id, invocation_id)
    view = results.read(selection.project_id, metadata["generation_id"])
    assert asyncio.run(service.execute(request, invocation_id=invocation_id)) == metadata and len(calls) == 1
    assert view["result"]["recovery_invocation_id"] == recovery_id
    assert jobs.repository.command(invocation_id)[1] == "failed"
    cursor, history = "", []
    while True:
        history_request = GenerationHistoryRequest(**selection.model_dump(mode="json"), after_id=cursor, limit=1)
        page = jobs.history(history_request)
        assert page["request"] == history_request.model_dump(mode="json")
        assert not page["has_running"] and not page["generation_authorized"] and not page["execution_authorized"]
        assert len(page["items"]) == 1
        assert set(page["items"][0]) == {"invocation_id", "source_invocation_id", "tool_id", "status"}
        history.extend(page["items"])
        if page["next_after_id"] is None:
            break
        assert page["next_after_id"] > cursor
        cursor = page["next_after_id"]
    assert [item["invocation_id"] for item in history] == sorted([invocation_id, recovery_id])
    assert {item["source_invocation_id"] for item in history} == {invocation_id}
    assert {item["status"] for item in history} == {"failed", "completed"} and len(calls) == 1
    stored = service.repository.get(selection.project_id, invocation_id)
    assert stored["reply"]["artifact_ref"].startswith("s3://")
    coverage = view["result"]["proposal"]["coverage"]
    assert coverage["constraint_denominator"] == coverage["planned_constraint_count"] == 2
    assert coverage["obligation_denominator"] == coverage["planned_obligation_count"] == 8
    assert coverage["passed_count"] == coverage["executed_on_target_count"] == coverage["assertion_mapped_count"] == 0
    batch_ledger = verify_exweb_batch_ledger(service, jobs, selected, planned, storage)
    batch_recovery = verify_exweb_archived_batch_recovery(service, jobs, selected, planned, storage)
    assert len(calls) == 1
    return view, {"metadata": metadata, "reservation": preview["reservation"], "native_request_count": len(calls),
        "batch_ledger": batch_ledger,
        "batch_recovery": batch_recovery,
        "batch_planning": {"planning_digest": planned.digest, "plan_digest": planned.plan["plan_digest"],
            "batch_count": len(planned.plan["batches"]), "source_binding_count": len(planned.preview["source_binding_ids"]),
            "estimated_input_tokens": planned.preview["reservation"]["estimated_input_tokens"],
            "complete_original_obligations_verified": True, "readonly_no_model_calls": True,
            "proposal_source": "explicit_fixture_not_external_model_or_author_approval",
            "multi_call_execution_enabled": False, "target_executed": False},
        "source_binding_count": len(request.execution.source_binding_ids), "minio_native_reply_roundtrip_verified": True,
        "recovery_without_resend_verified": True, "tokenizer_assets_pinned": True,
        "explicit_terminal_recovery_without_resend_verified": True, "source_failed_command_preserved": True,
        "bounded_generation_history_verified": True, "generation_history_command_count": len(history),
        "temporal_execution_in_this_fixture": False,
        "output_source": "explicit_native_http_transport_fixture_not_external_model", "external_provider_invoked": False,
        "usage_counts_are_protocol_fixtures_not_real_provider_charges": True, "target_executed": False}
