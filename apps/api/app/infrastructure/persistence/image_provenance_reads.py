"""Share complete graph audits only inside one read-only image MVCC snapshot."""
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from .image_read_snapshot import current_image_read_snapshot
from .image_revision_models import ImageRevisionRecord
from .object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from .relation_provenance_projection_v1 import RelationProvenanceProjectorV1


def verify_image_object_provenance(session, image, *, reuse_snapshot=False):
    """Read-only ancestry may reuse an already complete, owned image proof."""
    snapshot = current_image_read_snapshot()
    if reuse_snapshot and snapshot is not None:
        metadata = snapshot_digest({c.name: getattr(image, c.name) for c in image.__table__.columns})
        pinned = snapshot[0].get(ImageRevisionRecord, image.image_revision_id)
        if pinned is not None:
            if snapshot_digest({c.name: getattr(pinned, c.name)
                    for c in pinned.__table__.columns}) != metadata:
                raise ImageRevisionIntegrityError("Image metadata does not match its immutable read snapshot.")
            if snapshot[1].get((image.project_id, image.image_revision_id)) == metadata:
                return
    # An open scope, an absent/new image or an unverified image is not proof.
    # Do not cache this partial audit as a complete object-and-relation audit.
    ObjectProvenanceProjectorV1().image(session, image, write=False)


def verify_image_provenance(session, image, *, members=None, reuse_snapshot=False):
    snapshot = current_image_read_snapshot()
    metadata = snapshot_digest({c.name: getattr(image, c.name) for c in image.__table__.columns})
    if reuse_snapshot and snapshot is not None and snapshot[0] is not session and members is None:
        # Live publication commands/heads stay in the caller's fresh session;
        # only their exact immutable image ancestry belongs to this snapshot.
        pinned = snapshot[0].get(ImageRevisionRecord, image.image_revision_id)
        if pinned is None or snapshot_digest({c.name: getattr(pinned, c.name)
                for c in pinned.__table__.columns}) != metadata:
            raise ImageRevisionIntegrityError("Image metadata does not match its immutable read snapshot.")
        return verify_image_provenance(snapshot[0], pinned)
    verified = snapshot[1] if snapshot is not None and snapshot[0] is session else None
    key = (image.project_id, image.image_revision_id)
    if verified is not None and verified.get(key) == metadata:
        return
    ObjectProvenanceProjectorV1().image(session, image, write=False, members=members)
    RelationProvenanceProjectorV1().image(session, image, write=False, native_verified=True)
    if verified is not None:
        if key not in verified and len(verified) >= 2:
            del verified[next(iter(verified))]
        verified[key] = metadata
