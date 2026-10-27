"""Append exact plan/build parents and all source members with audit and Outbox."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.quality_loop.run_plan_build_inputs import RunPlanBuildRequest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan import RunPlanIntegrityError
from ...domain.quality_loop.run_plan_build import RUN_PLAN_BUILD_ARTIFACT_SCHEMA, RUN_PLAN_BUILD_TOOL
from .db_models import AuditEventRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .native_build_repository import NativeBuildRepository
from .run_plan_repository import RunPlanRepository
from .run_plan_models import RunPlanRecord
from .run_plan_build_models import RunPlanBuildRecord as Record, RunPlanBuildMemberRecord as Member
from .test_design_scope_repository import TestDesignScopeRepository
from .test_design_result_repository import TestDesignResultRepository
from .unit_of_work import session_scope


class RunPlanBuildRepository:
    @staticmethod
    def _request(command):
        try:
            return RunPlanBuildRequest.model_validate({key: value for key, value in query_payload(command.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}})
        except (ValueError, TypeError, AttributeError):
            raise RunPlanIntegrityError("canonical build binding request invalid") from None

    @classmethod
    def _canonical(cls, session, request, invocation_id, actor_id, *, historical=False):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        command = session.scalar(query if historical else query.with_for_update())
        if (command is None or command.tool_id != RUN_PLAN_BUILD_TOOL
                or command.status not in ({"running", "completed", "failed"} if historical else {"running"})
                or command.input_payload.get("confirmed_by_user") is not True
                or command.input_payload.get("confirmed_actor_id") != actor_id or cls._request(command) != request):
            raise RunPlanIntegrityError("build binding requires its exact confirmed canonical request and actor")
        if not historical:
            try:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                fresh = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
            except (ValueError, OverflowError):
                fresh = False
            if not fresh:
                raise RunPlanIntegrityError("build binding requires fresh confirmation before archive or commit")
        TestDesignResultRepository._project_scope(session, command, request.project_id)
        return command

    @staticmethod
    def _parents(session, request):
        row = session.get(RunPlanRecord, request.run_plan_id)
        if row is None or row.project_id != request.project_id or row.artifact_hash != request.run_plan_artifact_hash:
            raise RunPlanIntegrityError("build binding original plan registration mismatch")
        plan = RunPlanRepository._verify(session, row)
        builds = []
        for reference in request.native_builds:
            state = NativeBuildRepository._inspection(session, request.project_id, reference.invocation_id)
            result, reserved = state["result"], state["reservation"]
            if (result is None or reserved is None or any(result[key] != getattr(reference, key) for key in
                    ("invocation_id", "build_id", "artifact_hash", "receipt_digest"))
                    or reserved["image_revision_id"] != plan["image_revision_id"] or reserved["manifest_id"] != plan["manifest_id"]):
                raise RunPlanIntegrityError("build binding original build registration mismatch")
            builds.append((result, reserved))
        return plan, builds

    @staticmethod
    def _value(row, model):
        fields = {column.name for column in model.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
        if (row is None or type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash
                or any(row.payload.get(key) != getattr(row, key) for key in fields)):
            raise RunPlanIntegrityError("build binding registered metadata invalid")
        return row.payload

    @classmethod
    def _verify(cls, session, row):
        value = cls._value(row, Record)
        request = cls._request(session.get(ToolInvocationRecord, row.invocation_id))
        cls._canonical(session, request, row.invocation_id, row.actor_id, historical=True)
        plan, builds = cls._parents(session, request)
        if (row.status != "build_attested" or value.get("execution_authorized") is not False
                or value.get("native_build_source_attested") is not True
                or row.request_hash != acceptance_digest(request.model_dump(mode="json"))
                or row.binding_digest != request.binding_digest
                or any(getattr(row, key) != getattr(request, key) for key in
                    ("project_id", "run_plan_id", "run_plan_artifact_hash", "target_build_invocation_id"))
                or any(getattr(row, key) != plan[key] for key in ("plan_digest", "image_revision_id", "manifest_id"))
                or type(row.code_source_count) is not int or row.code_source_count != len(builds)):
            raise RunPlanIntegrityError("build binding canonical plan ancestry mismatch")
        actual = session.scalars(select(Member).where(Member.binding_id == row.binding_id)
            .order_by(Member.source_binding_id).limit(1001)).all()
        expected = []
        for result, reserved in builds:
            expected.append({"binding_id": row.binding_id, "project_id": row.project_id,
                "native_invocation_id": result["invocation_id"], "build_id": result["build_id"],
                "archive_hash": result["artifact_hash"], "receipt_digest": result["receipt_digest"],
                "image_revision_id": reserved["image_revision_id"], "manifest_id": reserved["manifest_id"],
                "source_binding_id": reserved["binding_id"], "source_revision_id": reserved["source_revision_id"]})
        expected.sort(key=lambda item: item["source_binding_id"])
        if (len(actual) != row.code_source_count or len({item["source_binding_id"] for item in expected}) != len(expected)
                or [cls._value(item, Member) for item in actual] != expected or value.get("members") != expected
                or row.target_build_invocation_id not in {item["native_invocation_id"] for item in expected}):
            raise RunPlanIntegrityError("build binding complete source members cannot be verified")
        return value

    @classmethod
    def _committed(cls, session, request, actor_id, invocation_id):
        row = session.scalar(select(Record).where(Record.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._verify(session, row)
        if row.project_id != request.project_id or row.actor_id != actor_id or row.request_hash != acceptance_digest(request.model_dump(mode="json")):
            raise RunPlanIntegrityError("build binding invocation cannot be rebound")
        return value

    def committed(self, request, *, actor_id, invocation_id, require_access):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            TestDesignScopeRepository._actor(session, request.project_id, actor_id)
            prior = self._committed(session, request, actor_id, invocation_id)
            self._canonical(session, request, invocation_id, actor_id, historical=prior is not None)
            self._parents(session, request)
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
            binding = payload.get("binding", {})
            if (payload.get("schema") != RUN_PLAN_BUILD_ARTIFACT_SCHEMA or acceptance_digest(payload) != digest
                    or payload.get("project_id") != request.project_id or payload.get("request") != request.model_dump(mode="json")
                    or binding.get("binding_digest") != request.binding_digest
                    or binding.get("execution_authorized") is not False or binding.get("native_build_source_attested") is not True):
                raise RunPlanIntegrityError("build binding requires the exact archived confirmed inputs")
            plan, _ = self._parents(session, request)
            require_current()
            members = [{"binding_id": payload["binding_id"], "project_id": request.project_id,
                "native_invocation_id": item["invocation_id"], "build_id": item["build_id"],
                "archive_hash": item["artifact_hash"], "receipt_digest": item["receipt_digest"],
                "image_revision_id": item["source_pin"]["image_revision_id"], "manifest_id": item["source_pin"]["manifest_id"],
                "source_binding_id": item["source_pin"]["binding_id"], "source_revision_id": item["source_pin"]["source_revision_id"]}
                for item in binding["builds"]]
            metadata = {"binding_id": payload["binding_id"], "project_id": request.project_id,
                "run_plan_id": request.run_plan_id, "run_plan_artifact_hash": request.run_plan_artifact_hash,
                "plan_digest": plan["plan_digest"], "image_revision_id": plan["image_revision_id"], "manifest_id": plan["manifest_id"],
                "target_build_invocation_id": request.target_build_invocation_id, "target_artifact_hash": binding["target_artifact_hash"],
                "code_source_count": len(members), "invocation_id": payload["invocation_id"], "artifact_hash": digest,
                "binding_digest": request.binding_digest, "request_hash": acceptance_digest(request.model_dump(mode="json")),
                "status": "build_attested", "actor_id": payload["actor_id"], "recorded_at": payload["recorded_at"],
                "members": members, "native_build_source_attested": True, "execution_authorized": False}
            row_fields = {column.name for column in Record.__table__.columns} - {"artifact_ref", "payload", "content_hash"}
            row = Record(**{key: metadata[key] for key in row_fields}, artifact_ref=ref,
                payload=metadata, content_hash=acceptance_digest(metadata))
            session.add(row)
            session.flush()
            for member in members:
                session.add(Member(**member, payload=member, content_hash=acceptance_digest(member)))
            session.flush()
            self._verify(session, row)
            event = "quality.run_plan.build_bound"
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=payload["recorded_at"], actor=payload["actor_id"], actor_kind="user",
                action=event, entity_type="run_plan_build", entity_id=row.binding_id, status="build_attested",
                summary="Original native build/source attested; no environment, fixture, target execution or passed coverage.",
                conversation_id=command.conversation_id, tool_invocation_id=command.id,
                object_refs=["run_plan_build:" + row.binding_id], evidence_refs=[],
                event_metadata={"run_plan_id": request.run_plan_id, "execution_authorized": False}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type=event,
                occurred_at=payload["recorded_at"], correlation_id=request.project_id,
                entity_type="run_plan_build", entity_id=row.binding_id, conversation_id=command.conversation_id,
                agent_goal_id=command.input_payload.get("agent_goal_id"), entity_version=0, mutation_kind="append",
                patch={key: metadata[key] for key in ("project_id", "binding_id", "run_plan_id", "binding_digest", "status")},
                query_keys=[["run-plan-builds", request.project_id]], snapshot_hint=True), session=session)
            session.flush()
            return metadata

    def read(self, project_id, binding_id):
        with session_scope() as session:
            row = session.get(Record, binding_id)
            if row is None or row.project_id != project_id:
                raise KeyError("RunPlan build binding not found")
            metadata = self._verify(session, row)
            request = self._request(session.get(ToolInvocationRecord, row.invocation_id))
            return {"metadata": metadata, "artifact_ref": row.artifact_ref, "request": request.model_dump(mode="json")}

    @classmethod
    def verify_event(cls, session, event):
        if event.event_type != "quality.run_plan.build_bound":
            return
        row = session.get(Record, event.entity_id)
        value = cls._verify(session, row)
        from .run_plan_event_integrity import verify_run_plan_event_envelope
        verify_run_plan_event_envelope(session, event, row, entity_type="run_plan_build", query_key="run-plan-builds")
        if event.correlation_id != row.project_id or event.patch != {key: value[key] for key in
                ("project_id", "binding_id", "run_plan_id", "binding_digest", "status")}:
            raise RunPlanIntegrityError("build binding event differs from its original fact")
