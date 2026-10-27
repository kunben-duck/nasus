"""Frozen publication ancestry; registration cannot confer business authority."""
from dataclasses import dataclass
import re

from .publication import PublicationIntegrityError
from .source_snapshots import snapshot_digest


PUBLICATION_PROVENANCE_POLICY = "nasus.publication-provenance.v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_FIELDS_V1 = ("project_id", "kind", "fact_id", "baseline_id", "image_revision_id", "image_artifact_hash",
    "manifest_id", "manifest_hash", "sequence", "metadata_hash", "request_hash", "invocation_id",
    "image_provenance_hash", "relations_provenance_hash", "dependencies")
DEPENDENCY_KINDS = {
    "previous_review": ("review", "review"), "expected_head": ("review", "publication"),
    "approval": ("publication", "review"), "previous_publication": ("publication", "publication"),
    "rollback_source": (None, "publication"),
}


def require_publication_provenance(condition):
    if not condition:
        raise PublicationIntegrityError("Publication provenance failed integrity verification")


@dataclass(frozen=True)
class PublicationProvenanceAnchor:
    project_id: str
    kind: str
    fact_id: str
    baseline_id: str
    image_revision_id: str
    image_artifact_hash: str
    manifest_id: str
    manifest_hash: str
    sequence: int
    metadata_hash: str
    request_hash: str
    invocation_id: str
    image_provenance_hash: str
    relations_provenance_hash: str
    dependencies: tuple[tuple[str, str, str, str], ...]

    def __post_init__(self):
        require_publication_provenance(type(self.kind) is str and self.kind in {"review", "publication"}
            and type(self.sequence) is int and self.sequence > 0
            and type(self.dependencies) is tuple and len(self.dependencies) <= 3
            and all(type(parent) is tuple and len(parent) == 4
                and all(type(value) is str for value in parent) for parent in self.dependencies))
        require_publication_provenance(self.dependencies == tuple(sorted(self.dependencies))
            and len({p[0] for p in self.dependencies}) == len(self.dependencies))
        for key in _FIELDS_V1:
            if key in {"sequence", "dependencies"}:
                continue
            value = getattr(self, key)
            require_publication_provenance(type(value) is str and 0 < len(value) <= 1024
                and (not key.endswith("hash") or _DIGEST.fullmatch(value) is not None))
        for relation, kind, ident, digest in self.dependencies:
            expected = DEPENDENCY_KINDS.get(relation)
            require_publication_provenance(expected is not None and expected[0] in {None, self.kind}
                and kind == expected[1] and type(ident) is str and 0 < len(ident) <= 128
                and type(digest) is str and _DIGEST.fullmatch(digest) is not None
                and (kind, ident) != (self.kind, self.fact_id))

    @property
    def record_v1(self):
        # Pin the formula; future domain or ORM fields must not rewrite history.
        value = {key: getattr(self, key) for key in _FIELDS_V1 if key != "dependencies"}
        value.update(dependencies_hash=snapshot_digest(self.dependencies), dependency_count=len(self.dependencies),
            image_node_key="image_objects:" + self.image_revision_id,
            relations_node_key="image_relations:" + self.image_revision_id,
            review_id=self.fact_id if self.kind == "review" else None,
            publication_id=self.fact_id if self.kind == "publication" else None,
            policy_revision=PUBLICATION_PROVENANCE_POLICY)
        return {**value, "content_hash": snapshot_digest(value)}
