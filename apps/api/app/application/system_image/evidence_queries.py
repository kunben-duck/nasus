from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Optional, Protocol

from ...domain.system_image.evidence import (
    DECODER_VERSION, EvidenceIntegrityError, EvidenceLocationUnavailable, EvidenceLocator,
    EvidencePageTooLarge, SourceEvidence, source_lines, text_digest,
)
from .source_access import SourceBindingAuthorizationPort


@dataclass(frozen=True)
class EvidenceReadTarget:
    evidence: SourceEvidence
    source_id: str
    manifest_ref: str
    manifest_hash: str
    source_content_hash: str


@dataclass(frozen=True)
class EvidenceSummary:
    evidence_id: str
    source_revision_id: str
    binding_id: str
    locator: EvidenceLocator
    file_hash: str
    snippet_hash: Optional[str]
    decoder_version: str
    captured_at: str

    @classmethod
    def from_evidence(cls, evidence: SourceEvidence) -> "EvidenceSummary":
        return cls(evidence.evidence_id, evidence.source_revision_id, evidence.binding_id,
                   evidence.locator, evidence.file_hash, evidence.snippet_hash,
                   evidence.decoder_version, evidence.captured_at)


@dataclass(frozen=True)
class EvidencePage:
    evidence: EvidenceSummary
    content: str
    start_line: int
    end_line: int
    next_start_line: Optional[int]
    excerpt_hash: str
    integrity: str = "verified"


class EvidenceRepositoryPort(Protocol):
    def get(self, project_id: str, evidence_id: str) -> EvidenceReadTarget: ...

    def get_many(self, project_id: str, evidence_ids: tuple[str, ...]) -> list[EvidenceReadTarget]: ...

    def list_for_alias(
        self, project_id: str, source_revision_id: str, object_id: str, *, entity_revision_id: str | None = None,
    ) -> list[SourceEvidence]: ...


class EvidenceSourceReaderPort(Protocol):
    def read(self, target: EvidenceReadTarget) -> bytes: ...


class EvidenceAuthorizationPort(Protocol):
    def require_project_access(self, project_id: str) -> object: ...


class EvidenceQueryApplicationService:
    def __init__(
        self, repository: EvidenceRepositoryPort, reader: EvidenceSourceReaderPort,
        authorization: EvidenceAuthorizationPort,
        source_authorization: SourceBindingAuthorizationPort,
    ) -> None:
        self.repository = repository
        self.reader = reader
        self.authorization = authorization
        self.source_authorization = source_authorization

    def verified_read_session(self):
        session = getattr(self.reader, "verified_read_session", None)
        return session() if session else nullcontext()

    def require_binding_access(self, project_id: str, binding_id: str) -> None:
        # This port checks membership and source policy in one live MVCC read.
        self.source_authorization.require_binding_access(project_id, binding_id)

    def require_revision_access(self, project_id: str, source_revision_id: str) -> None:
        self.authorization.require_project_access(project_id)
        self.source_authorization.require_revision_access(project_id, source_revision_id)

    def list_for_alias(self, project_id: str, source_revision_id: str, object_id: str, *,
                       entity_revision_id: str | None = None) -> list[EvidenceSummary]:
        self.require_revision_access(project_id, source_revision_id)
        result = self.repository.list_for_alias(project_id, source_revision_id, object_id, entity_revision_id=entity_revision_id)
        if any(item.project_id != project_id or item.source_revision_id != source_revision_id for item in result):
            raise KeyError("evidence not found")
        for binding_id in {item.binding_id for item in result}:
            self.require_binding_access(project_id, binding_id)
        self.require_revision_access(project_id, source_revision_id)
        return [EvidenceSummary.from_evidence(item) for item in result]

    def read(
        self, project_id: str, evidence_id: str, *, start_line: int | None = None, max_lines: int = 100,
        source_revision_id: str | None = None,
    ) -> EvidencePage:
        self.authorization.require_project_access(project_id)
        target = self.repository.get(project_id, evidence_id)
        evidence = target.evidence
        if evidence.project_id != project_id or evidence.evidence_id != evidence_id:
            raise KeyError("evidence not found")
        if source_revision_id is not None and evidence.source_revision_id != source_revision_id:
            raise KeyError("evidence not found at the requested source revision")
        self.require_binding_access(project_id, evidence.binding_id)
        if evidence.locator.precision != "exact":
            raise EvidenceLocationUnavailable("evidence has no exact source location")
        if type(max_lines) is not int or not 1 <= max_lines <= 200:
            raise ValueError("max_lines must be between 1 and 200")
        start = evidence.locator.start_line if start_line is None else start_line
        if type(start) is not int or not evidence.locator.start_line <= start <= evidence.locator.end_line:
            raise ValueError("requested line is outside the evidence range")
        if evidence.decoder_version != DECODER_VERSION:
            raise EvidenceIntegrityError("unsupported evidence decoder")
        lines = self._verified_lines(target)
        end = min(start + max_lines - 1, evidence.locator.end_line)
        content = "".join(lines[start - 1:end])
        # Bound responses without silently splitting UTF-8 or a source line.
        if len(content.encode("utf-8")) > 65536:
            raise EvidencePageTooLarge("evidence page exceeds 64 KiB; request fewer lines")
        # Membership can be revoked while remote object storage is being read.
        self.require_binding_access(project_id, evidence.binding_id)
        return EvidencePage(EvidenceSummary.from_evidence(evidence), content, start, end,
                            end + 1 if end < evidence.locator.end_line else None, text_digest(content))

    def verify_many(self, project_id: str, selection: tuple[tuple[str, str], ...]) -> list[EvidenceSummary]:
        """Verify bounded source/revision pins without exposing any source text."""
        if not 1 <= len(selection) <= 512 or len(set(selection)) != len(selection):
            raise ValueError("invalid evidence verification selection")
        self.authorization.require_project_access(project_id)
        targets = self.repository.get_many(project_id, tuple(eid for _, eid in selection))
        if (len(targets) != len(selection) or
                {(t.evidence.source_revision_id, t.evidence.evidence_id) for t in targets} != set(selection) or
                any(t.evidence.project_id != project_id for t in targets)):
            raise KeyError("evidence verification scope mismatch")
        bindings = {t.evidence.binding_id for t in targets}
        def authorize():
            for binding_id in bindings:
                self.require_binding_access(project_id, binding_id)
        authorize()
        files = {}
        for target in targets:
            evidence = target.evidence
            if evidence.locator.precision != "exact":
                raise EvidenceLocationUnavailable("evidence has no exact source location")
            if evidence.decoder_version != DECODER_VERSION:
                raise EvidenceIntegrityError("unsupported evidence decoder")
            # Only the same immutable file and complete archive scope may share
            # bytes. Evidence spans remain independently verified below.
            key = (evidence.project_id, evidence.binding_id, evidence.source_revision_id,
                   evidence.locator.relative_path, evidence.file_hash, evidence.object_ref,
                   evidence.decoder_version, target.source_id, target.manifest_ref,
                   target.manifest_hash, target.source_content_hash)
            files.setdefault(key, []).append(target)
        with self.verified_read_session():
            for group in files.values():
                self.require_binding_access(project_id, group[0].evidence.binding_id)
                lines = self._verified_file_lines(group[0])
                for target in group:
                    self._verify_span(target.evidence, lines)
                self.require_binding_access(project_id, group[0].evidence.binding_id)
        authorize()
        return [EvidenceSummary.from_evidence(target.evidence) for target in targets]

    def _verified_lines(self, target: EvidenceReadTarget):
        lines = self._verified_file_lines(target)
        self._verify_span(target.evidence, lines)
        return lines

    def _verified_file_lines(self, target: EvidenceReadTarget):
        evidence = target.evidence
        if evidence.decoder_version != DECODER_VERSION:
            raise EvidenceIntegrityError("unsupported evidence decoder")
        body = self.reader.read(target)
        if "sha256:" + hashlib.sha256(body).hexdigest() != evidence.file_hash:
            raise EvidenceIntegrityError("evidence raw file digest mismatch")
        return source_lines(body.decode("utf-8", errors="replace"))

    @staticmethod
    def _verify_span(evidence: SourceEvidence, lines: list[str]) -> None:
        if evidence.locator.end_line > len(lines):
            raise EvidenceIntegrityError("evidence range exceeds archived file")
        whole = "".join(lines[evidence.locator.start_line - 1:evidence.locator.end_line])
        if text_digest(whole) != evidence.snippet_hash:
            raise EvidenceIntegrityError("evidence snippet digest mismatch")
