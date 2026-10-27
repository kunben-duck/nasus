"""Actual PG read snapshots are local, bounded, immutable and never ACL grants."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence.image_read_snapshot import current_image_read_snapshot
from apps.api.app.infrastructure.persistence.object_provenance_models import ImageObjectProvenanceRecord as Root
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.image_provenance_reads import verify_image_provenance
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.tests.test_code_entity_registry import registry, pg_repo
from apps.api.tests.test_image_revision_repository import image_repo, inputs, writer, freeze


def fixture_image(image_repo, registry, tmp_path):
    manifest, objects = inputs(registry)
    image = freeze(writer(image_repo, tmp_path), manifest, objects)
    return image_repo[0], image, manifest, objects


def count_reads(repository, monkeypatch):
    original = repository._get
    calls = []

    def counted(session, *args):
        calls.append(args)
        return original(session, *args)

    monkeypatch.setattr(repository, "_get", counted)
    return calls


def test_one_verified_metadata_read_per_compilation_and_fresh_read_after_exit(image_repo, registry, tmp_path, monkeypatch):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    args = ("project", image.image_revision_id)
    calls = count_reads(repo, monkeypatch)
    with repo.verified_read_session():
        first = repo.get(*args)
        assert repo.get(*args) == first and len(calls) == 1
        session, cached = repo._read_snapshot.get()
        assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        assert set(cached) == {args}
    assert repo._read_snapshot.get() is None
    repo.get(*args)
    with repo.verified_read_session():
        repo.get(*args)
    assert len(calls) == 3


def test_nested_compilations_restore_outer_snapshot_and_do_not_share_cache(image_repo, registry, tmp_path, monkeypatch):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    args = ("project", image.image_revision_id)
    calls = count_reads(repo, monkeypatch)
    with repo.verified_read_session():
        repo.get(*args)
        outer = repo._read_snapshot.get()
        with repo.verified_read_session():
            assert repo._read_snapshot.get() is not outer
            repo.get(*args)
        assert repo._read_snapshot.get() is outer
        repo.get(*args)
    assert len(calls) == 2 and repo._read_snapshot.get() is None


def test_failed_or_wrong_project_read_is_not_memoized(image_repo, registry, tmp_path, monkeypatch):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    calls = count_reads(repo, monkeypatch)
    with repo.verified_read_session():
        repo.get("project", image.image_revision_id)
        for _ in range(2):
            with pytest.raises(KeyError):
                repo.get("other-project", image.image_revision_id)
        assert len(repo._read_snapshot.get()[1]) == 1
    assert len(calls) == 3


def test_snapshot_is_read_only_and_is_reset_after_exception(image_repo, registry, tmp_path):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    with pytest.raises(DBAPIError, match="read-only"):
        with repo.verified_read_session():
            repo.get("project", image.image_revision_id)
            session, _ = repo._read_snapshot.get()
            session.execute(delete(Root))
    assert repo._read_snapshot.get() is None
    assert repo.get("project", image.image_revision_id)


def test_concurrent_metadata_corruption_is_detected_by_next_compilation(image_repo, registry, tmp_path):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    args = ("project", image.image_revision_id)
    with image_repo[2].begin() as session:
        session.execute(text("ALTER TABLE image_object_provenance_roots DISABLE TRIGGER USER"))
    with repo.verified_read_session():
        original = repo.get(*args)
        # This corruption requires bypassing DB protection; it is confined to
        # this test's private schema. The active MVCC snapshot stays unchanged.
        with image_repo[2].begin() as session:
            session.execute(delete(Root))
        assert repo.get(*args) == original
    with image_repo[2].begin() as session:
        session.execute(text("ALTER TABLE image_object_provenance_roots ENABLE TRIGGER USER"))
    with pytest.raises(ImageRevisionIntegrityError, match="provenance"):
        with repo.verified_read_session():
            repo.get(*args)
    assert repo._read_snapshot.get() is None


def test_snapshot_cache_is_bounded_without_changing_its_database_view(image_repo, registry, tmp_path, monkeypatch):
    repo, first, manifest, objects = fixture_image(image_repo, registry, tmp_path)
    service = writer(image_repo, tmp_path)
    images = [first, *[freeze(service, manifest,
        [item.model_copy(update={"name": f"image-{index}"}) for item in objects], f"invoke-{index}")
        for index in range(2)]]
    calls = count_reads(repo, monkeypatch)
    with repo.verified_read_session():
        for image in images:
            repo.get("project", image.image_revision_id)
        assert len(repo._read_snapshot.get()[1]) == 2
        repo.get("project", first.image_revision_id)
        assert len(repo._read_snapshot.get()[1]) == 2
    assert len(calls) == 4


def test_fresh_metadata_session_reuses_only_complete_original_image_proof(image_repo, registry, tmp_path, monkeypatch):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    original, audits = ObjectProvenanceProjectorV1.image, []

    def audited(self, session, row, **kwargs):
        audits.append(session)
        return original(self, session, row, **kwargs)

    monkeypatch.setattr(ObjectProvenanceProjectorV1, "image", audited)
    with repo.verified_read_session():
        expected = repo.get("project", image.image_revision_id)
        snapshot = current_image_read_snapshot()[0]
        for _ in range(2):
            with image_repo[2]() as fresh:
                assert fresh is not snapshot
                row = fresh.get(ImageRevisionRecord, image.image_revision_id)
                verify_image_provenance(fresh, row, reuse_snapshot=True)
                assert repo._summary(row) == expected[0]
        assert audits == [snapshot]
    with image_repo[2]() as fresh:
        verify_image_provenance(fresh, fresh.get(ImageRevisionRecord, image.image_revision_id), reuse_snapshot=True)
    assert len(audits) == 2


@pytest.mark.parametrize("field", ["project_id", "artifact_hash", "manifest_hash"])
def test_cached_image_proof_cannot_validate_different_fresh_metadata(image_repo, registry, tmp_path, field):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    with repo.verified_read_session():
        repo.get("project", image.image_revision_id)
        with image_repo[2]() as fresh:
            row = fresh.get(ImageRevisionRecord, image.image_revision_id)
            setattr(row, field, "foreign-project" if field == "project_id" else "sha256:" + "0" * 64)
            with pytest.raises(ImageRevisionIntegrityError):
                verify_image_provenance(fresh, row, reuse_snapshot=True)


def test_ordinary_transaction_does_not_opt_into_another_sessions_proof(image_repo, registry, tmp_path, monkeypatch):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    original, audits = ObjectProvenanceProjectorV1.image, []

    def audited(self, session, row, **kwargs):
        audits.append(session)
        return original(self, session, row, **kwargs)

    monkeypatch.setattr(ObjectProvenanceProjectorV1, "image", audited)
    with repo.verified_read_session():
        repo.get("project", image.image_revision_id)
        with image_repo[2]() as fresh:
            verify_image_provenance(fresh, fresh.get(ImageRevisionRecord, image.image_revision_id))
            assert len(audits) == 2 and audits[-1] is fresh


@pytest.mark.parametrize("schedule", ["thread", "task", "delayed"])
def test_copied_context_reads_original_image_through_its_own_pg_snapshot(
        image_repo, registry, tmp_path, monkeypatch, schedule):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    args = ("project", image.image_revision_id)
    original_get, reads = repo._get, []

    def get(session, *keys):
        assert current_image_read_snapshot()[0] is session
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        reads.append((session, session.scalar(text("SELECT pg_backend_pid()"))))
        return original_get(session, *keys)

    monkeypatch.setattr(repo, "_get", get)

    async def run():
        def sibling():
            assert current_image_read_snapshot() is None
            with repo.verified_read_session():
                assert repo.get(*args) == expected
                assert repo.get(*args) == expected
            assert current_image_read_snapshot() is None

        with repo.verified_read_session():
            expected = repo.get(*args)
            parent = current_image_read_snapshot()
            copied = copy_context()
            if schedule == "thread":
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(copied.run, sibling).result(timeout=30)
            elif schedule == "task":
                async def child():
                    sibling()
                await asyncio.create_task(child())
            if schedule != "delayed":
                assert current_image_read_snapshot() is parent
                assert repo.get(*args) == expected
                assert reads[0][1] != reads[1][1]
        if schedule == "delayed":
            copied.run(sibling)

    asyncio.run(run())
    assert len(reads) == 2 and reads[0][0] is not reads[1][0]
    assert repo._read_snapshot.get() is None and current_image_read_snapshot() is None


def test_cancelled_child_releases_its_pg_connection_without_closing_parent(
        image_repo, registry, tmp_path, monkeypatch):
    repo, image, _, _ = fixture_image(image_repo, registry, tmp_path)
    args = ("project", image.image_revision_id)
    calls = count_reads(repo, monkeypatch)

    async def run():
        entered = asyncio.Event()
        with repo.verified_read_session():
            expected = repo.get(*args)
            parent = current_image_read_snapshot()

            async def child():
                with repo.verified_read_session():
                    assert repo.get(*args) == expected
                    assert current_image_read_snapshot()[0] is not parent[0]
                    entered.set()
                    await asyncio.Event().wait()

            task = asyncio.create_task(child())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert current_image_read_snapshot() is parent
            assert parent[0].scalar(text("SELECT 1")) == 1
            assert repo.get(*args) == expected

    asyncio.run(run())
    assert len(calls) == 2 and repo._read_snapshot.get() is None
