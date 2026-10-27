from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from .source_snapshots import snapshot_digest


@dataclass(frozen=True)
class CodeSymbolKey:
    """A matching key within one source binding, never a Nasus entity ID.

    Moves/renames require a separate lineage decision. Provider names, node IDs,
    checkout paths, line numbers and source revisions must not enter this key.
    """

    relative_path: str
    language: str
    kind: str
    scope: tuple[str, ...]
    name: str
    signature: tuple[str, ...] = ()
    schema_version: str = "nasus.code-symbol.v1"

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if (
            not path.parts or path.is_absolute() or ".." in path.parts
            or "\\" in self.relative_path or str(path) != self.relative_path
            or any(ord(char) < 32 for char in self.relative_path)
            or not self.name or not self.language or not self.kind
        ):
            raise ValueError("invalid canonical code symbol key")

    @property
    def fingerprint(self) -> str:
        return snapshot_digest(asdict(self))

    @property
    def scope_segment(self) -> str:
        # An enclosing overload is part of a nested declaration's scope.
        return json.dumps([self.kind, self.name, self.signature], separators=(",", ":"))
