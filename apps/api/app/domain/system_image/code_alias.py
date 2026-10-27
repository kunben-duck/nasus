"""Version-pinned aliases, never redirects to a mutable source head."""
import hashlib
import re
from dataclasses import asdict, dataclass
from uuid import UUID

from .image_revision import ImageRevisionIntegrityError
from .source_snapshots import snapshot_digest


CODE_ALIAS_POLICY = "nasus.code-object-alias.v1"


def canonical_code_object_id(entity_id: str) -> str:
    try:
        valid = type(entity_id) is str and str(UUID(entity_id)) == entity_id
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ImageRevisionIntegrityError("Invalid canonical code identity.")
    return "CODE-" + entity_id


def legacy_code_object_id(project_id: str, source_id: str, node_id: str) -> str:
    digest = hashlib.sha1("|".join((project_id, source_id, node_id)).encode()).hexdigest()[:16].upper()
    return "CTX-" + digest


@dataclass(frozen=True)
class CodeObjectAlias:
    project_id: str
    binding_id: str
    source_revision_id: str
    entity_id: str
    entity_revision_id: str
    legacy_object_id: str
    extraction_digest: str
    provider_node_hash: str
    policy_version: str = CODE_ALIAS_POLICY

    def __post_init__(self):
        for value in (self.project_id, self.binding_id, self.source_revision_id, self.entity_revision_id):
            if type(value) is not str or not 1 <= len(value) <= 256:
                raise ImageRevisionIntegrityError("Invalid code alias scope.")
        canonical_code_object_id(self.entity_id)
        if (self.policy_version != CODE_ALIAS_POLICY
                or type(self.legacy_object_id) is not str or not re.fullmatch(r"CTX-[0-9A-F]{16}", self.legacy_object_id)
                or any(type(value) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                       for value in (self.extraction_digest, self.provider_node_hash))):
            raise ImageRevisionIntegrityError("Invalid code alias registration.")

    @property
    def canonical_object_id(self):
        return canonical_code_object_id(self.entity_id)

    @property
    def content_hash(self):
        return snapshot_digest(asdict(self))


class AmbiguousCodeObjectAlias(ValueError):
    """The requested frozen image cannot uniquely resolve this alias."""
