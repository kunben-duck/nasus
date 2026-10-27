from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from apps.api.app.domain.system_image.image_revision import ImageArtifactUnavailable
from apps.api.app.infrastructure.persistence import image_read_snapshot as module
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.image_revision_repository import ImageRevisionRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def test_read_snapshot_pool_cannot_starve_live_reads_and_fails_closed_when_full(monkeypatch):
    assert engine.url.get_backend_name() == "postgresql"
    assert engine.url.database.startswith("nasus_test_")
    dedicated = create_engine(engine.url, pool_size=1, max_overflow=0, pool_timeout=0.05,
        isolation_level="REPEATABLE READ", future=True)
    sessions = sessionmaker(bind=dedicated, future=True)
    monkeypatch.setattr(module, "_session_factory", lambda: sessions)
    repository = ImageRevisionRepository()

    def another_compilation():
        assert repository._read_snapshot.get() is None
        with pytest.raises(ImageArtifactUnavailable, match="capacity"):
            with repository.verified_read_session():
                pytest.fail("A full snapshot pool must not open another transaction")
        assert repository._read_snapshot.get() is None
        with session_scope() as live:
            return live.scalar(text("SELECT 1"))

    try:
        with repository.verified_read_session():
            session, _ = repository._read_snapshot.get()
            assert session.scalar(text("SHOW transaction_read_only")) == "on"
            with ThreadPoolExecutor(max_workers=1) as executor:
                assert executor.submit(another_compilation).result(timeout=5) == 1
            with session_scope() as live:
                assert live.scalar(text("SHOW transaction_read_only")) == "off"
        assert dedicated.pool.checkedout() == 0
        with repository.verified_read_session():
            assert repository._read_snapshot.get()[0].scalar(text("SELECT 1")) == 1
    finally:
        dedicated.dispose()
