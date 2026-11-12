"""Complete parent-read port specimens; not PG latency or target evidence."""
from collections import Counter
from copy import deepcopy

import pytest

from apps.api.app.application.quality_loop.http_fixture_execution import HttpFixtureExecutionSelection
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_http_fixture_native_grants import native_grant, paired_grant_reader, spec


def observed_reads(value, monkeypatch):
    paired_grant_reader(value)
    metadata = value.service.issue(value.request, invocation_id="parent-read-original-grant")
    selection = HttpFixtureExecutionSelection(project_id=value.request.project_id, grant_id=metadata["record_id"],
        grant_digest=metadata["grant_digest"], operation=metadata["operation"])
    counts = Counter(live=0)
    for owner, name, key in ((value.service.recipes, "read_with_native_environment", "recipes"), (value.plans, "read", "plans"),
            (value.records, "read_with_plan", "environments"), (value.service.repository, "read", "grants"),
            (value.service.repository, "require_live", "live")):
        original = getattr(owner, name)
        def counted(*args, original=original, key=key, **kwargs):
            counts[key] += 1
            return original(*args, **kwargs)
        monkeypatch.setattr(owner, name, counted)
    return metadata, selection, counts


@pytest.mark.parametrize("live", [True, False])
def test_execution_keeps_independent_live_recheck_without_repeating_its_parents(native_grant, monkeypatch, live):
    value = native_grant
    metadata, selection, counts = observed_reads(value, monkeypatch)
    original = deepcopy((value.saved, value.manifest, value.environment, value.state["issued"]))
    inputs = value.service.execution_inputs(selection, live=live)
    assert counts == Counter(recipes=1, plans=1, environments=1, grants=1, live=int(live))
    assert inputs.scope == HttpFixtureScope(**metadata["scope"])
    assert inputs.manifest == value.manifest
    assert inputs.native_environment == metadata["native_environment"]
    assert inputs.parent.run_plan_id == value.saved["metadata"]["run_plan_id"]
    assert inputs.parent.run_plan_artifact_hash == value.saved["metadata"]["artifact_hash"]
    assert (value.saved, value.manifest, value.environment, value.state["issued"]) == original
    inputs.manifest["setup_steps"].clear()
    assert value.manifest == original[1]
    second = value.service.execution_inputs(selection, live=live)
    assert second.manifest == original[1] and second.consent == inputs.consent
    assert (value.saved, value.manifest, value.environment, value.state["issued"]) == original
    assert counts == Counter(recipes=2, plans=2, environments=2, grants=2, live=int(live) * 2)


def test_standalone_live_operation_reuses_only_this_complete_original_read(native_grant, monkeypatch):
    value = native_grant
    metadata, selection, counts = observed_reads(value, monkeypatch)
    scope = HttpFixtureScope(**metadata["scope"])
    assert value.service.require_operation(selection.project_id, selection.grant_id, scope, selection.operation) == metadata
    assert counts == Counter(recipes=1, plans=1, environments=1, grants=1, live=1)


def test_independent_second_current_plan_cannot_be_replaced_by_first_valid_read(native_grant, monkeypatch):
    value = native_grant
    _, selection, counts = observed_reads(value, monkeypatch)
    original = value.plans.read
    def changed(*args):
        result = original(*args)
        if counts["plans"] == 2:
            result["current_use"]["inputs_current"] = False
        return result
    monkeypatch.setattr(value.plans, "read", changed)
    before = deepcopy((value.saved, value.manifest, value.environment, value.state["issued"]))
    first = value.service.execution_inputs(selection, live=True)
    assert counts == Counter(recipes=1, plans=1, environments=1, grants=1, live=1)
    with pytest.raises(RunPlanChanged):
        value.service.execution_inputs(selection, live=True)
    assert counts == Counter(recipes=2, plans=2, environments=2, grants=2, live=1)
    assert first.manifest == before[1]
    assert (value.saved, value.manifest, value.environment, value.state["issued"]) == before


def test_final_source_revocation_after_live_permission_returns_no_execution_inputs(native_grant, monkeypatch):
    value = native_grant
    _, selection, counts = observed_reads(value, monkeypatch)
    before = deepcopy((value.saved, value.manifest, value.environment, value.state["issued"]))
    original = value.service.repository.require_live
    def revoked(*args, **kwargs):
        receipt = original(*args, **kwargs)
        value.state["revoked"] = True
        return receipt
    monkeypatch.setattr(value.service.repository, "require_live", revoked)
    with pytest.raises(SourceAccessDenied):
        value.service.execution_inputs(selection, live=True)
    assert counts == Counter(recipes=1, plans=1, environments=1, grants=1, live=1)
    assert (value.saved, value.manifest, value.environment, value.state["issued"]) == before


@pytest.mark.parametrize("fault", ["missing", "digest", "scope", "type"])
def test_live_receipt_drift_cannot_replace_complete_original_inputs(native_grant, monkeypatch, fault):
    value = native_grant
    _, selection, counts = observed_reads(value, monkeypatch)
    before = deepcopy((value.saved, value.manifest, value.environment, value.state["issued"]))
    original = value.service.repository.require_live

    def changed(*args, **kwargs):
        receipt = deepcopy(original(*args, **kwargs))
        if fault == "missing":
            return None
        if fault == "digest":
            receipt["grant_digest"] = acceptance_digest("different original grant")
        elif fault == "scope":
            receipt["scope"]["case_id"] = "different-original-case"
        else:
            assert receipt["execution_authorized"] is False
            receipt["execution_authorized"] = 0
        return receipt

    monkeypatch.setattr(value.service.repository, "require_live", changed)
    with pytest.raises(RunPlanIntegrityError, match="fixture permission changed"):
        value.service.execution_inputs(selection, live=True)
    assert counts == Counter(recipes=1, plans=1, environments=1, grants=1, live=1)
    assert (value.saved, value.manifest, value.environment, value.state["issued"]) == before


def test_parent_pair_failure_never_falls_back_to_old_reads(native_grant, monkeypatch):
    value = native_grant
    _, selection, _ = observed_reads(value, monkeypatch)
    error = RuntimeError("explicit original parent reader failure")
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(value.service.recipes, "read_with_native_environment", fail)
    monkeypatch.setattr(value.service.recipes, "read_with_plan", lambda *args: pytest.fail("failed pair cannot fall back"))
    monkeypatch.setattr(value.service.recipes, "read", lambda *args: pytest.fail("failed parent cannot fall back"))
    with pytest.raises(RuntimeError) as raised:
        value.service.execution_inputs(selection, live=True)
    assert raised.value is error
