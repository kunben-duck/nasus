"""Command-owned acquisition outcomes; these do not approve a system image."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from .source_acquisition import SourceAcquisitionIntent, _digest, _identity
from .source_snapshots import snapshot_digest


def _reference(value):
    return (type(value) is str and 0 < len(value) <= 8192
        and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value))


@dataclass(frozen=True)
class SourceAcquisitionResult:
    invocation_id: str
    project_id: str
    source_id: str
    binding_id: str
    intent_hash: str
    status: str
    acquired_at: str
    content_hash: str | None
    content_ref: str | None
    evidence_refs: tuple[str, ...]
    file_count: int
    byte_count: int
    source_revision_id: str | None
    snapshot_hash: str | None
    inventory_id: str | None
    inventory_hash: str | None
    failure_reason: str | None = None
    permission_status: str = "allowed"

    def __post_init__(self):
        if (not all(_identity(value) for value in (self.invocation_id, self.project_id, self.source_id, self.binding_id))
                or not _digest(self.intent_hash) or self.status not in {"captured", "legacy_unverified", "failed"}
                or type(self.evidence_refs) is not tuple or len(self.evidence_refs) > 128
                or not all(_reference(value) for value in self.evidence_refs)
                or any(type(value) is not int or value < 0 for value in (self.file_count, self.byte_count))
                or self.permission_status not in {"allowed", "denied"}):
            raise ValueError("Invalid acquisition result.")
        if type(self.acquired_at) is not str:
            raise ValueError("Acquisition result requires an aware timestamp.")
        try:
            timestamp = datetime.fromisoformat(self.acquired_at)
        except ValueError as exc:
            raise ValueError("Invalid acquisition timestamp.") from exc
        if timestamp.tzinfo is None:
            raise ValueError("Acquisition result requires an aware timestamp.")
        for ident, digest in ((self.source_revision_id, self.snapshot_hash), (self.inventory_id, self.inventory_hash)):
            if (ident is None) != (digest is None) or ident is not None and (not _identity(ident) or not _digest(digest)):
                raise ValueError("Incomplete acquisition artifact pin.")
        if self.status == "failed":
            if (self.content_hash is not None or self.content_ref is not None or self.source_revision_id is not None
                    or self.file_count or self.byte_count or self.failure_reason not in {
                        "source_connector_failed", "source_acquisition_incomplete", "source_acquisition_denied"}):
                raise ValueError("A failed acquisition cannot claim captured content.")
        elif (self.failure_reason is not None or self.permission_status != "allowed" or not self.evidence_refs
                or not _reference(self.content_ref) or not _reference(self.content_hash)
                or (self.status == "captured") != (self.source_revision_id is not None)
                or self.status == "captured" and (not _digest(self.content_hash) or self.file_count < 1)):
            raise ValueError("Acquisition content does not match its outcome.")

    @property
    def result_hash(self):
        return snapshot_digest({"schema": "nasus.source-acquisition-result.v1", **asdict(self)})

    def require_intent(self, intent: SourceAcquisitionIntent):
        if (self.invocation_id != intent.invocation_id or self.project_id != intent.project_id
                or self.intent_hash != intent.content_hash
                or not any(pin.source_id == self.source_id and pin.binding_id == self.binding_id for pin in intent.sources)):
            raise ValueError("Acquisition result is outside its original intent.")


def acquisition_results_hash(intent, results):
    ordered = tuple(sorted(results, key=lambda item: item.source_id))
    if tuple(item.source_id for item in ordered) != tuple(pin.source_id for pin in intent.sources):
        raise ValueError("Acquisition results must cover the complete original source selection.")
    for result in ordered:
        result.require_intent(intent)
    return snapshot_digest({"schema": "nasus.source-acquisition-results.v1", "intent_hash": intent.content_hash,
        "results": [{"source_id": item.source_id, "result_hash": item.result_hash} for item in ordered]})
