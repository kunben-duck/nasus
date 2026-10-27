"""Metadata-only source ancestry in the authority fact's own transaction."""
from sqlalchemy import select
from sqlalchemy.orm import aliased

from ...domain.quality_loop.acceptance_specification import AcceptanceIntegrityError, AcceptanceRevision
from ...domain.quality_loop.authority_provenance import AuthorityProvenanceAnchor
from ...domain.quality_loop.business_rule import BusinessRuleRevision
from .acceptance_specification_models import AcceptanceRevisionRecord as Acceptance
from .authority_provenance_models import AuthorityProvenanceRecord as Anchor
from .business_rule_models import BusinessRuleRevisionRecord as Rule
from .document_projection_models import SourceDocumentRevisionRecord as Document
from .image_revision_models import ImageRevisionRecord as Image, ImageObjectMemberRecord as Member
from .object_provenance_models import ObjectProvenanceNodeRecord as ObjectNode
from .image_provenance_reads import verify_image_object_provenance


FACT_TYPES = {
    "acceptance": (Acceptance, AcceptanceRevision, "ac_id", "acceptance_criterion"),
    "business_rule": (Rule, BusinessRuleRevision, "rule_id", "business_rule"),
}
FACT_EVENTS = {
    "quality.acceptance_specification.reviewed": "acceptance",
    "quality.business_rule.reviewed": "business_rule",
}


def _require(condition):
    if not condition:
        raise AcceptanceIntegrityError("authority provenance failed integrity verification")


class AuthorityProvenanceProjectorV1:
    def facts(self, session, kind, rows, *, write, new_revision=None, reuse_snapshot=False):
        try:
            return self._facts(session, kind, rows, write=write, new_revision=new_revision,
                reuse_snapshot=reuse_snapshot)
        except AcceptanceIntegrityError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise AcceptanceIntegrityError("authority provenance failed integrity verification") from exc

    def _facts(self, session, kind, rows, *, write, new_revision, reuse_snapshot):
        model, value_type, id_field, document_kind = FACT_TYPES[kind]
        images, heads, count = {}, {}, 0
        for row in rows:
            _require(row is not None)
            key = (row.project_id, getattr(row, id_field))
            if key not in heads or row.sequence > heads[key].sequence:
                heads[key] = row
        for row in heads.values():
            history = session.scalars(select(model).where(model.project_id == row.project_id,
                getattr(model, id_field) == getattr(row, id_field), model.sequence <= row.sequence)
                .order_by(model.sequence).limit(1001)).all()
            _require(0 < len(history) <= 1000 and history[-1].revision_id == row.revision_id)
            previous, previous_value = None, None
            for ordinal, native in enumerate(history, 1):
                value = value_type(**native.payload)
                _require(value.digest == native.content_hash and all(getattr(value, key) == getattr(native, key)
                    for key in ("revision_id", id_field, "project_id", "image_revision_id", "object_id", "binding_id",
                        "source_revision_id", "document_revision_id", "previous_revision_id", "sequence", "status", "invocation_id")))
                _require(value.sequence == ordinal and value.previous_revision_id ==
                    (previous_value.revision_id if previous_value else None)
                    and (value.status != "withdrawn" or previous_value is not None and previous_value.status == "approved"))
                image_key = (value.project_id, value.image_revision_id)
                if image_key not in images:
                    image = session.get(Image, value.image_revision_id)
                    _require(image is not None and image.project_id == value.project_id)
                    verify_image_object_provenance(session, image, reuse_snapshot=reuse_snapshot and not write)
                    images[image_key] = image
                image = images[image_key]
                member = session.get(Member, (value.image_revision_id, value.object_id))
                document = session.get(Document, value.document_revision_id)
                _require(image.artifact_hash == value.image_artifact_hash and member is not None
                    and member.project_id == value.project_id and member.kind == "source_document"
                    and document is not None and document.kind == document_kind
                    and all(getattr(member, key) == getattr(value, key) == getattr(document, key)
                        for key in ("project_id", "binding_id", "source_revision_id", "document_revision_id")))
                pins = ["image_objects:" + value.image_revision_id,
                    "member:" + value.image_revision_id + "/" + value.object_id,
                    "document:" + value.document_revision_id]
                hashes = [session.get(ObjectNode, (value.project_id, key)).content_hash for key in pins]
                anchor = AuthorityProvenanceAnchor(value.project_id, kind, value.revision_id, getattr(value, id_field),
                    value.digest, value.artifact_hash, value.image_revision_id, value.image_artifact_hash,
                    value.object_id, value.binding_id, value.source_revision_id, value.document_revision_id,
                    value.basis_digest, value.invocation_id, value.status, value.sequence, *hashes,
                    value.previous_revision_id, previous["content_hash"] if previous else None).record_v1
                saved = session.get(Anchor, (value.project_id, kind, value.revision_id))
                if saved is None:
                    _require(write and (new_revision is None or new_revision == value.revision_id))
                    session.add(Anchor(**anchor))
                    session.flush()
                    count += 1
                else:
                    _require(all(getattr(saved, key) == item for key, item in anchor.items()))
                previous, previous_value = anchor, value
        return count

    def project_event(self, session, event):
        kind = FACT_EVENTS.get(event.event_type)
        if kind is None:
            return
        model, _, id_field, _ = FACT_TYPES[kind]
        row = session.get(model, event.entity_id)
        _require(row is not None and all(event.patch.get(key) == getattr(row, key)
            for key in ("project_id", "revision_id", "image_revision_id", "status", id_field)))
        # The native writer registered the new fact before appending its event.
        # Even a replayed event must never repair current or predecessor pins.
        self.facts(session, kind, (row,), write=False)

    def backfill(self, session):
        count = 0
        for kind, (model, _, id_field, _) in FACT_TYPES.items():
            later = aliased(model)
            query = select(model).where(~select(later.revision_id).where(later.project_id == model.project_id,
                getattr(later, id_field) == getattr(model, id_field), later.sequence > model.sequence).exists())
            for row in session.scalars(query.order_by(model.project_id, getattr(model, id_field))
                    .execution_options(yield_per=128)):
                count += self.facts(session, kind, (row,), write=True)
        session.flush()
        return count
