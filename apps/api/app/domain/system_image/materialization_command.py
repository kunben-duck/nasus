"""Original source selection for a canonical materialization, not a work lease."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .image_revision import require_digest
from .source_snapshots import snapshot_digest


class MaterializationCommandConflict(RuntimeError):
    pass


class MaterializationOriginalInputUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class MaterializationCommandInput:
    invocation_id: str
    project_id: str
    actor_id: str
    command_hash: str
    manifest_id: str
    manifest_hash: str

    def __post_init__(self):
        for value in (self.invocation_id, self.project_id, self.actor_id, self.manifest_id):
            if (type(value) is not str or not 0 < len(value) <= 512 or value.strip() != value
                    or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)):
                raise ValueError("Invalid materialization command identity.")
        require_digest(self.command_hash)
        require_digest(self.manifest_hash)

    @property
    def content_hash(self):
        return snapshot_digest({"schema": "nasus.materialization-source-input.v1", **asdict(self)})

    def require_same(self, current):
        if self != current or self.content_hash != current.content_hash:
            raise MaterializationCommandConflict("Original materialization source selection changed.")
