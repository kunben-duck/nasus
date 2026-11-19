"""Bounded environment capabilities. IDs are not database or container selectors."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import re


MAX_LEASE_SECONDS = 900
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_GENERATION = 9007199254740991
SNAPSHOT_SCHEMA = "nasus.private-environment-snapshot.v1"


class EnvironmentLifecycleInvalid(ValueError):
    pass


class EnvironmentLeaseUnavailable(EnvironmentLifecycleInvalid):
    pass


class EnvironmentFenceRejected(EnvironmentLifecycleInvalid):
    pass


class EnvironmentOperationFailed(EnvironmentLifecycleInvalid):
    pass


def identity(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
        raise EnvironmentLifecycleInvalid("Lifecycle requires bounded opaque identities")
    return value


def checksum(value):
    if type(value) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise EnvironmentLifecycleInvalid("Lifecycle requires a SHA-256 checksum")
    return value


def bounded_integer(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise EnvironmentLifecycleInvalid("Lifecycle bound is invalid")
    return value


def snapshot_phase(value):
    if type(value) is not str or value not in {"before", "after"}:
        raise EnvironmentLifecycleInvalid("Snapshot phase must be before or after")
    return value


@dataclass(frozen=True)
class RegisteredExecutionEnvironment:
    environment_id: str
    project_id: str
    target_key: str
    inventory_hash: str
    max_snapshot_bytes: int = MAX_SNAPSHOT_BYTES

    def __post_init__(self):
        for value in (self.environment_id, self.project_id, self.target_key):
            identity(value)
        checksum(self.inventory_hash)
        bounded_integer(self.max_snapshot_bytes, MAX_SNAPSHOT_BYTES)


@dataclass(frozen=True)
class EnvironmentLease:
    lease_id: str
    environment_id: str
    project_id: str
    version_id: str
    batch_id: str
    owner_id: str
    generation: int
    target_key: str
    inventory_hash: str
    created_at: datetime
    expires_at: datetime
    max_snapshot_bytes: int

    def __post_init__(self):
        for value in (self.lease_id, self.environment_id, self.project_id, self.version_id,
                      self.batch_id, self.owner_id, self.target_key):
            identity(value)
        bounded_integer(self.generation, MAX_GENERATION)
        bounded_integer(self.max_snapshot_bytes, MAX_SNAPSHOT_BYTES)
        checksum(self.inventory_hash)
        if (not isinstance(self.created_at, datetime) or not isinstance(self.expires_at, datetime)
                or self.created_at.tzinfo is None or self.expires_at.tzinfo is None
                or not 0 < (self.expires_at - self.created_at).total_seconds() <= MAX_LEASE_SECONDS):
            raise EnvironmentLifecycleInvalid("Lease requires a bounded aware deadline")


@dataclass(frozen=True)
class BatchSnapshotScope:
    project_id: str
    version_id: str
    batch_id: str
    environment_id: str
    lease_id: str
    generation: int
    inventory_hash: str
    expires_at: str
    phase: str

    @classmethod
    def from_lease(cls, lease: EnvironmentLease, phase: str):
        return cls(lease.project_id, lease.version_id, lease.batch_id, lease.environment_id,
                   lease.lease_id, lease.generation, lease.inventory_hash, lease.expires_at.isoformat(), snapshot_phase(phase))

    def payload(self):
        for value in (self.project_id, self.version_id, self.batch_id, self.environment_id, self.lease_id):
            identity(value)
        bounded_integer(self.generation, MAX_GENERATION)
        checksum(self.inventory_hash)
        snapshot_phase(self.phase)
        try:
            if datetime.fromisoformat(self.expires_at).tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise EnvironmentLifecycleInvalid("Snapshot requires an aware lease deadline") from None
        return asdict(self)


@dataclass(frozen=True)
class ExecutionStoppedProof:
    lease_id: str
    generation: int
    proof_id: str
    execution_stopped: bool = False

    def require(self, lease):
        identity(self.lease_id)
        bounded_integer(self.generation, MAX_GENERATION)
        identity(self.proof_id)
        if (self.lease_id != lease.lease_id or self.generation != lease.generation
                or self.execution_stopped is not True):
            raise EnvironmentFenceRejected("Execution cessation has not been proved for this fence")


@dataclass(frozen=True)
class SnapshotVerification:
    lease_id: str
    generation: int
    snapshot_id: str
    content_hash: str
    phase: str
    verified: bool = False
    proof_id: str | None = None

    def require_scope(self, lease, snapshot_id, content_hash, phase):
        identity(self.lease_id)
        identity(self.snapshot_id)
        bounded_integer(self.generation, MAX_GENERATION)
        checksum(self.content_hash)
        snapshot_phase(self.phase)
        if (self.lease_id != lease.lease_id or self.generation != lease.generation
                or self.snapshot_id != snapshot_id or self.content_hash != content_hash
                or self.phase != phase
                or type(self.verified) is not bool):
            raise EnvironmentFenceRejected("Snapshot verification scope differs")
        if self.verified:
            identity(self.proof_id)


@dataclass(frozen=True)
class StoredExecutionSnapshot:
    """Immutable archive fact. Restore authority lives in ExecutionSnapshotStatus."""
    snapshot_id: str
    lease_id: str
    generation: int
    phase: str
    object_key: str
    content_hash: str
    encrypted_hash: str
    size_bytes: int
    storage_readback_verified: bool = False
    snapshot_verified: bool = False
    snapshot_proof_id: str | None = None
    restore_verified: bool = False

    def require(self, lease):
        identity(self.snapshot_id)
        identity(self.lease_id)
        bounded_integer(self.generation, MAX_GENERATION)
        snapshot_phase(self.phase)
        checksum(self.content_hash)
        checksum(self.encrypted_hash)
        bounded_integer(self.size_bytes, lease.max_snapshot_bytes)
        if (self.lease_id != lease.lease_id or self.generation != lease.generation
                or self.storage_readback_verified is not True
                or type(self.snapshot_verified) is not bool or self.restore_verified is not False
                or type(self.object_key) is not str or len(self.object_key) > 512):
            raise EnvironmentLifecycleInvalid("Snapshot archive is not verified for this lease")
        if self.snapshot_verified:
            identity(self.snapshot_proof_id)


@dataclass(frozen=True)
class IndependentRestoreVerification(SnapshotVerification):
    """A restore into a separate copy, never a reset of the execution environment."""
    independent_target_key: str | None = None
    independent_copy_verified: bool = False
    source_unchanged: bool = False

    def require(self, lease, snapshot):
        self.require_scope(lease, snapshot.snapshot_id, snapshot.content_hash, snapshot.phase)
        identity(self.independent_target_key)
        if (self.verified is not True or self.independent_copy_verified is not True
                or self.source_unchanged is not True or self.independent_target_key == lease.target_key):
            raise EnvironmentFenceRejected("Snapshot restoration requires a verified independent copy")


@dataclass(frozen=True)
class CleanBaselineVerification:
    lease_id: str
    generation: int
    proof_id: str
    clean_baseline_verified: bool = False
    execution_stopped: bool = False

    def require(self, lease):
        ExecutionStoppedProof(self.lease_id, self.generation, self.proof_id, self.execution_stopped).require(lease)
        if self.clean_baseline_verified is not True:
            raise EnvironmentFenceRejected("Readable snapshot bytes do not prove a clean baseline")


@dataclass(frozen=True)
class BaselineResetVerification(CleanBaselineVerification):
    before_snapshot_id: str | None = None
    after_snapshot_id: str | None = None

    def require_snapshots(self, lease, before, after):
        self.require(lease)
        if (before.phase != "before" or after.phase != "after"
                or self.before_snapshot_id != before.snapshot_id or self.after_snapshot_id != after.snapshot_id):
            raise EnvironmentFenceRejected("Baseline reset must bind both retained snapshots")


@dataclass(frozen=True)
class ExecutionSnapshotStatus:
    """Join of retained bytes and a separate, exact independent-copy restore proof."""
    archive: StoredExecutionSnapshot
    independent_restore: IndependentRestoreVerification | None = None

    @property
    def snapshot_verified(self):
        return self.archive.snapshot_verified

    @property
    def restore_verified(self):
        return self.independent_restore is not None and self.independent_restore.verified is True
