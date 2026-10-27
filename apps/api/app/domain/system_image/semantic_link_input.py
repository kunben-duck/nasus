from __future__ import annotations

from dataclasses import asdict, dataclass
import json

from .evidence import DECODER_VERSION, EvidenceLocator, text_digest
from .image_revision import require_digest
from .source_snapshots import snapshot_digest


SEMANTIC_LINK_METHOD = "nasus.semantic-link-judgment.v1"
SEMANTIC_INPUT_SCHEMA = "nasus.semantic-link-input.v1"
MAX_INPUT_BYTES = 256 * 1024


def require_identifier(value: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid semantic input identifier")


@dataclass(frozen=True)
class SemanticEndpoint:
    object_id: str
    revision_id: str
    source_revision_id: str
    kind: str
    content_hash: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self):
        for value in (self.object_id, self.revision_id, self.source_revision_id):
            require_identifier(value)
        require_digest(self.content_hash)
        if self.kind not in {"code_entity", "acceptance_criterion", "business_rule", "test_case"}:
            raise ValueError("unsupported semantic endpoint kind")
        if (type(self.evidence_ids) is not tuple or not 1 <= len(self.evidence_ids) <= 100
                or len(set(self.evidence_ids)) != len(self.evidence_ids)):
            raise ValueError("invalid semantic endpoint evidence")
        for value in self.evidence_ids:
            require_identifier(value)


@dataclass(frozen=True)
class GroundedExcerpt:
    object_id: str
    revision_id: str
    source_revision_id: str
    evidence_id: str
    binding_id: str
    relative_path: str
    start_line: int
    end_line: int
    file_hash: str
    snippet_hash: str
    raw_text: str
    text: str
    basis: str
    role: str
    field_index: int | None
    decoder_version: str = DECODER_VERSION

    def __post_init__(self):
        for value in (self.object_id, self.revision_id, self.source_revision_id, self.evidence_id, self.binding_id):
            require_identifier(value)
        EvidenceLocator(self.relative_path, self.start_line, self.end_line, "exact")
        for digest in (self.file_hash, self.snippet_hash):
            require_digest(digest)
        for value in (self.raw_text, self.text):
            if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 65536:
                raise ValueError("invalid or oversized semantic excerpt")
        if self.decoder_version != DECODER_VERSION or text_digest(self.raw_text) != self.snippet_hash:
            raise ValueError("semantic excerpt does not match source digest")
        if self.basis == "source_excerpt":
            if self.role != "implementation" or self.field_index is not None or self.text != self.raw_text:
                raise ValueError("code quotation must use original source text")
        elif self.basis == "projected_field":
            if (self.role not in {"acceptance_criterion", "business_rule", "expected_result"}
                    or type(self.field_index) is not int or self.field_index < 0):
                raise ValueError("document quotation requires a verified field")
        else:
            raise ValueError("unknown quotation basis")

    @property
    def text_hash(self) -> str:
        return text_digest(self.text)

    @property
    def span_id(self) -> str:
        # Raw source and parsed field have separate hashes, even on one CSV row.
        metadata = {key: value for key, value in asdict(self).items() if key not in {"text", "raw_text"}}
        return snapshot_digest({**metadata, "text_hash": self.text_hash})


@dataclass(frozen=True)
class SemanticLinkInput:
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    relation: str
    target: SemanticEndpoint
    subjects: tuple[SemanticEndpoint, ...]
    excerpts: tuple[GroundedExcerpt, ...]
    recall_method: str
    recall_digest: str
    recall_truncated: bool
    schema: str = SEMANTIC_INPUT_SCHEMA

    def __post_init__(self):
        require_identifier(self.project_id)
        require_identifier(self.image_revision_id)
        require_identifier(self.recall_method)
        require_digest(self.image_artifact_hash)
        require_digest(self.recall_digest)
        if self.schema != SEMANTIC_INPUT_SCHEMA or type(self.recall_truncated) is not bool:
            raise ValueError("invalid semantic input schema")
        if self.relation not in {"implements", "asserts"}:
            raise ValueError("unsupported semantic relation")
        target_kinds = {"acceptance_criterion", "business_rule"} if self.relation == "implements" else {"acceptance_criterion"}
        if self.target.kind not in target_kinds:
            raise ValueError("semantic target is not an independent specification component")
        if type(self.subjects) is not tuple or not 1 <= len(self.subjects) <= 30:
            raise ValueError("semantic batches require 1..30 selected subjects")
        subject_kind = "code_entity" if self.relation == "implements" else "test_case"
        if any(item.kind != subject_kind for item in self.subjects):
            raise ValueError("semantic subject kind does not match relation")
        endpoints = (self.target, *self.subjects)
        if len({item.object_id for item in endpoints}) != len(endpoints):
            raise ValueError("duplicate semantic endpoint")
        if type(self.excerpts) is not tuple or not 2 <= len(self.excerpts) <= 128:
            raise ValueError("semantic evidence budget exceeded")
        if len({item.span_id for item in self.excerpts}) != len(self.excerpts):
            raise ValueError("duplicate semantic excerpt")
        members = {item.object_id: item for item in endpoints}
        present = set()
        for excerpt in self.excerpts:
            member = members.get(excerpt.object_id)
            if (member is None or member.revision_id != excerpt.revision_id
                    or member.source_revision_id != excerpt.source_revision_id
                    or excerpt.evidence_id not in member.evidence_ids):
                raise ValueError("semantic excerpt is outside pinned endpoints")
            role = (member.kind if member.object_id == self.target.object_id else
                    "implementation" if self.relation == "implements" else "expected_result")
            if excerpt.role != role:
                raise ValueError("semantic excerpt role does not match endpoint")
            present.add((member.object_id, excerpt.evidence_id))
        required = {(item.object_id, evidence_id) for item in endpoints for evidence_id in item.evidence_ids}
        if present != required:
            raise ValueError("semantic evidence is incomplete; do not silently truncate")
        if len(json.dumps(self.model_payload(), ensure_ascii=False).encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("semantic input exceeds 256 KiB; reduce the explicit selection")

    @property
    def digest(self) -> str:
        return snapshot_digest(asdict(self))

    def model_payload(self) -> dict:
        return {**asdict(self), "input_digest": self.digest,
                "excerpts": [{**asdict(item), "span_id": item.span_id, "text_hash": item.text_hash}
                             for item in self.excerpts],
                "authority": {"kind": "source_projection", "object_id": self.target.object_id,
                              "revision_id": self.target.revision_id, "status": "pending_confirmation"}}
