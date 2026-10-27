"""Scheduling specimens: copied contexts must not extend a verified read scope."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from contextvars import copy_context
from copy import deepcopy
from threading import get_ident
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.application.system_image.evidence_queries import EvidenceReadTarget
from apps.api.app.domain.system_image.evidence import DECODER_VERSION, EvidenceLocator, SourceEvidence, text_digest
from apps.api.app.domain.system_image.image_revision import ImageArtifactUnavailable, build_image_artifact
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence import image_read_snapshot as snapshots
from apps.api.app.infrastructure.persistence import image_revision_repository as repositories
from apps.api.app.infrastructure.system_image.evidence_source_reader import ArchivedEvidenceSourceReader
from apps.api.tests.test_image_revision import candidate, header


def factory(monkeypatch):
    opened = []

    def create():
        session = SimpleNamespace(owner=get_ident(), closed=False, rollback_count=0)

        def execute(statement):
            assert session.owner == get_ident() and not session.closed

        def rollback():
            session.rollback_count += 1

        def close():
            session.closed = True

        session.connection = lambda **kwargs: None
        session.execute, session.rollback, session.close = execute, rollback, close
        opened.append(session)
        return session

    @contextmanager
    def independent_session():
        session = create()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    monkeypatch.setattr(snapshots, "_session_factory", lambda: create)
    monkeypatch.setattr(repositories, "session_scope", independent_session)
    return opened


def query(monkeypatch):
    opened = factory(monkeypatch)
    payload, _ = build_image_artifact(candidate()[0], "baseline", *candidate()[1:])
    original_header = header(payload)
    bindings = {item["binding_id"] for item in payload["source_members"]}
    scope = SimpleNamespace(actor_id="actor", fingerprint="original", acl_epoch=1, binding_ids=bindings)
    calls = {"metadata": [], "artifacts": [], "authority": []}
    repository = repositories.ImageRevisionRepository()

    def get(session, project_id, image_id):
        assert not session.closed and session.owner == get_ident()
        calls["metadata"].append(session)
        return original_header, "private-original", bindings

    def read(project_id, ref, digest):
        calls["artifacts"].append((get_ident(), ref, digest))
        return deepcopy(payload)

    allowed = [True]

    def current(value):
        calls["authority"].append(value)
        if not allowed[0]:
            raise SourceAccessDenied("original source authority was revoked")

    monkeypatch.setattr(repository, "_get", get)
    images = ImageRevisionQueryApplicationService(repository, SimpleNamespace(read=read),
        SimpleNamespace(scope=lambda project: scope, require_current=current))
    return images, opened, calls, allowed, (original_header.project_id, original_header.image_revision_id)


def test_closed_snapshot_is_not_reopened_by_a_delayed_context(monkeypatch):
    opened = factory(monkeypatch)
    with snapshots.image_read_snapshot_scope() as original:
        copied = copy_context()
        assert snapshots.current_image_read_snapshot()[0] is original
    assert original.closed

    def delayed():
        assert snapshots.current_image_read_snapshot() is None
        with snapshots.image_read_snapshot_scope() as own:
            assert own is not original and not own.closed
        assert snapshots.current_image_read_snapshot() is None

    copied.run(delayed)
    assert len(opened) == 2 and all(value.closed and value.rollback_count == 1 for value in opened)


@pytest.mark.parametrize("schedule", ["thread", "task"])
def test_snapshot_connection_never_crosses_execution_identity(monkeypatch, schedule):
    factory(monkeypatch)

    async def run():
        with snapshots.image_read_snapshot_scope() as original:
            copied = copy_context()

            def sibling():
                assert snapshots.current_image_read_snapshot() is None
                with snapshots.image_read_snapshot_scope() as own:
                    assert own is not original and snapshots.current_image_read_snapshot()[0] is own
                assert snapshots.current_image_read_snapshot() is None

            if schedule == "thread":
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(copied.run, sibling).result(timeout=5)
            else:
                async def child():
                    sibling()
                await asyncio.create_task(child())
            assert snapshots.current_image_read_snapshot()[0] is original and not original.closed

    asyncio.run(run())


@pytest.mark.parametrize("schedule", ["thread", "task", "delayed"])
@pytest.mark.parametrize("join", [False, True])
def test_complete_query_cannot_reuse_another_execution_or_closed_operation(monkeypatch, schedule, join):
    images, opened, calls, _, args = query(monkeypatch)

    async def run():
        def sibling():
            if join:
                with images.verified_read_session(reuse=True):
                    images.frozen_snapshot(*args)
                    images.frozen_snapshot(*args)
            else:
                images.frozen_snapshot(*args)
                images.frozen_snapshot(*args)

        with images.verified_read_session():
            images.frozen_snapshot(*args)
            copied = copy_context()
            if schedule == "thread":
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(copied.run, sibling).result(timeout=5)
            elif schedule == "task":
                async def child():
                    sibling()
                await asyncio.create_task(child())
            if schedule != "delayed":
                images.frozen_snapshot(*args)
                assert len(calls["artifacts"]) == (2 if join else 3)
                assert len(calls["metadata"]) == (2 if join else 3)
        if schedule == "delayed":
            copied.run(sibling)
            assert len(calls["artifacts"]) == (2 if join else 3)
            assert len(calls["metadata"]) == (2 if join else 3)

    asyncio.run(run())
    assert images._verified_reads.get() is None and images.repository._read_snapshot.get() is None
    assert len(opened) == (2 if join else 3)
    assert all(value.closed and value.rollback_count == 1 for value in opened)


def test_local_reuse_keeps_live_authority_and_returns_isolated_verified_bytes(monkeypatch):
    images, opened, calls, allowed, args = query(monkeypatch)
    with images.verified_read_session():
        first = images.frozen_snapshot(*args)
        first[1]["objects"].clear()
        with images.verified_read_session(reuse=True):
            second = images.frozen_snapshot(*args)
        assert second[1]["objects"]
        assert len(calls["artifacts"]) == len(calls["metadata"]) == 1
        before = len(calls["authority"])
        allowed[0] = False
        with pytest.raises(SourceAccessDenied, match="revoked"):
            images.frozen_snapshot(*args)
        assert len(calls["authority"]) > before and len(calls["artifacts"]) == 1
    assert len(opened) == 1 and opened[0].closed


def test_cancelled_child_closes_only_its_own_query_operation(monkeypatch):
    images, opened, calls, _, args = query(monkeypatch)

    async def run():
        entered = asyncio.Event()
        with images.verified_read_session():
            images.frozen_snapshot(*args)
            parent = snapshots.current_image_read_snapshot()[0]

            async def child():
                with images.verified_read_session(reuse=True):
                    images.frozen_snapshot(*args)
                    entered.set()
                    await asyncio.Event().wait()

            task = asyncio.create_task(child())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not parent.closed
            images.frozen_snapshot(*args)

    asyncio.run(run())
    assert len(opened) == 2 and all(value.closed for value in opened)
    assert len(calls["metadata"]) == len(calls["artifacts"]) == 2


def test_delayed_query_must_reverify_missing_original_artifact(monkeypatch):
    images, _, calls, _, args = query(monkeypatch)
    with images.verified_read_session():
        images.frozen_snapshot(*args)
        copied = copy_context()

    def unavailable(*args):
        raise ImageArtifactUnavailable("original archive is unavailable")

    monkeypatch.setattr(images.artifacts, "read", unavailable)
    with pytest.raises(ImageArtifactUnavailable, match="unavailable"):
        copied.run(images.frozen_snapshot, *args)
    assert len(calls["metadata"]) == 2


@pytest.mark.parametrize("schedule", ["thread", "task", "delayed"])
@pytest.mark.parametrize("join", [False, True])
def test_evidence_manifest_proof_does_not_cross_or_outlive_its_operation(monkeypatch, schedule, join):
    body = b"original code\n"
    reads = {"manifest": [], "raw": []}
    evidence = SourceEvidence("evidence", "project", "binding", "source-revision",
        EvidenceLocator("src.py", 1, 1, "exact"), text_digest(body.decode()),
        text_digest(body.decode()), "private-original", DECODER_VERSION, "extractor", "now")
    target = EvidenceReadTarget(evidence, "source", "original-manifest", "sha256:" + "a" * 64,
        "sha256:" + "b" * 64)

    def raw(ref, **kwargs):
        assert ref == evidence.object_ref
        reads["raw"].append(get_ident())
        return body

    reader = ArchivedEvidenceSourceReader(SimpleNamespace(read_session=lambda: nullcontext(), get_bytes=raw))

    def manifest(*args, **kwargs):
        reads["manifest"].append(get_ident())
        return {"files": [{"path": "src.py", "content_hash": evidence.file_hash,
            "content_ref": evidence.object_ref, "byte_count": len(body)}]}

    monkeypatch.setattr(reader.archive, "read_manifest", manifest)

    async def run():
        def sibling():
            with reader.verified_read_session() if join else nullcontext():
                assert reader.read(target) == body
                assert reader.read(target) == body

        with reader.verified_read_session():
            assert reader.read(target) == body
            copied = copy_context()
            if schedule == "thread":
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(copied.run, sibling).result(timeout=5)
            elif schedule == "task":
                async def child():
                    sibling()
                await asyncio.create_task(child())
            if schedule != "delayed":
                assert reader.read(target) == body
        if schedule == "delayed":
            copied.run(sibling)

    asyncio.run(run())
    assert len(reads["manifest"]) == (2 if join else 3)
    assert len(reads["raw"]) == (3 if schedule == "delayed" else 4)
    assert reader._manifests.get() is None
