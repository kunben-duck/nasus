"""Append-only call reservations and atomic native receipt/usage audit."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.generation_budget import GenerationModelPolicy, verify_generation_usage
from ...application.quality_loop.generation_execution_inputs import GENERATION_RESERVATION_SCHEMA
from ...application.quality_loop.generation_executor import GenerationOutcomeUnknown
from ...application.quality_loop.test_design_results import GENERATION_TOOL, TestDesignResultIntegrityError, response_digest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from .db_models import LLMCallRecord, ModelProviderConfigRecord, UserIdentityRecord, ProjectRoleBindingRecord, AuditEventRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .generation_execution_models import GenerationCallReservationRecord as Reservation, GenerationNativeReplyRecord as Reply
from .generation_batch_models import GenerationBatchReservationRecord
from .llm_call_repository import SQLAlchemyLLMCallRepository
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class GenerationExecutionRepository:
    @staticmethod
    def _value(row):
        value = row.payload
        if (acceptance_digest(value) != row.content_hash or value.get("invocation_id") != row.invocation_id
                or value.get("project_id") != row.project_id or value.get("call_id") != row.call_id):
            raise TestDesignResultIntegrityError("generation execution record integrity mismatch")
        return value

    def get(self, project_id, invocation_id):
        with session_scope() as session:
            row = session.get(Reservation, invocation_id)
            if row is None:
                return None
            if row.project_id != project_id:
                raise KeyError("generation execution not found")
            value = self._value(row)
            if value.get("schema") != GENERATION_RESERVATION_SCHEMA or value["request"]["scope_revision_id"] != row.scope_revision_id:
                raise TestDesignResultIntegrityError("generation reservation schema mismatch")
            reply = session.get(Reply, invocation_id)
            receipt = self._value(reply) if reply else None
            if receipt and any(receipt.get(key) != getattr(reply, key) for key in ("artifact_ref", "artifact_hash", "response_hash")):
                raise TestDesignResultIntegrityError("generation reply metadata mismatch")
            return {"reservation": value, "reply": receipt}

    def reserve(self, request, payload, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            actor_id = payload["actor_id"]
            TestDesignScopeRepository._actor(session, request.project_id, actor_id)
            identity = session.get(UserIdentityRecord, actor_id)
            role = session.scalar(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.project_id == request.project_id,
                ProjectRoleBindingRecord.user_id == actor_id, ProjectRoleBindingRecord.version_id.is_(None),
                ProjectRoleBindingRecord.session_id.is_(None), ProjectRoleBindingRecord.status == "active"))
            if identity.role != "platform_admin" and (role is None or role.role != "project_admin"):
                raise PermissionError("generation requires a current project administrator")
            command = TestDesignResultRepository._canonical(session, request, payload["invocation_id"], actor_id)
            if request.execution is None:
                raise TestDesignResultIntegrityError("generation requires explicit budget/source consent")
            confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
            if confirmed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900:
                raise ValueError("generation egress confirmation expired")
            model = session.scalar(select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.config_id == request.model_config_id).with_for_update(read=True))
            if model is None or payload["request"] != request.model_dump(mode="json") or payload.get("schema") != GENERATION_RESERVATION_SCHEMA:
                raise TestDesignResultIntegrityError("generation reservation pins mismatch")
            if session.get(Reservation, command.id) is not None or session.get(GenerationBatchReservationRecord, command.id) is not None:
                raise GenerationOutcomeUnknown("generation call already reserved; never duplicate model egress")
            require_current()
            session.add(Reservation(invocation_id=command.id, project_id=request.project_id, scope_revision_id=request.scope_revision_id,
                call_id=payload["call_id"], payload=payload, content_hash=acceptance_digest(payload)))
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=payload["reserved_at"], actor=actor_id, actor_kind="user",
                action="quality.test_design.call_reserved", entity_type="tool_invocation", entity_id=command.id, status="running",
                summary="Confirmed native generation budget reserved; unknown outcomes will not be resent.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id, object_refs=[], evidence_refs=[],
                event_metadata={"scope_revision_id": request.scope_revision_id, "reservation": payload["reservation"]}))
            self._event(session, command, "quality.test_design.call_reserved", {"call_id": payload["call_id"], "reservation": payload["reservation"]})
            session.flush()

    @classmethod
    def _reservation(cls, session, request, invocation_id, call):
        row = session.scalar(select(Reservation).where(Reservation.invocation_id == invocation_id).with_for_update())
        if row is None or row.project_id != request.project_id or cls._value(row)["request"] != request.model_dump(mode="json"):
            raise TestDesignResultIntegrityError("native call lacks its exact reservation")
        value = cls._value(row)
        binding = value["model_binding"]
        if (call.id != row.call_id or call.tool_invocation_id != invocation_id or call.project_id != request.project_id
                or call.purpose != GENERATION_TOOL or call.provider != binding["provider"] or call.model_name != binding["model_name"]
                or call.selected_provider != call.provider or call.selected_model_name != call.model_name
                or call.runtime_mode != "live" or call.model_calls != 1
                or call.request_hash != acceptance_digest(request.model_dump(mode="json"))):
            raise TestDesignResultIntegrityError("native call receipt differs from its reservation")
        return value

    def record_reply(self, request, payload, artifact_ref, artifact_hash, call, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, payload["actor_id"])
            command = TestDesignResultRepository._canonical(session, request, payload["invocation_id"], payload["actor_id"])
            model = session.scalar(select(ModelProviderConfigRecord).where(
                ModelProviderConfigRecord.config_id == request.model_config_id).with_for_update(read=True))
            if model is None:
                raise TestDesignResultIntegrityError("native generation model is no longer available")
            reservation = self._reservation(session, request, payload["invocation_id"], call)
            if (call.outcome != "success" or call.usage_source != "provider" or call.input_token_count <= 0 or call.output_token_count <= 0
                    or response_digest(payload["content"]) != call.response_hash or acceptance_digest(payload) != artifact_hash
                    or payload["request"] != request.model_dump(mode="json") or payload["actor_id"] != reservation["actor_id"]):
                raise TestDesignResultIntegrityError("native response does not match its audited call")
            expected_usage = verify_generation_usage(GenerationModelPolicy.model_validate(reservation["policy"]),
                request.execution.budget, call.input_token_count, call.output_token_count)
            if payload["usage"] != expected_usage:
                raise TestDesignResultIntegrityError("native response usage differs from its reservation and audit")
            require_current()
            metadata = {"project_id": request.project_id, "invocation_id": payload["invocation_id"], "call_id": call.id,
                "artifact_ref": artifact_ref, "artifact_hash": artifact_hash, "response_hash": call.response_hash, "usage": payload["usage"]}
            prior = session.get(Reply, payload["invocation_id"])
            if prior is not None:
                if self._value(prior) != metadata:
                    raise TestDesignResultIntegrityError("native response cannot overwrite history")
                return
            if session.get(LLMCallRecord, call.id) is not None:
                raise GenerationOutcomeUnknown("generation already has a terminal call receipt")
            session.add(SQLAlchemyLLMCallRepository._to_record(call))
            session.flush()
            session.add(Reply(**{key: metadata[key] for key in ("project_id", "invocation_id", "call_id", "artifact_ref", "artifact_hash", "response_hash")},
                payload=metadata, content_hash=acceptance_digest(metadata)))
            self._event(session, command, "quality.test_design.reply_archived", {"call_id": call.id, "usage": payload["usage"]})
            session.flush()

    def record_failure(self, request, invocation_id, call):
        with session_scope() as session:
            self._reservation(session, request, invocation_id, call)
            if session.get(LLMCallRecord, call.id) is not None:
                return
            session.add(SQLAlchemyLLMCallRepository._to_record(call))

    @staticmethod
    def _event(session, command, kind, metadata):
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=kind,
            occurred_at=datetime.now(timezone.utc).isoformat(), correlation_id=command.input_payload["project_id"],
            entity_type="tool_invocation", entity_id=command.id, conversation_id=command.conversation_id,
            agent_goal_id=command.input_payload.get("agent_goal_id"), entity_version=1, mutation_kind="append",
            patch=metadata, query_keys=[["test-design-executions", command.input_payload["project_id"]]]), session=session)
