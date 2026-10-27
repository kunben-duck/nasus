"""Canonical context proofs in real PG; no target or business-gold claims."""
from collections import Counter
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
import asyncio

import pytest
from sqlalchemy import event, text, update
from sqlalchemy.engine import Engine

from apps.api.app.domain.system_image.context_pack import ContextPackIntegrityError
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.context_pack_models import ContextPackRecord
from apps.api.app.infrastructure.persistence.context_pack_repository import ContextPackRepository
from apps.api.app.infrastructure.persistence.context_provenance_models import ContextProvenanceAnchorRecord as Anchor
from apps.api.app.infrastructure.persistence.context_provenance_projection_v1 import ContextProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.image_read_snapshot import (
    CONTEXT_PROVENANCE_CACHE, current_image_read_snapshot, image_read_snapshot_scope,
)
from apps.api.app.infrastructure.persistence.publication_provenance_projection_v1 import PublicationProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.image_publication_models import ImagePublicationRecord, ImagePublicationReviewRecord
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.relation_provenance_projection_v1 import RelationProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.retrieval_provenance_projection_v1 import RetrievalProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_context_provenance_api import archived, acceptance, documents, evidence_api
from apps.api.tests.test_context_packs_api import archive, read
from apps.api.tests.test_image_publications_api import publication
from apps.api.tests.test_published_context_packs import preview_response, request_for
from apps.api.tests.test_published_image_reads import publish
from apps.api.tests.test_semantic_evaluations_api import completed


def observed_proofs(monkeypatch):
    counts, sessions = Counter(), []
    for owner, name, phase in ((ContextProvenanceProjectorV1, "expected", "source"),
            (PublicationProvenanceProjectorV1, "context", "publication"),
            (RetrievalProvenanceProjectorV1, "context", "retrieval")):
        original = getattr(owner, name)

        def counted(self, session, *args, original=original, phase=phase, **kwargs):
            counts[phase] += 1
            sessions.append((phase, session))
            return original(self, session, *args, **kwargs)

        monkeypatch.setattr(owner, name, counted)
    return counts, sessions


def test_context_immutable_proof_reused_only_in_owned_snapshot_and_live_proofs_stay_fresh(archived, monkeypatch):
    _, view, _ = archived
    metadata = view["metadata"]
    repo = ContextPackRepository()
    args = metadata["project_id"], metadata["context_id"]
    counts, sessions = observed_proofs(monkeypatch)
    with image_read_snapshot_scope() as snapshot:
        assert snapshot.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert snapshot.scalar(text("SHOW transaction_read_only")) == "on"
        repo.verify_provenance(*args)
        initial = counts["source"]
        assert initial > 0
        repo.verify_provenance(*args)
        assert counts["source"] == initial
        assert counts["publication"] == counts["retrieval"] == 2
        assert all(session is snapshot for phase, session in sessions if phase == "source")
        live_sessions = [session for phase, session in sessions if phase == "publication"]
        assert live_sessions[0] is not live_sessions[1]
        assert all(session is not snapshot for phase, session in sessions if phase != "source")
        assert len(snapshot.info[CONTEXT_PROVENANCE_CACHE]) == 1
    assert CONTEXT_PROVENANCE_CACHE not in snapshot.info
    repo.verify_provenance(*args)
    assert counts["source"] > initial
    assert counts["publication"] == counts["retrieval"] == 3


def test_without_owned_snapshot_context_proof_is_reverified_on_every_read(archived, monkeypatch):
    _, view, _ = archived
    metadata = view["metadata"]
    counts, _ = observed_proofs(monkeypatch)
    repo = ContextPackRepository()
    repo.verify_provenance(metadata["project_id"], metadata["context_id"])
    first = counts["source"]
    repo.verify_provenance(metadata["project_id"], metadata["context_id"])
    assert counts["source"] == first * 2 and first > 0
    assert counts["publication"] == counts["retrieval"] == 2


def test_newly_committed_context_uses_complete_fresh_proof_not_snapshot_absence(archived, monkeypatch):
    v, original, _ = archived
    repo = ContextPackRepository()
    with image_read_snapshot_scope() as snapshot:
        repo.verify_provenance(v["project_id"], original["metadata"]["context_id"])
        newer, _ = read(v, completed(archive(v)[0]))
        ident = newer["metadata"]["context_id"]
        assert snapshot.get(ContextPackRecord, ident) is None
        counts, sessions = observed_proofs(monkeypatch)
        repo.verify_provenance(v["project_id"], ident)
        first = counts["source"]
        repo.verify_provenance(v["project_id"], ident)
        assert counts["source"] == first * 2 and first > 0
        assert all(session is not snapshot for _, session in sessions)
        assert (v["project_id"], ident) not in snapshot.info[CONTEXT_PROVENANCE_CACHE]


def test_complete_context_metadata_matches_and_actual_all_pool_sql_is_reduced(archived, monkeypatch):
    _, view, _ = archived
    args = view["metadata"]["project_id"], view["metadata"]["context_id"]
    repo = ContextPackRepository()
    counts, _ = observed_proofs(monkeypatch)

    def measure(reuse):
        statements, inputs = Counter(), []

        def statement(connection, _cursor, sql, _parameters, _context, _many):
            statements["total"] += 1
            statements["primary" if connection.engine is engine else "snapshot"] += 1
            assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
            assert "FOR UPDATE" not in sql.upper()

        event.listen(Engine, "before_cursor_execute", statement)
        try:
            with image_read_snapshot_scope() if reuse else nullcontext():
                for _ in range(2):
                    repo.verify_provenance(*args)
                    inputs.append(snapshot_digest(repo.get(*args)))
        finally:
            event.remove(Engine, "before_cursor_execute", statement)
        return statements, inputs

    control, original = measure(False)
    actual, replayed = measure(True)
    assert replayed == original and len(set(original)) == 1
    assert actual["total"] < control["total"] and actual["snapshot"] > 0
    assert counts["publication"] == counts["retrieval"] == 4


@pytest.mark.parametrize("phase", ["source", "relation", "publication", "retrieval"])
def test_failed_proof_never_memoizes_failure_or_suppresses_live_failure(archived, monkeypatch, phase):
    _, view, _ = archived
    metadata = view["metadata"]
    owner, name = {"source": (ContextProvenanceProjectorV1, "expected"),
        "relation": (RelationProvenanceProjectorV1, "context"),
        "publication": (PublicationProvenanceProjectorV1, "context"),
        "retrieval": (RetrievalProvenanceProjectorV1, "context")}[phase]
    original, calls = getattr(owner, name), []
    error = ContextPackIntegrityError("explicit immutable proof failure specimen")

    def failed(self, session, *args, **kwargs):
        calls.append(session)
        raise error

    monkeypatch.setattr(owner, name, failed)
    repo = ContextPackRepository()
    with image_read_snapshot_scope() as snapshot:
        for _ in range(2):
            with pytest.raises(ContextPackIntegrityError) as caught:
                repo.verify_provenance(metadata["project_id"], metadata["context_id"])
            assert caught.value is error
        assert len(calls) == 2
        if phase in {"source", "relation"}:
            assert not snapshot.info[CONTEXT_PROVENANCE_CACHE]
        monkeypatch.setattr(owner, name, original)
        repo.verify_provenance(metadata["project_id"], metadata["context_id"])
    assert CONTEXT_PROVENANCE_CACHE not in snapshot.info


def test_wrong_project_and_changed_metadata_cannot_use_successful_proof(archived):
    _, view, _ = archived
    metadata = view["metadata"]
    repo = ContextPackRepository()
    with image_read_snapshot_scope() as snapshot:
        repo.verify_provenance(metadata["project_id"], metadata["context_id"])
        for _ in range(2):
            with pytest.raises(KeyError):
                repo.verify_provenance("foreign-project", metadata["context_id"])
        assert len(snapshot.info[CONTEXT_PROVENANCE_CACHE]) == 1
        row = snapshot.get(ContextPackRecord, metadata["context_id"])
        original = row.payload
        row.payload = {**deepcopy(original), "image_revision_id": "foreign-image"}
        try:
            with pytest.raises(ContextPackIntegrityError):
                repo.verify_provenance(metadata["project_id"], metadata["context_id"])
        finally:
            row.payload = original
        repo.verify_provenance(metadata["project_id"], metadata["context_id"])


def test_next_operation_rechecks_corrupt_anchor_from_real_second_pg_connection(archived):
    _, view, _ = archived
    metadata = view["metadata"]
    args = metadata["project_id"], metadata["context_id"]
    repo = ContextPackRepository()
    with session_scope() as session:
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        original = session.get(Anchor, args).query_scope_fingerprint

    def replace(value):
        with session_scope() as session:
            session.execute(text("ALTER TABLE system_image_context_provenance_anchors DISABLE TRIGGER USER"))
            session.execute(update(Anchor).where(Anchor.project_id == args[0], Anchor.context_id == args[1])
                .values(query_scope_fingerprint=value))
            session.execute(text("ALTER TABLE system_image_context_provenance_anchors ENABLE TRIGGER USER"))

    try:
        with image_read_snapshot_scope():
            repo.verify_provenance(*args)
            replace("sha256:" + "0" * 64)
            repo.verify_provenance(*args)
        with pytest.raises(ContextPackIntegrityError), image_read_snapshot_scope():
            repo.verify_provenance(*args)
    finally:
        replace(original)
    with image_read_snapshot_scope():
        repo.verify_provenance(*args)


def test_context_proof_cache_is_bounded_and_nested_snapshots_restore_the_parent(archived, monkeypatch):
    v, first, _ = archived
    views = [first, *[read(v, completed(archive(v)[0]))[0] for _ in range(2)]]
    repo = ContextPackRepository()
    counts, _ = observed_proofs(monkeypatch)
    with image_read_snapshot_scope() as outer:
        for view in views:
            repo.verify_provenance(view["metadata"]["project_id"], view["metadata"]["context_id"])
        assert len(outer.info[CONTEXT_PROVENANCE_CACHE]) == 2
        before = counts["source"]
        repo.verify_provenance(v["project_id"], first["metadata"]["context_id"])
        assert counts["source"] > before and len(outer.info[CONTEXT_PROVENANCE_CACHE]) == 2
        with image_read_snapshot_scope() as child:
            repo.verify_provenance(v["project_id"], first["metadata"]["context_id"])
            assert child is not outer and len(child.info[CONTEXT_PROVENANCE_CACHE]) == 1
        assert CONTEXT_PROVENANCE_CACHE not in child.info
        assert current_image_read_snapshot()[0] is outer
        before = counts["source"]
        repo.verify_provenance(v["project_id"], first["metadata"]["context_id"])
        assert counts["source"] == before
    assert CONTEXT_PROVENANCE_CACHE not in outer.info


@pytest.mark.parametrize("schedule", ["thread", "task", "delayed"])
def test_copied_context_cannot_borrow_another_task_thread_or_finished_snapshot(archived, monkeypatch, schedule):
    _, view, _ = archived
    metadata = view["metadata"]
    args = metadata["project_id"], metadata["context_id"]
    repo = ContextPackRepository()
    counts, sessions = observed_proofs(monkeypatch)

    async def run():
        def sibling():
            assert current_image_read_snapshot() is None
            with image_read_snapshot_scope() as own:
                repo.verify_provenance(*args)
                repo.verify_provenance(*args)
                assert len(own.info[CONTEXT_PROVENANCE_CACHE]) == 1
            assert CONTEXT_PROVENANCE_CACHE not in own.info

        with image_read_snapshot_scope() as parent:
            repo.verify_provenance(*args)
            copied = copy_context()
            if schedule == "thread":
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(copied.run, sibling).result(timeout=30)
            elif schedule == "task":
                async def child():
                    sibling()
                await asyncio.create_task(child())
            before = counts["source"]
            repo.verify_provenance(*args)
            assert counts["source"] == before
        if schedule == "delayed":
            copied.run(sibling)
        assert CONTEXT_PROVENANCE_CACHE not in parent.info

    asyncio.run(run())
    assert counts["source"] == 4
    assert len({id(session) for phase, session in sessions if phase == "source"}) == 2


def test_all_pool_sql_observer_includes_actual_primary_and_read_snapshot_engines():
    observed = Counter()

    def statement(connection, _cursor, _sql, _parameters, _context, _many):
        observed["primary" if connection.engine is engine else "snapshot"] += 1

    event.listen(Engine, "before_cursor_execute", statement)
    try:
        with session_scope() as session:
            assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        with image_read_snapshot_scope() as snapshot:
            assert snapshot.get_bind() is not engine
            assert snapshot.scalar(text("SHOW transaction_read_only")) == "on"
    finally:
        event.remove(Engine, "before_cursor_execute", statement)
    assert observed["primary"] > 0 and observed["snapshot"] > 0
    before = observed.copy()
    with session_scope() as session:
        session.scalar(text("SELECT 1"))
    assert observed == before


@pytest.mark.parametrize("command_kind", ["compile", "publication", "review"])
def test_published_context_rechecks_original_commands_while_image_proof_is_reused(publication, monkeypatch, command_kind):
    v = publication
    head = publish(v)
    preview = preview_response(v, request_for(v, head))
    assert preview.status_code == 200, preview.text
    view, _ = read(v, completed(archive(v, preview.json())[0]))
    metadata = view["metadata"]
    repo = ContextPackRepository()
    args = metadata["project_id"], metadata["context_id"]
    original_audit, audits = ObjectProvenanceProjectorV1.image, []

    def audited(self, session, image, **kwargs):
        audits.append(session)
        return original_audit(self, session, image, **kwargs)

    monkeypatch.setattr(ObjectProvenanceProjectorV1, "image", audited)
    with session_scope() as session:
        native = session.get(ImagePublicationRecord, head["publication_id"])
        if command_kind == "compile":
            command_id, field = metadata["invocation_id"], "expected_input_digest"
        elif command_kind == "publication":
            command_id, field = native.invocation_id, "expected_preview_digest"
        else:
            command_id = session.get(ImagePublicationReviewRecord, native.approval_id).invocation_id
            field = "reason"
        original = deepcopy(session.get(ToolInvocationRecord, command_id).input_payload)

    def replace(payload):
        with session_scope() as session:
            session.get(ToolInvocationRecord, command_id).input_payload = deepcopy(payload)

    try:
        with image_read_snapshot_scope() as snapshot:
            repo.verify_provenance(*args)
            repo.verify_provenance(*args)
            assert audits == [snapshot]
            changed = "explicit changed review reason" if field == "reason" else "sha256:" + "0" * 64
            replace({**original, field: changed})
            with pytest.raises(ContextPackIntegrityError):
                repo.verify_provenance(*args)
    finally:
        replace(original)
    with image_read_snapshot_scope():
        repo.verify_provenance(*args)
    assert len(audits) == 2


@pytest.mark.parametrize("write", [False, True])
def test_context_publication_write_rechecks_native_graph_in_its_own_transaction(publication, monkeypatch, write):
    v = publication
    head = publish(v)
    preview = preview_response(v, request_for(v, head))
    assert preview.status_code == 200, preview.text
    view, _ = read(v, completed(archive(v, preview.json())[0]))
    args = v["project_id"], view["metadata"]["context_id"]
    original, audits = ObjectProvenanceProjectorV1.image, []

    def audited(self, session, image, **kwargs):
        audits.append(session)
        return original(self, session, image, **kwargs)

    monkeypatch.setattr(ObjectProvenanceProjectorV1, "image", audited)
    with image_read_snapshot_scope() as snapshot:
        ContextPackRepository().verify_provenance(*args)
        assert audits == [snapshot]
        with session_scope() as fresh:
            row = fresh.get(ContextPackRecord, args[1])
            PublicationProvenanceProjectorV1().context(fresh, row, write=write)
            assert audits == ([snapshot, fresh] if write else [snapshot])
