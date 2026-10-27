from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from typing import Protocol

from ...domain.system_image.document_projection import DOCUMENT_SCHEMA
from ...domain.system_image.document_components import COMPONENT_SCHEMA, validate_component_payload
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.evidence import EvidenceIntegrityError, EvidencePageTooLarge
from .source_access import SourceScopeAuthorizationPort


@dataclass(frozen=True)
class SourceDocumentPage:
    document: dict
    payload_hash: str
    projection: dict
    fields: tuple[dict, ...]
    total_fields: int
    next_offset: Optional[int]
    evidence: tuple[dict, ...]


class DocumentReadRepositoryPort(Protocol):
    def list(self, project_id, source_revision_id, *, binding_ids, after_id, limit) -> list[dict]: ...
    def get(self, project_id, document_revision_id, *, binding_ids) -> tuple[dict, str, str, list[dict]]: ...
    def list_extractions(self, project_id, source_revision_id, *, binding_ids, after_id, limit) -> list[dict]: ...
    def get_extraction(self, project_id, extraction_id, *, binding_ids) -> tuple[dict, str, str]: ...


class DocumentArtifactReadPort(Protocol):
    def read(self, project_id, ref, digest) -> dict: ...


class DocumentQueryApplicationService:
    def __init__(self, repository: DocumentReadRepositoryPort, artifacts: DocumentArtifactReadPort,
                 authorization: SourceScopeAuthorizationPort):
        self.repository, self.artifacts, self.authorization = repository, artifacts, authorization

    def list(self, project_id, source_revision_id, *, after_id="", limit=20):
        if type(limit) is not int or not 1 <= limit <= 100 or len(after_id) > 64:
            raise ValueError("invalid document page")
        scope = self.authorization.scope(project_id)
        rows = self.repository.list(project_id, source_revision_id, binding_ids=scope.binding_ids, after_id=after_id, limit=limit + 1)
        result = {"items": rows[:limit], "next_after_id": rows[limit - 1]["document_revision_id"] if len(rows) > limit else None}
        self._size(result)
        self.authorization.require_current(scope)
        return result

    def read(self, project_id, document_revision_id, *, offset=0, limit=20):
        if type(offset) is not int or not 0 <= offset <= 90 or type(limit) is not int or not 1 <= limit <= 90:
            raise ValueError("invalid document field page")
        scope = self.authorization.scope(project_id)
        header, ref, digest, evidence = self.repository.get(project_id, document_revision_id, binding_ids=scope.binding_ids)
        self.authorization.require_current(scope)
        try:
            payload = self.artifacts.read(project_id, ref, digest)
        except (ValueError, OSError) as exc:
            raise EvidenceIntegrityError("source document artifact is unavailable or invalid") from exc
        if (payload.get("schema") not in {DOCUMENT_SCHEMA, COMPONENT_SCHEMA} or payload.get("project_id") != project_id
                or snapshot_digest(payload) != digest
                or payload.get("source_manifest_hash") != header["source_manifest_hash"]
                or payload.get("title") != header["title"] or payload.get("kind") != header["kind"]):
            raise EvidenceIntegrityError("source document scope mismatch")
        if payload["schema"] == COMPONENT_SCHEMA:
            try:
                parent_header, parent_ref, parent_hash, _ = self.repository.get(project_id,
                    header["parent_document_revision_id"], binding_ids=scope.binding_ids)
                self.authorization.require_current(scope)
                parent = self.artifacts.read(project_id, parent_ref, parent_hash)
                if (parent_hash != payload["parent"]["payload_hash"] or snapshot_digest(parent) != parent_hash
                        or any(parent_header[k] != header[k] for k in ("project_id", "binding_id", "source_revision_id", "source_manifest_hash"))
                        or parent_header["kind"] != parent.get("kind") or parent_header["title"] != parent.get("title")):
                    raise ValueError("component parent revision mismatch")
                validate_component_payload(payload, parent, payload["parent"]["identity_hash"])
                spans = {(f["start_line"], f["end_line"], f["snippet_hash"]) for f in payload["fields"]}
                spans.add((payload["locator"]["start_line"], payload["locator"]["end_line"], payload["snippet_hash"]))
                if not spans <= {(e["start_line"], e["end_line"], e["snippet_hash"]) for e in evidence}:
                    raise ValueError("component evidence membership mismatch")
            except (KeyError, TypeError, ValueError, OSError) as exc:
                raise EvidenceIntegrityError("source component parent could not be verified") from exc
        fields = payload["fields"]
        if offset > len(fields):
            raise ValueError("document field offset is out of bounds")
        end = min(len(fields), offset + limit)
        while True:
            spans = {(item["start_line"], item["end_line"], item["snippet_hash"]) for item in fields[offset:end]}
            spans.add((payload["locator"]["start_line"], payload["locator"]["end_line"], payload["snippet_hash"]))
            page_evidence = [item for item in evidence if (item["start_line"], item["end_line"], item["snippet_hash"]) in spans]
            result = {"document": header, "payload_hash": digest,
                      "projection": {key: value for key, value in payload.items() if key not in {"fields", "source_id"}},
                      "fields": fields[offset:end], "total_fields": len(fields), "next_offset": end if end < len(fields) else None,
                      "evidence": page_evidence}
            try:
                self._size(result)
                break
            except EvidencePageTooLarge:
                if end <= offset + 1:
                    raise
                # Keep complete fields; the cursor carries the remainder, not truncated text.
                end -= 1
        self.authorization.require_current(scope)
        return result

    def list_extractions(self, project_id, source_revision_id, *, after_id="", limit=20):
        if type(limit) is not int or not 1 <= limit <= 100 or len(after_id) > 64:
            raise ValueError("invalid extraction page")
        scope = self.authorization.scope(project_id)
        rows = self.repository.list_extractions(project_id, source_revision_id, binding_ids=scope.binding_ids,
                                               after_id=after_id, limit=limit + 1)
        result = {"items": rows[:limit], "next_after_id": rows[limit - 1]["extraction_id"] if len(rows) > limit else None}
        self._size(result)
        self.authorization.require_current(scope)
        return result

    def read_extraction(self, project_id, extraction_id, *, offset=0, limit=20):
        if type(offset) is not int or not 0 <= offset <= 5000 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid extraction file page")
        scope = self.authorization.scope(project_id)
        header, ref, digest = self.repository.get_extraction(project_id, extraction_id, binding_ids=scope.binding_ids)
        self.authorization.require_current(scope)
        try:
            payload = self.artifacts.read(project_id, ref, digest)
        except (ValueError, OSError) as exc:
            raise EvidenceIntegrityError("document extraction artifact could not be verified") from exc
        if (snapshot_digest(payload) != digest or payload.get("schema") != "nasus.source-document-extraction.v1"
                or payload.get("source_manifest_hash") != header["source_manifest_hash"]
                or payload.get("summary") != header["summary"]):
            raise EvidenceIntegrityError("document extraction scope mismatch")
        files = payload["files"]
        if offset > len(files):
            raise ValueError("extraction offset outside report")
        end = min(offset + limit, len(files))
        result = {"extraction": header, "files": files[offset:end], "total_files": len(files),
                  "next_offset": end if end < len(files) else None, "report_hash": digest}
        self._size(result)
        self.authorization.require_current(scope)
        return result

    @staticmethod
    def _size(payload):
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 65536:
            raise EvidencePageTooLarge("request fewer source document fields")
