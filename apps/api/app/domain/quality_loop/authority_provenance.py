"""Immutable source and predecessor pins, not a new authority decision."""
from dataclasses import asdict, dataclass
import re
from typing import Optional

from .acceptance_specification import AcceptanceIntegrityError, acceptance_digest


AUTHORITY_PROVENANCE_POLICY = "nasus.requirement-authority-provenance.v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PIN_FIELDS_V1 = ("project_id", "kind", "revision_id", "authority_id", "metadata_hash", "artifact_hash",
    "image_revision_id", "image_artifact_hash", "object_id", "binding_id", "source_revision_id",
    "document_revision_id", "basis_digest", "invocation_id", "status", "sequence", "image_provenance_hash",
    "member_provenance_hash", "document_provenance_hash", "previous_revision_id", "previous_registration_hash")


@dataclass(frozen=True)
class AuthorityProvenanceAnchor:
    project_id: str
    kind: str
    revision_id: str
    authority_id: str
    metadata_hash: str
    artifact_hash: str
    image_revision_id: str
    image_artifact_hash: str
    object_id: str
    binding_id: str
    source_revision_id: str
    document_revision_id: str
    basis_digest: str
    invocation_id: str
    status: str
    sequence: int
    image_provenance_hash: str
    member_provenance_hash: str
    document_provenance_hash: str
    previous_revision_id: Optional[str]
    previous_registration_hash: Optional[str]

    def __post_init__(self):
        value = asdict(self)
        if (self.kind not in {"acceptance", "business_rule"} or self.status not in {"approved", "withdrawn"}
                or type(self.sequence) is not int or not 1 <= self.sequence <= 1000
                or (self.sequence == 1) != (self.previous_revision_id is None)
                or (self.previous_revision_id is None) != (self.previous_registration_hash is None)
                or self.previous_revision_id == self.revision_id
                or self.sequence == 1 and self.status != "approved"):
            raise AcceptanceIntegrityError("invalid authority provenance lineage")
        for key, item in value.items():
            if key == "sequence" or item is None and key.startswith("previous_"):
                continue
            if type(item) is not str or not 1 <= len(item) <= 1024:
                raise AcceptanceIntegrityError("invalid authority provenance pin")
            if (key.endswith("hash") or key == "basis_digest") and not _DIGEST.fullmatch(item):
                raise AcceptanceIntegrityError("invalid authority provenance digest")

    @property
    def record_v1(self):
        # Keep the v1 digest independent of any future fields or ORM columns.
        value = {field: getattr(self, field) for field in _PIN_FIELDS_V1}
        value.update(policy_revision=AUTHORITY_PROVENANCE_POLICY,
            image_node_key="image_objects:" + self.image_revision_id,
            member_node_key="member:" + self.image_revision_id + "/" + self.object_id,
            document_node_key="document:" + self.document_revision_id,
            acceptance_revision_id=self.revision_id if self.kind == "acceptance" else None,
            business_rule_revision_id=self.revision_id if self.kind == "business_rule" else None)
        return {**value, "content_hash": acceptance_digest(value)}
