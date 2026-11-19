from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.quality_loop.case_revisions import CASE_REVISION_SCHEMA, REVISE_CASES, CaseRevisionInput
from ...application.quality_loop.test_design_results import TestDesignResultIntegrityError
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from .db_models import ToolInvocationRecord, AuditEventRecord
from .event_outbox_repository import EventOutboxRepository
from .test_design_result_models import TestDesignResultRecord as Result, TestDesignCaseRecord as Case, TestDesignCoverageRecord as Coverage, TestDesignCaseEditRecord as Edit
from .test_design_result_repository import TestDesignResultRepository
from .test_design_scope_repository import TestDesignScopeRepository
from .version_delivery_repository import VersionDeliveryRepository
from .unit_of_work import session_scope


class CaseRevisionRepository:
    def is_current(self, project_id, generation_id):
        with session_scope() as session:
            return session.scalar(select(Edit.generation_id).where(
                Edit.project_id == project_id, Edit.parent_generation_id == generation_id)) is None

    @staticmethod
    def _command(session, request, invocation_id, actor_id, *, running):
        query = select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id)
        row = session.scalar(query.with_for_update() if running else query)
        if (row is None or row.tool_id != REVISE_CASES or running and row.status != "running"
                or row.input_payload.get("confirmed_by_user") is not True or row.input_payload.get("confirmed_actor_id") != actor_id
                or CaseRevisionInput.model_validate({k: v for k, v in query_payload(row.input_payload).items()
                    if k not in {"confirmed_by_user", "confirmed_at"}}) != request):
            raise TestDesignResultIntegrityError("Case edits require the exact confirmed command and actor")
        TestDesignResultRepository._project_scope(session, row, request.project_id)
        return row

    def verify_history(self, request, payload, metadata):
        with session_scope() as session:
            edit = session.get(Edit, payload["generation_id"])
            if edit is None or (edit.project_id, edit.parent_generation_id, edit.invocation_id, edit.actor_id,
                    edit.request_hash, edit.artifact_hash) != (request.project_id, request.generation_id,
                    payload["invocation_id"], payload["actor_id"], acceptance_digest(request.model_dump(mode="json")), metadata["artifact_hash"]):
                raise TestDesignResultIntegrityError("Case revision history mismatch")
            self._command(session, request, edit.invocation_id, edit.actor_id, running=False)

    def append(self, request, payload, ref, digest, *, scope, check):
        with session_scope() as session:
            TestDesignScopeRepository._lock(session, request.project_id)
            command = self._command(session, request, payload["invocation_id"], scope.actor_id, running=True)
            VersionDeliveryRepository._actor(session, request.project_id, scope.actor_id, scope.effective_project_role)
            parent = session.get(Result, request.generation_id)
            if parent is None or (parent.project_id, parent.artifact_hash) != (request.project_id, request.generation_artifact_hash):
                raise TestDesignResultIntegrityError("Case edit parent mismatch")
            if not self.is_current(request.project_id, request.generation_id):
                raise ValueError("Another edit already superseded this case revision")
            check()
            proposal = payload["proposal"]
            metadata = {"schema": CASE_REVISION_SCHEMA, "project_id": request.project_id,
                "generation_id": payload["generation_id"], "scope_revision_id": parent.scope_revision_id,
                "invocation_id": command.id, "call_id": None, "status": "draft", "artifact_hash": digest,
                "case_count": len(proposal["cases"]), "gap_count": len(proposal["gaps"])}
            session.add(Result(**{key: metadata[key] for key in ("project_id", "generation_id", "scope_revision_id", "invocation_id", "call_id", "status", "artifact_hash")},
                provenance_kind="human_revision", artifact_ref=ref, payload=metadata, content_hash=acceptance_digest(metadata)))
            session.flush()
            session.add(Edit(generation_id=payload["generation_id"], project_id=request.project_id,
                parent_generation_id=request.generation_id, invocation_id=command.id, actor_id=scope.actor_id,
                request_hash=acceptance_digest(request.model_dump(mode="json")), artifact_hash=digest))
            for case in proposal["cases"]:
                session.add(Case(generation_id=payload["generation_id"], case_id=case["case_id"], project_id=request.project_id,
                    payload=case, content_hash=acceptance_digest(case)))
            session.add(Coverage(generation_id=payload["generation_id"], project_id=request.project_id,
                payload=proposal["coverage"], content_hash=acceptance_digest(proposal["coverage"])))
            now = session.scalar(select(func.clock_timestamp())).isoformat()
            refs = ["test_design_result:" + payload["generation_id"]]
            command.status, command.summary = "completed", "Human case revision saved; independent mapping, case and script approval required."
            command.revision += 1
            command.result_payload = ToolResult(invocation_id=command.id, status="completed", summary=command.summary, object_refs=refs).model_dump(mode="json")
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=scope.actor_id, actor_kind="user",
                action=REVISE_CASES, entity_type="test_design_result", entity_id=payload["generation_id"], status="draft",
                summary=command.summary, conversation_id=command.conversation_id, tool_invocation_id=command.id,
                object_refs=refs, evidence_refs=[], event_metadata={"parent_generation_id": request.generation_id}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="quality.test_design.revised",
                occurred_at=now, correlation_id=request.project_id, entity_type="test_design_result", entity_id=payload["generation_id"],
                tool_invocation_id=command.id, entity_version=1, mutation_kind="append", patch=metadata,
                query_keys=[["test-design-results", request.project_id], ["test-design-review-drafts", request.project_id]]), session=session)
            session.flush()
            return metadata
