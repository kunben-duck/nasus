from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select

from ...application.platform.tool_models import EventPayload, ToolResult
from ...application.quality_loop.version_delivery_models import ADOPT_ITERATION_IMAGE
from ...domain.quality_loop.version_delivery import VersionDeliveryConflict, VersionDeliveryIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import AuditEventRecord, ToolInvocationRecord, VersionRecord
from .event_outbox_repository import EventOutboxRepository
from .image_publication_repository import ImagePublicationRepository
from .test_design_result_repository import TestDesignResultRepository
from .unit_of_work import session_scope
from .version_delivery_models import VersionImageAdoptionRecord as Adoption
from .version_delivery_repository import VersionDeliveryRepository


class IterationImageRepository:
    def append(self, request, *, invocation_id, scope, prepare, check):
        with session_scope() as session:
            ImagePublicationRepository._lock(session, request.project_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            if (command is None or command.tool_id != ADOPT_ITERATION_IMAGE or command.status != "running"
                    or command.input_payload.get("confirmed_by_user") is not True
                    or command.input_payload.get("confirmed_actor_id") != scope.actor_id
                    or any(command.input_payload.get(key) != value for key, value in request.model_dump(mode="json").items())):
                raise VersionDeliveryIntegrityError("Adoption requires the exact confirmed canonical command")
            TestDesignResultRepository._project_scope(session, command, request.project_id)
            VersionDeliveryRepository._actor(session, request.project_id, scope.actor_id, scope.effective_project_role)
            session.scalar(select(VersionRecord).where(VersionRecord.id == request.version_id,
                VersionRecord.project_id == request.project_id).with_for_update())
            check()
            request_hash = snapshot_digest(request.model_dump(mode="json"))
            prior = session.scalar(select(Adoption).where(Adoption.invocation_id == invocation_id))
            if prior is not None:
                if (prior.request_hash, prior.actor_id, prior.project_id, prior.version_id) != (
                        request_hash, scope.actor_id, request.project_id, request.version_id) or snapshot_digest(prior.payload) != prior.content_hash:
                    raise VersionDeliveryIntegrityError("Adoption command already has a different outcome")
                # Reauthorize the original frozen source, not just its receipt.
                return prior.adoption_id
            binding = VersionDeliveryRepository._binding(session, request.project_id, request.version_id)
            if not binding or (binding["iteration_image"]["image_revision_id"], binding["iteration_image"]["image_artifact_hash"]) != (
                    request.expected_image_revision_id, request.expected_image_artifact_hash):
                raise VersionDeliveryConflict("Iteration image changed before adoption")
            payload = prepare()
            now = session.scalar(select(func.clock_timestamp())).isoformat()
            row = Adoption(adoption_id="adopt_" + uuid4().hex, invocation_id=invocation_id,
                project_id=request.project_id, version_id=request.version_id, image_revision_id=request.image_revision_id,
                parent_image_revision_id=request.expected_image_revision_id, actor_id=scope.actor_id,
                recorded_at=now, request_hash=request_hash, content_hash=snapshot_digest(payload), payload=deepcopy(payload))
            session.add(row)
            refs = ["iteration_image_adoption:" + row.adoption_id, "version:" + request.version_id,
                "image_revision:" + request.image_revision_id]
            command.status, command.summary = "completed", "Working image adopted; requirement review and downstream approvals must be renewed."
            command.revision += 1
            command.result_payload = ToolResult(invocation_id=invocation_id, status="completed", summary=command.summary,
                object_refs=refs, requires_followup=True, followup_reason="requirement_review_required").model_dump(mode="json")
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=now, actor=scope.actor_id, actor_kind=command.initiator_actor,
                action=ADOPT_ITERATION_IMAGE, entity_type="iteration_image_adoption", entity_id=row.adoption_id,
                status="completed", summary=command.summary, conversation_id=command.conversation_id,
                tool_invocation_id=invocation_id, object_refs=refs, evidence_refs=[], event_metadata={
                    "project_id": request.project_id, "version_id": request.version_id, "reason": request.reason}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="version.image.adopted", occurred_at=now,
                correlation_id=request.project_id, tool_invocation_id=invocation_id, entity_type="version",
                entity_id=request.version_id, entity_version=0, mutation_kind="append",
                patch={"project_id": request.project_id, "version_id": request.version_id},
                query_keys=[["version-delivery", request.project_id, request.version_id],
                    ["version-requirements", request.project_id, request.version_id], ["requirement-review"]]), session=session)
            session.flush()
            VersionDeliveryRepository._binding(session, request.project_id, request.version_id)
            check()
            return row.adoption_id
