"""Append-only scope calls; a durable reservation is never resent."""
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.scope_draft_inputs import SCOPE_DRAFT_TOOL, ScopeDraftRequest
from ...application.quality_loop.generation_executor import GenerationOutcomeUnknown
from ...application.quality_loop.generation_budget import GenerationModelPolicy, verify_generation_usage
from ...application.quality_loop.scope_draft_inputs import SCOPE_DRAFT_PROMPT
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.test_design_scope import TestDesignScopeIntegrityError
from .automation_script_repository import AutomationScriptRepository
from .db_models import AuditEventRecord, LLMCallRecord, ModelProviderConfigRecord, ToolInvocationRecord
from .confirmation_clock import confirmation_time
from .event_outbox_repository import EventOutboxRepository
from .llm_call_repository import SQLAlchemyLLMCallRepository
from .scope_draft_models import ScopeDraftEventRecord as Record
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class ScopeDraftRepository:
    @staticmethod
    def _canonical(session, request, invocation_id, actor_id, *, running=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        if running:
            query = query.with_for_update().execution_options(populate_existing=True)
        command = session.scalar(query)
        if (command is None or command.tool_id != SCOPE_DRAFT_TOOL or running and command.status != "running"
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id
                or ScopeDraftRequest.model_validate({key: item for key, item in query_payload(command.input_payload).items()
                    if key not in {"confirmed_by_user", "confirmed_at"}}) != request):
            raise TestDesignScopeIntegrityError("scope draft requires its exact confirmed canonical command")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        return command

    @staticmethod
    def _verify_call(reserved, request, invocation_id, call, *, successful):
        binding = reserved["model_binding"]
        if (call is None or call.id != reserved["call_id"] or call.tool_invocation_id != invocation_id
                or call.project_id != request.project_id or call.route != "chat" or call.purpose != SCOPE_DRAFT_TOOL
                or call.model_name != binding["model_name"] or call.provider != binding["provider"]
                or call.selected_provider != call.provider or call.selected_model_name != call.model_name
                or call.prompt_id != SCOPE_DRAFT_PROMPT or call.prompt_version != "v1"
                or call.runtime_mode != "live" or call.model_calls != 1
                or call.request_hash != acceptance_digest(request.model_dump(mode="json"))
                or successful and (call.outcome != "success" or call.usage_source != "provider")):
            raise TestDesignScopeIntegrityError("scope native call provenance mismatch")
        if successful:
            return verify_generation_usage(GenerationModelPolicy.model_validate(reserved["plan"]["policy"]),
                request.budget, call.input_token_count, call.output_token_count)

    @staticmethod
    def _value(row):
        value = row.payload
        if acceptance_digest(value) != row.content_hash:
            raise TestDesignScopeIntegrityError("scope draft event digest mismatch")
        return {"event_id": row.event_id, "kind": row.kind, "actor_id": row.actor_id,
            "recorded_at": row.recorded_at, "invocation_id": row.invocation_id,
            "context_id": row.context_id, "project_id": row.project_id, "payload": deepcopy(value)}

    def events(self, project_id, invocation_id):
        with session_scope() as session:
            events = {row.kind: self._value(row) for row in session.scalars(select(Record).where(
                Record.project_id == project_id, Record.invocation_id == invocation_id))}
            if not events:
                return events
            reserved = events.get("reserved")
            if reserved is None:
                raise TestDesignScopeIntegrityError("scope events lack their reservation")
            value = reserved["payload"]
            request = ScopeDraftRequest.model_validate(value["request"])
            if (request.project_id != project_id or any(row["context_id"] != request.context_id
                    or row["actor_id"] != reserved["actor_id"] for row in events.values())
                    or acceptance_digest(value["plan"]) != request.plan_digest
                    or value["model_binding"] != value["plan"]["model_binding"]
                    or value["model_binding"]["config_digest"] != request.model_config_digest):
                raise TestDesignScopeIntegrityError("scope reservation identity mismatch")
            self._canonical(session, request, invocation_id, reserved["actor_id"])
            if "replied" in events and "failed" in events or "draft" in events and "replied" not in events:
                raise TestDesignScopeIntegrityError("scope event history is inconsistent")
            if "replied" in events or "failed" in events:
                call = session.get(LLMCallRecord, value["call_id"])
                usage = self._verify_call(value, request, invocation_id, call, successful="replied" in events)
                if "replied" in events:
                    reply = events["replied"]["payload"]
                    if usage != reply["usage"] or call.response_hash != reply["response_hash"]:
                        raise TestDesignScopeIntegrityError("scope reply differs from native usage or response")
            return events

    def history(self, project_id, context_id):
        with session_scope() as session:
            rows = session.scalars(select(Record).where(Record.project_id == project_id,
                Record.context_id == context_id, Record.kind == "reserved")
                .order_by(Record.recorded_at.desc(), Record.event_id.desc()).limit(101)).all()
            if len(rows) > 100:
                raise GenerationOutcomeUnknown("scope history exceeds this view; do not infer that earlier calls are resolved")
            return [self._value(row) for row in rows]

    def record(self, request, invocation_id, actor_id, kind, payload, *, require_current, call=None):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            AutomationScriptRepository._administrator(session, request.project_id, actor_id)
            command = self._canonical(session, request, invocation_id, actor_id, running=True)
            events = {row.kind: row for row in session.scalars(select(Record).where(Record.invocation_id == invocation_id))}
            require_current()
            if kind == "reserved" and events:
                raise GenerationOutcomeUnknown("scope call is already reserved; never resend")
            if kind == "reserved":
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                if confirmed.tzinfo is None or not 0 <= (confirmation_time(session) - confirmed).total_seconds() <= 900:
                    raise TestDesignScopeIntegrityError("scope model confirmation expired")
                model = session.scalar(select(ModelProviderConfigRecord).where(
                    ModelProviderConfigRecord.config_id == request.model_config_id).with_for_update(read=True))
                if (model is None or payload["request"] != request.model_dump(mode="json")
                        or acceptance_digest(payload["plan"]) != request.plan_digest
                        or payload["model_binding"] != payload["plan"]["model_binding"]
                        or payload["model_binding"]["config_digest"] != request.model_config_digest):
                    raise TestDesignScopeIntegrityError("scope reservation differs from its confirmed inputs")
            if kind != "reserved":
                reserved = events.get("reserved")
                if (reserved is None or reserved.actor_id != actor_id or reserved.project_id != request.project_id
                        or self._value(reserved)["payload"]["request"] != request.model_dump(mode="json")):
                    raise TestDesignScopeIntegrityError("scope call reservation mismatch")
                if kind in {"replied", "failed"}:
                    usage = self._verify_call(reserved.payload, request, invocation_id, call, successful=kind == "replied")
                    if kind == "replied" and (payload["usage"] != usage or payload["response_hash"] != call.response_hash):
                        raise TestDesignScopeIntegrityError("scope reply differs from its native call")
                    if "failed" in events or "replied" in events:
                        raise GenerationOutcomeUnknown("scope call already has a terminal reply")
                elif kind != "draft" or "replied" not in events:
                    raise TestDesignScopeIntegrityError("scope result requires its native reply")
            if kind in events:
                if events[kind].payload != payload:
                    raise TestDesignScopeIntegrityError("scope event cannot overwrite history")
                return self._value(events[kind])
            if call is not None:
                if session.get(LLMCallRecord, call.id) is not None:
                    raise GenerationOutcomeUnknown("scope call already recorded")
                session.add(SQLAlchemyLLMCallRepository._to_record(call))
            now = session.scalar(select(func.clock_timestamp())).isoformat()
            row = Record(event_id="scope_draft_" + uuid4().hex, project_id=request.project_id,
                context_id=request.context_id, invocation_id=invocation_id, kind=kind, actor_id=actor_id,
                recorded_at=now, payload=deepcopy(payload), content_hash=acceptance_digest(payload))
            session.add(row)
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=actor_id, actor_kind="user",
                action="quality.scope_draft." + kind, entity_type="tool_invocation", entity_id=invocation_id,
                status="recorded" if kind == "replied" else kind,
                summary="Model scope suggestion only; independent review is required.",
                conversation_id=command.conversation_id, tool_invocation_id=invocation_id,
                object_refs=[], evidence_refs=[], event_metadata={"project_id": request.project_id, "context_id": request.context_id}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="quality.scope_draft.updated",
                occurred_at=now, correlation_id=request.project_id, entity_type="tool_invocation", entity_id=invocation_id,
                entity_version=1, mutation_kind="append", conversation_id=command.conversation_id,
                patch={"status": kind}, query_keys=[["scope-drafts", request.project_id, request.context_id]]), session=session)
            session.flush()
            require_current()
            return self._value(row)
