"""Atomic PG budget/receipt/draft facts with exact canonical authority."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.quality_loop.automation_script_inputs import (SCRIPT_TOOL, SCRIPT_RESERVATION_SCHEMA,
    SCRIPT_REPLY_SCHEMA, SCRIPT_RESULT_SCHEMA, ScriptExecutionRequest, validate_script_output)
from ...application.quality_loop.generation_budget import GenerationModelPolicy, verify_generation_usage
from ...application.quality_loop.generation_executor import GenerationOutcomeUnknown
from ...application.quality_loop.test_design_results import TestDesignResultIntegrityError, response_digest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.system_image.source_access import SourceAccessDenied
from .automation_script_models import AutomationCallReservationRecord as Reservation, AutomationNativeReplyRecord as Reply, AutomationScriptRevisionRecord as Result
from .automation_provenance_v1 import AutomationProvenanceProjectorV1
from .db_models import AuditEventRecord, LLMCallRecord, ModelProviderConfigRecord, ProjectRoleBindingRecord, ToolInvocationRecord, UserIdentityRecord
from ...application.platform.tool_models import EventPayload
from .event_outbox_repository import EventOutboxRepository
from .llm_call_repository import SQLAlchemyLLMCallRepository
from .test_design_mapping_models import TestDesignMappingRecord
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class AutomationScriptRepository:
    @staticmethod
    def _value(row, fields):
        value = row.payload
        if acceptance_digest(value) != row.content_hash or any(value.get(key) != getattr(row, key) for key in fields):
            raise TestDesignResultIntegrityError("automation persistence integrity mismatch")
        if isinstance(row, Reservation) and any(value.get("request", {}).get(key) != getattr(row, key)
                for key in ("case_approval_revision_id", "case_approval_artifact_hash")):
            raise TestDesignResultIntegrityError("automation reservation lost its independent case admission")
        return value

    @staticmethod
    def _canonical(session, request, invocation_id, actor_id, *, running=True):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        if running:
            query = query.with_for_update()
        command = session.scalar(query)
        if (command is None or command.tool_id != SCRIPT_TOOL or running and command.status != "running"
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id
                or ScriptExecutionRequest.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                    if key not in {"confirmed_by_user", "confirmed_at"}}) != request):
            raise TestDesignResultIntegrityError("automation requires its exact confirmed canonical request")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        mapping = session.get(TestDesignMappingRecord, request.mapping_revision_id)
        if mapping is None or mapping.project_id != request.project_id or mapping.payload.get("artifact_hash") != request.mapping_artifact_hash:
            raise TestDesignResultIntegrityError("automation mapping pin mismatch")
        return command

    @staticmethod
    def _administrator(session, project_id, actor_id):
        TestDesignScopeRepository._actor(session, project_id, actor_id)
        identity = session.get(UserIdentityRecord, actor_id)
        roles = session.scalars(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.project_id == project_id,
            ProjectRoleBindingRecord.user_id == actor_id, ProjectRoleBindingRecord.version_id.is_(None),
            ProjectRoleBindingRecord.session_id.is_(None), ProjectRoleBindingRecord.status == "active")).all()
        if identity.role != "platform_admin" and (len(roles) != 1 or roles[0].role != "project_admin"):
            raise SourceAccessDenied("automation model egress requires a current project administrator")

    @classmethod
    def _reservation(cls, session, request, invocation_id):
        row = session.scalar(select(Reservation).where(Reservation.invocation_id == invocation_id).with_for_update())
        if row is None or row.project_id != request.project_id:
            raise TestDesignResultIntegrityError("automation lacks its original reservation")
        value = cls._value(row, ("project_id", "invocation_id", "call_id", "generation_id", "mapping_revision_id"))
        if value.get("schema") != SCRIPT_RESERVATION_SCHEMA or value["request"] != request.model_dump(mode="json"):
            raise TestDesignResultIntegrityError("automation reservation request mismatch")
        return value

    @classmethod
    def _verify_call(cls, value, call, request, *, successful=False):
        binding = value["model_binding"]
        if (call.id != value["call_id"] or call.tool_invocation_id != value["invocation_id"]
                or call.project_id != request.project_id or call.purpose != SCRIPT_TOOL or call.route != "chat"
                or call.provider != binding["provider"] or call.model_name != binding["model_name"]
                or call.selected_provider != call.provider or call.selected_model_name != call.model_name
                or call.runtime_mode != "live" or call.model_calls != 1
                or call.request_hash != acceptance_digest(request.model_dump(mode="json"))
                or successful and (call.outcome != "success" or call.usage_source != "provider")):
            raise TestDesignResultIntegrityError("automation call differs from its original reservation")
        if successful:
            return verify_generation_usage(GenerationModelPolicy.model_validate(value["policy"]), request.budget,
                call.input_token_count, call.output_token_count)

    def get(self, project_id, invocation_id):
        with session_scope() as session:
            row = session.get(Reservation, invocation_id)
            if row is None:
                return None
            if row.project_id != project_id:
                raise KeyError("automation reservation not found")
            value = self._value(row, ("project_id", "invocation_id", "call_id", "generation_id", "mapping_revision_id"))
            request = ScriptExecutionRequest.model_validate(value["request"])
            if value.get("schema") != SCRIPT_RESERVATION_SCHEMA or request.mapping_revision_id != row.mapping_revision_id:
                raise TestDesignResultIntegrityError("automation reservation schema mismatch")
            self._canonical(session, request, invocation_id, value["actor_id"], running=False)
            mapping = session.get(TestDesignMappingRecord, request.mapping_revision_id)
            if mapping.generation_id != value["generation_id"]:
                raise TestDesignResultIntegrityError("automation reservation generation mismatch")
            reply = session.get(Reply, invocation_id)
            receipt = self._value(reply, ("project_id", "invocation_id", "call_id", "artifact_ref", "artifact_hash", "response_hash")) if reply else None
            if receipt:
                call = session.get(LLMCallRecord, value["call_id"])
                if call is None or receipt["call_id"] != value["call_id"] or receipt["response_hash"] != call.response_hash:
                    raise TestDesignResultIntegrityError("automation native call archive missing")
                usage = self._verify_call(value, call, request, successful=True)
                if usage != receipt["usage"]:
                    raise TestDesignResultIntegrityError("automation native usage archive mismatch")
            result = session.scalar(select(Result).where(Result.invocation_id == invocation_id))
            metadata = self._value(result, ("project_id", "script_revision_id", "invocation_id", "call_id", "artifact_hash", "response_hash", "status")) if result else None
            if metadata and (receipt is None or metadata["call_id"] != receipt["call_id"] or metadata["response_hash"] != receipt["response_hash"]):
                raise TestDesignResultIntegrityError("automation result lacks its original native reply")
            if metadata:
                AutomationProvenanceProjectorV1().verify(session, result)
            return {"reservation": value, "reply": receipt, "result": metadata}

    def reserve(self, request, payload, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            self._administrator(session, request.project_id, payload["actor_id"])
            command = self._canonical(session, request, payload["invocation_id"], payload["actor_id"])
            confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
            if confirmed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900:
                raise TestDesignResultIntegrityError("automation confirmation expired")
            model = session.scalar(select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.config_id == request.model_config_id).with_for_update(read=True))
            if (model is None or payload["request"] != request.model_dump(mode="json")
                    or payload.get("schema") != SCRIPT_RESERVATION_SCHEMA
                    or session.get(TestDesignMappingRecord, request.mapping_revision_id).generation_id != payload.get("generation_id")):
                raise TestDesignResultIntegrityError("automation reservation input mismatch")
            if session.get(Reservation, command.id) is not None:
                raise GenerationOutcomeUnknown("automation call already reserved; never repeat uncertain egress")
            if request.case_approval_revision_id is None:
                raise TestDesignResultIntegrityError("new automation reservations require independent case admission")
            require_current()
            payload = {**payload, "mapping_revision_id": request.mapping_revision_id}
            session.add(Reservation(invocation_id=command.id, project_id=request.project_id, generation_id=payload["generation_id"], mapping_revision_id=request.mapping_revision_id,
                case_approval_revision_id=request.case_approval_revision_id, case_approval_artifact_hash=request.case_approval_artifact_hash,
                call_id=payload["call_id"], payload=payload, content_hash=acceptance_digest(payload)))
            self._audit(session, command, payload["actor_id"], "quality.automation.call_reserved", "running",
                {"mapping_revision_id": request.mapping_revision_id, "reservation": payload["reservation"]})
            session.flush()

    def record_reply(self, request, payload, ref, digest, call, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            self._administrator(session, request.project_id, payload["actor_id"])
            command = self._canonical(session, request, payload["invocation_id"], payload["actor_id"])
            reservation = self._reservation(session, request, command.id)
            usage = self._verify_call(reservation, call, request, successful=True)
            if (payload["request"] != request.model_dump(mode="json") or payload["actor_id"] != reservation["actor_id"]
                    or payload.get("schema") != SCRIPT_REPLY_SCHEMA or payload.get("project_id") != request.project_id
                    or payload["call_id"] != call.id or response_digest(payload["content"]) != call.response_hash
                    or acceptance_digest(payload) != digest or payload["usage"] != usage):
                raise TestDesignResultIntegrityError("automation native reply mismatch")
            model = session.scalar(select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.config_id == request.model_config_id).with_for_update(read=True))
            if model is None:
                raise TestDesignResultIntegrityError("automation model configuration unavailable")
            require_current()
            metadata = {"project_id": request.project_id, "invocation_id": command.id, "call_id": call.id,
                "artifact_ref": ref, "artifact_hash": digest, "response_hash": call.response_hash, "usage": usage}
            prior = session.get(Reply, command.id)
            if prior is not None:
                if prior.payload != metadata or acceptance_digest(prior.payload) != prior.content_hash:
                    raise TestDesignResultIntegrityError("automation native reply cannot overwrite history")
                return
            if session.get(LLMCallRecord, call.id) is not None:
                raise GenerationOutcomeUnknown("automation already has a terminal call receipt")
            session.add(SQLAlchemyLLMCallRepository._to_record(call))
            session.flush()
            session.add(Reply(**{key: metadata[key] for key in ("project_id", "invocation_id", "call_id", "artifact_ref", "artifact_hash", "response_hash")},
                payload=metadata, content_hash=acceptance_digest(metadata)))
            self._audit(session, command, payload["actor_id"], "quality.automation.reply_archived", "running", {"call_id": call.id, "usage": usage})
            session.flush()

    def record_failure(self, request, invocation_id, call):
        with session_scope() as session:
            self._verify_call(self._reservation(session, request, invocation_id), call, request)
            if session.get(LLMCallRecord, call.id) is None:
                session.add(SQLAlchemyLLMCallRepository._to_record(call))

    def record_result(self, request, payload, ref, digest, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            self._administrator(session, request.project_id, payload["actor_id"])
            command = self._canonical(session, request, payload["invocation_id"], payload["actor_id"])
            reservation = self._reservation(session, request, command.id)
            reply = session.get(Reply, command.id)
            call = session.get(LLMCallRecord, payload["call_id"])
            if reply is None or call is None or reply.call_id != payload["call_id"]:
                raise TestDesignResultIntegrityError("automation result lacks a native reply")
            self._verify_call(reservation, call, request, successful=True)
            self._value(reply, ("project_id", "invocation_id", "call_id", "artifact_ref", "artifact_hash", "response_hash"))
            if (acceptance_digest(payload) != digest or payload["request"] != request.model_dump(mode="json")
                    or payload.get("schema") != SCRIPT_RESULT_SCHEMA or payload.get("project_id") != request.project_id
                    or payload["model_binding"] != reservation["model_binding"] or payload["actor_id"] != reservation["actor_id"]
                    or payload["response_hash"] != call.response_hash or reply.response_hash != call.response_hash
                    or response_digest(payload["raw_output"]) != call.response_hash or payload["status"] != "draft"
                    or payload["prepared"]["input_digest"] != request.input_digest
                    or validate_script_output(payload["prepared"], payload["raw_output"], http_protocol=request.selected_http_protocol()) != payload["proposal"]):
                raise TestDesignResultIntegrityError("automation result provenance mismatch")
            model = session.scalar(select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.config_id == request.model_config_id).with_for_update(read=True))
            if model is None:
                raise TestDesignResultIntegrityError("automation model configuration unavailable")
            require_current()
            prior = session.scalar(select(Result).where(Result.invocation_id == command.id))
            if prior is not None:
                if prior.artifact_hash != digest or prior.artifact_ref != ref:
                    raise TestDesignResultIntegrityError("automation script invocation already has a different result")
                AutomationProvenanceProjectorV1().verify(session, prior)
                return self._value(prior, ("project_id", "script_revision_id", "invocation_id", "call_id", "artifact_hash", "response_hash", "status"))
            metadata = {key: payload[key] for key in ("project_id", "script_revision_id", "invocation_id", "call_id", "response_hash", "status")}
            metadata.update(artifact_hash=digest, script_count=payload["proposal"]["script_count"], gap_count=payload["proposal"]["gap_count"],
                input_digest=request.input_digest, mapping_revision_id=request.mapping_revision_id,
                mapping_artifact_hash=request.mapping_artifact_hash, execution_authorized=False)
            result = Result(**{key: metadata[key] for key in ("project_id", "script_revision_id", "invocation_id", "call_id", "artifact_hash", "response_hash", "status")},
                artifact_ref=ref, payload=metadata, content_hash=acceptance_digest(metadata))
            session.add(result)
            AutomationProvenanceProjectorV1().record_script(session, result)
            self._audit(session, command, payload["actor_id"], "quality.automation.draft_saved", "draft",
                {"script_revision_id": metadata["script_revision_id"], "artifact_hash": digest, "input_digest": request.input_digest})
            session.flush()
            return metadata

    def result(self, project_id, revision_id):
        with session_scope() as session:
            row = session.get(Result, revision_id)
            if row is None or row.project_id != project_id:
                raise KeyError("automation script revision not found")
            AutomationProvenanceProjectorV1().verify(session, row)
            return {"metadata": self._value(row, ("project_id", "script_revision_id", "invocation_id", "call_id", "artifact_hash", "response_hash", "status")),
                "artifact_ref": row.artifact_ref}

    def history(self, query):
        with session_scope() as session:
            rows = session.scalars(select(ToolInvocationRecord).where(
                ToolInvocationRecord.tool_id == SCRIPT_TOOL,
                ToolInvocationRecord.input_payload["project_id"].as_string() == query.project_id,
                ToolInvocationRecord.input_payload["mapping_revision_id"].as_string() == query.mapping_revision_id,
                ToolInvocationRecord.input_payload["confirmed_by_user"].as_boolean().is_(True),
                ToolInvocationRecord.status.in_(("running", "completed", "failed", "cancelled")),
                ToolInvocationRecord.id > query.after_id,
            ).order_by(ToolInvocationRecord.id).limit(query.limit + 1)).all()
            values = []
            for row in rows:
                value = query_payload(row.input_payload)
                request = ScriptExecutionRequest.model_validate({key: item for key, item in value.items()
                    if key not in {"confirmed_by_user", "confirmed_at"}})
                TestDesignResultRepository._project_scope(session, row, query.project_id)
                if (request.mapping_revision_id != query.mapping_revision_id
                        or request.mapping_artifact_hash != query.mapping_artifact_hash):
                    raise TestDesignResultIntegrityError("automation history canonical mapping mismatch")
                values.append({"invocation_id": row.id, "status": row.status})
            return values

    @staticmethod
    def _audit(session, command, actor_id, action, status, metadata):
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=datetime.now(timezone.utc).isoformat(), actor=actor_id,
            actor_kind="user", action=action, entity_type="tool_invocation", entity_id=command.id, status=status,
            summary="Fixed native automation draft lifecycle; no target execution or verified coverage.",
            conversation_id=command.conversation_id, tool_invocation_id=command.id, object_refs=[], evidence_refs=[], event_metadata=metadata))
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=action,
            occurred_at=datetime.now(timezone.utc).isoformat(), correlation_id=command.input_payload["project_id"],
            entity_type="tool_invocation", entity_id=command.id, conversation_id=command.conversation_id,
            agent_goal_id=command.input_payload.get("agent_goal_id"), entity_version=1, mutation_kind="append",
            patch=metadata, query_keys=[["automation-script-revisions", command.input_payload["project_id"]]]), session=session)
