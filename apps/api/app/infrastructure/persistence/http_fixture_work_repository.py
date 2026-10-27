"""PG-clock leases fence private workers; unknown effects are never redispatched."""
from dataclasses import asdict
from contextlib import nullcontext
from datetime import timedelta

from sqlalchemy import func, select

from ...application.quality_loop.http_fixture_work import (
    FIXTURE_WORK_LEASE_SECONDS, HttpFixtureWorkBusy, HttpFixtureWorkLease, HttpFixtureWorkLost,
    fixture_work_digest, fixture_work_identity,
)
from ...application.quality_loop.http_fixtures import HttpFixtureScope
from ...application.quality_loop.http_fixture_diagnostics import fixture_phase
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid
from .db_models import UserIdentityRecord, ProjectRoleBindingRecord
from .http_fixture_journal_models import HttpFixtureDispatchRecord
from .http_fixture_work_models import HttpFixtureWorkLeaseRecord as Lease, HttpFixtureDispatchOwnershipRecord as Ownership
from .unit_of_work import session_scope


def verify_dispatch_ownership(session, dispatch):
    row = session.get(Ownership, dispatch["claim_id"])
    if row is None:
        if dispatch.get("schema") in {"nasus.http-fixture-dispatch.v2", "nasus.http-fixture-dispatch.v3", "nasus.http-fixture-dispatch.v4"} or "work_ownership" in dispatch:
            raise HttpFixtureInvalid("original leased dispatch ownership is missing; never downgrade it to legacy")
        return None
    columns = {column.name for column in row.__table__.columns} - {"payload", "content_hash"}
    value = row.payload
    if (type(value) is not dict or acceptance_digest(value) != row.content_hash
            or acceptance_digest({key: value.get(key) for key in columns}) != acceptance_digest({key: getattr(row, key) for key in columns})
            or type(value.get("epoch")) is not int or not 1 <= value["epoch"] <= 2147483647
            or value.get("schema") != "nasus.http-fixture-dispatch-ownership.v1"
            or value["project_id"] != dispatch["project_id"]
            or value["dispatch_digest"] != acceptance_digest(dispatch)
            or value.get("execution_authorized") is not False
            or value.get("business_coverage_verified") is not False
            or dispatch.get("schema") not in {"nasus.http-fixture-dispatch.v2", "nasus.http-fixture-dispatch.v3", "nasus.http-fixture-dispatch.v4"}
            or acceptance_digest(dispatch.get("work_ownership")) != acceptance_digest({key: value[key] for key in
                ("work_id", "owner_id", "epoch", "request_digest")})):
        raise HttpFixtureInvalid("fixture dispatch ownership is not its original immutable history")
    scope = HttpFixtureScope(**dispatch["scope"])
    operation = "setup" if dispatch["phase"] == "setup" else "cleanup"
    lease = session.get(Lease, value["work_id"])
    if (lease is None or value["work_id"] != fixture_work_identity(scope, operation)
            or value["request_digest"] != fixture_work_digest(scope, operation)
            or lease.scope != asdict(scope) or lease.scope_digest != scope.digest
            or lease.request_digest != value["request_digest"] or lease.actor_id != dispatch["actor_id"]
            or value["epoch"] > lease.epoch):
        raise HttpFixtureInvalid("fixture historical ownership differs from its original work scope")
    return value


class PostgresHttpFixtureWorkRepository:
    def __init__(self, journal):
        self.journal = journal

    def _read_session(self):
        reader = getattr(self.journal.access, "verified_read_session", None)
        return reader() if callable(reader) else nullcontext()

    @staticmethod
    def _actor_current(session, project_id, actor_id):
        # This read-only fence also runs inside callbacks holding the journal's
        # transaction locks; taking another connection's actor lock would deadlock.
        actor = session.get(UserIdentityRecord, actor_id, populate_existing=True)
        roles = session.scalars(select(ProjectRoleBindingRecord).where(
            ProjectRoleBindingRecord.project_id == project_id, ProjectRoleBindingRecord.user_id == actor_id,
            ProjectRoleBindingRecord.version_id.is_(None), ProjectRoleBindingRecord.session_id.is_(None),
            ProjectRoleBindingRecord.status == "active").execution_options(populate_existing=True)).all()
        if (actor is None or actor.status != "active" or (actor.role != "platform_admin"
                and (len(roles) != 1 or roles[0].role != "project_admin"))):
            raise PermissionError("fixture worker requires a current project administrator")

    def _pins(self, session, row, scope, operation, parent):
        plan = self.journal._parent(session, parent)
        expected = {"work_id": fixture_work_identity(scope, operation), "project_id": scope.project_id,
            "attempt_id": scope.attempt_id, "case_id": scope.case_id, "operation": operation,
            "scope": asdict(scope), "scope_digest": scope.digest,
            "request_digest": fixture_work_digest(scope, operation), "actor_id": self.journal.actor_id,
            **{key: parent[key] for key in ("run_plan_id", "run_plan_artifact_hash", "plan_digest")},
            "image_revision_id": plan.image_revision_id, "manifest_id": plan.manifest_id}
        if row is not None and any(getattr(row, key) != value for key, value in expected.items()):
            raise HttpFixtureInvalid("fixture work cannot rebind original scope, actor or parent")
        return expected

    def _live(self, session, lease, parent, *, lock=False):
        query = select(Lease).where(Lease.work_id == lease.work_id).execution_options(populate_existing=True)
        row = session.scalar(query.with_for_update() if lock else query)
        self._pins(session, row, lease.scope, lease.operation, parent)
        self._actor_current(session, lease.scope.project_id, self.journal.actor_id)
        now = session.scalar(select(func.clock_timestamp()))
        if (row is None or row.owner_id != lease.owner_id or row.epoch != lease.epoch
                or row.request_digest != lease.request_digest or row.expires_at <= now
                or row.acquired_at > row.renewed_at or row.renewed_at >= row.expires_at):
            raise HttpFixtureWorkLost("fixture worker lost its original live lease")
        return row, now

    def acquire(self, scope, operation, owner_id, *, require_current):
        with self._read_session(), fixture_phase("work_acquire"):
            return self._acquire(scope, operation, owner_id, require_current=require_current)

    def _acquire(self, scope, operation, owner_id, *, require_current):
        # Validate before reads, including booleans posing as epochs/identities.
        provisional = HttpFixtureWorkLease(scope, operation, owner_id, 1, fixture_work_digest(scope, operation))
        with fixture_phase("work_initial_authority"):
            require_current()
        with fixture_phase("work_original_scope"):
            parent = self.journal.access.require_scope(scope)
        with session_scope() as session:
            with fixture_phase("work_transaction_lock"):
                self.journal._lock(session, parent)
            with fixture_phase("work_locked_authority"):
                require_current()
            with fixture_phase("work_registered_parent"):
                query = select(Lease).where(Lease.work_id == provisional.work_id).with_for_update()
                row = session.scalar(query)
                pins = self._pins(session, row, scope, operation, parent)
                now = session.scalar(select(func.clock_timestamp()))
                if row is not None and row.expires_at > now:
                    raise HttpFixtureWorkBusy("another worker still owns the original fixture operation")
            with fixture_phase("work_final_scope"):
                if acceptance_digest(self.journal.access.require_scope(scope)) != acceptance_digest(parent):
                    raise HttpFixtureInvalid("fixture work original parent changed during acquisition")
            with fixture_phase("work_final_authority"):
                require_current()
            # Original-input/ACL reads may take most of a lease interval. Start
            # ownership only after those guards, not before their I/O.
            now = session.scalar(select(func.clock_timestamp()))
            lease = HttpFixtureWorkLease(scope, operation, owner_id, row.epoch + 1 if row else 1, pins["request_digest"])
            if row is None:
                row = Lease(**pins)
                session.add(row)
            row.owner_id, row.epoch = lease.owner_id, lease.epoch
            row.acquired_at = row.renewed_at = now
            row.expires_at = now + timedelta(seconds=FIXTURE_WORK_LEASE_SECONDS)
            session.flush()
            return lease

    def require(self, lease):
        with self._read_session(), fixture_phase("work_require"):
            return self._require(lease)

    def _require(self, lease):
        with fixture_phase("work_original_scope"):
            parent = self.journal.access.require_scope(lease.scope)
        with session_scope() as session:
            with fixture_phase("work_live_lease"):
                self._live(session, lease, parent)

    def renew(self, lease, *, require_current):
        with self._read_session(), fixture_phase("work_renew"):
            return self._renew(lease, require_current=require_current)

    def _renew(self, lease, *, require_current):
        with fixture_phase("work_initial_authority"):
            require_current()
        with fixture_phase("work_original_scope"):
            parent = self.journal.access.require_scope(lease.scope)
        with session_scope() as session:
            with fixture_phase("work_transaction_lock"):
                self.journal._lock(session, parent)
            with fixture_phase("work_live_lease"):
                self._live(session, lease, parent, lock=True)
            with fixture_phase("work_final_scope"):
                if acceptance_digest(self.journal.access.require_scope(lease.scope)) != acceptance_digest(parent):
                    raise HttpFixtureInvalid("fixture work original parent changed during renewal")
            with fixture_phase("work_final_authority"):
                require_current()
            # The old lease must still be live after slow guards; an expired
            # owner cannot revive itself by having started renewal earlier.
            with fixture_phase("work_live_lease"):
                row, now = self._live(session, lease, parent, lock=True)
            row.renewed_at = now
            row.expires_at = now + timedelta(seconds=FIXTURE_WORK_LEASE_SECONDS)
            session.flush()

    def fence(self, lease):
        return PostgresHttpFixtureWorkFence(self, lease)


class PostgresHttpFixtureWorkFence:
    def __init__(self, repository, lease):
        self.repository, self.lease = repository, lease

    def ownership_pin(self, scope, phase):
        self.lease.require_phase(scope, phase)
        return {"work_id": self.lease.work_id, "owner_id": self.lease.owner_id,
            "epoch": self.lease.epoch, "request_digest": self.lease.request_digest}

    def require(self, session, scope, phase, command):
        self.lease.require_phase(scope, phase)
        parent = self.repository.journal.access.require_scope(scope)
        self.repository._live(session, self.lease, parent, lock=True)
        # The journal compiles and verifies the full command before opening its
        # write transaction. Re-entering cleanup inspection here would acquire
        # the same actor lock on another connection and deadlock.
        if command.metadata.get("fixture_scope") != asdict(scope) or command.metadata.get("fixture_phase") != phase:
            raise HttpFixtureInvalid("worker phase differs from the original command scope")

    def claim(self, session, dispatch):
        value = {"schema": "nasus.http-fixture-dispatch-ownership.v1", "claim_id": dispatch["claim_id"],
            "project_id": dispatch["project_id"], "work_id": self.lease.work_id,
            "owner_id": self.lease.owner_id, "epoch": self.lease.epoch, "request_digest": self.lease.request_digest,
            "dispatch_digest": acceptance_digest(dispatch), "recorded_at": dispatch["recorded_at"],
            "execution_authorized": False, "business_coverage_verified": False}
        if session.get(Ownership, dispatch["claim_id"]) is not None:
            raise HttpFixtureInvalid("fixture dispatch already has original worker ownership")
        original = session.get(HttpFixtureDispatchRecord, dispatch["claim_id"])
        if original is None or original.content_hash != value["dispatch_digest"]:
            raise HttpFixtureInvalid("worker ownership requires this transaction's original dispatch")
        session.add(self.repository.journal._row(Ownership, value))

    def complete(self, session, dispatch):
        original = verify_dispatch_ownership(session, dispatch)
        if (original is None or any(original[key] != value for key, value in {
                "work_id": self.lease.work_id, "owner_id": self.lease.owner_id,
                "epoch": self.lease.epoch, "request_digest": self.lease.request_digest}.items())):
            raise HttpFixtureWorkLost("a replacement worker cannot adopt another dispatch's unknown effect")
