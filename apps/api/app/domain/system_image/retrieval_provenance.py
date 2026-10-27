"""Versioned dependency receipts, not retrieval relevance or execution authority."""
import re

from .image_revision import ImageRevisionIntegrityError
from .source_snapshots import snapshot_digest


RETRIEVAL_PROVENANCE_POLICY = "nasus.retrieval-provenance.v1"
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")


def require_retrieval_provenance(condition):
    if not condition:
        raise ImageRevisionIntegrityError("Retrieval provenance failed integrity verification")


def retrieval_registration(*, project_id, kind, artifact_id, metadata_hash, publication_pin,
                           publication_registration_hash, parent=None, documents=()):
    require = require_retrieval_provenance
    require(type(kind) is str and kind in {"reservation", "generation", "retrieval"} and type(documents) is tuple
        and len(documents) <= 4096 and all(type(item) is tuple and len(item) == 3
            and all(type(value) is str for value in item) for item in documents))
    require(type(publication_pin) is dict and {"baseline_id", "publication_id", "image_revision_id",
        "image_artifact_hash"}.issubset(publication_pin))
    require(all(0 < len(item[0]) <= 128 for item in documents))
    require(documents == tuple(sorted(documents)) and len({item[0] for item in documents}) == len(documents)
        and (bool(documents) if kind == "generation" else not documents))
    require(parent is None if kind == "reservation" else type(parent) is tuple and len(parent) == 3)
    if parent is not None:
        require(parent[0] == ("reservation" if kind == "generation" else "generation"))
    value = dict(project_id=project_id, kind=kind, artifact_id=artifact_id, metadata_hash=metadata_hash,
        baseline_id=publication_pin["baseline_id"], publication_id=publication_pin["publication_id"],
        image_revision_id=publication_pin["image_revision_id"], image_artifact_hash=publication_pin["image_artifact_hash"],
        publication_kind="publication", publication_registration_hash=publication_registration_hash,
        parent_kind=parent[0] if parent else None, parent_id=parent[1] if parent else None,
        parent_hash=parent[2] if parent else None, documents_hash=snapshot_digest(documents), document_count=len(documents),
        reservation_id=artifact_id if kind == "reservation" else None,
        generation_id=artifact_id if kind == "generation" else None,
        retrieval_id=artifact_id if kind == "retrieval" else None, policy_revision=RETRIEVAL_PROVENANCE_POLICY)
    for key in ("project_id", "artifact_id", "baseline_id", "publication_id", "image_revision_id"):
        require(type(value[key]) is str and 0 < len(value[key]) <= 128)
    for digest in (metadata_hash, publication_registration_hash, value["image_artifact_hash"],
                   *((parent[2],) if parent else ()), *(d for item in documents for d in item[1:])):
        require(type(digest) is str and _HASH.fullmatch(digest) is not None)
    if parent:
        require(type(parent[1]) is str and 0 < len(parent[1]) <= 128)
    return {**value, "content_hash": snapshot_digest(value)}
