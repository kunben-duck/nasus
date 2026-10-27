"""Reverse source dependencies: immutable root pins, not business impact claims."""
from dataclasses import dataclass
from typing import Optional

from .evidence import valid_digest
from .derivation_impact import DerivationImpactIntegrityError


ROOT_POLICY = "nasus.source-context-roots.v1"
MAX_ROOT_PAGE = 50


@dataclass(frozen=True)
class SourceContextRoot:
    context_id: str
    context_artifact_hash: str
    image_revision_id: str
    image_artifact_hash: str

    def __post_init__(self):
        if (any(type(value) is not str or not 1 <= len(value) <= 128
                for value in (self.context_id, self.image_revision_id))
                or any(type(value) is not str or not valid_digest(value)
                       for value in (self.context_artifact_hash, self.image_artifact_hash))):
            raise DerivationImpactIntegrityError("invalid reverse source dependency pin")


@dataclass(frozen=True)
class SourceContextRootInventory:
    items: tuple[SourceContextRoot, ...]
    total: int
    next_after_id: Optional[str]

    def validate(self, after_id, limit):
        if (type(self.items) is not tuple or any(type(item) is not SourceContextRoot for item in self.items)
                or type(self.total) is not int or self.total < len(self.items)
                or len(self.items) > limit
                or tuple(item.context_id for item in self.items)
                   != tuple(sorted({item.context_id for item in self.items}))
                or any(item.context_id <= after_id for item in self.items)
                or self.next_after_id is not None and (len(self.items) != limit
                    or self.next_after_id != self.items[-1].context_id)
                or not after_id and (len(self.items) != min(self.total, limit)
                    or (self.next_after_id is not None) != (self.total > limit))):
            raise DerivationImpactIntegrityError("invalid reverse source dependency page")
        return self
