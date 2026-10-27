from uuid import uuid4
from contextlib import contextmanager

from sqlalchemy import select, text

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...application.system_image.publications import (PublicationReviewInput, PublicationPublishInput, RollbackTarget,
    RollbackReviewInput, RollbackPublishInput, target_of)
from ...domain.system_image.publication import (PUBLICATION_REVIEW_TOOL, ROLLBACK_POLICY,
    ROLLBACK_REVIEW_TOOL, ROLLBACK_TOOL, PublicationChanged, PublicationIntegrityError, require_live_approval)
from ...domain.system_image.source_snapshots import snapshot_digest
from .db_models import BaselineRecord, ToolInvocationRecord, ConversationRecord, AgentGoalRecord, ApprovalRecord, ProjectRoleBindingRecord, UserIdentityRecord, AuditEventRecord
from .image_revision_models import ImageRevisionRecord
from .image_publication_models import ImagePublicationReviewRecord, ImagePublicationRecord, ImagePublicationHeadRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope
from .image_read_snapshot import current_image_read_snapshot


class ImagePublicationRepository:
    @staticmethod
    @contextmanager
    def _read_session():
        snapshot = current_image_read_snapshot()
        if snapshot is not None:
            yield snapshot[0]
        else:
            with session_scope() as session:
                yield session

    def publication(self, project_id, publication_id):
        with self._read_session() as session:
            row = session.get(ImagePublicationRecord, publication_id)
            if row is None or row.project_id != project_id:
                raise KeyError("Publication not found")
            return self._value(row, session=session)

    def read_selection(self, project_id, *, version_id=None):
        # One MVCC query selects both the adoption state and target. A version
        # without its own working head never inherits a moving official head.
        with session_scope() as session:
            rows = session.execute(select(BaselineRecord, ImagePublicationHeadRecord, ImagePublicationRecord)
                .outerjoin(ImagePublicationHeadRecord, (ImagePublicationHeadRecord.project_id == BaselineRecord.project_id)
                    & (ImagePublicationHeadRecord.baseline_id == BaselineRecord.id))
                .outerjoin(ImagePublicationRecord, ImagePublicationRecord.publication_id == ImagePublicationHeadRecord.publication_id)
                .where(BaselineRecord.project_id == project_id)).all()
            if not any(head is not None for _, head, _ in rows):
                return None
            matches = [(baseline, head, publication) for baseline, head, publication in rows
                if (baseline.kind == "version_working" and baseline.source_version_id == version_id if version_id
                    else baseline.kind == "official" and baseline.source_version_id is None)]
            if len(matches) > 1:
                raise PublicationChanged("Ambiguous published image target")
            if not matches:
                return {"baseline": None, "head": None}
            baseline, head, publication = matches[0]
            if head is not None and (publication is None or
                    (publication.project_id, publication.baseline_id, publication.sequence) != (project_id, baseline.id, head.sequence)):
                raise PublicationIntegrityError("Publication head integrity failed")
            return {"baseline": {"baseline_id": baseline.id, "project_id": project_id,
                "kind": baseline.kind, "source_version_id": baseline.source_version_id},
                "head": self._value(publication, session=session) if head is not None else None}

    def require_current_pin(self, project_id, pin):
        # Current adoption is live even while immutable image ancestry uses an
        # enclosing MVCC snapshot. Never memoize a head across a compilation.
        with session_scope() as session:
            value = session.execute(select(ImagePublicationHeadRecord, ImagePublicationRecord)
                .outerjoin(ImagePublicationRecord, ImagePublicationRecord.publication_id == ImagePublicationHeadRecord.publication_id)
                .where(ImagePublicationHeadRecord.project_id == project_id,
                    ImagePublicationHeadRecord.baseline_id == pin.baseline_id)).one_or_none()
            if value is None:
                raise PublicationChanged("Published image head changed; select the current publication")
            head, publication = value
            if publication is None or (publication.project_id, publication.baseline_id, publication.sequence) != (
                    project_id, pin.baseline_id, head.sequence):
                raise PublicationIntegrityError("Publication head integrity failed")
            if (head.publication_id, head.sequence) != (pin.publication_id, pin.sequence):
                raise PublicationChanged("Published image head changed; select the current publication")

    def has_heads(self, project_id):
        with session_scope() as session:
            return session.scalar(select(ImagePublicationHeadRecord.project_id).where(
                ImagePublicationHeadRecord.project_id == project_id).limit(1)) is not None

    @staticmethod
    def _value(row, *, session):
        keys = ("project_id", "baseline_id", "image_revision_id", "sequence", "invocation_id")
        keys += ("review_id", "claim_digest") if isinstance(row, ImagePublicationReviewRecord) else ("publication_id", "approval_id", "previous_publication_id")
        if snapshot_digest(row.payload) != row.content_hash or any(row.payload.get(k) != getattr(row, k) for k in keys):
            raise PublicationIntegrityError("Publication record integrity failed")
        if (row.payload.get("rollback_publication_id") != row.rollback_publication_id
                or (row.payload.get("policy_revision") == ROLLBACK_POLICY) != (row.rollback_publication_id is not None)):
            raise PublicationIntegrityError("Publication rollback pin integrity failed")
        from .publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
        PublicationProvenanceProjectorV1().fact(session,
            "review" if isinstance(row, ImagePublicationReviewRecord) else "publication", row)
        return dict(row.payload)

    @staticmethod
    def _lock(session, project_id):
        SourceSnapshotRepository._lock(session, project_id)
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"nasus:source-access:{project_id}"})

    @classmethod
    def _target(cls, session, project_id, baseline_id):
        baseline = session.get(BaselineRecord, baseline_id)
        if baseline is None or baseline.project_id != project_id:
            raise KeyError("Publication target not found")
        baseline_value = {"baseline_id": baseline.id, "project_id": project_id, "kind": baseline.kind, "source_version_id": baseline.source_version_id}
        head = session.get(ImagePublicationHeadRecord, (project_id, baseline_id))
        if head is None:
            return baseline_value, None
        row = session.get(ImagePublicationRecord, head.publication_id)
        if row is None or (row.project_id, row.baseline_id, row.sequence) != (project_id, baseline_id, head.sequence):
            raise PublicationIntegrityError("Publication head integrity failed")
        return baseline_value, cls._value(row, session=session)

    def target(self, project_id, baseline_id):
        with self._read_session() as session:
            return self._target(session, project_id, baseline_id)

    @classmethod
    def _review_head(cls, session, project_id, claim_digest):
        row = session.scalar(select(ImagePublicationReviewRecord).where(
            ImagePublicationReviewRecord.project_id == project_id, ImagePublicationReviewRecord.claim_digest == claim_digest,
        ).order_by(ImagePublicationReviewRecord.sequence.desc()).limit(1))
        return cls._value(row, session=session) if row is not None else None

    def review_head(self, project_id, claim_digest):
        with self._read_session() as session:
            return self._review_head(session, project_id, claim_digest)

    def history(self, project_id, baseline_id, *, after_sequence, limit):
        with self._read_session() as session:
            rows = session.scalars(select(ImagePublicationRecord).where(ImagePublicationRecord.project_id == project_id,
                ImagePublicationRecord.baseline_id == baseline_id, ImagePublicationRecord.sequence > after_sequence,
            ).order_by(ImagePublicationRecord.sequence).limit(limit + 1)).all()
            items = [self._value(row, session=session) for row in rows[:limit]]
            return {"items": items, "next_after_sequence": items[-1]["sequence"] if len(rows) > limit else None}

    @staticmethod
    def _actor(session, project_id, actor_id):
        identity = session.scalar(select(UserIdentityRecord).where(UserIdentityRecord.user_id == actor_id)
            .with_for_update().execution_options(populate_existing=True))
        if identity is None or identity.status != "active":
            raise PermissionError("Publication needs an active registered reviewer")
        roles = session.scalars(select(ProjectRoleBindingRecord).where(ProjectRoleBindingRecord.project_id == project_id,
            ProjectRoleBindingRecord.user_id == actor_id, ProjectRoleBindingRecord.version_id.is_(None),
            ProjectRoleBindingRecord.session_id.is_(None), ProjectRoleBindingRecord.status == "active")
            .with_for_update().execution_options(populate_existing=True)).all()
        if identity.role != "platform_admin" and (len(roles) != 1 or roles[0].role != "project_admin"):
            raise PermissionError("Publication reviewer is no longer a project administrator")

    @staticmethod
    def _canonical(session, request, invocation_id, review):
        row = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
        rollback = isinstance(request, RollbackTarget)
        model = (RollbackReviewInput if review else RollbackPublishInput) if rollback else (PublicationReviewInput if review else PublicationPublishInput)
        tool = (ROLLBACK_REVIEW_TOOL if review else ROLLBACK_TOOL) if rollback else (PUBLICATION_REVIEW_TOOL if review else "baseline.promote")
        if (row is None or row.tool_id != tool or row.status != "running"
                or review and row.input_payload.get("confirmed_by_user") is not True
                or model.model_validate({k: v for k, v in query_payload(row.input_payload).items() if k not in {"confirmed_by_user", "confirmed_at"}}) != request):
            raise PublicationIntegrityError("Canonical bound publication command required")
        if row.conversation_id:
            conversation = session.get(ConversationRecord, row.conversation_id)
            if conversation is None or conversation.project_id != request.project_id:
                raise PublicationIntegrityError("Publication conversation mismatch")
        if row.input_payload.get("agent_goal_id"):
            goal = session.get(AgentGoalRecord, row.input_payload["agent_goal_id"])
            if goal is None or goal.project_id != request.project_id or goal.conversation_id != row.conversation_id:
                raise PublicationIntegrityError("Publication goal mismatch")
        image = session.get(ImageRevisionRecord, request.image_revision_id)
        if image is None or image.project_id != request.project_id or image.artifact_hash != request.image_artifact_hash:
            raise PublicationIntegrityError("Publication image mismatch")
        baseline = session.scalar(select(BaselineRecord).where(BaselineRecord.id == request.target_baseline_id).with_for_update())
        if baseline is None or baseline.project_id != request.project_id:
            raise PublicationIntegrityError("Publication target mismatch")

    @classmethod
    def _committed(cls, session, request, invocation_id, actor_id, review):
        model = ImagePublicationReviewRecord if review else ImagePublicationRecord
        row = session.scalar(select(model).where(model.invocation_id == invocation_id))
        if row is None:
            return None
        value = cls._value(row, session=session)
        if row.project_id != request.project_id or row.request_hash != snapshot_digest(request.model_dump(mode="json")) or value["actor_id"] != actor_id:
            raise PublicationIntegrityError("Publication invocation already bound")
        return value

    def committed(self, request, *, invocation_id, actor_id, review, require_access):
        with session_scope() as session:
            self._lock(session, request.project_id)
            self._canonical(session, request, invocation_id, review)
            self._actor(session, request.project_id, actor_id)
            value = self._committed(session, request, invocation_id, actor_id, review)
            require_access()
            return value

    @staticmethod
    def _claim(request):
        return snapshot_digest({"target": target_of(request).model_dump(mode="json"), "preview_digest": request.expected_preview_digest})

    @staticmethod
    def _event(session, value, kind, ident):
        from .publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
        session.flush()
        fact_kind = "review" if kind == "reviewed" else "publication"
        native = session.get(ImagePublicationReviewRecord if fact_kind == "review" else ImagePublicationRecord, ident)
        PublicationProvenanceProjectorV1().fact(session, fact_kind, native, write=True, new_fact=(fact_kind, ident))
        invocation = session.get(ToolInvocationRecord, value["invocation_id"])
        session.add(AuditEventRecord(id=str(uuid4()), occurred_at=value["recorded_at"],
            actor=value["actor_id"], actor_kind="user", action="system_image.publication." + kind,
            entity_type="image_publication", entity_id=ident, status="completed",
            summary="Pinned image publication " + kind + "; not quality generation or release authority.",
            conversation_id=invocation.conversation_id, tool_invocation_id=value["invocation_id"],
            agent_goal_id=invocation.input_payload.get("agent_goal_id"),
            object_refs=["project:" + value["project_id"], "image_revision:" + value["image_revision_id"]],
            evidence_refs=[], event_metadata={k: value[k] for k in ("project_id", "baseline_id", "image_artifact_hash", "sequence", "policy_revision")}))
        EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="system_image.publication." + kind,
            occurred_at=value["recorded_at"], correlation_id=value["project_id"], tool_invocation_id=value["invocation_id"],
            entity_type="image_publication", entity_id=ident, entity_version=value["sequence"], mutation_kind="append",
            patch={k: value[k] for k in ("project_id", "baseline_id", "image_revision_id", "sequence")},
            query_keys=[["image-publications", value["project_id"]], ["system-image", value["project_id"]]]), session=session)

    def _write(self, request, preview, *, invocation_id, actor_id, recorded_at, require_current, require_access, review):
        with session_scope() as session:
            self._lock(session, request.project_id)
            self._canonical(session, request, invocation_id, review)
            self._actor(session, request.project_id, actor_id)
            prior = self._committed(session, request, invocation_id, actor_id, review)
            if prior is not None:
                require_access()
                return prior
            claim = self._claim(request)
            reviewed = self._review_head(session, request.project_id, claim)
            _, old_head = self._target(session, request.project_id, request.target_baseline_id)
            if (old_head["publication_id"] if old_head else None) != request.expected_head_id:
                raise PublicationChanged("Publication head changed")
            if review:
                if (reviewed["review_id"] if reviewed else None) != request.expected_review_id:
                    raise PublicationChanged("Publication review changed")
            else:
                if reviewed is None:
                    raise PublicationChanged("Exact-image publication approval required")
                approval = session.scalar(select(ApprovalRecord).where(ApprovalRecord.id == request.approval_id).with_for_update())
                if approval is None or approval.project_id != request.project_id or approval.status != "approved":
                    raise PublicationChanged("Publication approval is not active")
                require_live_approval(reviewed, claim=claim, previous_review_id=request.approval_id, policy=request.policy_revision)
                self._actor(session, request.project_id, reviewed["actor_id"])
            require_current()
            rollback_id = request.rollback_publication_id if isinstance(request, RollbackTarget) else None
            value = {"project_id": request.project_id, "baseline_id": request.target_baseline_id,
                "image_revision_id": request.image_revision_id, "image_artifact_hash": request.image_artifact_hash,
                "manifest_id": preview["image"]["manifest_id"], "manifest_hash": preview["image"]["manifest_hash"],
                "actor_id": actor_id, "invocation_id": invocation_id, "recorded_at": recorded_at,
                "policy_revision": request.policy_revision, "preview_digest": request.expected_preview_digest,
                "quality_generation_authorized": False, "release_authorized": False}
            if rollback_id is not None:
                value["rollback_publication_id"] = rollback_id
            common = {k: value[k] for k in ("project_id", "baseline_id", "image_revision_id", "invocation_id")}
            if review:
                ident = str(uuid4())
                value.update(review_id=ident, claim_digest=claim, sequence=reviewed["sequence"] + 1 if reviewed else 1,
                    previous_review_id=request.expected_review_id, decision=request.decision, reason=request.reason)
                session.add(ImagePublicationReviewRecord(**common, rollback_publication_id=rollback_id, review_id=ident, claim_digest=claim,
                    sequence=value["sequence"], payload=value, content_hash=snapshot_digest(value), request_hash=snapshot_digest(request.model_dump(mode="json"))))
                session.add(ApprovalRecord(id=ident, project_id=request.project_id, title="Pinned image publication review",
                    status="approved" if request.decision == "approve" else "rejected", summary="Review applies only to its exact image, target and expected head.",
                    policy_reason=request.policy_revision, conflict_fields=[], recommended_resolution="Use the exact pinned publication command before this review expires.",
                    evidence=[f"image_revision:{request.image_revision_id}", f"publication_review:{ident}", claim], sort_order=0))
                self._event(session, value, "reviewed", ident)
            else:
                ident = str(uuid4())
                value.update(publication_id=ident, approval_id=request.approval_id, previous_publication_id=request.expected_head_id,
                    sequence=old_head["sequence"] + 1 if old_head else 1)
                session.add(ImagePublicationRecord(**common, rollback_publication_id=rollback_id, publication_id=ident, approval_id=request.approval_id,
                    previous_publication_id=request.expected_head_id, sequence=value["sequence"], payload=value,
                    content_hash=snapshot_digest(value), request_hash=snapshot_digest(request.model_dump(mode="json"))))
                session.flush()
                head = session.get(ImagePublicationHeadRecord, (request.project_id, request.target_baseline_id))
                if head is None:
                    session.add(ImagePublicationHeadRecord(project_id=request.project_id, baseline_id=request.target_baseline_id, publication_id=ident, sequence=value["sequence"]))
                else:
                    head.publication_id, head.sequence = ident, value["sequence"]
                self._event(session, value, "rolled_back" if rollback_id else "published", ident)
            session.flush()
            return value

    def review(self, request, preview, **kwargs):
        return self._write(request, preview, review=True, **kwargs)

    def publish(self, request, preview, **kwargs):
        return self._write(request, preview, review=False, **kwargs)
