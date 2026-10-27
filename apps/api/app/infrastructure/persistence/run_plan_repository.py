"""Append original plan, exact registered ancestry, audit and Outbox atomically."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.run_plan_inputs import RunPlanRequest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan import run_plan_artifact_schema, RUN_PLAN_TOOL, RunPlanChanged, RunPlanIntegrityError
from .automation_provenance_v1 import AutomationProvenanceProjectorV1
from .automation_script_models import AutomationScriptRevisionRecord as Script
from .automation_script_review_models import AutomationScriptReviewRecord as Review
from .db_models import AuditEventRecord, ToolInvocationRecord
from .context_pack_models import ContextPackRecord
from .event_outbox_repository import EventOutboxRepository
from .run_plan_models import RunPlanRecord as Record
from .test_design_scope_repository import TestDesignScopeRepository
from .test_design_result_repository import TestDesignResultRepository
from .unit_of_work import session_scope


class RunPlanRepository:
    @staticmethod
    def _value(row):
        fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
        if (row is None or type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash
                or any(row.payload.get(key) != getattr(row, key) for key in fields)
                or row.status != "prepared" or row.payload.get("execution_authorized") is not False):
            raise RunPlanIntegrityError("stored RunPlan metadata invalid")
        return row.payload

    @staticmethod
    def _request(command):
        try:
            return RunPlanRequest.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValueError, TypeError, AttributeError):
            raise RunPlanIntegrityError("canonical RunPlan request invalid") from None

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        command = session.scalar(query if historical else query.with_for_update())
        if (command is None or command.tool_id != RUN_PLAN_TOOL
                or command.status not in ({"running", "completed", "failed"} if historical else {"running"})
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id or cls._request(command) != request):
            raise RunPlanIntegrityError("RunPlan requires its exact confirmed canonical request and actor")
        if not historical:
            try:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                fresh = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
            except (ValueError, OverflowError):
                fresh = False
            if not fresh:
                raise RunPlanIntegrityError("RunPlan requires fresh confirmation before archiving or committing")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        return command

    @staticmethod
    def _parents(session, request):
        script = session.get(Script, request.script_revision_id)
        review = session.get(Review, request.review_revision_id)
        if (script is None or review is None or script.project_id != request.project_id
                or review.project_id != request.project_id or review.script_revision_id != script.script_revision_id
                or script.artifact_hash != request.script_artifact_hash
                or review.payload.get("artifact_hash") != request.review_artifact_hash or review.status != "reviewed"):
            raise RunPlanIntegrityError("RunPlan registered script/review mismatch")
        history = session.scalars(select(Review).where(Review.project_id == request.project_id,
            Review.script_revision_id == script.script_revision_id, Review.sequence <= review.sequence)
            .order_by(Review.sequence).limit(1001)).all()
        if len(history) != review.sequence or len(history) > 1000:
            raise RunPlanIntegrityError("RunPlan original review prefix incomplete")
        projector = AutomationProvenanceProjectorV1()
        script_pin = projector.verify(session, script)
        review_pin = projector.reviews(session, script, history)[-1]
        return script_pin, review_pin

    @classmethod
    def _verify(cls, session, row):
        value = cls._value(row)
        command = session.get(ToolInvocationRecord, row.invocation_id)
        request = cls._request(command)
        cls._canonical(session, request, row.invocation_id, row.actor_id, historical=True)
        script, review = cls._parents(session, request)
        context = session.get(ContextPackRecord, row.context_id)
        if (request.project_id != row.project_id or request.script_revision_id != row.script_revision_id
                or request.review_revision_id != row.review_revision_id
                or request.plan_digest != row.plan_digest
                or context is None or context.image_revision_id != row.image_revision_id
                or acceptance_digest(request.model_dump(mode="json")) != row.request_hash
                or script.context_id != row.context_id or review.context_id != row.context_id
                or script.key != row.script_node_key or script.content_hash != row.script_node_hash
                or review.key != row.review_node_key or review.content_hash != row.review_node_hash):
            raise RunPlanIntegrityError("RunPlan canonical provenance or registered ancestry mismatch")
        return value

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._verify(session, row)
        if (row.project_id != request.project_id or row.actor_id != actor_id
                or row.request_hash != acceptance_digest(request.model_dump(mode="json"))):
            raise RunPlanIntegrityError("RunPlan invocation cannot be rebound")
        return value

    def committed(self, request, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, actor_id)
            prior = self._committed(session, request, actor_id, invocation_id)
            self._canonical(session, request, invocation_id, actor_id, historical=prior is not None)
            require_access()
            return prior

    def record(self, request, payload, ref, digest, *, require_current):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, payload["actor_id"])
            prior = self._committed(session, request, payload["actor_id"], payload["invocation_id"])
            command = self._canonical(session, request, payload["invocation_id"], payload["actor_id"], historical=prior is not None)
            if prior is not None:
                require_current()
                return prior
            plan = payload.get("plan", {})
            if (command.status != "running" or payload.get("schema") != run_plan_artifact_schema(request.policy_revision)
                    or payload.get("project_id") != request.project_id or payload.get("request") != request.model_dump(mode="json")
                    or acceptance_digest(payload) != digest or plan.get("plan_digest") != request.plan_digest
                    or plan.get("status") != "prepared" or plan.get("execution_authorized") is not False):
                raise RunPlanIntegrityError("RunPlan requires fresh confirmation and its exact archived inputs")
            script, review = self._parents(session, request)
            head = session.scalar(select(Review).where(Review.script_revision_id == request.script_revision_id)
                .order_by(Review.sequence.desc()).limit(1))
            if head is None or head.revision_id != request.review_revision_id:
                raise RunPlanChanged("script review head changed before RunPlan commit")
            require_current()
            source = plan["source_pin"]
            metadata = {"run_plan_id": payload["run_plan_id"], "project_id": request.project_id,
                "context_id": script.context_id, "image_revision_id": source["image_revision_id"],
                "manifest_id": source["manifest_id"], "script_revision_id": request.script_revision_id,
                "review_revision_id": request.review_revision_id, "script_node_key": script.key,
                "script_node_hash": script.content_hash, "review_node_key": review.key, "review_node_hash": review.content_hash,
                "invocation_id": payload["invocation_id"], "artifact_hash": digest,
                "request_hash": acceptance_digest(request.model_dump(mode="json")), "plan_digest": request.plan_digest,
                "status": "prepared", "actor_id": payload["actor_id"], "recorded_at": payload["recorded_at"],
                "execution_authorized": False}
            row = Record(**{key: value for key, value in metadata.items() if key != "execution_authorized"},
                artifact_ref=ref, payload=metadata, content_hash=acceptance_digest(metadata))
            session.add(row)
            session.flush()
            self._verify(session, row)
            event = "quality.run_plan.prepared"
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=payload["recorded_at"], actor=payload["actor_id"], actor_kind="user",
                action=event, entity_type="run_plan", entity_id=row.run_plan_id, status="prepared",
                summary="Immutable reviewed inputs and target declarations; no verified build, execution or coverage.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                object_refs=["run_plan:" + row.run_plan_id], evidence_refs=[],
                event_metadata={"script_revision_id": request.script_revision_id, "execution_authorized": False}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=event,
                occurred_at=payload["recorded_at"], correlation_id=request.project_id,
                entity_type="run_plan", entity_id=row.run_plan_id, conversation_id=command.conversation_id,
                agent_goal_id=command.input_payload.get("agent_goal_id"), entity_version=0, mutation_kind="append",
                patch={"project_id": request.project_id, "run_plan_id": row.run_plan_id,
                    "plan_digest": request.plan_digest, "status": "prepared"},
                query_keys=[["run-plans", request.project_id]], snapshot_hint=True), session=session)
            session.flush()
            return metadata

    def read(self, project_id, run_plan_id):
        with session_scope() as session:
            row = session.get(Record, run_plan_id)
            if row is None or row.project_id != project_id:
                raise KeyError("RunPlan not found")
            metadata = self._verify(session, row)
            request = self._request(session.get(ToolInvocationRecord, row.invocation_id))
            return {"metadata": metadata, "artifact_ref": row.artifact_ref, "request": request.model_dump(mode="json")}

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type != "quality.run_plan.prepared":
            return
        row = session.get(Record, event.entity_id)
        value = cls._verify(session, row)
        from .run_plan_event_integrity import verify_run_plan_event_envelope
        verify_run_plan_event_envelope(session, event, row, entity_type="run_plan", query_key="run-plans")
        if event.correlation_id != row.project_id or event.patch != {key: value[key] for key in
                ("project_id", "run_plan_id", "plan_digest", "status")}:
            raise RunPlanIntegrityError("RunPlan event differs from its original fact")
