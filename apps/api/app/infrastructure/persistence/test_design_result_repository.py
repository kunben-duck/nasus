from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.test_design_results import BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA, GENERATION_TOOL, GenerationResultRequest, TestDesignResultIntegrityError
from ...application.quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL, GenerationRecoveryRequest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from .db_models import ToolInvocationRecord, ConversationRecord, AgentGoalRecord, LLMCallRecord, AuditEventRecord, ModelProviderConfigRecord
from .event_outbox_repository import EventOutboxRepository
from .test_design_scope_models import TestDesignScopeRecord
from .test_design_scope_repository import TestDesignScopeRepository
from .test_design_result_models import TestDesignResultRecord as Result, TestDesignCaseRecord as Case, TestDesignCoverageRecord as Coverage
from .unit_of_work import session_scope


class TestDesignResultRepository:
    __test__ = False

    @staticmethod
    def _canonical(session, request, invocation_id, actor_id, *, authority_invocation_id=None):
        row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
        recovering = authority_invocation_id is not None
        if (row is None or row.tool_id != GENERATION_TOOL or row.status != ("failed" if recovering else "running")
                or row.input_payload.get("confirmed_by_user") is not True
                or row.input_payload.get("confirmed_actor_id") != actor_id
                or GenerationResultRequest.model_validate({k: v for k, v in query_payload(row.input_payload).items()
                    if k not in {"confirmed_by_user", "confirmed_at"}}) != request):
            raise TestDesignResultIntegrityError("generation requires its confirmed canonical actor and request")
        if recovering:
            from datetime import datetime, timezone
            from .generation_execution_models import GenerationNativeReplyRecord
            authority = session.scalar(select(ToolInvocationRecord).where(
                ToolInvocationRecord.id == authority_invocation_id).with_for_update())
            if (authority is None or authority.tool_id != GENERATION_RECOVER_TOOL or authority.status != "running"
                    or authority.input_payload.get("confirmed_by_user") is not True
                    or authority.input_payload.get("confirmed_actor_id") != actor_id):
                raise TestDesignResultIntegrityError("generation recovery requires independent canonical confirmation")
            recovery = GenerationRecoveryRequest.model_validate({k: v for k, v in query_payload(authority.input_payload).items()
                if k not in {"confirmed_by_user", "confirmed_at"}})
            reply = session.get(GenerationNativeReplyRecord, invocation_id)
            if (reply is None or reply.project_id != request.project_id or recovery.project_id != request.project_id
                    or recovery.invocation_id != invocation_id
                    or recovery.request_hash != acceptance_digest(request.model_dump(mode="json"))
                    or recovery.reply_artifact_hash != reply.artifact_hash or recovery.response_hash != reply.response_hash):
                raise TestDesignResultIntegrityError("generation recovery response pins mismatch")
            confirmed = datetime.fromisoformat(str(authority.input_payload.get("confirmed_at", "")))
            if confirmed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900:
                raise TestDesignResultIntegrityError("generation recovery confirmation expired")
            TestDesignResultRepository._project_scope(session, authority, request.project_id)
        TestDesignResultRepository._project_scope(session, row, request.project_id)
        scope = session.get(TestDesignScopeRecord, request.scope_revision_id)
        if scope is None or scope.project_id != request.project_id or scope.payload.get("artifact_hash") != request.scope_artifact_hash:
            raise TestDesignResultIntegrityError("generation scope pin mismatch")
        return row

    @staticmethod
    def _project_scope(session, row, project_id):
        if row.conversation_id:
            conversation = session.get(ConversationRecord, row.conversation_id)
            if conversation is None or conversation.project_id != project_id:
                raise TestDesignResultIntegrityError("generation conversation mismatch")
        if row.input_payload.get("agent_goal_id"):
            goal = session.get(AgentGoalRecord, row.input_payload["agent_goal_id"])
            if goal is None or goal.project_id != project_id or goal.conversation_id != row.conversation_id:
                raise TestDesignResultIntegrityError("generation goal mismatch")

    @classmethod
    def _call(cls, session, request, invocation_id, actor_id, call_id, response_hash, binding, *, authority_invocation_id=None):
        cls._canonical(session, request, invocation_id, actor_id, authority_invocation_id=authority_invocation_id)
        row = session.scalar(select(LLMCallRecord).where(LLMCallRecord.id == call_id).with_for_update())
        if (row is None or row.tool_invocation_id != invocation_id or row.project_id != request.project_id
                or row.purpose != GENERATION_TOOL or row.route != "chat" or row.runtime_mode != "live" or row.outcome != "success"
                or row.model_calls != 1 or row.provider != binding["provider"] or row.model_name != binding["model_name"]
                or row.selected_provider != row.provider or row.selected_model_name != row.model_name
                or row.usage_source != "provider" or row.input_token_count <= 0 or row.output_token_count <= 0
                or row.request_hash != acceptance_digest(request.model_dump(mode="json")) or row.response_hash != response_hash):
            raise TestDesignResultIntegrityError("generation lacks the exact successful native model-call receipt")
        if request.execution is not None:
            from .generation_execution_models import GenerationCallReservationRecord, GenerationNativeReplyRecord
            reservation = session.get(GenerationCallReservationRecord, invocation_id)
            reply = session.get(GenerationNativeReplyRecord, invocation_id)
            if (reservation is None or reply is None or reservation.project_id != request.project_id
                    or reservation.call_id != call_id or reply.call_id != call_id or reply.response_hash != response_hash
                    or acceptance_digest(reservation.payload) != reservation.content_hash
                    or reservation.payload["request"] != request.model_dump(mode="json")
                    or reservation.payload["actor_id"] != actor_id or reservation.payload["model_binding"] != binding
                    or acceptance_digest(reply.payload) != reply.content_hash):
                raise TestDesignResultIntegrityError("generation is missing its durable budgeted native response")
        return {"id": row.id, "provider": row.provider, "model_name": row.model_name,
                "request_hash": row.request_hash, "response_hash": row.response_hash,
                "input_tokens": row.input_token_count, "output_tokens": row.output_token_count,
                "usage_source": row.usage_source, "occurred_at": row.occurred_at.isoformat()}

    def require_recovery(self, request, invocation_id, actor_id, authority_invocation_id):
        with session_scope() as session:
            self._canonical(session, request, invocation_id, actor_id, authority_invocation_id=authority_invocation_id)

    def verify_recovery_history(self, payload):
        from .generation_execution_models import GenerationNativeReplyRecord
        with session_scope() as session:
            source = session.get(ToolInvocationRecord, payload["invocation_id"])
            authority = session.get(ToolInvocationRecord, payload["recovery_invocation_id"])
            reply = session.get(GenerationNativeReplyRecord, payload["invocation_id"])
            if (source is None or authority is None or reply is None or source.tool_id != GENERATION_TOOL
                    or authority.tool_id != GENERATION_RECOVER_TOOL
                    or any(row.input_payload.get("confirmed_by_user") is not True
                        or row.input_payload.get("confirmed_actor_id") != payload["actor_id"] for row in (source, authority))):
                raise TestDesignResultIntegrityError("generation recovery history is unavailable")
            original = GenerationResultRequest.model_validate({k: v for k, v in query_payload(source.input_payload).items()
                if k not in {"confirmed_by_user", "confirmed_at"}})
            recovery = GenerationRecoveryRequest.model_validate({k: v for k, v in query_payload(authority.input_payload).items()
                if k not in {"confirmed_by_user", "confirmed_at"}})
            if (original.model_dump(mode="json") != payload["request"] or recovery.project_id != payload["project_id"]
                    or recovery.invocation_id != source.id or recovery.request_hash != acceptance_digest(payload["request"])
                    or recovery.reply_artifact_hash != reply.artifact_hash or recovery.response_hash != payload["call"]["response_hash"]
                    or reply.response_hash != recovery.response_hash or reply.call_id != payload["call"]["id"]
                    or reply.project_id != payload["project_id"] or acceptance_digest(reply.payload) != reply.content_hash):
                raise TestDesignResultIntegrityError("generation recovery history pins mismatch")
            for row in (source, authority):
                self._project_scope(session, row, payload["project_id"])

    def verify_call(self, request, invocation_id, actor_id, call_id, response_hash, binding, *, authority_invocation_id=None):
        with session_scope() as session:
            return self._call(session, request, invocation_id, actor_id, call_id, response_hash, binding,
                authority_invocation_id=authority_invocation_id)

    def verify_batch_history(self, payload):
        from .generation_batch_result_repository import GenerationBatchResultRepository
        GenerationBatchResultRepository().verify_history(payload)

    @staticmethod
    def _metadata(row):
        value = row.payload
        if (acceptance_digest(value) != row.content_hash or any(value.get(k) != getattr(row, k) for k in (
                "project_id", "generation_id", "scope_revision_id", "invocation_id", "call_id", "status", "artifact_hash"))):
            raise TestDesignResultIntegrityError("generation result metadata mismatch")
        if (row.provenance_kind == "batch" and (row.call_id is not None or value.get("schema") not in {BATCH_RESULT_SCHEMA, RECOVERED_BATCH_RESULT_SCHEMA})
                or row.provenance_kind == "single" and (row.call_id is None or "call_ids" in value)
                or row.provenance_kind not in {"single", "batch"}):
            raise TestDesignResultIntegrityError("generation result has the wrong native provenance kind")
        if row.provenance_kind == "batch":
            recovered = value.get("schema") == RECOVERED_BATCH_RESULT_SCHEMA
            authority = value.get("recovery_invocation_id")
            if (recovered and (type(authority) is not str or not authority.strip() or authority == row.invocation_id)
                    or not recovered and "recovery_invocation_id" in value):
                raise TestDesignResultIntegrityError("aggregate metadata has inconsistent recovery provenance")
        return value

    def by_invocation(self, project_id, invocation_id):
        with session_scope() as session:
            row = session.scalar(select(Result).where(Result.invocation_id == invocation_id))
            if row is not None and row.project_id != project_id:
                raise KeyError("generation invocation not found")
            return self._metadata(row) if row is not None else None

    def list_metadata(self, request):
        with session_scope() as session:
            query = select(Result).where(Result.project_id == request.project_id)
            if request.after_id:
                cursor = session.get(Result, request.after_id)
                if cursor is None or cursor.project_id != request.project_id:
                    raise KeyError("draft cursor not found")
                query = query.where(Result.generation_id > request.after_id)
            rows = session.scalars(query.order_by(Result.generation_id).limit(request.limit + 1)).all()
            return [self._metadata(row) for row in rows]

    def get(self, project_id, generation_id):
        with session_scope() as session:
            row = session.get(Result, generation_id)
            if row is None or row.project_id != project_id:
                raise KeyError("generation result not found")
            metadata = self._metadata(row)
            cases = session.scalars(select(Case).where(Case.generation_id == generation_id).order_by(Case.case_id)).all()
            coverage = session.get(Coverage, generation_id)
            if (coverage is None or coverage.project_id != project_id or acceptance_digest(coverage.payload) != coverage.content_hash
                    or len(cases) != metadata["case_count"] or any(case.project_id != project_id
                        or case.case_id != case.payload.get("case_id") or acceptance_digest(case.payload) != case.content_hash for case in cases)):
                raise TestDesignResultIntegrityError("generation case or coverage projection mismatch")
            return {"metadata": metadata, "artifact_ref": row.artifact_ref,
                    "cases": [case.payload for case in cases], "coverage": coverage.payload}

    def record(self, request, payload, ref, digest, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, payload["actor_id"])
            # Keep the tested model/credential revision stable through the final
            # application-port recheck and transaction commit.
            model = session.scalar(select(ModelProviderConfigRecord).where(
                ModelProviderConfigRecord.config_id == request.model_config_id).with_for_update(read=True))
            if model is None:
                raise TestDesignResultIntegrityError("generation model configuration is unavailable")
            prior = session.scalar(select(Result).where(Result.invocation_id == payload["invocation_id"]))
            if prior is not None:
                if (prior.project_id != request.project_id or prior.artifact_hash != digest or prior.artifact_ref != ref):
                    raise TestDesignResultIntegrityError("generation invocation has a conflicting result")
                require_current()
                return self._metadata(prior)
            call = self._call(session, request, payload["invocation_id"], payload["actor_id"], payload["call"]["id"],
                              payload["call"]["response_hash"], payload["model_binding"],
                              authority_invocation_id=payload.get("recovery_invocation_id"))
            if (acceptance_digest(payload) != digest or payload["request"] != request.model_dump(mode="json") or call != payload["call"]):
                raise TestDesignResultIntegrityError("generation commit payload mismatch")
            require_current()
            proposal = payload["proposal"]
            metadata = {"project_id": request.project_id, "generation_id": payload["generation_id"],
                "scope_revision_id": request.scope_revision_id, "invocation_id": payload["invocation_id"], "call_id": call["id"],
                "status": "draft", "artifact_hash": digest, "case_count": len(proposal["cases"]), "gap_count": len(proposal["gaps"])}
            if "recovery_invocation_id" in payload:
                metadata["recovery_invocation_id"] = payload["recovery_invocation_id"]
            session.add(Result(**{k: metadata[k] for k in ("project_id", "generation_id", "scope_revision_id", "invocation_id", "call_id", "status", "artifact_hash")},
                artifact_ref=ref, payload=metadata, content_hash=acceptance_digest(metadata)))
            session.flush()
            for case in proposal["cases"]:
                session.add(Case(generation_id=metadata["generation_id"], case_id=case["case_id"], project_id=request.project_id,
                    payload=case, content_hash=acceptance_digest(case)))
            session.add(Coverage(generation_id=metadata["generation_id"], project_id=request.project_id,
                payload=proposal["coverage"], content_hash=acceptance_digest(proposal["coverage"])))
            command = session.get(ToolInvocationRecord, payload.get("recovery_invocation_id", payload["invocation_id"]))
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=call["occurred_at"], actor=payload["actor_id"], actor_kind="user",
                action="quality.test_design.generated", entity_type="test_design_result", entity_id=metadata["generation_id"], status="draft",
                summary="Draft cases and planned coverage archived; independent mapping review and target execution are not granted.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                object_refs=["test_design_result:" + metadata["generation_id"]], evidence_refs=[],
                event_metadata={"scope_revision_id": request.scope_revision_id, "call_id": call["id"],
                    "source_invocation_id": payload["invocation_id"]}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="quality.test_design.generated",
                occurred_at=call["occurred_at"], correlation_id=request.project_id, entity_type="test_design_result", entity_id=metadata["generation_id"],
                conversation_id=command.conversation_id, agent_goal_id=command.input_payload.get("agent_goal_id"),
                entity_version=1, mutation_kind="append", patch=metadata,
                query_keys=[["test-design-results", request.project_id, request.scope_revision_id]]), session=session)
            session.flush()
            return metadata
