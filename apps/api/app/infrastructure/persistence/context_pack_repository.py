from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.platform.tool_models import EventPayload
from ...application.platform.tool_handlers.query_input import query_payload
from ...application.system_image.context_pack_inputs import ContextCompileInput
from ...application.system_image.context_pack_inputs import ContextAuthorityRegistrationInput
from ...domain.system_image.context_pack import COMPILE_CONTEXT_TOOL, ContextPackIntegrityError
from ...domain.system_image.context_authorities import REGISTER_CONTEXT_AUTHORITIES_TOOL, require_context_authority
from ...domain.system_image.source_snapshots import snapshot_digest
from .context_pack_models import ContextPackRecord
from .db_models import ToolInvocationRecord, ConversationRecord, AgentGoalRecord
from .image_revision_models import ImageRevisionRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .event_outbox_repository import EventOutboxRepository
from .unit_of_work import session_scope


class ContextPackRepository:
    @classmethod
    def _verify_authorities(cls, session, row, *, pins=None, reuse_snapshot=False):
        from .context_authority_projection_v1 import ContextAuthorityProjectorV1
        from .context_authority_models import ContextAuthorityRootRecord, ContextAuthorityBackfillTargetRecord
        from ...domain.system_image.context_authorities import ContextAuthorityRegistrationRequired
        metadata = cls._metadata(row)
        key = (row.project_id, row.context_id)
        if session.get(ContextAuthorityRootRecord, key) is None:
            target = session.get(ContextAuthorityBackfillTargetRecord, key)
            if target is not None and target.context_metadata_hash == row.content_hash and target.artifact_hash == metadata["artifact_hash"]:
                raise ContextAuthorityRegistrationRequired("original historical archive requires authorized dependency registration")
        return ContextAuthorityProjectorV1().verify(session, row, pins=pins, reuse_snapshot=reuse_snapshot)

    def verify_authorities(self, project_id, context_id, *, pins=None):
        with session_scope() as session:
            row = session.get(ContextPackRecord, context_id)
            if row is None or row.project_id != project_id:
                raise KeyError("context not found")
            return self._verify_authorities(session, row, pins=pins, reuse_snapshot=True)

    def pending_authority_registrations(self, project_id, *, after_id, limit):
        from .context_authority_models import ContextAuthorityRootRecord as Root, ContextAuthorityBackfillTargetRecord as Target
        with session_scope() as session:
            query = select(Target).where(Target.project_id == project_id, ~select(Root.context_id).where(
                Root.project_id == Target.project_id, Root.context_id == Target.context_id).exists())
            if after_id:
                require_context_authority(session.get(Target, (project_id, after_id)) is not None)
                query = query.where(Target.context_id > after_id)
            targets = session.scalars(query.order_by(Target.context_id).limit(limit + 1)).all()
            result = []
            for target in targets:
                row = session.get(ContextPackRecord, target.context_id)
                require_context_authority(row is not None and self._metadata(row)["artifact_hash"] == target.artifact_hash
                    and row.content_hash == target.context_metadata_hash)
                result.append(row.payload)
            return result

    def verify_provenance(self, project_id, context_id):
        from .context_provenance_reads import context_metadata_digest, verify_context_provenance
        from .image_read_snapshot import current_image_read_snapshot
        snapshot = current_image_read_snapshot()
        # Canonical publication/retrieval inputs are checked afresh, even while
        # the immutable source/relation proof is pinned to the owned snapshot.
        with session_scope() as session:
            row = session.get(ContextPackRecord, context_id)
            if row is None or row.project_id != project_id:
                raise KeyError("context not found")
            self._metadata(row)
            if snapshot is None:
                verify_context_provenance(session, row)
            else:
                pinned = snapshot[0].get(ContextPackRecord, context_id)
                if pinned is None:
                    # A context committed after this snapshot needs its complete
                    # fresh proof, not a cached absence or an invented anchor.
                    verify_context_provenance(session, row)
                else:
                    if pinned.project_id != project_id:
                        raise ContextPackIntegrityError("context provenance project mismatch")
                    self._metadata(pinned)
                    original = verify_context_provenance(snapshot[0], pinned)
                    if context_metadata_digest(row) != original:
                        raise ContextPackIntegrityError("context provenance metadata changed during read")
            from .publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
            PublicationProvenanceProjectorV1().context(session, row)
            from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
            RetrievalProvenanceProjectorV1().context(session, row)

    def stale_state(self, project_id, context_id, artifact_hash):
        from .context_invalidation_repository import ContextInvalidationRepository
        return ContextInvalidationRepository().stale_state(project_id, context_id, artifact_hash)

    @staticmethod
    def _metadata(row):
        if (snapshot_digest(row.payload) != row.content_hash
                or any(row.payload.get(key) != getattr(row, key) for key in ("context_id", "project_id", "image_revision_id", "invocation_id"))):
            raise ContextPackIntegrityError("stored context metadata mismatch")
        return row.payload

    def get(self, project_id, context_id):
        with session_scope() as session:
            row = session.get(ContextPackRecord, context_id)
            if row is None or row.project_id != project_id:
                raise KeyError("context not found")
            return self._metadata(row), row.artifact_ref

    def list(self, request):
        with session_scope() as session:
            query = select(ContextPackRecord).where(ContextPackRecord.project_id == request.project_id,
                ContextPackRecord.image_revision_id == request.image_revision_id)
            if request.after_id:
                cursor = session.get(ContextPackRecord, request.after_id)
                if cursor is None or cursor.project_id != request.project_id or cursor.image_revision_id != request.image_revision_id:
                    raise KeyError("context cursor not found")
                query = query.where(ContextPackRecord.context_id > request.after_id)
            rows = session.scalars(query.order_by(ContextPackRecord.context_id).limit(request.limit + 1)).all()
            items = [self._metadata(row) for row in rows[:request.limit]]
            if any(item["image_artifact_hash"] != request.image_artifact_hash for item in items):
                raise ContextPackIntegrityError("context history image mismatch")
            from .context_provenance_projection_v1 import ContextProvenanceProjectorV1
            for row in rows[:request.limit]:
                ContextProvenanceProjectorV1().verify(session, row)
                from .relation_provenance_projection_v1 import RelationProvenanceProjectorV1
                RelationProvenanceProjectorV1().context(session, row, write=False)
                self._verify_authorities(session, row, reuse_snapshot=True)
                from .publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
                PublicationProvenanceProjectorV1().context(session, row)
                from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
                RetrievalProvenanceProjectorV1().context(session, row)
            return {"items": items, "next_after_id": items[-1]["context_id"] if len(rows) > request.limit else None}

    @staticmethod
    def _canonical(session, request, invocation_id):
        row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
        if (row is None or row.tool_id != COMPILE_CONTEXT_TOOL or row.status != "running"
                or row.input_payload.get("confirmed_by_user") is not True
                or ContextCompileInput.model_validate({k: v for k, v in query_payload(row.input_payload).items()
                    if k not in {"confirmed_by_user", "confirmed_at"}}) != request):
            raise ContextPackIntegrityError("confirmed canonical context command required")
        if row.conversation_id:
            conversation = session.get(ConversationRecord, row.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise ContextPackIntegrityError("context conversation mismatch")
        if row.input_payload.get("agent_goal_id"):
            goal = session.get(AgentGoalRecord, row.input_payload["agent_goal_id"])
            if goal is None or goal.project_id != request.project_id or goal.conversation_id != row.conversation_id:
                raise ContextPackIntegrityError("context goal mismatch")
        image = session.get(ImageRevisionRecord, request.image_revision_id)
        if image is None or image.project_id != request.project_id or image.artifact_hash != request.image_artifact_hash:
            raise ContextPackIntegrityError("context image mismatch")

    @classmethod
    def _committed(cls, session, request, invocation_id, actor_id):
        row = session.scalar(select(ContextPackRecord).where(ContextPackRecord.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._metadata(row)
        from .publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
        PublicationProvenanceProjectorV1().context(session, row)
        from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
        RetrievalProvenanceProjectorV1().context(session, row)
        if row.project_id != request.project_id or row.request_hash != snapshot_digest(request.model_dump(mode="json")) or value["actor_id"] != actor_id:
            raise ContextPackIntegrityError("context invocation already bound")
        return value

    def committed(self, request, *, invocation_id, actor_id, require_access):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            self._canonical(session, request, invocation_id)
            value = self._committed(session, request, invocation_id, actor_id)
            require_access()
            return value

    def record(self, request, metadata, artifact_ref, *, authority_pins, require_current, require_access):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            if (any(metadata.get(k) != getattr(request, k) for k in ("project_id", "image_revision_id", "image_artifact_hash", "policy_revision", "purpose"))
                    or metadata.get("input_digest") != request.expected_input_digest):
                raise ContextPackIntegrityError("context commit metadata scope mismatch")
            self._canonical(session, request, metadata["invocation_id"])
            prior = self._committed(session, request, metadata["invocation_id"], metadata["actor_id"])
            if prior is not None:
                from .context_authority_projection_v1 import ContextAuthorityProjectorV1
                ContextAuthorityProjectorV1().verify(session, session.get(ContextPackRecord, prior["context_id"]), pins=authority_pins)
                require_access()
                return prior
            # AC/review/ACL writers share this project lock. Recheck the full
            # application-derived input under it, not just a pre-write token.
            require_current()
            row = ContextPackRecord(**{k: metadata[k] for k in ("context_id", "project_id", "image_revision_id", "invocation_id")},
                payload=metadata, content_hash=snapshot_digest(metadata), artifact_ref=artifact_ref,
                request_hash=snapshot_digest(request.model_dump(mode="json")))
            session.add(row)
            session.flush()
            from .context_authority_projection_v1 import ContextAuthorityProjectorV1
            ContextAuthorityProjectorV1().record(session, row, authority_pins, invocation_id=metadata["invocation_id"],
                actor_id=metadata["actor_id"], recorded_at=metadata["recorded_at"])
            from .publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
            PublicationProvenanceProjectorV1().context(session, row, write=True)
            from .retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
            RetrievalProvenanceProjectorV1().context(session, row, write=True)
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="system_image.context.compiled",
                occurred_at=metadata["recorded_at"], correlation_id=request.project_id, entity_type="context_pack", entity_id=metadata["context_id"],
                entity_version=1, mutation_kind="append", patch={k: metadata[k] for k in ("context_id", "project_id", "image_revision_id", "readiness")},
                query_keys=[["context-packs", request.project_id]]), session=session)
            session.flush()
            require_access()
            return metadata

    def register_authorities(self, request, metadata, pins, *, invocation_id, actor_id, recorded_at, require_current):
        from .context_authority_models import ContextAuthorityRootRecord, ContextAuthorityBackfillTargetRecord
        from .context_authority_projection_v1 import ContextAuthorityProjectorV1
        from .context_invalidation_repository import ContextInvalidationRepository
        with session_scope() as session:
            ContextInvalidationRepository._lock(session, request.project_id)
            ContextInvalidationRepository._actor(session, request.project_id, actor_id)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            require_context_authority(command is not None and command.tool_id == REGISTER_CONTEXT_AUTHORITIES_TOOL
                and command.status == "running" and command.input_payload.get("confirmed_by_user") is True
                and command.input_payload.get("confirmed_actor_id") == actor_id
                and ContextAuthorityRegistrationInput.model_validate({k: v for k, v in query_payload(command.input_payload).items()
                    if k not in {"confirmed_by_user", "confirmed_at"}}) == request)
            try:
                confirmed = datetime.fromisoformat(str(command.input_payload.get("confirmed_at", "")))
                fresh = confirmed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - confirmed).total_seconds() <= 900
            except (TypeError, ValueError):
                fresh = False
            require_context_authority(fresh)
            if command.conversation_id:
                conversation = session.get(ConversationRecord, command.conversation_id)
                require_context_authority(conversation is not None and conversation.project_id == request.project_id)
            if command.input_payload.get("agent_goal_id"):
                goal = session.get(AgentGoalRecord, command.input_payload["agent_goal_id"])
                require_context_authority(goal is not None and goal.project_id == request.project_id
                    and goal.conversation_id == command.conversation_id)
            row = session.get(ContextPackRecord, request.context_id)
            require_context_authority(row is not None and row.project_id == request.project_id
                and self._metadata(row) == metadata and metadata["artifact_hash"] == request.artifact_hash)
            require_current()
            projector = ContextAuthorityProjectorV1()
            prior = session.get(ContextAuthorityRootRecord, (request.project_id, request.context_id))
            if prior is not None:
                value = projector.verify(session, row, pins=pins)
                require_current()
                return value
            target = session.get(ContextAuthorityBackfillTargetRecord, (request.project_id, request.context_id))
            require_context_authority(target is not None and target.context_metadata_hash == row.content_hash
                and target.artifact_hash == metadata["artifact_hash"] and target.policy_revision == request.policy_revision)
            value = projector.record(session, row, pins, invocation_id=invocation_id, actor_id=actor_id, recorded_at=recorded_at)
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="system_image.context.authorities_registered",
                occurred_at=recorded_at, correlation_id=request.project_id, entity_type="context_pack", entity_id=request.context_id,
                entity_version=1, mutation_kind="append", patch={key: value[key] for key in (
                    "project_id", "context_id", "authority_count", "authority_pins_hash", "registration_invocation_id")},
                query_keys=[["context-packs", request.project_id]]), session=session)
            require_current()
            return value
