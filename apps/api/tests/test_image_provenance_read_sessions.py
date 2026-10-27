"""No cross-request or write-transaction graph audit cache."""
from types import SimpleNamespace

import pytest

from apps.api.app.infrastructure.persistence import image_provenance_reads as reads
from apps.api.app.infrastructure.persistence import image_read_snapshot as snapshots


def image(ident="image", digest="original"):
    values = dict(project_id="project", image_revision_id=ident, artifact_hash=digest)
    return SimpleNamespace(**values, __table__=SimpleNamespace(columns=[SimpleNamespace(name=k) for k in values]))


@pytest.fixture
def audits(monkeypatch):
    calls = []
    monkeypatch.setattr(reads.ObjectProvenanceProjectorV1, "image", lambda _, session, value, **kwargs:
        calls.append(("objects", session, value.image_revision_id)))
    monkeypatch.setattr(reads.RelationProvenanceProjectorV1, "image", lambda _, session, value, **kwargs:
        calls.append(("relations", session, value.image_revision_id)))
    return calls


def session_factory(monkeypatch):
    monkeypatch.setattr(snapshots, "_session_factory", lambda: lambda:
        SimpleNamespace(connection=lambda **kwargs: None, execute=lambda statement: None,
            rollback=lambda: None, close=lambda: None))


def test_read_snapshot_reuses_complete_audits_but_next_scope_is_fresh(monkeypatch, audits):
    session_factory(monkeypatch)
    with snapshots.image_read_snapshot_scope() as session:
        for _ in range(3):
            reads.verify_image_provenance(session, image())
        assert len(audits) == 2
    assert snapshots.current_image_read_snapshot() is None
    with snapshots.image_read_snapshot_scope() as session:
        reads.verify_image_provenance(session, image())
    assert len(audits) == 4


def test_writes_or_independent_sessions_never_reuse_read_audits(monkeypatch, audits):
    session_factory(monkeypatch)
    independent = object()
    with snapshots.image_read_snapshot_scope() as session:
        reads.verify_image_provenance(session, image())
        for _ in range(2):
            reads.verify_image_provenance(independent, image())
    for _ in range(2):
        reads.verify_image_provenance(independent, image())
    assert len(audits) == 10


def test_changed_metadata_and_evicted_images_require_full_verification(monkeypatch, audits):
    session_factory(monkeypatch)
    with snapshots.image_read_snapshot_scope() as session:
        reads.verify_image_provenance(session, image())
        reads.verify_image_provenance(session, image(digest="changed"))
        reads.verify_image_provenance(session, image("second"))
        reads.verify_image_provenance(session, image("third"))
        assert len(snapshots.current_image_read_snapshot()[1]) == 2
        reads.verify_image_provenance(session, image())
        assert len(snapshots.current_image_read_snapshot()[1]) == 2
    assert len(audits) == 10


def test_failed_relation_audit_is_not_memoized_and_nested_scopes_restore(monkeypatch, audits):
    session_factory(monkeypatch)
    def fail(*args, **kwargs):
        raise ValueError("corrupt relation graph")
    with snapshots.image_read_snapshot_scope() as session:
        outer = snapshots.current_image_read_snapshot()
        reads.verify_image_provenance(session, image())
        with snapshots.image_read_snapshot_scope() as nested:
            monkeypatch.setattr(reads.RelationProvenanceProjectorV1, "image", fail)
            for _ in range(2):
                with pytest.raises(ValueError, match="corrupt relation"):
                    reads.verify_image_provenance(nested, image())
            assert snapshots.current_image_read_snapshot()[1] == {}
        assert snapshots.current_image_read_snapshot() is outer
        reads.verify_image_provenance(session, image())
    assert snapshots.current_image_read_snapshot() is None
    assert len(audits) == 4
