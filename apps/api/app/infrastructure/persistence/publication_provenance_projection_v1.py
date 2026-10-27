"""Register exact native publication ancestry, never today's mutable head/approval."""
from sqlalchemy import select

from ...application.platform.tool_handlers.query_input import query_payload
from ...application.system_image.context_pack_inputs import ContextCompileInput
from ...application.system_image.publications import (PublicationReviewInput, PublicationPublishInput,
    RollbackReviewInput, RollbackPublishInput)
from ...domain.system_image.context_pack import ContextPackIntegrityError
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.publication import (PUBLICATION_REVIEW_TOOL, ROLLBACK_POLICY, ROLLBACK_REVIEW_TOOL,
    ROLLBACK_TOOL, PublicationIntegrityError)
from ...domain.system_image.publication_provenance import (PUBLICATION_PROVENANCE_POLICY,
    PublicationProvenanceAnchor, require_publication_provenance as require)
from ...domain.system_image.source_snapshots import snapshot_digest
from .context_pack_models import ContextPackRecord as Context
from .db_models import ToolInvocationRecord as Command
from .image_publication_models import ImagePublicationRecord as Publication, ImagePublicationReviewRecord as Review
from .image_revision_models import ImageRevisionRecord as Image
from .object_provenance_models import ImageObjectProvenanceRecord as ObjectRoot
from .image_provenance_reads import verify_image_provenance
from .relation_provenance_models import ImageRelationProvenanceRecord as RelationRoot
from .publication_provenance_models import (PublicationProvenanceRecord as Anchor,
    PublicationProvenanceDependencyRecord as Edge, ContextPublicationDependencyRecord as ContextAnchor)


def _columns(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class PublicationProvenanceProjectorV1:
    def fact(self, session, kind, row, *, write=False, new_fact=None, reuse_snapshot=False):
        try:
            return self._fact(session, kind, row, write=write, new_fact=new_fact, reuse_snapshot=reuse_snapshot)
        except PublicationIntegrityError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError, ImageRevisionIntegrityError) as error:
            raise PublicationIntegrityError("Publication provenance failed integrity verification") from error

    @staticmethod
    def _native(session, kind, row):
        require(row is not None and kind in {"review", "publication"})
        value = row.payload
        ident = row.review_id if kind == "review" else row.publication_id
        keys = ("project_id", "baseline_id", "image_revision_id", "sequence", "invocation_id")
        keys += ("review_id", "claim_digest") if kind == "review" else ("publication_id", "approval_id", "previous_publication_id")
        require(type(value) is dict and snapshot_digest(value) == row.content_hash
            and all(value.get(key) == getattr(row, key) for key in keys)
            and value.get("rollback_publication_id") == row.rollback_publication_id
            and value.get("quality_generation_authorized") is False and value.get("release_authorized") is False)
        rollback = row.rollback_publication_id is not None
        require((value.get("policy_revision") == ROLLBACK_POLICY) == rollback)
        model = (RollbackReviewInput if kind == "review" else RollbackPublishInput) if rollback else (
            PublicationReviewInput if kind == "review" else PublicationPublishInput)
        command = session.get(Command, row.invocation_id)
        tool = (ROLLBACK_REVIEW_TOOL if kind == "review" else ROLLBACK_TOOL) if rollback else (
            PUBLICATION_REVIEW_TOOL if kind == "review" else "baseline.promote")
        require(command is not None and command.tool_id == tool)
        request = model.model_validate({k: v for k, v in query_payload(command.input_payload).items()
            if k not in {"confirmed_by_user", "confirmed_at"}})
        require(snapshot_digest(request.model_dump(mode="json")) == row.request_hash
            and (request.project_id, request.target_baseline_id, request.image_revision_id, request.image_artifact_hash,
                request.policy_revision, request.expected_preview_digest) ==
                (row.project_id, row.baseline_id, row.image_revision_id, value["image_artifact_hash"],
                 value["policy_revision"], value["preview_digest"]))
        parents = []
        if kind == "review":
            require(command.input_payload.get("confirmed_by_user") is True
                and value["previous_review_id"] == request.expected_review_id
                and value["decision"] == request.decision and value["reason"] == request.reason
                and value["claim_digest"] == snapshot_digest({"target": request.model_dump(mode="json",
                    exclude={"expected_preview_digest", "expected_review_id", "decision", "reason"}),
                    "preview_digest": request.expected_preview_digest}))
            if request.expected_review_id:
                parents.append(("previous_review", "review", request.expected_review_id))
            if request.expected_head_id:
                parents.append(("expected_head", "publication", request.expected_head_id))
        else:
            require(value["approval_id"] == request.approval_id
                and value["previous_publication_id"] == request.expected_head_id)
            parents.append(("approval", "review", request.approval_id))
            if request.expected_head_id:
                parents.append(("previous_publication", "publication", request.expected_head_id))
        if rollback:
            require(row.rollback_publication_id == request.rollback_publication_id)
            parents.append(("rollback_source", "publication", request.rollback_publication_id))
        return ident, value, tuple(sorted(parents))

    def _fact(self, session, kind, row, *, write, new_fact, reuse_snapshot):
        model = {"review": Review, "publication": Publication}
        require(kind in model and row is not None)
        root = (kind, row.review_id if kind == "review" else row.publication_id)
        stack, active, finished, natives, audited = [(root, row, False)], set(), {}, {}, set()
        while stack:
            key, native, ready = stack.pop()
            if key in finished:
                continue
            if not ready:
                require(key not in active and len(active) + len(finished) < 1000)
                active.add(key)
                ident, value, parents = self._native(session, key[0], native)
                require(key[1] == ident and native.project_id == row.project_id and native.baseline_id == row.baseline_id)
                natives[key] = (native, value, parents)
                stack.append((key, native, True))
                for _, parent_kind, parent_id in reversed(parents):
                    parent = (parent_kind, parent_id)
                    if parent not in finished:
                        stack.append((parent, session.get(model[parent_kind], parent_id), False))
                continue
            native, value, parents = natives[key]
            dependencies = []
            for relation, parent_kind, parent_id in parents:
                parent = finished[(parent_kind, parent_id)]
                parent_value = natives[(parent_kind, parent_id)][1]
                if relation == "previous_review":
                    require(parent["sequence"] + 1 == native.sequence and parent_value["claim_digest"] == value["claim_digest"])
                elif relation == "previous_publication":
                    require(parent["sequence"] + 1 == native.sequence)
                elif relation == "approval":
                    require(parent_value["decision"] == "approve" and all(parent_value[k] == value[k]
                        for k in ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash", "preview_digest", "policy_revision")))
                    require(parent_value.get("rollback_publication_id") == value.get("rollback_publication_id"))
                    approval_parents = natives[(parent_kind, parent_id)][2]
                    require(next((p[2] for p in approval_parents if p[0] == "expected_head"), None) == value["previous_publication_id"])
                elif relation == "rollback_source":
                    require(all(parent_value[k] == value[k] for k in ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")))
                dependencies.append((relation, parent_kind, parent_id, parent["content_hash"]))
            previous = "previous_review" if key[0] == "review" else "previous_publication"
            require((native.sequence == 1) == (not any(p[0] == previous for p in parents)))
            image = session.get(Image, native.image_revision_id)
            require(image is not None and image.project_id == native.project_id and image.artifact_hash == value["image_artifact_hash"]
                and image.manifest_id == value["manifest_id"] and image.manifest_hash == value["manifest_hash"])
            if image.image_revision_id not in audited:
                verify_image_provenance(session, image, reuse_snapshot=reuse_snapshot and not write)
                audited.add(image.image_revision_id)
            object_root = session.get(ObjectRoot, (native.project_id, image.image_revision_id))
            relation_root = session.get(RelationRoot, (native.project_id, image.image_revision_id))
            require(object_root is not None and relation_root is not None)
            expected = PublicationProvenanceAnchor(native.project_id, key[0], key[1], native.baseline_id,
                image.image_revision_id, image.artifact_hash, image.manifest_id, image.manifest_hash, native.sequence,
                native.content_hash, native.request_hash, native.invocation_id, object_root.content_hash,
                relation_root.content_hash, tuple(sorted(dependencies))).record_v1
            edges = [dict(project_id=native.project_id, baseline_id=native.baseline_id, fact_kind=key[0], fact_id=key[1],
                fact_hash=expected["content_hash"], relation=relation, parent_kind=parent_kind, parent_id=parent_id,
                parent_hash=digest) for relation, parent_kind, parent_id, digest in sorted(dependencies)]
            saved = session.get(Anchor, (native.project_id, *key))
            saved_edges = [_columns(e) for e in session.scalars(select(Edge).where(Edge.project_id == native.project_id,
                Edge.fact_kind == key[0], Edge.fact_id == key[1]).order_by(Edge.relation).limit(4))]
            if saved is None:
                require(write and (new_fact is None or new_fact == key) and not saved_edges)
                session.add(Anchor(**expected))
                session.flush()
                session.add_all(Edge(**edge) for edge in edges)
                session.flush()
            else:
                require(_columns(saved) == expected and saved_edges == edges)
            active.remove(key)
            finished[key] = expected
        return finished[root]

    def context(self, session, row, *, write=False):
        try:
            require(row is not None and snapshot_digest(row.payload) == row.content_hash)
            command = session.get(Command, row.invocation_id)
            require(command is not None and command.tool_id == "system_image.context.compile")
            request = ContextCompileInput.model_validate({k: v for k, v in query_payload(command.input_payload).items()
                if k not in {"confirmed_by_user", "confirmed_at"}})
            require(request.project_id == row.project_id and request.image_revision_id == row.image_revision_id
                and request.image_artifact_hash == row.payload["image_artifact_hash"]
                and request.policy_revision == row.payload["policy_revision"] and request.purpose == row.payload["purpose"]
                and request.expected_input_digest == row.payload["input_digest"]
                and all(row.payload.get(k) == getattr(row, k) for k in ("project_id", "context_id", "image_revision_id", "invocation_id"))
                and snapshot_digest(request.model_dump(mode="json")) == row.request_hash)
            saved = session.get(ContextAnchor, (row.project_id, row.context_id))
            if request.publication_id is None:
                require(saved is None)
                return None
            publication = session.get(Publication, request.publication_id)
            require(publication is not None and publication.project_id == row.project_id)
            pin = self.fact(session, "publication", publication, reuse_snapshot=not write)
            require(pin["image_revision_id"] == row.image_revision_id and pin["image_artifact_hash"] == request.image_artifact_hash)
            expected = dict(project_id=row.project_id, context_id=row.context_id, context_metadata_hash=row.content_hash,
                context_request_hash=row.request_hash, image_revision_id=row.image_revision_id,
                image_artifact_hash=request.image_artifact_hash, baseline_id=publication.baseline_id,
                publication_kind="publication", publication_id=request.publication_id,
                publication_registration_hash=pin["content_hash"], policy_revision=PUBLICATION_PROVENANCE_POLICY)
            expected["content_hash"] = snapshot_digest(expected)
            if saved is None:
                require(write)
                session.add(ContextAnchor(**expected))
                session.flush()
            else:
                require(_columns(saved) == expected)
            return expected
        except (PublicationIntegrityError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise ContextPackIntegrityError("Context publication dependencies failed integrity verification") from error

    def project_event(self, session, event):
        if event.event_type in {"system_image.publication.reviewed", "system_image.publication.published", "system_image.publication.rolled_back"}:
            kind = "review" if event.event_type.endswith("reviewed") else "publication"
            row = session.get(Review if kind == "review" else Publication, event.entity_id)
            require(row is not None and event.patch == {k: row.payload[k] for k in
                ("project_id", "baseline_id", "image_revision_id", "sequence")}
                and event.occurred_at == row.payload["recorded_at"] and event.correlation_id == row.project_id
                and event.tool_invocation_id == row.invocation_id and event.mutation_kind == "append"
                and event.entity_type == "image_publication"
                and (kind == "review" or event.event_type.endswith("rolled_back") == (row.rollback_publication_id is not None)))
            self.fact(session, kind, row)
        elif event.event_type == "system_image.context.compiled":
            self.context(session, session.get(Context, event.entity_id))

    def backfill(self, session):
        # DFS registers parents before children; existing corrupt pins are never repaired.
        for kind, model in (("review", Review), ("publication", Publication)):
            for row in session.scalars(select(model).order_by(model.project_id, model.baseline_id, model.sequence)
                    .execution_options(yield_per=128)):
                self.fact(session, kind, row, write=True)
        for row in session.scalars(select(Context).order_by(Context.project_id, Context.context_id).execution_options(yield_per=128)):
            self.context(session, row, write=True)
        session.flush()
