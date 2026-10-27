"""Actual PG complete-proof reuse; partial audits cannot seed a reusable proof."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest
from sqlalchemy import delete, text

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence.image_provenance_reads import verify_image_object_provenance
from apps.api.app.infrastructure.persistence.image_read_snapshot import current_image_read_snapshot
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord as Image
from apps.api.app.infrastructure.persistence.object_provenance_models import ImageObjectProvenanceRecord as Root
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from apps.api.tests.test_image_revision_read_snapshot import (
    fixture_image, image_repo, registry, pg_repo,
)


def observed(monkeypatch):
    original, audits = ObjectProvenanceProjectorV1.image, []

    def counted(self, session, *args, **kwargs):
        audits.append(session)
        return original(self, session, *args, **kwargs)

    monkeypatch.setattr(ObjectProvenanceProjectorV1, "image", counted)
    return audits


@pytest.mark.parametrize("field", [col.name for col in Image.__table__.columns])
def test_complete_proof_rejects_every_different_fresh_image_column(image_repo, registry, tmp_path, field):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    with repo.verified_read_session():
        repo.get("project", image.image_revision_id)
        with image_repo[2]() as fresh:
            row = fresh.get(Image, image.image_revision_id)
            value = getattr(row, field)
            setattr(row, field, value + 1 if type(value) is int else "different-fixed-metadata")
            with fresh.no_autoflush, pytest.raises(ImageRevisionIntegrityError):
                verify_image_object_provenance(fresh, row, reuse_snapshot=True)


def test_partial_object_audit_never_seeds_complete_proof_or_implicit_write_reuse(
        image_repo, registry, tmp_path, monkeypatch):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    audits = observed(monkeypatch)
    with repo.verified_read_session():
        snapshot, cached = current_image_read_snapshot()
        for _ in range(2):
            with image_repo[2]() as fresh:
                verify_image_object_provenance(fresh, fresh.get(Image, image.image_revision_id), reuse_snapshot=True)
        assert len(audits) == 2 and cached == {}
        repo.get("project", image.image_revision_id)
        assert audits[-1] is snapshot and len(audits) == 3
        with image_repo[2]() as fresh:
            verify_image_object_provenance(fresh, fresh.get(Image, image.image_revision_id), reuse_snapshot=True)
            assert len(audits) == 3
            verify_image_object_provenance(fresh, fresh.get(Image, image.image_revision_id))
            assert len(audits) == 4 and audits[-1] is fresh


@pytest.mark.parametrize("schedule", ["thread", "task", "delayed"])
def test_copied_context_cannot_borrow_parent_complete_object_proof(
        image_repo, registry, tmp_path, monkeypatch, schedule):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    audits = observed(monkeypatch)

    async def run():
        def child():
            assert current_image_read_snapshot() is None
            with image_repo[2]() as fresh:
                verify_image_object_provenance(fresh, fresh.get(Image, image.image_revision_id), reuse_snapshot=True)
                assert audits[-1] is fresh

        with repo.verified_read_session():
            repo.get("project", image.image_revision_id)
            parent = current_image_read_snapshot()
            copied = copy_context()
            if schedule == "thread":
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(copied.run, child).result(timeout=30)
            elif schedule == "task":
                async def task():
                    child()
                await asyncio.create_task(task())
            assert current_image_read_snapshot() is parent
            with image_repo[2]() as fresh:
                verify_image_object_provenance(fresh, fresh.get(Image, image.image_revision_id), reuse_snapshot=True)
        if schedule == "delayed":
            copied.run(child)

    asyncio.run(run())
    assert len(audits) == 2 and current_image_read_snapshot() is None


def test_expired_proof_cannot_hide_next_operation_source_graph_corruption(image_repo, registry, tmp_path):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    with repo.verified_read_session():
        repo.get("project", image.image_revision_id)
        with image_repo[2].begin() as session:
            session.execute(text("ALTER TABLE image_object_provenance_roots DISABLE TRIGGER USER"))
            session.execute(delete(Root))
            session.execute(text("ALTER TABLE image_object_provenance_roots ENABLE TRIGGER USER"))
        with image_repo[2]() as fresh:
            verify_image_object_provenance(fresh, fresh.get(Image, image.image_revision_id), reuse_snapshot=True)
    with pytest.raises(ImageRevisionIntegrityError):
        with image_repo[2]() as fresh:
            verify_image_object_provenance(fresh, fresh.get(Image, image.image_revision_id), reuse_snapshot=True)
