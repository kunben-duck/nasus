"""Private v4 recovery contract/application fixtures, not PG or public dispatch."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.generation_batch_recovery import batch_recovery_request
from apps.api.app.application.quality_loop.generation_batch_recovery_results import GenerationBatchRecoveryApplicationService, recovery_result_provenance
from apps.api.app.application.quality_loop.generation_batch_results import validate_batch_result
from apps.api.app.application.quality_loop.generation_work_lease import GenerationLeaseLost, GenerationWorkLease
from apps.api.app.application.quality_loop.test_design_results import RECOVERED_BATCH_RESULT_SCHEMA, TestDesignResultIntegrityError
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.tests.test_generation_batch_results import result_fixture


def recovered_fixture():
    prepared, plan, payload, objects, _ = result_fixture()
    objects = deepcopy(objects)
    request = batch_recovery_request(plan, prepared.input, prepared.plan, payload["calls"])
    payload.update(schema=RECOVERED_BATCH_RESULT_SCHEMA, recovery_invocation_id="recovery-command",
        recovery_request=request.model_dump(mode="json"))
    artifacts = SimpleNamespace(read=lambda project, ref, digest: deepcopy(objects[ref]))
    return prepared, plan, payload, request, artifacts


def test_v4_recovery_preserves_all_original_call_ids_obligations_oracles_and_native_lineage():
    prepared, plan, payload, request, artifacts = recovered_fixture()
    assert validate_batch_result(prepared.input, payload, artifacts) == plan
    assert payload["invocation_id"] != payload["recovery_invocation_id"]
    assert [proof["claim"]["call_id"] for proof in payload["calls"]] == [pin.call_id for pin in request.replies]
    value = recovery_result_provenance(payload, acceptance_digest(payload))
    assert value["source_invocation_id"] == plan.invocation_id
    assert value["authority_invocation_id"] == "recovery-command" and value["recovery_request"] == payload["recovery_request"]
    coverage = payload["proposal"]["coverage"]
    assert coverage["obligation_denominator"] == len(prepared.input["obligations"])
    assert coverage["automated_count"] == coverage["executed_on_target_count"] == coverage["passed_count"] == 0


@pytest.mark.parametrize("mutation", ["original_authority", "invalid_authority", "trimmed_authority", "missing_authority",
    "missing_request", "foreign_request", "partial_request", "fake_usage", "unknown_schema", "authority_in_v3",
    "single_call", "oracle", "passed", "extra_secret"])
def test_v4_recovery_rejects_missing_foreign_or_fabricated_provenance(mutation):
    prepared, plan, payload, _, artifacts = recovered_fixture()
    if mutation == "original_authority":
        payload["recovery_invocation_id"] = plan.invocation_id
    elif mutation == "invalid_authority":
        payload["recovery_invocation_id"] = True
    elif mutation == "trimmed_authority":
        payload["recovery_invocation_id"] = " recovery-command "
    elif mutation == "missing_authority":
        payload.pop("recovery_invocation_id")
    elif mutation == "missing_request":
        payload.pop("recovery_request")
    elif mutation == "foreign_request":
        payload["recovery_request"]["invocation_id"] = "another-generation"
    elif mutation == "partial_request":
        payload["recovery_request"]["replies"].pop()
    elif mutation == "fake_usage":
        payload["recovery_request"]["replies"][1]["usage_digest"] = acceptance_digest("invented invoice")
    elif mutation in {"unknown_schema", "authority_in_v3"}:
        payload["schema"] = "nasus.test-design-result.v99" if mutation == "unknown_schema" else "nasus.test-design-result.v3"
    elif mutation == "single_call":
        payload["call"] = payload["calls"][0]["audit"]
    elif mutation == "oracle":
        payload["proposal"]["cases"][0]["assertions"][0]["oracle"]["expected_value"] = "invented"
    elif mutation == "passed":
        payload["proposal"]["coverage"]["passed_count"] = 1
    else:
        payload["recovery_request"]["api_key"] = "forbidden"
    with pytest.raises(TestDesignResultIntegrityError):
        validate_batch_result(prepared.input, payload, artifacts)


def application_fixture():
    prepared, plan, payload, request, replies = recovered_fixture()
    lease = GenerationWorkLease(plan.project_id, payload["recovery_invocation_id"], "worker", 1, acceptance_digest("lease"))
    checks, stored, writes = [], {}, []
    access = SimpleNamespace(actor_id=plan.actor_id, effective_project_role="project_admin", require_binding=lambda ident: None)
    authority = SimpleNamespace(scope=lambda project: access, require_current=lambda value: checks.append("authority"))
    def fence(value):
        assert value == lease
        checks.append("lease")
    repository = SimpleNamespace(reservation_for_recovery=lambda value, **kw: plan, require_lease=fence,
        load_for_recovery=lambda value, *args, **kw: {"plan": plan, "calls": deepcopy(payload["calls"])},
        by_invocation=lambda *args: stored.get("metadata"), get=lambda *args: {"artifact_ref": "private-result"})
    def put(project, value):
        writes.append(deepcopy(value))
        stored["artifact"] = deepcopy(value)
        return "private-result", acceptance_digest(value)
    def record(value, fixed, body, ref, digest, *, require_current, **kw):
        require_current()
        assert value == request and fixed == plan and ref == "private-result" and digest == acceptance_digest(body)
        stored["metadata"] = {"schema": RECOVERED_BATCH_RESULT_SCHEMA, "generation_id": body["generation_id"],
            "artifact_hash": digest, "recovery_invocation_id": lease.invocation_id}
        return stored["metadata"]
    repository.record_recovered = record
    service = GenerationBatchRecoveryApplicationService(SimpleNamespace(prepare=lambda value: prepared), authority,
        repository, replies, SimpleNamespace(put=put, read=lambda *args: deepcopy(stored["artifact"])))
    return service, request, lease, plan, access, checks, stored, writes


def test_private_application_recovers_and_replays_without_rewriting_archive_or_having_a_provider_port():
    service, request, lease, _, _, checks, stored, writes = application_fixture()
    metadata = service.recover(request, lease=lease)
    assert service.recover(request, lease=lease) == metadata and len(writes) == 1
    assert stored["artifact"]["recovery_request"] == request.model_dump(mode="json")
    assert "provider" not in vars(service) and "lease" in checks and "authority" in checks


@pytest.mark.parametrize("failure", ["actor", "role", "lease", "planning", "digest", "rebound_result"])
def test_private_application_cannot_recover_after_authority_or_fixed_dependencies_change(failure):
    service, request, lease, plan, access, _, stored, writes = application_fixture()
    if failure == "actor":
        access.actor_id = "foreign"
    elif failure == "role":
        access.effective_project_role = "qa_lead"
    elif failure == "lease":
        service.repository.require_lease = lambda value: (_ for _ in ()).throw(GenerationLeaseLost("lost"))
    elif failure == "planning":
        original = service.planning.prepare(None)
        changed = deepcopy(original.preview)
        changed["source_scope_digest"] = acceptance_digest("new scope")
        service.planning.prepare = lambda value: replace(original, preview=changed)
    elif failure == "digest":
        service.result_artifacts.put = lambda *args: ("private-result", acceptance_digest("wrong write"))
    else:
        service.recover(request, lease=lease)
        stored["metadata"]["recovery_invocation_id"] = "another-recovery"
    with pytest.raises((PermissionError, GenerationLeaseLost, TestDesignResultIntegrityError)):
        service.recover(request, lease=lease)
    if failure not in {"digest", "rebound_result"}:
        assert not writes
