"""Complete immutable context proofs, never live authority or archived bytes."""
from ...domain.system_image.source_snapshots import snapshot_digest
from .context_provenance_projection_v1 import ContextProvenanceProjectorV1
from .image_read_snapshot import CONTEXT_PROVENANCE_CACHE, current_image_read_snapshot
from .relation_provenance_projection_v1 import RelationProvenanceProjectorV1


def context_metadata_digest(context):
    return snapshot_digest({column.name: getattr(context, column.name) for column in context.__table__.columns})


def verify_context_provenance(session, context):
    snapshot = current_image_read_snapshot()
    cached = (session.info.setdefault(CONTEXT_PROVENANCE_CACHE, {})
        if snapshot is not None and snapshot[0] is session else None)
    key = (context.project_id, context.context_id)
    metadata = context_metadata_digest(context)
    if cached is not None and cached.get(key) == metadata:
        return metadata
    ContextProvenanceProjectorV1().verify(session, context)
    RelationProvenanceProjectorV1().context(session, context, write=False)
    if cached is not None:
        if key not in cached and len(cached) >= 2:
            del cached[next(iter(cached))]
        cached[key] = metadata
    return metadata
