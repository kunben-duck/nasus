"""Durable claims surround external operations; failures never free an environment."""
from dataclasses import replace
import hashlib
from uuid import uuid4

from ...domain.quality_loop.execution_environment_lifecycle import (
    EnvironmentLifecycleInvalid, EnvironmentOperationFailed, ExecutionSnapshotStatus, snapshot_phase,
)
from .environment_lifecycle_ports import (
    ControlledSnapshotTargetsPort, EnvironmentLifecycleAccessPort,
    EnvironmentLifecycleRepositoryPort, ExecutionSnapshotStorePort,
)


class EnvironmentLifecycleService:
    def __init__(self, *, repository: EnvironmentLifecycleRepositoryPort,
                 access: EnvironmentLifecycleAccessPort, snapshots: ExecutionSnapshotStorePort,
                 targets: ControlledSnapshotTargetsPort):
        self.repository, self.access, self.snapshots, self.targets = repository, access, snapshots, targets

    def _access(self, lease):
        self.access.require_access(project_id=lease.project_id, version_id=lease.version_id, batch_id=lease.batch_id)

    def _check(self, lease, phase):
        self._access(lease)
        self.repository.require_live(lease, phases=(phase,))

    def acquire(self, *, environment_id, project_id, version_id, batch_id, owner_id, ttl_seconds=900):
        self.access.require_access(project_id=project_id, version_id=version_id, batch_id=batch_id)
        lease = self.repository.acquire(environment_id=environment_id, project_id=project_id,
            version_id=version_id, batch_id=batch_id, owner_id=owner_id, ttl_seconds=ttl_seconds)
        try:
            self._check(lease, "leased")
            return lease
        except BaseException:
            self.repository.quarantine(lease, reason="access_failed")
            raise

    def mark_running(self, lease):
        """Runner must claim this phase before dispatch, then enforce the target fence."""
        self._access(lease)
        self.repository.transition(lease, expected=("before_ready",), phase="running")

    def _fail(self, lease, reason, error):
        # Store only bounded reason codes, never exception text with possible secrets.
        self.repository.quarantine(lease, reason=reason)
        if not isinstance(error, Exception):
            raise error
        raise EnvironmentOperationFailed(reason + "; environment quarantined") from None

    def stop(self, lease):
        self._access(lease)
        self.repository.transition(lease, expected=("running",), phase="stopping")
        try:
            self._check(lease, "stopping")
            proof = self.targets.resolve(lease.target_key).stop_and_fence(lease)
            proof.require(lease)
            self._check(lease, "stopping")
            self.repository.transition(lease, expected=("stopping",), phase="stopped", stopped=proof)
            return proof
        except BaseException as error:
            self._fail(lease, "stop_failed", error)

    def capture(self, lease, *, phase):
        snapshot_phase(phase)
        claimed_phase = "capturing_" + phase
        self._access(lease)
        self.repository.transition(lease, expected=("leased" if phase == "before" else "stopped",), phase=claimed_phase)
        try:
            self._check(lease, claimed_phase)
            target = self.targets.resolve(lease.target_key)
            stopped = target.stop_and_fence(lease)
            stopped.require(lease)
            self._check(lease, claimed_phase)
            if phase == "before":
                baseline = target.verify_clean_baseline(lease, stopped)
                baseline.require(lease)
                self._check(lease, claimed_phase)
                self.repository.record_baseline(lease, baseline)
            body = target.capture(lease, stopped, max_bytes=lease.max_snapshot_bytes)
            if type(body) is not bytes or not 1 <= len(body) <= lease.max_snapshot_bytes:
                raise EnvironmentLifecycleInvalid("Snapshot exceeds its byte bound")
            self._check(lease, claimed_phase)
            snapshot_id = uuid4().hex
            stored = self.snapshots.archive(lease, snapshot_id, phase, body)
            stored.require(lease)
            content_hash = "sha256:" + hashlib.sha256(body).hexdigest()
            if (stored.snapshot_id != snapshot_id or stored.phase != phase or stored.content_hash != content_hash
                    or stored.size_bytes != len(body) or stored.snapshot_verified is not False):
                raise EnvironmentLifecycleInvalid("Archive cannot attest target validity")
            self._check(lease, claimed_phase)
            try:
                verification = target.verify_snapshot(lease, snapshot_id, phase, body)
                verification.require_scope(lease, snapshot_id, content_hash, phase)
            except Exception:
                # Retain the verified archive even when target validation fails;
                # readable bytes still carry no snapshot or restore authority.
                self._check(lease, claimed_phase)
                self.repository.record_snapshot(lease, stored)
                raise
            stored = replace(stored, snapshot_verified=verification.verified,
                             snapshot_proof_id=verification.proof_id)
            self._check(lease, claimed_phase)
            self.repository.record_snapshot(lease, stored)
            if not stored.snapshot_verified:
                raise EnvironmentLifecycleInvalid("Adapter has not proved snapshot validity")
            restored_body = self.snapshots.read_verified(lease, stored)
            if restored_body != body:
                raise EnvironmentLifecycleInvalid("Independent restore bytes differ from retained snapshot")
            self._check(lease, claimed_phase)
            restored = target.restore_to_independent_copy(lease, stored, restored_body)
            restored.require(lease, stored)
            self._check(lease, claimed_phase)
            self.repository.record_independent_restore(lease, restored)
            return ExecutionSnapshotStatus(stored, restored)
        except BaseException as error:
            self._fail(lease, "capture_failed", error)

    def reset(self, lease):
        """Only an explicitly installed, controlled adapter can implement this operation."""
        self._access(lease)
        self.repository.transition(lease, expected=("after_ready",), phase="resetting")
        try:
            self._check(lease, "resetting")
            before, after = self.repository.snapshot(lease, "before"), self.repository.snapshot(lease, "after")
            bodies = {}
            for snapshot in (before, after):
                snapshot.require(lease)
                if not snapshot.snapshot_verified:
                    raise EnvironmentLifecycleInvalid("Reset requires both adapter-verified snapshots")
                self.repository.restore_verification(lease, snapshot.phase).require(lease, snapshot)
                body = self.snapshots.read_verified(lease, snapshot)
                if (type(body) is not bytes or len(body) != snapshot.size_bytes
                        or "sha256:" + hashlib.sha256(body).hexdigest() != snapshot.content_hash):
                    raise EnvironmentLifecycleInvalid("Snapshot readback differs")
                bodies[snapshot.phase] = body
            self._check(lease, "resetting")
            target = self.targets.resolve(lease.target_key)
            stopped = target.stop_and_fence(lease)
            stopped.require(lease)
            self._check(lease, "resetting")
            proof = target.reset_to_clean_baseline(lease, before, after, bodies["before"], stopped)
            proof.require_snapshots(lease, before, after)
            self._check(lease, "resetting")
            self.repository.record_reset(lease, proof)
            return proof
        except BaseException as error:
            self._fail(lease, "reset_failed", error)

    def release(self, lease):
        self._access(lease)
        self.repository.release(lease)
