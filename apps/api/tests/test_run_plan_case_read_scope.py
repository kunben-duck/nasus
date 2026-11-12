"""Actual operation-scope composition; original records/target remain protocol specimens."""
import asyncio
from contextvars import copy_context
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.run_plans import RunPlanApplicationService
from apps.api.app.application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
from apps.api.app.application.system_image.generation_sources import ImageGenerationSourceInventory
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged
from apps.api.app.domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_run_plan_case_inputs import case_inputs, spec
from apps.api.tests.test_run_plan_fixture_handoff import fixture_inputs


def verified_scope(v, monkeypatch):
    images = ImageRevisionQueryApplicationService(SimpleNamespace(), SimpleNamespace(), v.authority)
    plans = RunPlanApplicationService(None, None, ImageGenerationSourceInventory(images), v.authority, None, None)
    monkeypatch.setattr(v.service.original_inputs, "plans", plans, raising=False)
    reads = []

    def observe(port, name):
        operation = getattr(port, name)

        def read(*args, **kwargs):
            cache = images._current_verified_reads()
            assert cache is not None and images._verified_read_scope.get().is_current
            reads.append((name, cache))
            return operation(*args, **kwargs)

        monkeypatch.setattr(port, name, read)

    for port, name in ((v.service.commands, "original_command"), (v.service.original_inputs, "original_inputs"),
            (v.service.environments, "read"), (v.service.locators, "read"), (v.fixtures, "read"),
            (v.fixtures, "read_native"), (v.service.health, "probe_pinned_inventory")):
        observe(port, name)
    return images, plans, reads


@pytest.mark.parametrize("fixture", ["case_inputs", "fixture_inputs"])
def test_full_input_verification_shares_one_scope_but_each_fence_and_history_is_fresh(request, monkeypatch, fixture):
    v = request.getfixturevalue(fixture)
    images, _, reads = verified_scope(v, monkeypatch)
    original = deepcopy((v.v.saved, v.v.environment, v.locator, v.state["phases"]))
    scopes = []
    prepared = None
    for mode in ("prepare", "fence", "history"):
        start = len(reads)
        if mode == "prepare":
            prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
        elif mode == "fence":
            v.service.require_current(prepared)
        else:
            v.snapshot["status"] = "completed"
            v.state["target_up"] = False
            historical = v.service.historical_inputs(prepared.scope)
            assert historical.plan == prepared.plan and historical.scope == prepared.scope
            assert historical.fixture_captures == prepared.fixture_captures
            if fixture == "fixture_inputs":
                assert historical.fixture_inputs == prepared.fixture_inputs
        group = reads[start:]
        assert group and all(cache is group[0][1] for _, cache in group)
        names = [name for name, _ in group]
        assert names.count("original_inputs") == 2
        if mode != "history":
            first, last = names.index("original_inputs"), len(names) - 1 - names[::-1].index("original_inputs")
            assert first < names.index("probe_pinned_inventory") < last
        else:
            assert "probe_pinned_inventory" not in names
        scopes.append(group[0][1])
        assert images._current_verified_reads() is None
    assert len({id(cache) for cache in scopes}) == 3
    assert v.state["health_reads"] == 2
    assert v.state["journal_reads"] == 6 * len(v.selection.fixture_setups)
    assert (v.v.saved, v.v.environment, v.locator, v.state["phases"]) == original
    assert len(v.runner.commands) == v.state["initial_request_count"]


def test_original_case_entry_hands_fresh_inputs_to_worker_binding(case_inputs):
    v = case_inputs
    calls = []

    async def bind(prepared, *, require_current):
        assert prepared.scope.invocation_id == v.snapshot["id"]
        assert v.state["health_reads"] == 1
        require_current.poll()
        assert v.state["health_reads"] == 1
        calls.append(prepared.scope)
        return "original work binding"

    worker = SimpleNamespace(execute_prepared=bind, execute=lambda *a, **k: pytest.fail("prepared worker path not selected"))
    app = RunPlanCaseApplicationService(v.service, worker)
    assert asyncio.run(app.execute(v.selection, invocation_id=v.snapshot["id"])) == "original work binding"
    assert len(calls) == 1 and len(v.runner.commands) == v.state["initial_request_count"]


@pytest.mark.parametrize("fixture", ["case_inputs", "fixture_inputs"])
def test_shared_immutable_scope_never_caches_revocation_and_closes_on_failure(request, monkeypatch, fixture):
    v = request.getfixturevalue(fixture)
    images, _, reads = verified_scope(v, monkeypatch)
    original = v.service.health.probe_pinned_inventory

    def revoke(*args, **kwargs):
        value = original(*args, **kwargs)
        v.v.state["revoked"] = True
        return value

    monkeypatch.setattr(v.service.health, "probe_pinned_inventory", revoke)
    with pytest.raises(SourceAccessDenied):
        v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    failed_cache = reads[0][1]
    assert images._current_verified_reads() is None
    v.v.state["revoked"] = False
    monkeypatch.setattr(v.service.health, "probe_pinned_inventory", original)
    start = len(reads)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    assert reads[start][1] is not failed_cache
    v.binding["current_use"]["inputs_current"] = False
    with pytest.raises(RunPlanChanged):
        v.service.require_current(prepared)
    assert images._current_verified_reads() is None and v.state["health_reads"] == 2
    assert len(v.runner.commands) == v.state["initial_request_count"]


@pytest.mark.parametrize("fixture", ["case_inputs", "fixture_inputs"])
def test_cleanup_claim_between_fences_is_not_hidden_by_shared_source_scope(request, monkeypatch, fixture):
    v = request.getfixturevalue(fixture)
    images, _, reads = verified_scope(v, monkeypatch)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    first_cache = reads[0][1]
    v.state["phases"] = (v.state["phases"][0], ("cleanup:session", v.state["phases"][0][1]))
    start = len(reads)
    with pytest.raises(RunPlanCaseExecutionInvalid):
        v.service.require_current(prepared)
    assert reads[start][1] is not first_cache
    assert images._current_verified_reads() is None and v.state["health_reads"] == 1
    assert len(v.runner.commands) == v.state["initial_request_count"]


@pytest.mark.parametrize("fault", [None, "revoked", "locator"])
def test_one_case_receipt_shares_source_proofs_without_caching_live_checks(case_inputs, monkeypatch, fault):
    v = case_inputs
    images, _, reads = verified_scope(v, monkeypatch)
    prepared = v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    preparation_cache = reads[0][1]
    v.snapshot["status"] = "completed"
    reads.clear()
    before = v.state["journal_reads"]

    def read_archive(plan, scope, *, require_access):
        assert (plan, scope) == (prepared.plan, prepared.scope)
        cache = images._current_verified_reads()
        assert cache is not None and images._verified_read_scope.get().is_current
        reads.append(("case_archive", cache))
        require_access()
        if fault == "revoked":
            v.v.state["revoked"] = True
        elif fault == "locator":
            v.locator["metadata"]["artifact_hash"] = "sha256:" + "0" * 64
        return {"original": True}

    app = RunPlanCaseApplicationService(v.service, SimpleNamespace(read=read_archive))
    if fault is None:
        assert app.read(prepared.scope) == {"original": True}
        assert v.state["journal_reads"] - before == 4 * len(v.selection.fixture_setups)
        receipt_cache = reads[0][1]
        assert all(cache is receipt_cache for _, cache in reads)
        assert receipt_cache is not preparation_cache
        assert [name for name, _ in reads].count("original_inputs") == 4
        reads.clear()
        assert app.read(prepared.scope) == {"original": True}
        assert reads[0][1] is not receipt_cache
    else:
        with pytest.raises(SourceAccessDenied if fault == "revoked" else RunPlanCaseExecutionInvalid):
            app.read(prepared.scope)
        assert [name for name, _ in reads].count("case_archive") == 1
        assert v.state["journal_reads"] - before == 2 * len(v.selection.fixture_setups)
        if fault == "locator":
            assert [name for name, _ in reads].count("read") >= 4
    assert images._current_verified_reads() is None
    assert len(v.runner.commands) == v.state["initial_request_count"]


@pytest.mark.parametrize("schedule", ["thread", "task", "delayed"])
def test_copied_context_cannot_reuse_another_task_thread_or_expired_source_scope(case_inputs, monkeypatch, schedule):
    v = case_inputs
    images, plans, reads = verified_scope(v, monkeypatch)

    async def verify():
        async def prepare():
            return v.service.prepare(v.selection, invocation_id=v.snapshot["id"])

        with plans.verified_read_session():
            outer = images._current_verified_reads()
            assert outer is not None
            if schedule == "thread":
                prepared = await asyncio.to_thread(v.service.prepare, v.selection, invocation_id=v.snapshot["id"])
            elif schedule == "task":
                prepared = await asyncio.create_task(prepare())
            else:
                inherited = copy_context()
            assert images._current_verified_reads() is outer
        if schedule == "delayed":
            prepared = await inherited.run(asyncio.create_task, prepare())
        assert prepared.plan == v.v.saved["artifact"]["plan"]
        assert reads and all(cache is reads[0][1] for _, cache in reads)
        assert all(cache is not outer for _, cache in reads)
        assert images._current_verified_reads() is None
    asyncio.run(verify())
