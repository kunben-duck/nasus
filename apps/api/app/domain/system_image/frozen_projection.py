"""Validate a manifest-rooted projection without manufacturing graph topology."""
from .image_revision import ImageRevisionIntegrityError, require_frozen_inputs
from .materialization import (
    SYNTHETIC_EVIDENCE_MARKERS, InsufficientSystemImageEvidenceError,
    SystemImageMaterializationDecision,
)


def _source_backed(refs):
    return bool(refs) and all(isinstance(ref, str) and ref.strip()
        and not any(marker in ref.lower() for marker in SYNTHETIC_EVIDENCE_MARKERS) for ref in refs)


def require_frozen_projection(manifest, baseline_id, *, objects, relationships, metrics):
    """Membership validity is not exhaustive analysis, business authority or coverage."""
    require_frozen_inputs(manifest)
    objects, relationships, metrics = tuple(objects), tuple(relationships), tuple(metrics)
    if (not baseline_id or len(objects) > 50000 or len(relationships) > 100000
            or len(metrics) > 1000):
        raise ImageRevisionIntegrityError("Invalid frozen projection scope or size.")
    revisions = {member.source_revision_id: member.source_type for member in manifest.members
                 if member.status == "captured"}
    if len(revisions) != sum(member.status == "captured" for member in manifest.members):
        raise ImageRevisionIntegrityError("Frozen sources have duplicate revision identities.")
    ids = set()
    code_count = 0
    for item in objects:
        code = getattr(item, "code_reference", None)
        document = getattr(item, "document_reference", None)
        if (not item.id or item.id in ids or bool(code) == bool(document)
                or not _source_backed(item.evidence)):
            raise ImageRevisionIntegrityError("Frozen objects require unique source-pinned identities.")
        ids.add(item.id)
        if code:
            if (not code.entity_id or not code.entity_revision_id
                    or revisions.get(code.source_revision_id) != "code"):
                raise ImageRevisionIntegrityError("Code object differs from the frozen source manifest.")
            code_count += 1
        elif (not document.document_revision_id
                or revisions.get(document.source_revision_id) not in {"us_doc", "test_asset"}):
            raise ImageRevisionIntegrityError("Document object differs from the frozen source manifest.")
    relationship_ids = set()
    for item in relationships:
        if (not item.id or item.id in relationship_ids
                or item.project_id != manifest.project_id or item.baseline_id != baseline_id
                or item.from_object_id not in ids or item.to_object_id not in ids
                or not _source_backed(item.source_refs)):
            raise ImageRevisionIntegrityError("Relationship is outside the frozen projection.")
        relationship_ids.add(item.id)
    for item in metrics:
        if (item.project_id != manifest.project_id or item.baseline_id != baseline_id
                or not _source_backed(item.evidence_refs)):
            raise ImageRevisionIntegrityError("Metric is outside the frozen projection.")
    missing = []
    if not code_count:
        missing.append("at least one source-pinned code object")
    if not any(item.metric_group == "code_quality" for item in metrics):
        missing.append("a source-derived code_quality metric")
    decision = SystemImageMaterializationDecision(not missing, len(objects), len(relationships),
        len(metrics), tuple(missing))
    if missing:
        raise InsufficientSystemImageEvidenceError(decision)
    return decision
