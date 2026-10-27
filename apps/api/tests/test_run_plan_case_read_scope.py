"""Actual operation-scope composition; original records/target remain protocol specimens."""
import asyncio
from contextvars import copy_context
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.run_plans import RunPlanApplicationService
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
            (v.fixtures, "read_native"), (v.service.health, "inspect")):
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
        scopes.append(group[0][1])
        assert images._current_verified_reads() is None
    assert len({id(cache) for cache in scopes}) == 3
    assert v.state["health_reads"] == 2
    assert v.state["journal_reads"] == 6 * len(v.selection.fixture_setups)
    assert (v.v.saved, v.v.environment, v.locator, v.state["phases"]) == original
    assert len(v.runner.commands) == v.state["initial_request_count"]


@pytest.mark.parametrize("fixture", ["case_inputs", "fixture_inputs"])
def test_shared_immutable_scope_never_caches_revocation_and_closes_on_failure(request, monkeypatch, fixture):
    v = request.getfixturevalue(fixture)
    images, _, reads = verified_scope(v, monkeypatch)
    original = v.service.health.inspect

    def revoke(*args, **kwargs):
        value = original(*args, **kwargs)
        v.v.state["revoked"] = True
        return value

    monkeypatch.setattr(v.service.health, "inspect", revoke)
    with pytest.raises(SourceAccessDenied):
        v.service.prepare(v.selection, invocation_id=v.snapshot["id"])
    failed_cache = reads[0][1]
    assert images._current_verified_reads() is None
    v.v.state["revoked"] = False
    monkeypatch.setattr(v.service.health, "inspect", original)
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
