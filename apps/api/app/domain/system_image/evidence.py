from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, Optional


DECODER_VERSION = "nasus.utf8-replace-lf.v1"


def source_lines(text: str) -> list[str]:
    # Parser row offsets count LF, not Unicode separators inside string literals.
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + [parts[-1]]


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_digest(value: str) -> bool:
    return bool(re.fullmatch(r"sha256:[0-9a-f]{64}", value))


@dataclass(frozen=True)
class EvidenceLocator:
    relative_path: str
    start_line: int
    end_line: int
    precision: Literal["exact", "approximate"]

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if (not path.parts or path.is_absolute() or ".." in path.parts
                or "\\" in self.relative_path or str(path) != self.relative_path
                or any(ord(char) < 32 for char in self.relative_path)):
            raise ValueError("invalid evidence path")
        if (type(self.start_line) is not int or type(self.end_line) is not int
                or not 1 <= self.start_line <= self.end_line
                or self.precision not in {"exact", "approximate"}):
            raise ValueError("invalid evidence range")


@dataclass(frozen=True)
class SourceEvidence:
    evidence_id: str
    project_id: str
    binding_id: str
    source_revision_id: str
    locator: EvidenceLocator
    file_hash: str
    snippet_hash: Optional[str]
    object_ref: str
    decoder_version: str
    extractor_version: str
    captured_at: str

    def __post_init__(self) -> None:
        if not valid_digest(self.file_hash):
            raise ValueError("invalid evidence file digest")
        if self.locator.precision == "exact":
            if self.snippet_hash is None or not valid_digest(self.snippet_hash):
                raise ValueError("exact evidence requires a snippet digest")
        elif self.snippet_hash is not None:
            raise ValueError("approximate evidence cannot claim an exact snippet")


class EvidenceIntegrityError(RuntimeError):
    pass


class EvidenceLocationUnavailable(ValueError):
    pass


class EvidencePageTooLarge(ValueError):
    pass


class EvidenceUnavailableError(RuntimeError):
    pass
