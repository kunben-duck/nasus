from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from .evidence import valid_digest


@dataclass(frozen=True)
class SourceInventoryEntry:
    path: str
    kind: str
    status: str
    reason: str
    byte_count: int = 0
    content_hash: str | None = None

    def __post_init__(self) -> None:
        path = PurePosixPath(self.path)
        if (not self.path or len(self.path.encode("utf-8")) > 4096 or path.is_absolute()
                or ".." in path.parts or "\\" in self.path or path.as_posix() != self.path
                or any(ord(char) < 32 or ord(char) == 127 for char in self.path)):
            raise ValueError("unsafe source inventory path")
        if self.kind not in {"file", "directory", "symlink", "special", "unknown"}:
            raise ValueError("invalid inventory kind")
        if self.status not in {"included", "enumerated", "excluded", "unsupported", "failed"}:
            raise ValueError("invalid inventory status")
        if not self.reason or len(self.reason) > 80 or not self.reason.replace("_", "").isalnum():
            raise ValueError("inventory requires a reason code, not an OS error message")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ValueError("invalid inventory byte count")
        if self.status == "included":
            if self.kind != "file" or not isinstance(self.content_hash, str) or not valid_digest(self.content_hash):
                raise ValueError("included inventory files require a digest")
        elif self.content_hash is not None or self.byte_count:
            raise ValueError("only captured files have content metadata")
        if self.status == "enumerated" and self.kind != "directory":
            raise ValueError("only directories can be enumerated")
        if self.path == "." and self.kind not in {"directory", "unknown"}:
            raise ValueError("invalid inventory root")


@dataclass(frozen=True)
class SourceInventory:
    entries: tuple[SourceInventoryEntry, ...]
    excluded_names: tuple[str, ...]
    enumeration_complete: bool
    schema_version: str = "nasus.source-inventory.v1"
    stage: str = "acquisition"

    def __post_init__(self) -> None:
        if self.schema_version != "nasus.source-inventory.v1" or self.stage != "acquisition":
            raise ValueError("unsupported source inventory schema")
        if not isinstance(self.entries, tuple) or not isinstance(self.excluded_names, tuple):
            raise ValueError("inventory collections must be immutable")
        if type(self.enumeration_complete) is not bool or not self.entries or len(self.entries) > 50000:
            raise ValueError("invalid inventory bounds")
        paths = [entry.path for entry in self.entries]
        if paths != sorted(set(paths)):
            raise ValueError("inventory paths must be unique and sorted")
        if self.enumeration_complete and any(
            entry.status == "failed" and entry.kind in {"directory", "unknown"} for entry in self.entries
        ):
            raise ValueError("failed traversal cannot prove complete enumeration")
        if sum(len(path.encode("utf-8")) + 512 for path in paths) > 8 * 1024 * 1024:
            raise ValueError("inventory exceeds metadata byte limit")
        if tuple(sorted(set(self.excluded_names))) != self.excluded_names:
            raise ValueError("inventory exclusions must be unique and sorted")
        if any(not name or name in {".", ".."} or "/" in name or "\\" in name for name in self.excluded_names):
            raise ValueError("invalid inventory exclusion")

    @property
    def complete(self) -> bool:
        return self.enumeration_complete and self.file_count > 0 and not any(
            entry.status in {"failed", "unsupported"} for entry in self.entries
        )

    @property
    def file_count(self) -> int:
        return sum(entry.status == "included" for entry in self.entries)

    @property
    def byte_count(self) -> int:
        return sum(entry.byte_count for entry in self.entries)

    def to_payload(self) -> dict:
        return {**asdict(self), "entries": [asdict(entry) for entry in self.entries],
                "excluded_names": list(self.excluded_names)}

    @classmethod
    def from_payload(cls, payload: dict) -> SourceInventory:
        if not isinstance(payload, dict) or set(payload) != {
            "entries", "excluded_names", "enumeration_complete", "schema_version", "stage",
        }:
            raise ValueError("invalid inventory payload")
        if not isinstance(payload["entries"], list) or not isinstance(payload["excluded_names"], list):
            raise ValueError("invalid inventory collections")
        try:
            return cls(**{**payload, "entries": tuple(SourceInventoryEntry(**item) for item in payload["entries"]),
                          "excluded_names": tuple(payload["excluded_names"])})
        except (TypeError, AttributeError, UnicodeError) as exc:
            raise ValueError("invalid inventory entry") from exc


@dataclass(frozen=True)
class SourceInventoryArtifact:
    project_id: str
    source_id: str
    report_hash: str
    report_ref: str
    status: str
    enumeration_complete: bool
    file_count: int
    byte_count: int
    entry_count: int

    def __post_init__(self) -> None:
        if not self.project_id or not self.source_id or not self.report_ref or not valid_digest(self.report_hash):
            raise ValueError("inventory artifact requires scope and durable digest")
        if self.status not in {"complete", "failed"} or type(self.enumeration_complete) is not bool:
            raise ValueError("invalid inventory outcome")
        if any(type(count) is not int or count < 0 for count in (self.file_count, self.byte_count, self.entry_count)):
            raise ValueError("invalid inventory counters")
        if not 1 <= self.entry_count <= 50000 or self.file_count > self.entry_count:
            raise ValueError("invalid inventory entry count")
        if self.status == "complete" and (not self.enumeration_complete or not self.file_count):
            raise ValueError("incomplete scan cannot prove acquisition completeness")
