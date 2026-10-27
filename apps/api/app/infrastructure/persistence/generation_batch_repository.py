"""Fenced, append-only batch egress ledger. No provider I/O or task lifecycle."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select

from ...application.quality_loop.generation_batch_ledger import (
    GenerationBatchReservation, batch_call_request_hash, validate_batch_reply,
)
from ...application.quality_loop.generation_budget import verify_generation_usage
from ...application.quality_loop.generation_executor import GenerationOutcomeUnknown
from ...application.quality_loop.generation_work_lease import GenerationLeaseLost
from ...application.quality_loop.test_design_results import GENERATION_TOOL, TestDesignResultIntegrityError
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from .db_models import AuditEventRecord, LLMCallRecord, ModelProviderConfigRecord, ProjectRoleBindingRecord, UserIdentityRecord, ToolInvocationRecord
from .generation_batch_models import GenerationBatchReservationRecord as Plan, GenerationBatchCallRecord as Claim, GenerationBatchReplyRecord as Reply
from .generation_execution_models import GenerationCallReservationRecord
from .generation_execution_repository import GenerationExecutionRepository
from .generation_job_repository import GenerationJobRepository
from .llm_call_repository import SQLAlchemyLLMCallRepository
from .test_design_result_models import TestDesignResultRecord
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .unit_of_work import session_scope


class GenerationBatchRepository:
    def get_plan(self, project_id, invocation_id):
        with session_scope() as session:
            row = session.get(Plan, invocation_id)
            if row is None:
                return None
            plan = GenerationBatchReservation.model_validate(row.payload)
            if plan.project_id != project_id:
                raise TestDesignResultIntegrityError("batch reservation belongs to another project")
            self._stored_plan(session, plan)
            return plan

    def inspect(self, request, invocation_id, actor_id):
        """Presence/usage metadata only; callers reauthorize all pinned sources."""
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            row = session.get(Plan, invocation_id)
            if row is None:
                return None
            plan = GenerationBatchReservation.model_validate(row.payload)
            self._stored_plan(session, plan)
            command = session.get(ToolInvocationRecord, invocation_id)
            if (plan.request != request or plan.actor_id != actor_id or plan.project_id != request.project_id
                    or GenerationJobRepository._request(command) != request
                    or command.input_payload.get("confirmed_actor_id") != actor_id):
                raise TestDesignResultIntegrityError("batch job inspection has different canonical source or actor pins")
            claims, replies = self._records(session, plan)
            return {"schema": "nasus.test-design-batch-progress.v1", "plan_digest": plan.plan_digest,
                "call_count": len(plan.batches), "claimed_calls": len(claims), "archived_calls": len(replies),
                "unknown_calls": len(claims) - len(replies),
                "unstarted_calls": len(plan.batches) - len(claims),
                "known_input_tokens": sum(item["usage"]["input_tokens"] for item in replies),
                "known_output_tokens": sum(item["usage"]["output_tokens"] for item in replies),
                "known_cost_nanos_at_policy_rates": sum(item["usage"]["cost_nanos_at_policy_rates"] for item in replies),
                "reservation": plan.reservation.model_dump(mode="json"), "reservation_released": False,
                "invoice_verified": False, "execution_authorized": False}

    @staticmethod
    def _copy(plan):
        return GenerationBatchReservation.model_validate(plan.model_dump(mode="json"))

    @staticmethod
    def _guard(session, plan, lease):
        if (lease.project_id, lease.invocation_id) != (plan.project_id, plan.invocation_id):
            raise GenerationLeaseLost("batch ledger requires its exact canonical worker lease")
        TestDesignScopeRepository._actor(session, plan.project_id, plan.actor_id)
        identity = session.get(UserIdentityRecord, plan.actor_id)
        roles = session.scalars(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.project_id == plan.project_id,
            ProjectRoleBindingRecord.user_id == plan.actor_id, ProjectRoleBindingRecord.version_id.is_(None),
            ProjectRoleBindingRecord.session_id.is_(None), ProjectRoleBindingRecord.status == "active")).all()
        if identity.role != "platform_admin" and (len(roles) != 1 or roles[0].role != "project_admin"):
            raise PermissionError("batch model egress requires a current project administrator")
        command = TestDesignResultRepository._canonical(session, plan.request, plan.invocation_id, plan.actor_id)
        GenerationJobRepository._require_lease(session, command, lease)
        model = session.scalar(select(ModelProviderConfigRecord).where(
            ModelProviderConfigRecord.config_id == plan.request.model_config_id).with_for_update(read=True))
        if model is None:
            raise TestDesignResultIntegrityError("batch model configuration is unavailable")
        return command

    @staticmethod
    def _stored_plan(session, plan):
        row = session.get(Plan, plan.invocation_id)
        if row is None or row.project_id != plan.project_id:
            raise TestDesignResultIntegrityError("batch call requires its complete budget reservation")
        stored = GenerationBatchReservation.model_validate(row.payload)
        if (stored != plan or acceptance_digest(row.payload) != row.content_hash
                or row.scope_revision_id != plan.request.scope_revision_id or row.plan_digest != plan.plan_digest):
            raise TestDesignResultIntegrityError("batch reservation was changed or rebound")
        return row

    @staticmethod
    def _sequence(plan, sequence):
        if type(sequence) is not int or not 0 <= sequence < len(plan.batches):
            raise TestDesignResultIntegrityError("batch call is outside the confirmed complete plan")

    @staticmethod
    def _claim(plan, row):
        value = row.payload
        GenerationBatchRepository._sequence(plan, row.sequence)
        expected = {"project_id": plan.project_id, "invocation_id": plan.invocation_id, "sequence": row.sequence,
            "batch_digest": plan.batches[row.sequence].batch_digest, "call_id": row.call_id,
            "request_hash": batch_call_request_hash(plan, row.sequence)}
        if (set(value) != {*expected, "reserved_at"} or type(value["sequence"]) is not int
                or acceptance_digest(value) != row.content_hash or row.project_id != plan.project_id
                or row.batch_digest != expected["batch_digest"] or any(value.get(key) != item for key, item in expected.items())):
            raise TestDesignResultIntegrityError("batch call reservation integrity mismatch")
        when = datetime.fromisoformat(value["reserved_at"])
        if when.tzinfo is None:
            raise TestDesignResultIntegrityError("batch call reservation requires an absolute timestamp")
        return value

    @staticmethod
    def _call(plan, claim, call, *, outcome):
        binding = plan.model_binding
        if (call.id != claim["call_id"] or call.project_id != plan.project_id or call.tool_invocation_id != plan.invocation_id
                or call.route != "chat" or call.purpose != GENERATION_TOOL or call.runtime_mode != "live" or call.outcome != outcome
                or type(call.model_calls) is not int or call.model_calls != 1 or call.provider != binding.provider
                or call.model_name != binding.model_name or call.selected_provider != call.provider
                or call.selected_model_name != call.model_name or call.request_hash != claim["request_hash"]
                or call.prompt_id != "nasus.test-design-generation" or call.prompt_version != "batch-v1"):
            raise TestDesignResultIntegrityError("batch audit differs from the exact reserved provider call")
        if outcome == "success":
            if call.usage_source != "provider":
                raise TestDesignResultIntegrityError("successful native batch lacks authoritative provider usage")
            return verify_generation_usage(plan.policy, plan.request.execution.budget, call.input_token_count, call.output_token_count)

    @classmethod
    def _records(cls, session, plan):
        calls = session.scalars(select(Claim).where(Claim.invocation_id == plan.invocation_id).order_by(Claim.sequence).limit(65)).all()
        replies = session.scalars(select(Reply).where(Reply.invocation_id == plan.invocation_id).order_by(Reply.sequence).limit(65)).all()
        if (len(calls) > len(plan.batches) or [row.sequence for row in calls] != list(range(len(calls)))
                or [row.sequence for row in replies] != list(range(len(replies))) or len(replies) > len(calls)):
            raise TestDesignResultIntegrityError("batch ledger has an incomplete or foreign call sequence")
        claims = [cls._claim(plan, row) for row in calls]
        receipts = []
        for row in replies:
            claim, value = claims[row.sequence], row.payload
            call = session.get(LLMCallRecord, claim["call_id"])
            if call is None:
                raise TestDesignResultIntegrityError("native batch receipt lacks its provider audit")
            usage = cls._call(plan, claim, call, outcome="success")
            expected = {**{key: claim[key] for key in ("project_id", "invocation_id", "sequence", "batch_digest", "call_id")},
                "artifact_ref": row.artifact_ref, "artifact_hash": row.artifact_hash, "response_hash": call.response_hash, "usage": usage}
            if (value != expected or acceptance_digest(value) != row.content_hash or row.project_id != plan.project_id
                    or row.call_id != claim["call_id"] or row.batch_digest != claim["batch_digest"]
                    or row.response_hash != call.response_hash):
                raise TestDesignResultIntegrityError("native batch receipt integrity mismatch")
            receipts.append(value)
        if len(claims) > len(receipts) + 1:
            raise TestDesignResultIntegrityError("new batch started before the prior response was archived")
        return claims, receipts

    @staticmethod
    def _audit(session, command, plan, action, summary, metadata):
        now = session.scalar(select(func.clock_timestamp())).isoformat()
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=plan.actor_id, actor_kind="user",
            action=action, entity_type="tool_invocation", entity_id=plan.invocation_id, status="running", summary=summary,
            conversation_id=command.conversation_id, tool_invocation_id=command.id,
            agent_goal_id=command.input_payload.get("agent_goal_id"), object_refs=[], evidence_refs=[], event_metadata=metadata))
        GenerationExecutionRepository._event(session, command, action, metadata)

    def reserve(self, plan, *, lease, require_current):
        plan = self._copy(plan)
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, plan.project_id)
            command = self._guard(session, plan, lease)
            if (session.get(GenerationCallReservationRecord, plan.invocation_id) is not None
                    or session.scalar(select(TestDesignResultRecord).where(TestDesignResultRecord.invocation_id == plan.invocation_id)) is not None):
                raise GenerationOutcomeUnknown("canonical generation already has a single-call reservation or result")
            prior = session.get(Plan, plan.invocation_id)
            if prior is not None:
                self._stored_plan(session, plan)
                require_current()
                GenerationJobRepository._require_lease(session, command, lease)
                return plan.model_dump(mode="json")
            confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
            now = session.scalar(select(func.clock_timestamp()))
            if confirmed.tzinfo is None or not 0 <= (now - confirmed).total_seconds() <= 900:
                raise TestDesignResultIntegrityError("batch egress confirmation expired")
            require_current()
            GenerationJobRepository._require_lease(session, command, lease)
            payload = plan.model_dump(mode="json")
            session.add(Plan(invocation_id=plan.invocation_id, project_id=plan.project_id,
                scope_revision_id=plan.request.scope_revision_id, plan_digest=plan.plan_digest,
                payload=payload, content_hash=acceptance_digest(payload)))
            self._audit(session, command, plan, "quality.test_design.batch_budget_reserved",
                "Complete batch budget reserved; no native call has started and unknown usage is never refunded.",
                {"plan_digest": plan.plan_digest, "reservation": plan.reservation.model_dump(mode="json")})
            session.flush()
            return payload

    def claim_call(self, plan, sequence, *, lease, require_current):
        plan = self._copy(plan)
        self._sequence(plan, sequence)
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, plan.project_id)
            command = self._guard(session, plan, lease)
            self._stored_plan(session, plan)
            claims, receipts = self._records(session, plan)
            if sequence < len(claims):
                raise GenerationOutcomeUnknown("batch call already reserved; replay an archived reply or stop without resending")
            if sequence != len(claims) or len(receipts) != len(claims):
                raise GenerationOutcomeUnknown("prior batch outcome is unknown or the call sequence was skipped")
            require_current()
            GenerationJobRepository._require_lease(session, command, lease)
            value = {"project_id": plan.project_id, "invocation_id": plan.invocation_id, "sequence": sequence,
                "batch_digest": plan.batches[sequence].batch_digest, "call_id": str(uuid4()),
                "request_hash": batch_call_request_hash(plan, sequence),
                "reserved_at": session.scalar(select(func.clock_timestamp())).isoformat()}
            session.add(Claim(**{key: value[key] for key in ("project_id", "invocation_id", "sequence", "batch_digest", "call_id")},
                payload=value, content_hash=acceptance_digest(value)))
            self._audit(session, command, plan, "quality.test_design.batch_call_reserved",
                "One native batch call claimed exactly once; no source text or provider credentials in the receipt.",
                {"sequence": sequence, "batch_digest": value["batch_digest"], "call_id": value["call_id"]})
            session.flush()
            return value

    def record_reply(self, plan, sequence, payload, artifact_ref, artifact_hash, call, *, lease, require_current):
        plan = self._copy(plan)
        self._sequence(plan, sequence)
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, plan.project_id)
            command = self._guard(session, plan, lease)
            self._stored_plan(session, plan)
            row = session.get(Claim, (plan.invocation_id, sequence))
            if row is None:
                raise TestDesignResultIntegrityError("native batch reply lacks its exact call reservation")
            claim = self._claim(plan, row)
            value = validate_batch_reply(plan, sequence, claim, payload)
            usage = self._call(plan, claim, call, outcome="success")
            if (usage != value["usage"] or call.response_hash != value["response_hash"]
                    or acceptance_digest(payload) != artifact_hash or type(artifact_ref) is not str or not 0 < len(artifact_ref) <= 4096):
                raise TestDesignResultIntegrityError("native batch reply differs from private archive or provider audit")
            metadata = {**value, "artifact_ref": artifact_ref, "artifact_hash": artifact_hash}
            require_current()
            GenerationJobRepository._require_lease(session, command, lease)
            prior = session.get(Reply, (plan.invocation_id, sequence))
            if prior is not None:
                self._records(session, plan)
                if prior.payload != metadata:
                    raise TestDesignResultIntegrityError("native batch reply cannot overwrite history")
                return metadata
            if session.get(LLMCallRecord, claim["call_id"]) is not None:
                raise GenerationOutcomeUnknown("native batch call already has a terminal audit; do not overwrite or resend")
            self._records(session, plan)
            session.add(SQLAlchemyLLMCallRepository._to_record(call))
            session.flush()
            session.add(Reply(**{key: metadata[key] for key in ("project_id", "invocation_id", "sequence", "batch_digest", "call_id", "artifact_ref", "artifact_hash", "response_hash")},
                payload=metadata, content_hash=acceptance_digest(metadata)))
            self._audit(session, command, plan, "quality.test_design.batch_reply_archived",
                "Native batch reply and provider usage archived atomically; no mapping or execution authority granted.",
                {"sequence": sequence, "batch_digest": claim["batch_digest"], "call_id": claim["call_id"], "usage": usage})
            session.flush()
            return metadata

    def record_failure(self, plan, sequence, call):
        # A lost worker may still report charged/unknown usage for its own call.
        # This cannot produce a usable reply or advance the business sequence.
        plan = self._copy(plan)
        self._sequence(plan, sequence)
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, plan.project_id)
            self._stored_plan(session, plan)
            row = session.get(Claim, (plan.invocation_id, sequence))
            if row is None:
                raise TestDesignResultIntegrityError("batch failure lacks an exact call reservation")
            claim = self._claim(plan, row)
            self._call(plan, claim, call, outcome="error")
            if session.get(LLMCallRecord, call.id) is None:
                session.add(SQLAlchemyLLMCallRepository._to_record(call))

    def read(self, plan, *, lease, require_current):
        plan = self._copy(plan)
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, plan.project_id)
            command = self._guard(session, plan, lease)
            self._stored_plan(session, plan)
            claims, replies = self._records(session, plan)
            require_current()
            GenerationJobRepository._require_lease(session, command, lease)
            return {"plan": plan.model_dump(mode="json"), "calls": claims, "replies": replies,
                "budget": {**plan.reservation.model_dump(mode="json"), "claimed_calls": len(claims),
                    "archived_calls": len(replies), "unknown_calls": len(claims) - len(replies),
                    "known_input_tokens": sum(item["usage"]["input_tokens"] for item in replies),
                    "known_output_tokens": sum(item["usage"]["output_tokens"] for item in replies),
                    "known_cost_nanos_at_policy_rates": sum(item["usage"]["cost_nanos_at_policy_rates"] for item in replies),
                    "reservation_released": False, "invoice_verified": False}}
