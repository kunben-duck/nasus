from copy import deepcopy

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.generation_batch_recovery import archived_batch_recovery_request, GenerationBatchRecoveryRequest
from apps.api.app.application.quality_loop.generation_job_ports import GenerationRecoveryRequest, parse_generation_recovery
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.tests.test_generation_batch_recovery import recovery_fixture


def test_versioned_batch_and_legacy_single_recovery_remain_distinct_strict_contracts():
    _, _, _, request = recovery_fixture()
    value = request.model_dump(mode="json")
    assert parse_generation_recovery(value) == request and isinstance(parse_generation_recovery(value), GenerationBatchRecoveryRequest)
    single = {key: value[key] for key in ("project_id", "invocation_id", "request_hash")}
    single.update(reply_artifact_hash=value["replies"][0]["reply_artifact_hash"], response_hash=value["replies"][0]["response_hash"])
    assert isinstance(parse_generation_recovery(single), GenerationRecoveryRequest)
    for invalid in ({**value, "schema_version": "unknown"}, {**single, "schema_version": value["schema_version"]},
                    {**value, "reply_artifact_hash": single["reply_artifact_hash"]}, {**value, "confirmed_by_user": True}):
        with pytest.raises(ValidationError):
            parse_generation_recovery(invalid)


@pytest.mark.parametrize("mutation", ["none", "partial", "order", "call", "request", "response", "bool", "secret", "invoice", "malformed"])
def test_metadata_only_recovery_offer_cannot_relax_the_native_receipt_contract(mutation):
    _, plan, result, request = recovery_fixture()
    calls = deepcopy(result["calls"])
    assert archived_batch_recovery_request(plan, calls) == request
    if mutation == "none": calls = None
    elif mutation == "partial": calls.pop()
    elif mutation == "order": calls.reverse()
    elif mutation == "call": calls[0]["reply"]["call_id"] = "foreign"
    elif mutation == "request": calls[0]["claim"]["request_hash"] = request.request_hash
    elif mutation == "response": calls[0]["reply"]["response_hash"] = request.request_hash
    elif mutation == "bool": calls[0]["audit"]["input_tokens"] = True
    elif mutation == "secret": calls[0]["audit"]["api_key"] = "forbidden"
    elif mutation == "invoice": calls[0]["reply"]["usage"]["invoice_verified"] = True
    else: calls[0]["reply"]["usage"] = None
    with pytest.raises(TestDesignResultIntegrityError):
        archived_batch_recovery_request(plan, calls)
