from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from collections import Counter
import json

from .evidence import EvidenceLocator, source_lines, text_digest
from .source_snapshots import snapshot_digest


DOCUMENT_SCHEMA = "nasus.source-document.v1"
DOCUMENT_EXTRACTOR = "nasus.explicit-document.v2"
LEGACY_DOCUMENT_EXTRACTORS = frozenset({"nasus.explicit-document.v1", "nasus.explicit-document.v2"})
OPENAPI_DOCUMENT_EXTRACTOR = "nasus.openapi-document.v1"
DOCUMENT_EXTRACTORS = LEGACY_DOCUMENT_EXTRACTORS | {OPENAPI_DOCUMENT_EXTRACTOR}


def validate_document_extractor(version, *, legacy_only=False):
    supported = LEGACY_DOCUMENT_EXTRACTORS if legacy_only else DOCUMENT_EXTRACTORS
    if not isinstance(version, str) or version not in supported:
        raise ValueError("unsupported source document extractor version")
    return version


@dataclass(frozen=True)
class DocumentField:
    name: str
    value: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class DocumentObservation:
    kind: str
    title: str
    external_id: str | None
    relative_path: str
    start_line: int
    end_line: int
    fields: tuple[DocumentField, ...]
    references: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    identity_status: str = "explicit_id"
    extractor_version: str = DOCUMENT_EXTRACTOR

    def __post_init__(self):
        validate_document_extractor(self.extractor_version)
        if self.extractor_version == OPENAPI_DOCUMENT_EXTRACTOR and (
                self.kind not in {"requirement_document", "test_document"}
                or any(field.name != "description" for field in self.fields)
                or self.external_id is not None or self.references or self.identity_status != "source_occurrence"):
            raise ValueError("OpenAPI projections must be supporting document context only")

    @classmethod
    def from_payload(cls, payload):
        """Read the stored version explicitly; never upgrade an archived projection."""
        if payload.get("schema") != DOCUMENT_SCHEMA:
            raise ValueError("invalid source document schema")
        locator = payload["locator"]
        observation = cls(payload["kind"], payload["title"], payload["external_id"],
            locator["relative_path"], locator["start_line"], locator["end_line"],
            tuple(DocumentField(**{key: field[key] for key in ("name", "value", "start_line", "end_line")})
                  for field in payload["fields"]), tuple(payload["references"]), tuple(payload["gaps"]),
            payload["identity_status"], payload["extractor_version"])
        if observation.extractor_version == OPENAPI_DOCUMENT_EXTRACTOR and (
                payload.get("semantic_status") != "source_projection_not_approved_specification"
                or payload.get("reference_semantics") != "references_only_not_asserts_or_implements"
                or any(key in payload for key in ("parent", "authority_status", "approved", "oracle"))):
            raise ValueError("OpenAPI projections cannot carry specification authority")
        return observation

    def payload(self, text: str, file_hash: str) -> dict:
        if self.kind not in {"requirement", "test_case", "test_script", "requirement_document", "test_document"}:
            raise ValueError("invalid source document kind")
        if not self.title or len(self.title) > 500 or len(self.fields) > 90 or len(self.relative_path.encode("utf-8")) > 1024:
            raise ValueError("source document exceeds title or field limit")
        if (self.identity_status not in {"explicit_id", "ambiguous", "source_occurrence"}
                or (self.identity_status != "source_occurrence" and not self.external_id)
                or (self.external_id is not None and len(self.external_id) > 128)
                or len(self.references) > 100 or any(len(value) > 128 for value in self.references)):
            raise ValueError("invalid source document identity or reference limits")
        lines = source_lines(text)
        locator = EvidenceLocator(self.relative_path, self.start_line, self.end_line, "exact")
        if self.end_line > len(lines):
            raise ValueError("document location exceeds archived source")
        fields = []
        for field in self.fields:
            if (field.name not in {"description", "acceptance_criterion", "business_rule", "precondition", "step", "expected_result", "reference"}
                    or not self.start_line <= field.start_line <= field.end_line <= self.end_line
                    or not field.value or len(json.dumps(field.value, ensure_ascii=False).encode("utf-8")) > 32768):
                raise ValueError("invalid document field")
            fields.append({**asdict(field), "snippet_hash": text_digest("".join(lines[field.start_line - 1:field.end_line]))})
        return {"schema": DOCUMENT_SCHEMA, "extractor_version": self.extractor_version,
                "kind": self.kind, "title": self.title, "external_id": self.external_id,
                "identity_status": self.identity_status, "locator": asdict(locator),
                "source_file_hash": file_hash, "snippet_hash": text_digest("".join(lines[self.start_line - 1:self.end_line])),
                "fields": fields, "references": list(self.references), "gaps": list(self.gaps),
                "semantic_status": "source_projection_not_approved_specification",
                "reference_semantics": "references_only_not_asserts_or_implements"}

    @property
    def identity_key(self) -> dict:
        if self.external_id and self.identity_status == "explicit_id":
            return {"schema": DOCUMENT_SCHEMA, "kind": self.kind, "external_id": self.external_id}
        # Anonymous/duplicate IDs never imply a stable cross-file identity.
        return {"schema": DOCUMENT_SCHEMA, "kind": self.kind, "path": self.relative_path,
                "content": snapshot_digest([self.title, [(f.name, f.value) for f in self.fields]]),
                "occurrence": self.start_line, "identity_status": self.identity_status}


def disambiguate_documents(items: tuple[DocumentObservation, ...]) -> tuple[DocumentObservation, ...]:
    counts = Counter((item.kind, item.external_id) for item in items if item.external_id)
    return tuple(replace(item, identity_status="ambiguous", gaps=(*item.gaps, "duplicate_external_id"))
                 if item.external_id and counts[(item.kind, item.external_id)] > 1 else item for item in items)
