"""Recovery proof contracts only; not canonical authority, PG, or Provider proof."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.generation_batch_recovery import (
    GenerationBatchRecoveryRequest, batch_recovery_request, verify_batch_recovery_request, prepare_archived_batch_recovery,
)
from apps.api.app.application.quality_loop.generation_work_lease import GenerationLeaseLost, GenerationWorkLease
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.tests.test_generation_batch_results import result_fixture


def recovery_fixture():
    prepared, plan, result, _, _ = result_fixture()
    request = batch_recovery_request(plan, prepared.input, result["batch_plan"], result["calls"])
    return prepared, plan, result, request


def preparation_fixture():
    prepared, plan, result, objects, _ = result_fixture()
    objects = deepcopy(objects)
    request = batch_recovery_request(plan, prepared.input, result["batch_plan"], result["calls"])
    lease = GenerationWorkLease(plan.project_id, "independent-recovery", "new-owner", 1, acceptance_digest("canonical-recovery"))
    checks, reads = [], []
    def read(project, ref, digest):
        reads.append((project, ref, digest))
        return deepcopy(objects[ref])
    options = {"authority_invocation_id": lease.invocation_id, "lease": lease,
        "leases": SimpleNamespace(require_lease=lambda value: checks.append(value)), "require_current": lambda: None}
    def prepare(**changes):
        pinned = changes.pop("recovery_request", request)
        return prepare_archived_batch_recovery(pinned, plan, prepared.input, result["batch_plan"], result["calls"],
            SimpleNamespace(read=read), **{**options, **changes})
    return prepared, plan, result, objects, options, checks, reads, prepare


def test_recovery_pins_all_original_calls_without_source_text_private_refs_or_new_egress():
    prepared, plan, result, request = recovery_fixture()
    assert len(request.replies) == len(plan.batches) == 3
    assert request.request_hash == acceptance_digest(plan.request.model_dump(mode="json"))
    assert request.reservation_hash == acceptance_digest(plan.model_dump(mode="json"))
    assert request.replies_digest == acceptance_digest(result["calls"])
    assert GenerationBatchRecoveryRequest.model_validate_json(request.model_dump_json()) == request
    assert verify_batch_recovery_request(request, plan, prepared.input, result["batch_plan"], result["calls"]) == request
    text = request.model_dump_json()
    assert all(word not in text for word in ("private:", "artifact_ref", "content", "api_key", "oracle", "confirmed", "authorized"))
    assert request.replies[0].call_id != request.replies[1].call_id


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered", "foreign_call", "foreign_request",
    "foreign_reply", "usage", "invoice", "bool_usage", "extra_secret", "malformed", "foreign_plan"])
def test_recovery_cannot_pin_partial_unknown_foreign_or_corrupt_call_sets(mutation):
    prepared, plan, result, _ = recovery_fixture()
    calls, batch_plan = deepcopy(result["calls"]), deepcopy(result["batch_plan"])
    if mutation == "missing":
        calls.pop()
    elif mutation == "duplicate":
        calls[1] = deepcopy(calls[0])
    elif mutation == "reordered":
        calls.reverse()
    elif mutation == "foreign_call":
        calls[0]["reply"]["call_id"] = "another-call"
    elif mutation == "foreign_request":
        calls[0]["claim"]["request_hash"] = acceptance_digest("another-request")
    elif mutation == "foreign_reply":
        calls[0]["reply"]["response_hash"] = acceptance_digest("another-response")
    elif mutation == "usage":
        calls[0]["reply"]["usage"]["cost_nanos_at_policy_rates"] += 1
    elif mutation == "invoice":
        calls[0]["reply"]["usage"]["invoice_verified"] = True
    elif mutation == "bool_usage":
        calls[0]["audit"]["input_tokens"] = True
    elif mutation == "extra_secret":
        calls[0]["audit"]["api_key"] = "never-accepted"
    elif mutation == "malformed":
        calls[0]["reply"]["usage"] = None
    else:
        batch_plan["batches"].pop()
    with pytest.raises(TestDesignResultIntegrityError):
        batch_recovery_request(plan, prepared.input, batch_plan, calls)


@pytest.mark.parametrize("field", ["project_id", "invocation_id", "request_hash", "reservation_hash", "plan_digest", "replies_digest"])
def test_recovery_revalidates_every_top_level_pin(field):
    prepared, plan, result, request = recovery_fixture()
    changed = request.model_copy(update={field: "foreign" if field.endswith("_id") else acceptance_digest("changed")})
    with pytest.raises(TestDesignResultIntegrityError):
        verify_batch_recovery_request(changed, plan, prepared.input, result["batch_plan"], result["calls"])


@pytest.mark.parametrize("field", ["batch_digest", "call_id", "request_hash", "reply_artifact_hash", "response_hash", "usage_digest", "audit_digest"])
def test_recovery_revalidates_every_original_native_reply_pin(field):
    prepared, plan, result, request = recovery_fixture()
    changed = request.model_dump(mode="json")
    changed["replies"][1][field] = "foreign" if field == "call_id" else acceptance_digest("changed")
    with pytest.raises(TestDesignResultIntegrityError):
        verify_batch_recovery_request(GenerationBatchRecoveryRequest.model_validate(changed),
            plan, prepared.input, result["batch_plan"], result["calls"])


@pytest.mark.parametrize("mutation", ["empty", "bool_sequence", "skipped", "duplicate_call", "duplicate_batch", "body", "authority", "private_ref"])
def test_recovery_dto_cannot_smuggle_unknown_metadata_or_authority(mutation):
    _, _, _, request = recovery_fixture()
    changed = request.model_dump(mode="json")
    if mutation == "empty":
        changed["replies"] = []
    elif mutation in {"bool_sequence", "skipped"}:
        changed["replies"][1]["sequence"] = True if mutation == "bool_sequence" else 3
    elif mutation in {"duplicate_call", "duplicate_batch"}:
        field = "call_id" if mutation == "duplicate_call" else "batch_digest"
        changed["replies"][1][field] = changed["replies"][0][field]
    elif mutation == "private_ref":
        changed["replies"][0]["artifact_ref"] = "s3://private/response"
    else:
        changed["content" if mutation == "body" else "execution_authorized"] = "source" if mutation == "body" else True
    with pytest.raises(ValidationError):
        GenerationBatchRecoveryRequest.model_validate(changed)


def test_private_recovery_preflight_replays_every_response_and_preserves_all_original_obligations():
    prepared, _, result, _, options, checks, reads, prepare = preparation_fixture()
    rebuilt = prepare()
    assert rebuilt["proposal"] == result["proposal"]
    assert rebuilt["provenance"] == result["provenance"]
    assert len(reads) == len(result["calls"]) == 3
    assert checks and all(value == options["lease"] for value in checks)
    coverage = rebuilt["proposal"]["coverage"]
    assert coverage["obligation_denominator"] == len(prepared.input["obligations"])
    assert coverage["automated_count"] == coverage["executed_on_target_count"] == coverage["passed_count"] == 0
    assert not coverage["execution_authorized"]


@pytest.mark.parametrize("mutation", ["original_command_lease", "foreign_command", "foreign_project"])
def test_private_recovery_cannot_reuse_terminal_source_worker_or_foreign_lease(mutation):
    _, plan, _, _, options, _, reads, prepare = preparation_fixture()
    lease = options["lease"]
    if mutation == "original_command_lease":
        lease = GenerationWorkLease(plan.project_id, plan.invocation_id, "old-owner", 1, lease.request_digest)
    elif mutation == "foreign_command":
        lease = GenerationWorkLease(plan.project_id, "different-recovery", lease.owner_id, lease.epoch, lease.request_digest)
    else:
        lease = GenerationWorkLease("different-project", lease.invocation_id, lease.owner_id, lease.epoch, lease.request_digest)
    with pytest.raises(GenerationLeaseLost):
        prepare(lease=lease)
    assert not reads


@pytest.mark.parametrize("gate", ["lease", "authority"])
def test_private_recovery_requires_current_authority_before_any_native_archive_read(gate):
    *_, reads, prepare = preparation_fixture()
    def denied(*args):
        raise PermissionError("current source/command authority unavailable")
    options = {"leases": SimpleNamespace(require_lease=denied)} if gate == "lease" else {"require_current": denied}
    with pytest.raises(PermissionError):
        prepare(**options)
    assert not reads


@pytest.mark.parametrize("gate", ["lease", "authority"])
def test_private_recovery_rechecks_authority_after_each_read_and_never_returns_revoked_body(gate):
    *_, reads, prepare = preparation_fixture()
    def revoked(*args):
        if reads:
            raise GenerationLeaseLost("new recovery worker/source authority revoked")
    options = {"leases": SimpleNamespace(require_lease=revoked)} if gate == "lease" else {"require_current": revoked}
    with pytest.raises(GenerationLeaseLost):
        prepare(**options)
    assert len(reads) == 1


@pytest.mark.parametrize("mutation", ["content", "foreign_call", "usage", "missing", "invalid_proposal"])
def test_private_recovery_rejects_damaged_or_inapplicable_native_body(mutation):
    import json
    prepared, plan, result, objects, _, _, reads, prepare = preparation_fixture()
    options = {}
    if mutation == "missing":
        objects.pop("private:1")
    elif mutation == "content":
        objects["private:1"]["content"] += " "
    elif mutation == "foreign_call":
        objects["private:1"]["call_id"] = "foreign"
    elif mutation == "usage":
        objects["private:1"]["usage"]["invoice_verified"] = True
    else:
        output = json.loads(objects["private:1"]["content"])
        output["cases"][0]["assertions"][0]["oracle_digest"] = acceptance_digest("invented oracle")
        objects["private:1"]["content"] = json.dumps(output)
        # Recompute archive/response/audit hashes to show that self-consistent
        # metadata cannot turn an inapplicable assertion into valid coverage.
        proof = result["calls"][1]
        from apps.api.app.application.quality_loop.test_design_results import response_digest
        proof["reply"]["artifact_hash"] = acceptance_digest(objects["private:1"])
        proof["reply"]["response_hash"] = proof["audit"]["response_hash"] = response_digest(objects["private:1"]["content"])
        options["recovery_request"] = batch_recovery_request(plan, prepared.input, result["batch_plan"], result["calls"])
    with pytest.raises((ValueError, KeyError)):
        prepare(**options)
    assert len(reads) == (3 if mutation == "invalid_proposal" else 2)
