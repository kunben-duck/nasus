from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.generation_batch_ledger import (
    BATCH_REPLY_SCHEMA, GenerationBatchReservation, batch_execution_request, batch_reservation,
    batch_call_request_hash, validate_batch_reply,
)
from apps.api.app.application.quality_loop.generation_budget import verify_generation_usage
from apps.api.app.application.quality_loop.generation_batch_receipts import GenerationBatchReceiptApplicationService
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.tests.test_generation_batches import multi_input, divided_plan, FixtureCounter
from apps.api.tests.test_generation_executor import executor


def prepared_ledger():
    service, selected, dependencies, _ = executor()
    prepared = multi_input()
    _, _, _, limits = divided_plan(prepared)
    selected = selected.model_copy(update={"budget": limits, "scope_revision_id": prepared["scope_pin"]["revision_id"],
        "scope_artifact_hash": prepared["scope_pin"]["artifact_hash"]})
    dependencies["generation"].prepare = lambda request: deepcopy(prepared)
    dependencies["policies"].resolve = lambda binding: FixtureCounter(binding)
    planned = service.batch_planning.prepare(selected)
    return planned, batch_reservation(planned, invocation_id="command", actor_id="actor")


def test_batch_ledger_preserves_complete_three_call_budget_and_no_source_body():
    planned, plan = prepared_ledger()
    assert len(plan.batches) == plan.reservation.call_count == 3
    assert plan.request == batch_execution_request(planned)
    assert plan.request.execution.plan_digest == planned.digest
    assert plan.reservation.reserved_tokens == 3 * 136192
    body = json.dumps(plan.model_dump(mode="json"))
    assert "Untrusted source observation" not in body and "private-provider-key" not in body
    assert "facts" not in body and "oracle" not in body
    assert len({batch_call_request_hash(plan, seq) for seq in range(3)}) == 3
    assert GenerationBatchReservation.model_validate_json(body) == plan


@pytest.mark.parametrize("mutation", ["sequence", "duplicate", "count", "cost", "tokens", "policy", "source_scope", "actor_extra", "binding_extra", "message", "model"])
def test_batch_ledger_rejects_altered_budget_pins_and_arbitrary_metadata(mutation):
    _, plan = prepared_ledger()
    value = plan.model_dump(mode="json")
    if mutation == "sequence":
        value["batches"][1]["sequence"] = True
    elif mutation == "duplicate":
        value["batches"][1]["batch_digest"] = value["batches"][0]["batch_digest"]
    elif mutation == "count":
        value["batches"].pop()
    elif mutation in {"cost", "tokens"}:
        value["reservation"]["reserved_" + ("cost_nanos" if mutation == "cost" else "tokens")] -= 1
    elif mutation == "policy":
        value["policy"]["input_nanos_per_token"] += 1
    elif mutation == "source_scope":
        value["request"]["execution"]["source_scope_digest"] = acceptance_digest("wrong ACL")
    elif mutation == "actor_extra":
        value["source_body"] = "Untrusted source content must not enter ledger metadata"
    elif mutation == "binding_extra":
        value["model_binding"]["api_key"] = "never allowed"
    elif mutation == "message":
        value["batches"][0]["messages_hash"] = acceptance_digest("wrong prompt")
    else:
        value["request"]["model_config_digest"] = acceptance_digest("wrong credential revision")
    with pytest.raises((ValidationError, ValueError)):
        GenerationBatchReservation.model_validate(value)


@pytest.mark.parametrize("key", ["messages_hashes", "model_binding", "plan_digest", "input_digest", "planning_digest"])
def test_batch_ledger_rejects_tampered_readonly_preview_before_reservation(key):
    planned, _ = prepared_ledger()
    view = deepcopy(planned.preview)
    if key == "messages_hashes":
        view[key].append(acceptance_digest("extra prompt"))
    elif key == "model_binding":
        view[key]["base_url"] = "https://unconfirmed.example/v1"
    else:
        view[key] = acceptance_digest("wrong pin")
    with pytest.raises((ValueError, ValidationError)):
        batch_reservation(replace(planned, preview=view), invocation_id="command", actor_id="actor")


def reply_payload(plan, sequence=0):
    claim = {"call_id": "reserved-call"}
    usage = verify_generation_usage(plan.policy, plan.request.execution.budget, 100, 50)
    payload = {"schema": BATCH_REPLY_SCHEMA, "project_id": plan.project_id, "invocation_id": plan.invocation_id,
        "actor_id": plan.actor_id, "request": plan.request.model_dump(mode="json"), "plan_digest": plan.plan_digest,
        "sequence": sequence, "batch_digest": plan.batches[sequence].batch_digest,
        "messages_hash": plan.batches[sequence].messages_hash, "call_id": claim["call_id"], "content": "native fixture JSON", "usage": usage}
    return claim, payload


@pytest.mark.parametrize("mutation", ["sequence", "foreign_batch", "call", "raw_field", "usage", "missing_usage", "oversized", "empty"])
def test_batch_reply_requires_exact_owner_call_archive_and_provider_usage(mutation):
    _, plan = prepared_ledger()
    claim, payload = reply_payload(plan)
    assert validate_batch_reply(plan, 0, claim, payload)["usage"]["invoice_verified"] is False
    if mutation == "sequence":
        payload["sequence"] = False
    elif mutation == "foreign_batch":
        payload["batch_digest"] = plan.batches[1].batch_digest
    elif mutation == "call":
        payload["call_id"] = "another native call"
    elif mutation == "raw_field":
        payload["api_key"] = "not persisted"
    elif mutation == "usage":
        payload["usage"]["invoice_verified"] = True
    elif mutation == "missing_usage":
        payload["usage"] = {"input_tokens": 100}
    elif mutation == "oversized":
        payload["content"] = "x" * (1024 * 1024 + 1)
    else:
        payload["content"] = ""
    with pytest.raises(ValueError):
        validate_batch_reply(plan, 0, claim, payload)


def test_batch_native_call_audit_uses_individual_request_hash_not_synthetic_aggregate():
    _, plan = prepared_ledger()
    claim = {"call_id": "per-batch-call", "request_hash": batch_call_request_hash(plan, 2)}
    reply = SimpleNamespace(content="native response", usage_source="provider", input_tokens=100, output_tokens=50)
    call = GenerationBatchReceiptApplicationService._call(plan, claim, reply, outcome="success", latency_ms=20)
    assert call.model_calls == 1 and call.prompt_version == "batch-v1"
    assert call.request_hash != acceptance_digest(plan.request.model_dump(mode="json"))
    assert call.request_hash != batch_call_request_hash(plan, 1)
    error = GenerationBatchReceiptApplicationService._call(plan, claim, None, outcome="error", latency_ms=20)
    assert error.model_calls == 1 and error.usage_source == "none" and error.input_token_count == 0
    with pytest.raises(ValueError):
        GenerationBatchReceiptApplicationService._call(plan, claim, reply, outcome="success", latency_ms=True)
