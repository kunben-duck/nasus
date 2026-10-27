"""Durable projection identity, separate from a worker's native index session."""
from dataclasses import dataclass
from typing import Optional

from .source_snapshots import snapshot_digest
from .image_revision import require_digest
from .code_index import CodeIndexUnavailable
from .code_provider_protocol import CODE_PROVIDER_CONTRACT_TYPES, CodeProviderContractReceipt


class CodeIndexLeaseLost(CodeIndexUnavailable):
    pass


class CodeIndexBusy(CodeIndexUnavailable):
    pass


@dataclass(frozen=True)
class CodeIndexGenerationPin:
    generation_id: str
    project_id: str
    binding_id: str
    source_revision_id: str
    source_manifest_hash: str
    snapshot_hash: str
    provider_fingerprint: str
    invocation_id: str
    content_hash: str

    def __post_init__(self):
        for value in (self.generation_id, self.project_id, self.binding_id, self.source_revision_id, self.invocation_id):
            if type(value) is not str or not value or len(value) > 128:
                raise ValueError("invalid code index generation identity")
        for value in (self.source_manifest_hash, self.snapshot_hash, self.provider_fingerprint, self.content_hash):
            require_digest(value)
        if self.content_hash != snapshot_digest(self.metadata()):
            raise ValueError("code index generation pin has changed")

    def metadata(self):
        return {key: getattr(self, key) for key in (
            "generation_id", "project_id", "binding_id", "source_revision_id", "source_manifest_hash",
            "snapshot_hash", "provider_fingerprint", "invocation_id")}


@dataclass(frozen=True)
class CodeIndexLease:
    pin: CodeIndexGenerationPin
    epoch: int
    owner_id: str

    def __post_init__(self):
        if type(self.epoch) is not int or self.epoch < 1 or type(self.owner_id) is not str or not self.owner_id:
            raise ValueError("invalid code index worker lease")


@dataclass(frozen=True)
class CodeIndexGenerationStatus:
    pin: CodeIndexGenerationPin
    state: str
    epoch: int
    worker_state: str
    invocation_status: str
    observed_at: str
    protocol: Optional[CodeProviderContractReceipt] = None
    projection_hash: Optional[str] = None
    provider_version: Optional[str] = None
    entity_count: Optional[int] = None
    relationship_count: Optional[int] = None
    scope: str = "durable_projection_metadata_not_native_cache_or_business_authority"

    def __post_init__(self):
        if (not isinstance(self.pin, CodeIndexGenerationPin)
                or self.state not in {"idle", "preparing", "ready", "degraded", "cancel_requested", "cancelled", "failed"}
                or type(self.epoch) is not int or self.epoch < 0
                or self.worker_state not in {"none", "active", "expired"}
                or self.invocation_status not in {"pending", "running", "waiting_confirmation", "waiting_approval", "completed", "failed", "cancelled"}
                or type(self.observed_at) is not str or not self.observed_at
                or self.scope != "durable_projection_metadata_not_native_cache_or_business_authority"):
            raise CodeIndexLeaseLost("invalid durable code index status")
        if (self.state in {"preparing", "ready", "degraded", "cancel_requested"}) != (self.worker_state != "none"):
            raise CodeIndexLeaseLost("durable code index worker state is inconsistent")
        if self.protocol is not None and not isinstance(self.protocol, CODE_PROVIDER_CONTRACT_TYPES):
            raise CodeIndexLeaseLost("invalid durable native protocol receipt")
        values = (self.projection_hash, self.provider_version, self.entity_count, self.relationship_count)
        if any(value is not None for value in values):
            if (any(value is None for value in values) or self.protocol is None
                    or type(self.provider_version) is not str or not self.provider_version or len(self.provider_version) > 120
                    or any(type(count) is not int or not 0 <= count <= 100000000 for count in (self.entity_count, self.relationship_count))):
                raise CodeIndexLeaseLost("invalid durable projection metadata")
            require_digest(self.projection_hash)
        if self.state in {"ready", "degraded"} and self.protocol is None:
            raise CodeIndexLeaseLost("prepared status lacks its durable native contract")
