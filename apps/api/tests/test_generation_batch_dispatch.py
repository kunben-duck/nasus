"""Canonical plan hashes choose an executor, never a capacity-driven fallback."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api.app.application.quality_loop.generation_work_lease import GenerationWorkLease
from apps.api.app.application.quality_loop.generation_executor import GenerationOutcomeUnknown
from apps.api.app.application.quality_loop.test_design_results import GenerationResultRequest, TestDesignResultIntegrityError
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.tests.test_generation_executor import executor


def configured():
    app, selection, deps, prepared = executor()
    execute = AsyncMock(return_value={"generation_id": "batch-draft", "status": "draft"})
    repository = SimpleNamespace(get_plan=lambda *args: None)
    app.batch_executor = SimpleNamespace(execute=execute, receipts=SimpleNamespace(repository=repository))
    work = GenerationWorkLease("p", "invocation", "worker", 1, acceptance_digest("canonical"))
    return app, selection, deps, prepared, execute, repository, work


def test_batch_preview_is_metadata_only_and_a_different_exact_consent_from_single():
    app, selection, deps, _, _, _, _ = configured()
    single, batch = app.preview(selection), app.preview_batches(selection)
    assert single["request"]["execution"]["plan_digest"] != batch["request"]["execution"]["plan_digest"]
    assert batch["batching"] == "complete_constraint_batches_no_truncation"
    assert batch["call_count"] == batch["reservation"]["call_count"] == len(batch["batch_planning"]["batches"])
    assert not batch["generation_authorized"] and not batch["execution_authorized"]
    assert "HTTP 400" not in str(batch) and "private-provider-key" not in str(batch)
    assert deps["provider"].calls == 0 and deps["repository"].stored is None


def test_exact_confirmed_batch_plan_dispatches_with_the_current_canonical_lease():
    app, selection, deps, _, execute, _, work = configured()
    request = GenerationResultRequest.model_validate(app.preview_batches(selection)["request"])
    assert asyncio.run(app.execute(request, invocation_id="invocation", work_lease=work))["generation_id"] == "batch-draft"
    execute.assert_awaited_once_with(request, lease=work)
    assert deps["provider"].calls == 0 and deps["repository"].stored is None


def test_legacy_single_plan_remains_single_even_when_batch_execution_is_composed():
    app, selection, deps, _, execute, _, work = configured()
    request = GenerationResultRequest.model_validate(app.preview(selection)["request"])
    assert asyncio.run(app.execute(request, invocation_id="invocation", work_lease=work))["generation_id"] == "draft"
    execute.assert_not_awaited()
    assert deps["provider"].calls == 1


@pytest.mark.parametrize("work", [None, "foreign"])
def test_durable_batch_budget_never_falls_back_without_its_exact_lease(work):
    app, selection, deps, _, execute, repository, lease = configured()
    request = GenerationResultRequest.model_validate(app.preview_batches(selection)["request"])
    repository.get_plan = lambda *args: {"explicit_stored_plan_fixture": True}
    with pytest.raises(TestDesignResultIntegrityError):
        asyncio.run(app.execute(request, invocation_id="invocation", work_lease=replace(lease, invocation_id="other") if work else None))
    execute.assert_not_awaited()
    assert deps["provider"].calls == 0


def test_unknown_batch_is_propagated_without_resending_or_switching_to_single():
    app, selection, deps, _, execute, repository, lease = configured()
    request = GenerationResultRequest.model_validate(app.preview_batches(selection)["request"])
    repository.get_plan = lambda *args: {"explicit_stored_plan_fixture": True}
    execute.side_effect = GenerationOutcomeUnknown("already claimed")
    with pytest.raises(GenerationOutcomeUnknown):
        asyncio.run(app.execute(request, invocation_id="invocation", work_lease=lease))
    assert deps["provider"].calls == 0 and deps["repository"].stored is None


def test_changed_plan_pin_cannot_egress_through_either_executor():
    app, selection, deps, _, execute, _, lease = configured()
    request = GenerationResultRequest.model_validate(app.preview_batches(selection)["request"])
    altered = request.model_copy(update={"execution": request.execution.model_copy(update={"plan_digest": acceptance_digest("changed")})})
    with pytest.raises(ValueError):
        asyncio.run(app.execute(altered, invocation_id="invocation", work_lease=lease))
    execute.assert_not_awaited()
    assert deps["provider"].calls == 0 and deps["repository"].stored is None
