"""Recover a complete archived batch into a draft; never invoke a Provider."""
from dataclasses import asdict

from .generation_batch_ledger import batch_reservation
from .generation_batch_recovery import GenerationBatchRecoveryPort, GenerationBatchRecoveryRequest, prepare_archived_batch_recovery
from .generation_batch_results import batch_result_payload, validate_batch_result
from .generation_execution_inputs import GenerationExecutionSelection
from .generation_work_lease import GenerationLeaseLost, GenerationWorkLease
from .test_design_results import RECOVERED_BATCH_RESULT_SCHEMA, TestDesignResultIntegrityError
from ...domain.quality_loop.acceptance_specification import acceptance_digest


def recovery_result_provenance(payload, artifact_hash):
    return {"schema": "nasus.test-design-batch-recovery-result.v1", "project_id": payload["project_id"],
        "generation_id": payload["generation_id"], "source_invocation_id": payload["invocation_id"],
        "authority_invocation_id": payload["recovery_invocation_id"], "artifact_hash": artifact_hash,
        "recovery_request": payload["recovery_request"]}


class GenerationBatchRecoveryApplicationService:
    """Trusted execution port; canonical dispatch/lifecycle is composed separately."""
    def __init__(self, planning, authorization, repository: GenerationBatchRecoveryPort, reply_artifacts, result_artifacts):
        self.planning, self.authorization, self.repository = planning, authorization, repository
        self.reply_artifacts, self.result_artifacts = reply_artifacts, result_artifacts

    def offer(self, source, invocation_id):
        access = self.authorization.scope(source.project_id)
        if access.effective_project_role not in {"platform_admin", "project_admin"}:
            raise PermissionError("batch recovery requires a current administrator")
        for ident in source.execution.source_binding_ids:
            access.require_binding(ident)
        return self.repository.recovery_offer(source, invocation_id, access.actor_id,
            require_current=lambda: self.authorization.require_current(access))

    def recover(self, request, *, lease):
        request = GenerationBatchRecoveryRequest.model_validate(request.model_dump(mode="json"))
        lease = GenerationWorkLease(**asdict(lease))
        if lease.project_id != request.project_id or lease.invocation_id == request.invocation_id:
            raise GenerationLeaseLost("archived batch recovery requires its own exact command lease")
        plan = self.repository.reservation_for_recovery(request, lease=lease)
        access = self.authorization.scope(request.project_id)
        if access.actor_id != plan.actor_id or access.effective_project_role not in {"platform_admin", "project_admin"}:
            raise PermissionError("batch recovery requires the original confirming administrator")
        for ident in plan.request.execution.source_binding_ids:
            access.require_binding(ident)
        selected = GenerationExecutionSelection(**plan.request.selection().model_dump(mode="json"),
            model_config_id=plan.request.model_config_id, budget=plan.request.execution.budget)

        def prepare_current():
            self.repository.require_lease(lease)
            self.authorization.require_current(access)
            prepared = self.planning.prepare(selected)
            if batch_reservation(prepared, invocation_id=plan.invocation_id, actor_id=access.actor_id) != plan:
                raise TestDesignResultIntegrityError("recovery source, scope, model or budget dependencies changed")
            self.authorization.require_current(access)
            self.repository.require_lease(lease)
            return prepared

        prepared = prepare_current()
        loaded = self.repository.load_for_recovery(request, prepared.input, prepared.plan,
            lease=lease, require_current=prepare_current)
        if loaded["plan"] != plan:
            raise TestDesignResultIntegrityError("recovery reservation changed during preparation")
        calls = loaded["calls"]
        merged = prepare_archived_batch_recovery(request, plan, prepared.input, prepared.plan, calls,
            self.reply_artifacts, authority_invocation_id=lease.invocation_id, lease=lease,
            leases=self.repository, require_current=prepare_current)
        payload = batch_result_payload(plan, prepared.input, prepared.plan, calls, merged)
        payload.update(schema=RECOVERED_BATCH_RESULT_SCHEMA, recovery_invocation_id=lease.invocation_id,
            recovery_request=request.model_dump(mode="json"))
        validate_batch_result(prepared.input, payload, self.reply_artifacts)
        prepare_current()
        prior = self.repository.by_invocation(plan.project_id, plan.invocation_id)
        digest = acceptance_digest(payload)
        if prior is None:
            ref, written_hash = self.result_artifacts.put(plan.project_id, payload)
            if written_hash != digest:
                raise TestDesignResultIntegrityError("recovered batch private artifact write mismatch")
        else:
            if (prior.get("schema") != RECOVERED_BATCH_RESULT_SCHEMA or prior["artifact_hash"] != digest
                    or prior.get("recovery_invocation_id") != lease.invocation_id):
                raise TestDesignResultIntegrityError("recovery cannot replace a committed result or its authority")
            ref = self.repository.get(plan.project_id, prior["generation_id"])["artifact_ref"]
            if self.result_artifacts.read(plan.project_id, ref, digest) != payload:
                raise TestDesignResultIntegrityError("recovery replay cannot rewrite its private result")

        def require_current():
            prepare_current()
            validate_batch_result(prepared.input, payload, self.reply_artifacts)
            prepare_current()

        result = self.repository.record_recovered(request, plan, payload, ref, digest,
            lease=lease, require_current=require_current)
        self.authorization.require_current(access)
        return result
