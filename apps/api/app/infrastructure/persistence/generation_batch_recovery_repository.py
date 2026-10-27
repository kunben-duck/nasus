"""Archived-batch recovery under independent authority and atomic PG provenance."""
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.quality_loop.generation_batch_ledger import GenerationBatchReservation
from ...application.quality_loop.generation_batch_recovery import GenerationBatchRecoveryRequest, archived_batch_recovery_request, verify_batch_recovery_request
from ...application.quality_loop.generation_batch_recovery_results import recovery_result_provenance
from ...application.quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL
from ...application.quality_loop.generation_work_lease import GenerationLeaseLost, GenerationWorkLease
from ...application.quality_loop.test_design_results import RECOVERED_BATCH_RESULT_SCHEMA, GENERATION_TOOL, GenerationResultRequest, TestDesignResultIntegrityError
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from .db_models import ModelProviderConfigRecord, ProjectRoleBindingRecord, ToolInvocationRecord, UserIdentityRecord
from .generation_batch_models import GenerationBatchReservationRecord as Plan
from .generation_batch_repository import GenerationBatchRepository
from .generation_batch_result_repository import GenerationBatchResultRepository
from .generation_batch_recovery_models import GenerationBatchRecoveryResultRecord as Recovery
from .generation_execution_models import GenerationCallReservationRecord
from .generation_job_repository import GenerationJobRepository
from .test_design_result_models import TestDesignResultRecord as Result
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_models import TestDesignScopeRecord as Scope
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


def command_payload(command):
    return {key: value for key, value in query_payload(command.input_payload).items()
            if key not in {"confirmed_by_user", "confirmed_at"}}


class GenerationBatchRecoveryRepository(GenerationBatchResultRepository):
    @staticmethod
    def _administrator(session, plan, *, locking=True):
        identity_query = select(UserIdentityRecord).where(UserIdentityRecord.user_id == plan.actor_id)
        roles_query = select(ProjectRoleBindingRecord).where(
            ProjectRoleBindingRecord.project_id == plan.project_id, ProjectRoleBindingRecord.user_id == plan.actor_id,
            ProjectRoleBindingRecord.version_id.is_(None), ProjectRoleBindingRecord.session_id.is_(None),
            ProjectRoleBindingRecord.status == "active")
        identity = session.scalar(identity_query.with_for_update() if locking else identity_query)
        roles = session.scalars(roles_query.with_for_update() if locking else roles_query).all()
        if (identity is None or identity.status != "active"
                or identity.role != "platform_admin" and (len(roles) != 1 or roles[0].role != "project_admin")):
            raise PermissionError("batch recovery requires a current project administrator")
        model_query = select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.config_id == plan.request.model_config_id)
        model = session.scalar(model_query.with_for_update(read=True) if locking else model_query)
        if model is None:
            raise TestDesignResultIntegrityError("batch recovery model configuration is unavailable")

    @classmethod
    def _confirmation(cls, session, request, plan, authority_id, *, locking=True):
        if (authority_id == plan.invocation_id or request.invocation_id != plan.invocation_id
                or request.project_id != plan.project_id):
            raise GenerationLeaseLost("batch recovery must own a distinct new canonical command")
        source_query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == plan.invocation_id)
        authority_query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == authority_id)
        source = session.scalar(source_query.with_for_update() if locking else source_query)
        authority = session.scalar(authority_query.with_for_update() if locking else authority_query)
        if (source is None or source.tool_id != GENERATION_TOOL or source.status != "failed"
                or authority is None or authority.tool_id != GENERATION_RECOVER_TOOL or authority.status != "running"
                or any(not isinstance(row.input_payload, dict) or row.input_payload.get("confirmed_by_user") is not True
                    or row.input_payload.get("confirmed_actor_id") != plan.actor_id for row in (source, authority))):
            raise TestDesignResultIntegrityError("batch recovery requires original failed and independently confirmed commands")
        if (GenerationResultRequest.model_validate(command_payload(source)) != plan.request
                or GenerationBatchRecoveryRequest.model_validate(command_payload(authority)) != request):
            raise TestDesignResultIntegrityError("batch recovery canonical request pins changed")
        for row in (source, authority):
            TestDesignResultRepository._project_scope(session, row, plan.project_id)
        scope = session.get(Scope, plan.request.scope_revision_id)
        if (scope is None or scope.project_id != plan.project_id
                or scope.payload.get("artifact_hash") != plan.request.scope_artifact_hash):
            raise TestDesignResultIntegrityError("batch recovery scope pin mismatch")
        now = session.scalar(select(func.clock_timestamp()))
        confirmed = datetime.fromisoformat(str(authority.input_payload.get("confirmed_at", "")))
        if confirmed.tzinfo is None or not 0 <= (now - confirmed).total_seconds() <= 900:
            raise TestDesignResultIntegrityError("batch recovery independent confirmation expired")
        cls._administrator(session, plan, locking=locking)
        return authority

    @classmethod
    def _authority(cls, session, request, plan, lease, *, locking=True):
        if lease.project_id != plan.project_id:
            raise GenerationLeaseLost("batch recovery lease belongs to another project")
        authority = cls._confirmation(session, request, plan, lease.invocation_id, locking=locking)
        # The full typed command is verified before using the raw-state fence.
        GenerationJobRepository._require_lease_state(session, authority, lease)
        return authority

    @staticmethod
    def _plan(session, request):
        row = session.get(Plan, request.invocation_id)
        if row is None or row.project_id != request.project_id:
            raise TestDesignResultIntegrityError("batch recovery source reservation is unavailable")
        plan = GenerationBatchReservation.model_validate(row.payload)
        GenerationBatchRepository._stored_plan(session, plan)
        if (request.request_hash != acceptance_digest(plan.request.model_dump(mode="json"))
                or request.reservation_hash != acceptance_digest(plan.model_dump(mode="json"))
                or request.plan_digest != plan.plan_digest):
            raise TestDesignResultIntegrityError("batch recovery reservation pins changed")
        return plan

    @classmethod
    def _existing(cls, session, request, plan, authority_id):
        if session.get(GenerationCallReservationRecord, plan.invocation_id) is not None:
            raise TestDesignResultIntegrityError("batch recovery cannot replace a single reservation")
        prior = session.scalar(select(Result).where(Result.invocation_id == plan.invocation_id))
        if prior is not None:
            metadata = cls._metadata(prior)
            row = session.get(Recovery, prior.generation_id)
            expected = {"schema": "nasus.test-design-batch-recovery-result.v1", "project_id": plan.project_id,
                "generation_id": prior.generation_id, "source_invocation_id": plan.invocation_id,
                "authority_invocation_id": authority_id, "artifact_hash": prior.artifact_hash,
                "recovery_request": request.model_dump(mode="json")}
            if (metadata.get("schema") != RECOVERED_BATCH_RESULT_SCHEMA
                    or metadata.get("recovery_invocation_id") != authority_id
                    or row is None or row.payload != expected or row.content_hash != acceptance_digest(expected)
                    or any(getattr(row, key) != expected[key] for key in ("project_id", "generation_id", "source_invocation_id", "authority_invocation_id", "artifact_hash"))):
                raise TestDesignResultIntegrityError("batch recovery cannot replace a committed result or authority")
        return prior

    def require_confirmation(self, request, authority_id, actor_id):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            plan = self._plan(session, request)
            if plan.actor_id != actor_id:
                raise PermissionError("batch recovery cannot inherit another administrator's confirmation")
            self._confirmation(session, request, plan, authority_id)
            self._existing(session, request, plan, authority_id)
            if archived_batch_recovery_request(plan, self._proofs(session, plan)) != request:
                raise TestDesignResultIntegrityError("batch recovery dispatch requires exact complete native receipts")

    def recovery_offer(self, source, invocation_id, actor_id, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, source.project_id)
            row = session.get(Plan, invocation_id)
            if row is None:
                raise TestDesignResultIntegrityError("batch recovery reservation is unavailable")
            plan = GenerationBatchReservation.model_validate(row.payload)
            GenerationBatchRepository._stored_plan(session, plan)
            command = session.get(ToolInvocationRecord, invocation_id)
            if (plan.request != source or plan.actor_id != actor_id or command is None
                    or command.tool_id != GENERATION_TOOL or command.status != "failed"
                    or command.input_payload.get("confirmed_by_user") is not True
                    or command.input_payload.get("confirmed_actor_id") != actor_id
                    or GenerationResultRequest.model_validate(command_payload(command)) != source):
                raise TestDesignResultIntegrityError("recovery offer differs from the original failed command")
            self._project_scope(session, command, source.project_id)
            self._administrator(session, plan)
            if session.get(GenerationCallReservationRecord, invocation_id) is not None:
                raise TestDesignResultIntegrityError("batch recovery cannot acquire a single-call reservation")
            if session.scalar(select(Result).where(Result.invocation_id == invocation_id)) is not None:
                return None
            require_current()
            value = archived_batch_recovery_request(plan, self._proofs(session, plan))
            require_current()
            return value

    def reservation_for_recovery(self, request, *, lease):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            plan = self._plan(session, request)
            self._authority(session, request, plan, lease)
            self._existing(session, request, plan, lease.invocation_id)
            return plan

    def require_lease(self, lease):
        # Rechecks can run inside a project-locked commit on another connection.
        # Never acquire row/advisory locks on that second read-only connection.
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, lease.invocation_id)
            if command is None:
                raise GenerationLeaseLost("batch recovery command is unavailable")
            request = GenerationBatchRecoveryRequest.model_validate(command_payload(command))
            self._authority(session, request, self._plan(session, request), lease, locking=False)

    def load_for_recovery(self, request, prepared, batch_plan, *, lease, require_current):
        request = GenerationBatchRecoveryRequest.model_validate(request.model_dump(mode="json"))
        lease = GenerationWorkLease(**asdict(lease))
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            plan = self._plan(session, request)
            authority = self._authority(session, request, plan, lease)
            self._existing(session, request, plan, lease.invocation_id)
            require_current()
            calls = GenerationBatchResultRepository._proofs(session, plan)
            verify_batch_recovery_request(request, plan, prepared, batch_plan, calls)
            require_current()
            GenerationJobRepository._require_lease_state(session, authority, lease)
            return {"plan": plan, "calls": calls}

    @classmethod
    def _verify_history(cls, session, payload):
        """Verify past authority without requiring its old lease, TTL or model."""
        source = session.get(ToolInvocationRecord, payload["invocation_id"])
        authority = session.get(ToolInvocationRecord, payload["recovery_invocation_id"])
        row = session.get(Recovery, payload["generation_id"])
        result = session.get(Result, payload["generation_id"])
        digest = acceptance_digest(payload)
        expected = recovery_result_provenance(payload, digest)
        if (source is None or authority is None or source.id == authority.id
                or source.tool_id != GENERATION_TOOL or source.status != "failed"
                or authority.tool_id != GENERATION_RECOVER_TOOL or authority.status not in {"running", "completed", "failed", "cancelled"}
                or any(command.input_payload.get("confirmed_by_user") is not True
                    or command.input_payload.get("confirmed_actor_id") != payload["actor_id"] for command in (source, authority))
                or GenerationResultRequest.model_validate(command_payload(source)).model_dump(mode="json") != payload["request"]
                or GenerationBatchRecoveryRequest.model_validate(command_payload(authority)).model_dump(mode="json") != payload["recovery_request"]
                or row is None or row.payload != expected or row.content_hash != acceptance_digest(expected)
                or any(getattr(row, key) != expected[key] for key in ("project_id", "generation_id", "source_invocation_id", "authority_invocation_id", "artifact_hash"))
                or result is None or result.artifact_hash != digest
                or cls._metadata(result).get("recovery_invocation_id") != authority.id):
            raise TestDesignResultIntegrityError("archived batch independent recovery provenance mismatch")
        confirmed = datetime.fromisoformat(str(authority.input_payload.get("confirmed_at", "")))
        if confirmed.tzinfo is None:
            raise TestDesignResultIntegrityError("historical batch recovery confirmation timestamp is invalid")
        for command in (source, authority):
            cls._project_scope(session, command, payload["project_id"])

    def record_recovered(self, request, plan, payload, ref, digest, *, lease, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, plan.project_id)
            if self._plan(session, request) != plan:
                raise TestDesignResultIntegrityError("recovered batch reservation differs from its original ledger")
            command = self._authority(session, request, plan, lease)
            prior = self._existing(session, request, plan, lease.invocation_id)
            proofs = self._proofs(session, plan)
            if (payload.get("schema") != RECOVERED_BATCH_RESULT_SCHEMA or acceptance_digest(payload) != digest
                    or payload["recovery_invocation_id"] != command.id or payload["recovery_request"] != request.model_dump(mode="json")
                    or payload["reservation"] != plan.model_dump(mode="json") or payload["calls"] != proofs
                    or payload["request"] != plan.request.model_dump(mode="json") or payload["status"] != "draft"
                    or payload["execution_authorized"] is not False or payload["mapping_status"] != "pending_independent_review"):
                raise TestDesignResultIntegrityError("recovery transaction differs from its original ledger and new authority")
            require_current()
            self._authority(session, request, plan, lease)
            if prior is not None:
                if prior.artifact_hash != digest or prior.artifact_ref != ref:
                    raise TestDesignResultIntegrityError("recovery replay conflicts with its immutable result")
                self._verify_history(session, payload)
                return self._metadata(prior)
            metadata = self._insert(session, plan, payload, ref, digest, proofs, command)
            value = recovery_result_provenance(payload, digest)
            session.add(Recovery(**{key: value[key] for key in (
                "project_id", "generation_id", "source_invocation_id", "authority_invocation_id", "artifact_hash")},
                payload=value, content_hash=acceptance_digest(value)))
            session.flush()
            self._authority(session, request, plan, lease)
            return metadata
