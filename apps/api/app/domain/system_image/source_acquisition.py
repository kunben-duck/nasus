"""Immutable admission pins; an intent is neither a lease nor source authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .source_snapshots import snapshot_digest


class SourceAcquisitionIntentConflict(RuntimeError):
    pass


def _identity(value):
    return (type(value) is str and 0 < len(value) <= 512 and value.strip() == value
        and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value))


def _digest(value):
    return (type(value) is str and len(value) == 71 and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:]))


@dataclass(frozen=True)
class AcquisitionSourcePin:
    source_id: str
    binding_id: str
    identity_hash: str

    def __post_init__(self):
        if not all(_identity(value) for value in (self.source_id, self.binding_id)) or not _digest(self.identity_hash):
            raise ValueError("Invalid acquisition source pin.")


@dataclass(frozen=True)
class SourceAcquisitionIntent:
    invocation_id: str
    project_id: str
    actor_id: str
    command_hash: str
    selection_mode: str
    sources: tuple[AcquisitionSourcePin, ...]
    origin_manifest_id: str | None
    origin_manifest_hash: str | None

    def __post_init__(self):
        if (not all(_identity(value) for value in (self.invocation_id, self.project_id, self.actor_id))
                or not _digest(self.command_hash) or self.selection_mode not in {"selected", "whole_project"}
                or type(self.sources) is not tuple or not 1 <= len(self.sources) <= 1000
                or not all(type(item) is AcquisitionSourcePin for item in self.sources)
                or len({item.source_id for item in self.sources}) != len(self.sources)
                or len({item.binding_id for item in self.sources}) != len(self.sources)
                or self.sources != tuple(sorted(self.sources, key=lambda item: item.source_id))):
            raise ValueError("Invalid acquisition intent.")
        if (self.origin_manifest_id is None) != (self.origin_manifest_hash is None):
            raise ValueError("Incomplete acquisition origin manifest.")
        if self.origin_manifest_id is not None and (
                not _identity(self.origin_manifest_id) or not _digest(self.origin_manifest_hash)):
            raise ValueError("Invalid acquisition origin manifest.")
        if self.selection_mode == "selected" and (self.origin_manifest_id is None or len(self.sources) > 100):
            raise ValueError("Selected acquisition requires its original manifest.")

    @property
    def content_hash(self):
        return snapshot_digest({"schema": "nasus.source-acquisition-intent.v1", **asdict(self)})

    def require_same(self, current: SourceAcquisitionIntent):
        if self != current or self.content_hash != current.content_hash:
            raise SourceAcquisitionIntentConflict("Original acquisition pins changed; submit a separately authorized command.")
