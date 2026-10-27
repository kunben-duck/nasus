from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...domain.system_image.code_alias import CodeObjectAlias


class CodeObjectAliasReadPort(Protocol):
    def find_in_image(self, project_id: str, image_revision_id: str, object_id: str, *,
                      registration_hash: str | None = None) -> tuple[tuple[CodeObjectAlias, str], ...]: ...


@dataclass(frozen=True)
class FrozenCodeObjectIdentity:
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    requested_object_id: str
    frozen_object_id: str
    canonical_object_id: str
    entity_id: str
    entity_revision_id: str
    source_revision_id: str
    alias_registration_hash: str
