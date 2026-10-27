"""One PG transaction for all cases, coverage and exact multi-call provenance."""
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.generation_batch_ledger import GenerationBatchReservation
from ...application.quality_loop.test_design_results import BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA, GENERATION_TOOL, GenerationResultRequest, TestDesignResultIntegrityError
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from .db_models import AuditEventRecord, LLMCallRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .generation_batch_repository import GenerationBatchRepository
from .generation_job_repository import GenerationJobRepository
from .test_design_result_models import TestDesignResultRecord as Result, TestDesignCaseRecord as Case, TestDesignCoverageRecord as Coverage, TestDesignResultBatchCallRecord as Provenance
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class GenerationBatchResultRepository(TestDesignResultRepository):
    @staticmethod
    def _proofs(session, plan):
        GenerationBatchRepository._stored_plan(session, plan)
        claims, replies = GenerationBatchRepository._records(session, plan)
        if len(claims) != len(plan.batches) or len(replies) != len(plan.batches):
            raise TestDesignResultIntegrityError("aggregate result requires every successful archived native reply")
        result = []
        for claim, reply in zip(claims, replies):
            call = session.get(LLMCallRecord, claim["call_id"])
            result.append({"claim": claim, "reply": reply, "audit": {
                "id": call.id, "provider": call.provider, "model_name": call.model_name,
                "request_hash": call.request_hash, "response_hash": call.response_hash,
                "input_tokens": call.input_token_count, "output_tokens": call.output_token_count,
                "usage_source": call.usage_source, "occurred_at": call.occurred_at.isoformat()}})
        return result

    def verified_calls(self, plan, *, lease, require_current):
        plan = GenerationBatchReservation.model_validate(plan.model_dump(mode="json"))
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, plan.project_id)
            command = GenerationBatchRepository._guard(session, plan, lease)
            result = self._proofs(session, plan)
            require_current()
            GenerationJobRepository._require_lease(session, command, lease)
            return result

    def verify_history(self, payload):
        plan = GenerationBatchReservation.model_validate(payload["reservation"])
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, plan.invocation_id)
            if (command is None or command.tool_id != GENERATION_TOOL
                    or command.input_payload.get("confirmed_by_user") is not True
                    or command.input_payload.get("confirmed_actor_id") != plan.actor_id):
                raise TestDesignResultIntegrityError("aggregate historical canonical confirmation is unavailable")
            request = GenerationResultRequest.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
            if request != plan.request:
                raise TestDesignResultIntegrityError("aggregate historical canonical request differs")
            self._project_scope(session, command, plan.project_id)
            proofs = self._proofs(session, plan)
            rows = session.scalars(select(Provenance).where(Provenance.generation_id == payload["generation_id"])
                .order_by(Provenance.sequence).limit(65)).all()
            if (proofs != payload["calls"] or len(rows) != len(proofs)
                    or any(row.sequence != sequence or row.project_id != plan.project_id or row.invocation_id != plan.invocation_id
                        or row.call_id != proof["claim"]["call_id"] or row.payload != proof
                        or acceptance_digest(row.payload) != row.content_hash for sequence, (row, proof) in enumerate(zip(rows, proofs)))):
                raise TestDesignResultIntegrityError("aggregate persisted native provenance differs from its archive")
            if payload.get("schema") == RECOVERED_BATCH_RESULT_SCHEMA:
                from .generation_batch_recovery_repository import GenerationBatchRecoveryRepository
                GenerationBatchRecoveryRepository._verify_history(session, payload)
            elif "recovery_invocation_id" in payload or "recovery_request" in payload:
                raise TestDesignResultIntegrityError("normal aggregate cannot acquire recovery authority")

    def record_batch(self, plan, payload, ref, digest, *, lease, require_current):
        plan = GenerationBatchReservation.model_validate(plan.model_dump(mode="json"))
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, plan.project_id)
            command = GenerationBatchRepository._guard(session, plan, lease)
            proofs = self._proofs(session, plan)
            if (payload.get("schema") != BATCH_RESULT_SCHEMA or acceptance_digest(payload) != digest
                    or payload["reservation"] != plan.model_dump(mode="json") or payload["calls"] != proofs
                    or payload["request"] != plan.request.model_dump(mode="json") or payload["status"] != "draft"
                    or payload["execution_authorized"] is not False or payload["mapping_status"] != "pending_independent_review"):
                raise TestDesignResultIntegrityError("aggregate transaction does not match its exact native call ledger")
            require_current()
            GenerationJobRepository._require_lease(session, command, lease)
            prior = session.scalar(select(Result).where(Result.invocation_id == plan.invocation_id))
            if prior is not None:
                if prior.provenance_kind != "batch" or prior.artifact_hash != digest or prior.artifact_ref != ref:
                    raise TestDesignResultIntegrityError("canonical generation already has a conflicting result")
                self.verify_history(payload)
                return self._metadata(prior)
            metadata = self._insert(session, plan, payload, ref, digest, proofs, command)
            GenerationJobRepository._require_lease(session, command, lease)
            return metadata

    @staticmethod
    def _insert(session, plan, payload, ref, digest, proofs, command):
        """Shared projections; callers hold and recheck their own command authority."""
        proposal = payload["proposal"]
        metadata = {"schema": payload["schema"], "project_id": plan.project_id, "generation_id": payload["generation_id"],
            "scope_revision_id": plan.request.scope_revision_id, "invocation_id": plan.invocation_id, "call_id": None,
            "call_ids": [proof["claim"]["call_id"] for proof in proofs], "batch_count": len(proofs),
            "plan_digest": plan.plan_digest, "status": "draft", "artifact_hash": digest,
            "case_count": len(proposal["cases"]), "gap_count": len(proposal["gaps"])}
        if payload["schema"] == RECOVERED_BATCH_RESULT_SCHEMA:
            metadata["recovery_invocation_id"] = command.id
        session.add(Result(**{key: metadata[key] for key in ("project_id", "generation_id", "scope_revision_id", "invocation_id", "call_id", "status", "artifact_hash")},
            provenance_kind="batch", artifact_ref=ref, payload=metadata, content_hash=acceptance_digest(metadata)))
        session.flush()
        for case in proposal["cases"]:
            session.add(Case(generation_id=metadata["generation_id"], case_id=case["case_id"], project_id=plan.project_id,
                payload=case, content_hash=acceptance_digest(case)))
        session.add(Coverage(generation_id=metadata["generation_id"], project_id=plan.project_id,
            payload=proposal["coverage"], content_hash=acceptance_digest(proposal["coverage"])))
        for sequence, proof in enumerate(proofs):
            session.add(Provenance(generation_id=metadata["generation_id"], sequence=sequence, project_id=plan.project_id,
                invocation_id=plan.invocation_id, call_id=proof["claim"]["call_id"], payload=proof, content_hash=acceptance_digest(proof)))
        now = session.scalar(select(func.clock_timestamp())).isoformat()
        event_metadata = {"scope_revision_id": plan.request.scope_revision_id, "call_ids": metadata["call_ids"], "batch_count": len(proofs)}
        if "recovery_invocation_id" in metadata:
            event_metadata.update(recovery_invocation_id=command.id, source_invocation_id=plan.invocation_id)
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=plan.actor_id, actor_kind="user",
            action="quality.test_design.generated", entity_type="test_design_result", entity_id=metadata["generation_id"], status="draft",
            summary="All native batch cases, full planned coverage and per-call lineage committed; no mapping approval or target execution granted.",
            conversation_id=command.conversation_id, tool_invocation_id=command.id, agent_goal_id=command.input_payload.get("agent_goal_id"),
            object_refs=["test_design_result:" + metadata["generation_id"]], evidence_refs=[], event_metadata=event_metadata))
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="quality.test_design.generated",
            occurred_at=now, correlation_id=plan.project_id, entity_type="test_design_result", entity_id=metadata["generation_id"],
            conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"), entity_version=1,
            mutation_kind="append", patch=metadata, query_keys=[["test-design-results", plan.project_id, plan.request.scope_revision_id]]), session=session)
        session.flush()
        return metadata
