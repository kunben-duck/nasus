from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.domain.system_image.source_inventory import SourceInventoryArtifact
from apps.api.app.infrastructure.persistence import source_snapshot_repository as module
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.source_inventory_models import SourceInventoryRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord, SourceRevisionRecord
from apps.api.tests.test_source_snapshot_repository import pg_repo, source


@pytest.fixture
def inventory_repo(pg_repo):
    repo, sessions = pg_repo
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0036_source_inventories.py"
    spec = importlib.util.spec_from_file_location("inventory_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sessions.kw["bind"].begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
    yield repo, sessions
    with sessions.kw["bind"].begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()


def artifact():
    return SourceInventoryArtifact(
        "project", "source", "sha256:" + "a" * 64, "s3://private/inventory.json",
        "failed", False, 2, 15, 4,
    )


def test_failed_inventory_is_immutable_idempotent_and_not_a_successful_revision(inventory_repo):
    repo, sessions = inventory_repo
    first = repo.record_inventory(source(), artifact(), recorded_at="2026-09-10T00:00:00Z")
    assert repo.record_inventory(source(), artifact(), recorded_at="2026-09-10T01:00:00Z") == first
    with sessions() as session:
        record = session.scalars(select(SourceInventoryRecord)).one()
        assert record.status == "failed" and not record.enumeration_complete
        assert session.scalar(select(func.count()).select_from(SourceRevisionRecord)) == 0
        events = session.scalars(select(SSEEventOutboxRecord)).all()
        assert len(events) == 1
        payload = json.dumps(events[0].event_payload)
        assert "s3://" not in payload and "inventory.json" not in payload
        assert events[0].event_payload["event_type"] == "system_image.source.inventory_recorded"
    for statement in (update(SourceInventoryRecord).values(status="complete"), delete(SourceInventoryRecord)):
        with pytest.raises(IntegrityError):
            with sessions.begin() as session:
                session.execute(statement)


def test_inventory_scope_and_digest_reuse_are_checked(inventory_repo):
    repo, _ = inventory_repo
    with pytest.raises(ValueError, match="scope mismatch"):
        repo.record_inventory(source(project="other"), artifact(), recorded_at="now")
    repo.record_inventory(source(), artifact(), recorded_at="now")
    with pytest.raises(ValueError, match="different content"):
        repo.record_inventory(source(), replace(artifact(), file_count=1), recorded_at="now")


def test_inventory_and_outbox_share_a_transaction(inventory_repo, monkeypatch):
    repo, sessions = inventory_repo

    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(module.EventOutboxRepository, "append", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        repo.record_inventory(source(), artifact(), recorded_at="now")
    with sessions() as session:
        for model in (SourceInventoryRecord, SourceBindingRecord, SSEEventOutboxRecord):
            assert session.scalar(select(func.count()).select_from(model)) == 0
