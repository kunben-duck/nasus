from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import re

from .document_projection import DOCUMENT_EXTRACTOR, DocumentObservation
from .evidence import text_digest, source_lines
from .source_snapshots import snapshot_digest


COMPONENT_SCHEMA = "nasus.source-document-component.v1"
COMPONENT_KINDS = frozenset({"acceptance_criterion", "business_rule"})
_ITEM = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
_ID = re.compile(r"^(AC|BR|RULE)-([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\s*[:\uff1a]\s*|\s+|$)", re.I)


def component_identifier(kind: str, text: str):
    if "\n" in text:
        return None
    value = _ITEM.sub("", text.strip())
    match = _ID.match(value)
    if kind in COMPONENT_KINDS and match and ((match[1].upper() == "AC") == (kind == "acceptance_criterion")):
        identifier = f"{match[1]}-{match[2]}".upper()
        if len(identifier) > 128:
            raise ValueError("source component identifier exceeds limit")
        return identifier
    return None


@dataclass(frozen=True)
class DocumentComponent:
    parent: DocumentObservation
    field_indices: tuple[int, ...]
    external_id: str | None
    identity_status: str
    gaps: tuple[str, ...] = ()

    @property
    def kind(self):
        return self.parent.fields[self.field_indices[0]].name

    @property
    def identity_key(self):
        base = {"schema": COMPONENT_SCHEMA, "kind": self.kind,
                "parent_identity_hash": snapshot_digest(self.parent.identity_key)}
        if self.external_id and self.identity_status == "explicit_id":
            return {**base, "external_id": self.external_id}
        return {**base, "identity_status": self.identity_status, "path": self.parent.relative_path,
                "occurrence": self.parent.fields[self.field_indices[0]].start_line,
                "content": snapshot_digest([self.parent.fields[i].value for i in self.field_indices])}

    def payload(self, parent_payload):
        if (self.parent.kind != "requirement" or not self.field_indices
                or tuple(sorted(set(self.field_indices))) != self.field_indices
                or any(type(i) is not int or not 0 <= i < len(self.parent.fields) for i in self.field_indices)
                or self.kind not in COMPONENT_KINDS
                or any(self.parent.fields[i].name != self.kind for i in self.field_indices)):
            raise ValueError("invalid source document component")
        fields = [parent_payload["fields"][i] for i in self.field_indices]
        first, last = fields[0], fields[-1]
        return {"schema": COMPONENT_SCHEMA, "extractor_version": DOCUMENT_EXTRACTOR,
                "kind": self.kind, "external_id": self.external_id, "identity_status": self.identity_status,
                "title": f"{self.parent.external_id} / {first['value']}"[:500],
                "locator": {**parent_payload["locator"], "start_line": first["start_line"], "end_line": last["end_line"]},
                "source_file_hash": parent_payload["source_file_hash"],
                "fields": fields, "references": [], "gaps": list(self.gaps),
                "parent": {"identity_hash": snapshot_digest(self.parent.identity_key),
                           "payload_hash": snapshot_digest(parent_payload), "external_id": self.parent.external_id,
                           "field_indices": list(self.field_indices), "relation": "source_contains"},
                "semantic_status": "source_projection_not_approved_specification",
                "authority_status": "pending_confirmation",
                "reference_semantics": "references_only_not_asserts_or_implements"}


def requirement_components(parent: DocumentObservation) -> tuple[DocumentComponent, ...]:
    if parent.kind != "requirement":
        return ()
    groups = []
    for index, field in enumerate(parent.fields):
        if field.name not in COMPONENT_KINDS:
            continue
        identifier = component_identifier(field.name, field.value)
        previous = parent.fields[groups[-1][-1]] if groups else None
        starts_item = identifier is not None or bool(_ITEM.match(field.value.strip()))
        if (previous is None or starts_item or previous.name != field.name or groups[-1][-1] != index - 1
                or previous.end_line + 1 != field.start_line):
            groups.append([index])
        else:
            groups[-1].append(index)
    result = []
    for indices in groups:
        field = parent.fields[indices[0]]
        identifier = component_identifier(field.name, field.value)
        status = "explicit_id" if identifier and parent.identity_status == "explicit_id" else "source_occurrence"
        gaps = [] if identifier else ["no_explicit_component_identity"]
        if parent.identity_status != "explicit_id":
            gaps.append("parent_identity_not_unique")
        if any("\n" in parent.fields[i].value for i in indices):
            gaps.append("compound_source_field_not_decomposed")
        result.append(DocumentComponent(parent, tuple(indices), identifier, status, tuple(gaps)))
    counts = Counter((item.kind, item.external_id) for item in result if item.external_id)
    return tuple(replace(item, identity_status="ambiguous", gaps=(*item.gaps, "duplicate_component_id"))
                 if item.external_id and counts[(item.kind, item.external_id)] > 1 else item for item in result)


def component_payloads(parent, parent_payload, text):
    lines = source_lines(text)
    for component in requirement_components(parent):
        payload = component.payload(parent_payload)
        locator = payload["locator"]
        payload["snippet_hash"] = text_digest("".join(lines[locator["start_line"] - 1:locator["end_line"]]))
        for key in ("project_id", "source_id", "source_manifest_hash"):
            payload[key] = parent_payload[key]
        yield component.identity_key, payload


def validate_component_payload(payload, parent_payload, parent_identity_hash):
    """Rebuild the projection from its exact parent; never accept caller-made semantics."""
    from .document_projection import DOCUMENT_SCHEMA, DocumentField
    if parent_payload.get("schema") != DOCUMENT_SCHEMA or parent_payload.get("kind") != "requirement":
        raise ValueError("component parent must be an evidenced requirement")
    locator = parent_payload["locator"]
    parent = DocumentObservation(parent_payload["kind"], parent_payload["title"], parent_payload["external_id"],
        locator["relative_path"], locator["start_line"], locator["end_line"],
        tuple(DocumentField(**{k: field[k] for k in ("name", "value", "start_line", "end_line")})
              for field in parent_payload["fields"]), tuple(parent_payload["references"]),
        tuple(parent_payload["gaps"]), parent_payload["identity_status"])
    if snapshot_digest(parent.identity_key) != parent_identity_hash:
        raise ValueError("component parent identity mismatch")
    candidates = [item for item in requirement_components(parent)
                  if list(item.field_indices) == payload.get("parent", {}).get("field_indices")]
    if len(candidates) != 1:
        raise ValueError("component is not an exact parent field group")
    expected = candidates[0].payload(parent_payload)
    expected.update({key: parent_payload[key] for key in ("project_id", "source_id", "source_manifest_hash")})
    # The span hash is verified against archived bytes by source evidence reads.
    expected["snippet_hash"] = payload.get("snippet_hash")
    if snapshot_digest(expected) != snapshot_digest(payload):
        raise ValueError("component scope or source projection mismatch")
    return candidates[0].identity_key
