"""Actual read-scope wiring with explicit parent/transaction specimens, not PG proof."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.run_plans import RunPlanApplicationService
from apps.api.app.application.system_image.generation_sources import ImageGenerationSourceInventory
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence import http_fixture_journal_repository as journals
from apps.api.app.infrastructure.persistence.http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from apps.api.tests.test_http_fixture_journal_access import saved_inputs


@pytest.fixture
def reader(monkeypatch):
    access, scope, _manifest, view = saved_inputs()
    images = ImageRevisionQueryApplicationService(None, None, None)
    sources = ImageGenerationSourceInventory(images)
    plans = RunPlanApplicationService(None, None, sources, SimpleNamespace(), None, None)
    state = SimpleNamespace(reads=0, proofs=0, revoked_at=None, error_at=None, scopes=[])

    def original_read(project_id, plan_id):
        assert (project_id, plan_id) == (scope.project_id, access.parent.run_plan_id)
        state.reads += 1
        proof = images._current_verified_reads()
        assert proof is not None
        state.scopes.append(images._verified_read_scope.get())
        if state.reads == state.revoked_at:
            raise SourceAccessDenied("explicit current source revocation")
        if state.reads == state.error_at:
            raise RuntimeError("explicit original archive failure")
        if "original" not in proof:
            proof["original"] = True
            state.proofs += 1
        # Only immutable proof is shared, never this live result or its guards.
        return deepcopy(view)

    plans.read = original_read
    access.plans = plans
    monkeypatch.setattr(journals, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    journal = journals.PostgresHttpFixtureDispatchJournal(access, None, actor_id="scope-actor-specimen")

    @contextmanager
    def transaction_specimen():
        yield None

    monkeypatch.setattr(journals, "session_scope", transaction_specimen)
    monkeypatch.setattr(journal, "_lock", lambda *_args: pytest.fail("fixture inspection is read-only"))
    monkeypatch.setattr(journal, "_parent", lambda *_args: None)
    def actor(_session, project_id, actor_id, *, lock):
        assert (project_id, actor_id, lock) == (scope.project_id, "scope-actor-specimen", False)
    monkeypatch.setattr(journals.NativeBuildRepository, "_actor", staticmethod(actor))
    monkeypatch.setattr(journal, "_records", lambda *_args: (None, None))
    return SimpleNamespace(access=access, scope=scope, images=images, journal=journal,
        work=PostgresHttpFixtureWorkRepository(journal), state=state)


def test_journal_inspection_reuses_immutable_proof_but_not_live_original_reads(reader):
    v = reader
    assert v.journal.inspect(v.scope, "setup") is None
    assert (v.state.reads, v.state.proofs) == (2, 1)
    assert v.images._current_verified_reads() is None
    assert all(not value.is_open for value in v.state.scopes)
    assert v.journal.inspect(v.scope, "setup") is None
    assert (v.state.reads, v.state.proofs) == (4, 2)


@pytest.mark.parametrize("status", ["absent", "reserved", "observed"])
@pytest.mark.parametrize("revoke", [False, True])
def test_readonly_journal_revalidates_original_scope_on_both_sides_of_the_read(reader, monkeypatch, status, revoke):
    v = reader
    steps, execution = [], object()
    original = v.access.plans.read

    def plan(*args):
        steps.append("original_scope")
        return original(*args)

    def records(*_args):
        steps.append("journal_records")
        if revoke:
            v.state.revoked_at = v.state.reads + 1
        return (None if status == "absent" else {}, {} if status == "observed" else None)

    def archive(*_args):
        steps.append("original_result_archive")
        return execution, None

    monkeypatch.setattr(v.access.plans, "read", plan)
    monkeypatch.setattr(v.journal, "_records", records)
    monkeypatch.setattr(v.journal, "_read_verified_result", archive)
    if revoke:
        with pytest.raises(SourceAccessDenied):
            v.journal.inspect(v.scope, "setup", read_only=True)
    else:
        result = v.journal.inspect(v.scope, "setup", read_only=True)
        if status == "absent":
            assert result is None
        else:
            assert result.execution is (execution if status == "observed" else None)
    assert steps == ["original_scope", "journal_records",
        *(["original_result_archive"] if status == "observed" else []), "original_scope"]
    assert (v.state.reads, v.state.proofs) == (2, 1)
    assert v.images._current_verified_reads() is None


@pytest.mark.parametrize("revoked_before", ["records", "archive"])
def test_readonly_journal_checks_current_access_before_protected_reads(reader, monkeypatch, revoked_before):
    v = reader
    reads = []

    def current():
        if ("archive" if reads else "records") == revoked_before:
            raise SourceAccessDenied("source access changed before reading original fixture evidence")

    def records(*_args):
        reads.append("records")
        return {}, {}

    monkeypatch.setattr(v.journal, "_records", records)
    monkeypatch.setattr(v.journal, "_read_verified_result", lambda *_: pytest.fail("revoked archive was read"))
    with pytest.raises(SourceAccessDenied):
        v.journal.inspect(v.scope, "setup", read_only=True, require_current=current)
    assert reads == ([] if revoked_before == "records" else ["records"])
    assert v.state.reads == 1 and v.images._current_verified_reads() is None


def test_phase_port_shares_original_proof_across_journal_operations_only(reader):
    v = reader
    with v.journal.verified_read_session():
        assert v.journal.inspect(v.scope, "setup") is None
        assert v.access.require_scope(v.scope) == v.access.parent.model_dump(mode="json")
        assert v.journal.inspect(v.scope, "setup") is None
        assert (v.state.reads, v.state.proofs) == (5, 1)
        original = v.images._verified_read_scope.get()
        assert original.is_current
        v.state.revoked_at = 6
        with pytest.raises(SourceAccessDenied):
            v.access.require_scope(v.scope)
        assert (v.state.reads, v.state.proofs) == (6, 1)
    assert not original.is_open and v.images._current_verified_reads() is None
    v.state.revoked_at = None
    assert v.journal.inspect(v.scope, "setup") is None
    assert (v.state.reads, v.state.proofs) == (8, 2)


@pytest.mark.parametrize("stage", [1, 2])
@pytest.mark.parametrize("failure", ["revoked_at", "error_at"])
def test_every_original_guard_still_fails_and_closes_the_operation(reader, stage, failure):
    v = reader
    setattr(v.state, failure, stage)
    with pytest.raises(SourceAccessDenied if failure == "revoked_at" else RuntimeError):
        v.journal.inspect(v.scope, "setup")
    assert v.images._current_verified_reads() is None
    assert all(not value.is_open for value in v.state.scopes)
    assert v.state.reads == stage
    setattr(v.state, failure, None)
    assert v.journal.inspect(v.scope, "setup") is None
    assert v.state.reads == stage + 2


@pytest.mark.parametrize("method", ["claim", "complete", "acquire", "require", "renew"])
def test_write_and_lease_entrypoints_share_only_their_own_read_operation(reader, monkeypatch, method):
    v = reader
    owner = v.journal if method in {"claim", "complete"} else v.work
    callback = lambda: None
    args = {"claim": (v.scope, "setup", "original-command"),
        "complete": (v.scope, "setup", "original-command", "original-execution"),
        "acquire": (v.scope, "setup", "original-owner"),
        "require": ("original-lease",), "renew": ("original-lease",)}[method]
    options = {} if method == "require" else {"require_current": callback}

    def original_stage(*actual_args, **actual_options):
        assert actual_args == args and actual_options == options
        assert v.access.require_scope(v.scope) == v.access.parent.model_dump(mode="json")
        assert v.access.require_scope(v.scope) == v.access.parent.model_dump(mode="json")
        return "original-result"

    monkeypatch.setattr(owner, "_" + method, original_stage)
    assert getattr(owner, method)(*args, **options) == "original-result"
    assert (v.state.reads, v.state.proofs) == (2, 1)
    assert v.images._current_verified_reads() is None
    v.state.revoked_at = 4
    with pytest.raises(SourceAccessDenied):
        getattr(owner, method)(*args, **options)
    assert (v.state.reads, v.state.proofs) == (4, 2)
    assert all(not value.is_open for value in v.state.scopes)


def test_child_tasks_and_threads_do_not_inherit_a_parent_journal_proof(reader):
    v = reader

    async def check():
        with v.access.verified_read_session():
            assert v.journal.inspect(v.scope, "setup") is None
            parent = v.images._verified_read_scope.get()
            assert parent.is_current and (v.state.reads, v.state.proofs) == (2, 1)

            async def child():
                assert v.images._current_verified_reads() is None
                assert v.journal.inspect(v.scope, "setup") is None
                assert v.images._current_verified_reads() is None

            await asyncio.create_task(child())
            assert parent.is_current and (v.state.reads, v.state.proofs) == (4, 2)
            assert await asyncio.to_thread(v.journal.inspect, v.scope, "setup") is None
            assert parent.is_current and (v.state.reads, v.state.proofs) == (6, 3)
            assert v.journal.inspect(v.scope, "setup") is None
            assert (v.state.reads, v.state.proofs) == (8, 3)
        assert not parent.is_open and v.images._current_verified_reads() is None
        assert all(not value.is_open for value in v.state.scopes)

    asyncio.run(check())


def test_ports_without_optional_read_session_keep_all_original_checks(reader, monkeypatch):
    v = reader
    monkeypatch.setattr(v.access.plans, "verified_read_session", None)
    with v.access.verified_read_session():
        assert v.images._current_verified_reads() is None
    monkeypatch.setattr(v.access, "verified_read_session", None)
    with v.journal._read_session(), v.work._read_session():
        assert v.images._current_verified_reads() is None
