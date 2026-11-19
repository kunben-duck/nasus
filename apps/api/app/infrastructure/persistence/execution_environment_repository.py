"""PostgreSQL-only fencing with server time and short per-environment row locks.

Expired owners are quarantined, never automatically replaced. External calls run
outside transactions; their claimed phases survive process death. A sweeper must
call reap_expired to quarantine interrupted operations. No recovery/reset shortcut
or lease extension is provided by this foundation.
"""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ...domain.quality_loop.execution_environment_lifecycle import (
    EnvironmentFenceRejected, EnvironmentLease, EnvironmentLeaseUnavailable,
    EnvironmentLifecycleInvalid, MAX_GENERATION, MAX_LEASE_SECONDS,
    IndependentRestoreVerification, StoredExecutionSnapshot, bounded_integer, identity, snapshot_phase,
)
from .database import SessionLocal
from .execution_environment_models import (
    ExecutionEnvironmentLeaseRecord as Lease, ExecutionEnvironmentRecord as Environment,
    ExecutionEnvironmentSnapshotRecord as Snapshot,
    ExecutionEnvironmentSnapshotRestoreRecord as Restore,
)


TRANSITIONS = {"capturing_before": {"leased"}, "running": {"before_ready"}, "stopping": {"running"},
               "stopped": {"stopping"}, "capturing_after": {"stopped"}, "resetting": {"after_ready"}}
SNAPSHOT_READ_PHASES = ("capturing_before", "before_ready", "running", "stopping", "stopped",
                        "capturing_after", "after_ready", "resetting", "reset_complete")
QUARANTINE_REASONS = {"expired", "access_failed", "stop_failed", "capture_failed", "reset_failed", "operator_hold"}


class PostgresExecutionEnvironmentRepository:
    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    @contextmanager
    def _transaction(self):
        with self.session_factory() as session:
            if session.get_bind().dialect.name != "postgresql":
                raise EnvironmentLifecycleInvalid("Durable environment leases require PostgreSQL")
            with session.begin():
                yield session

    @staticmethod
    def _environment(session, environment_id):
        row = session.scalar(select(Environment).where(Environment.environment_id == identity(environment_id))
                             .with_for_update())
        if row is None:
            raise EnvironmentLeaseUnavailable("Environment is not registered")
        return row

    @staticmethod
    def _lease(environment, row):
        return EnvironmentLease(row.lease_id, environment.environment_id, environment.project_id,
            row.version_id, row.batch_id, row.owner_id, row.generation, environment.target_key,
            environment.inventory_hash, row.created_at, row.expires_at, environment.max_snapshot_bytes)

    @staticmethod
    def _quarantine(environment, row, reason):
        environment.state, row.phase, row.quarantine_reason = "quarantined", "quarantined", reason

    @contextmanager
    def _live(self, lease, phases):
        expired = False
        with self._transaction() as session:
            environment = self._environment(session, lease.environment_id)
            row = session.get(Lease, lease.lease_id)
            if (row is None or row.environment_id != environment.environment_id
                    or environment.active_lease_id != lease.lease_id or environment.generation != lease.generation
                    or self._lease(environment, row) != lease or environment.state != "leased"):
                raise EnvironmentFenceRejected("Lease is stale, quarantined, or differs from registration")
            # Sample after acquiring the row lock, not at transaction start.
            if row.expires_at <= session.scalar(select(func.clock_timestamp())):
                self._quarantine(environment, row, "expired")
                expired = True
            else:
                if row.phase not in phases:
                    raise EnvironmentFenceRejected("Lifecycle phase does not permit this operation")
                yield session, environment, row
        if expired:
            # Raise after commit so expiry quarantine cannot be rolled back by rejection.
            raise EnvironmentFenceRejected("Lease expired; environment quarantined")

    def register(self, environment):
        """Operator composition only; registration is immutable and never model-supplied."""
        with self._transaction() as session:
            session.execute(insert(Environment).values(**asdict(environment), generation=0, state="available")
                            .on_conflict_do_nothing())
            row = self._environment(session, environment.environment_id)
            if any(getattr(row, key) != value for key, value in asdict(environment).items()):
                raise EnvironmentLifecycleInvalid("Registered target cannot be rebound")

    def acquire(self, *, environment_id, project_id, version_id, batch_id, owner_id, ttl_seconds):
        for value in (environment_id, project_id, version_id, batch_id, owner_id):
            identity(value)
        bounded_integer(ttl_seconds, MAX_LEASE_SECONDS)
        result = None
        with self._transaction() as session:
            environment = self._environment(session, environment_id)
            if environment.project_id != project_id:
                raise EnvironmentLeaseUnavailable("Environment is not registered for this project")
            now = session.scalar(select(func.clock_timestamp()))
            if environment.state != "available":
                active = session.get(Lease, environment.active_lease_id)
                if active is not None and active.expires_at <= now and environment.state == "leased":
                    self._quarantine(environment, active, "expired")
            else:
                bounded_integer(environment.generation + 1, MAX_GENERATION)
                environment.generation += 1
                row = Lease(lease_id=uuid4().hex, environment_id=environment_id, version_id=version_id,
                    batch_id=batch_id, owner_id=owner_id, generation=environment.generation,
                    created_at=now, expires_at=now + timedelta(seconds=ttl_seconds), phase="leased",
                    baseline_verified=False, reset_verified=False)
                environment.active_lease_id, environment.state = row.lease_id, "leased"
                session.add(row)
                session.flush()
                result = self._lease(environment, row)
        if result is None:
            raise EnvironmentLeaseUnavailable("Environment is exclusively leased or quarantined")
        return result

    def require_live(self, lease, *, phases):
        with self._live(lease, phases):
            pass

    def transition(self, lease, *, expected, phase, stopped=None):
        if not expected or not set(expected) <= TRANSITIONS.get(phase, set()):
            raise EnvironmentLifecycleInvalid("Unsupported lifecycle transition")
        with self._live(lease, expected) as (session, _, row):
            if phase == "stopped":
                if stopped is None:
                    raise EnvironmentFenceRejected("Stopping execution is not proof it stopped")
                stopped.require(lease)
                row.stopped_proof_id = stopped.proof_id
            if phase == "resetting":
                for snapshot_phase_name in ("before", "after"):
                    snapshot = self._snapshot(session, lease, snapshot_phase_name)
                    self._restore(session, lease, snapshot)
                    if not snapshot.snapshot_verified or row.stopped_proof_id is None:
                        raise EnvironmentFenceRejected("Reset requires stopped execution and both verified snapshots")
            if phase == "running":
                before = self._snapshot(session, lease, "before")
                self._restore(session, lease, before)
                if not row.baseline_verified or not before.snapshot_verified:
                    raise EnvironmentFenceRejected("Execution requires independently verified clean baseline")
            row.phase = phase

    def record_baseline(self, lease, proof):
        proof.require(lease)
        with self._live(lease, ("capturing_before",)) as (_, _, row):
            if row.baseline_verified:
                raise EnvironmentFenceRejected("Initial baseline proof cannot be replaced")
            row.baseline_verified, row.baseline_proof_id = True, proof.proof_id
            row.stopped_proof_id = proof.proof_id

    @staticmethod
    def _snapshot(session, lease, phase):
        snapshot_phase(phase)
        row = session.scalar(select(Snapshot).where(Snapshot.lease_id == lease.lease_id, Snapshot.phase == phase))
        if row is None:
            raise EnvironmentFenceRejected("No snapshot is registered for this lease")
        result = StoredExecutionSnapshot(**{key: getattr(row, key) for key in StoredExecutionSnapshot.__dataclass_fields__})
        result.require(lease)
        return result

    def record_snapshot(self, lease, snapshot):
        snapshot.require(lease)
        with self._live(lease, ("capturing_" + snapshot.phase,)) as (session, _, row):
            if row.stopped_proof_id is None or not row.baseline_verified:
                raise EnvironmentFenceRejected("Snapshot requires stopped execution")
            session.add(Snapshot(**asdict(snapshot)))

    def snapshot(self, lease, phase):
        with self._live(lease, SNAPSHOT_READ_PHASES) as (session, _, _row):
            return self._snapshot(session, lease, phase)

    @staticmethod
    def _restore(session, lease, snapshot):
        row = session.get(Restore, snapshot.snapshot_id)
        if row is None:
            raise EnvironmentFenceRejected("Independent-copy restoration has not been proved")
        proof = IndependentRestoreVerification(**{key: getattr(row, key)
            for key in IndependentRestoreVerification.__dataclass_fields__})
        proof.require(lease, snapshot)
        return proof

    def restore_verification(self, lease, phase):
        with self._live(lease, SNAPSHOT_READ_PHASES) as (session, _, _row):
            return self._restore(session, lease, self._snapshot(session, lease, phase))

    def record_independent_restore(self, lease, proof):
        snapshot_phase(proof.phase)
        with self._live(lease, ("capturing_" + proof.phase,)) as (session, _, row):
            snapshot = self._snapshot(session, lease, proof.phase)
            proof.require(lease, snapshot)
            if not snapshot.snapshot_verified or not row.baseline_verified:
                raise EnvironmentFenceRejected("Independent restore requires a verified snapshot and initial baseline")
            session.add(Restore(**asdict(proof)))
            row.phase = proof.phase + "_ready"

    def record_reset(self, lease, proof):
        with self._live(lease, ("resetting",)) as (session, _, row):
            before, after = self._snapshot(session, lease, "before"), self._snapshot(session, lease, "after")
            self._restore(session, lease, before)
            self._restore(session, lease, after)
            proof.require_snapshots(lease, before, after)
            row.reset_verified, row.reset_proof_id, row.phase = True, proof.proof_id, "reset_complete"

    def release(self, lease):
        # A never-dispatched lease can be relinquished. Once running, only a real
        # stopped clean-baseline reset permits reuse; other outcomes stay exclusive.
        with self._live(lease, ("leased", "reset_complete")) as (_, environment, row):
            if row.phase == "reset_complete" and not row.reset_verified:
                raise EnvironmentFenceRejected("Clean-baseline reset has not been proved")
            row.phase, environment.state, environment.active_lease_id = "released", "available", None

    def quarantine(self, lease, *, reason):
        if reason not in QUARANTINE_REASONS:
            raise EnvironmentLifecycleInvalid("Unknown quarantine reason")
        with self._transaction() as session:
            environment = self._environment(session, lease.environment_id)
            row = session.get(Lease, lease.lease_id)
            if (row is not None and environment.active_lease_id == lease.lease_id
                    and environment.generation == lease.generation and self._lease(environment, row) == lease):
                self._quarantine(environment, row, reason)

    def reap_expired(self, environment_id):
        with self._transaction() as session:
            environment = self._environment(session, environment_id)
            if environment.state != "leased":
                return False
            row = session.get(Lease, environment.active_lease_id)
            if row is not None and row.expires_at <= session.scalar(select(func.clock_timestamp())):
                self._quarantine(environment, row, "expired")
                return True
            return False
