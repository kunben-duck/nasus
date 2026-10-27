from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ...domain.system_image.source_access import SourceAccessScope


@dataclass(frozen=True)
class RetrievalSubjectProvenance:
    project_id: str
    subject_ref: str
    source_ids: tuple[str, ...]
    complete: bool


@dataclass(frozen=True)
class AuthorizedRetrievalSubjects:
    project_id: str
    scope_fingerprint: str
    subject_refs: tuple[str, ...]

    @classmethod
    def compile(cls, scope: SourceAccessScope, subjects: Sequence[RetrievalSubjectProvenance]) -> "AuthorizedRetrievalSubjects":
        refs = set()
        for subject in subjects:
            if subject.project_id != scope.project_id:
                raise ValueError("retrieval provenance project mismatch")
            kind, separator, identifier = subject.subject_ref.partition(":")
            if not separator or not identifier or kind not in {"raw_asset", "raw_asset_chunk", "context_object"}:
                raise ValueError("unknown retrieval subject reference")
            if subject.complete and scope.permits_sources(subject.source_ids):
                refs.add(subject.subject_ref)
        return cls(scope.project_id, scope.fingerprint, tuple(sorted(refs)))
