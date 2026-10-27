"""Complete parent-read port specimens; not PG latency or target evidence."""
from collections import Counter
from copy import deepcopy

import pytest

from apps.api.app.application.quality_loop.http_fixture_execution import HttpFixtureExecutionSelection
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.domain.quality_loop.run_plan import RunPlanChanged
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_http_fixture_native_grants import native_grant, spec


def observed_reads(value, monkeypatch):
    metadata = value.service.issue(value.request, invocation_id="parent-read-original-grant")
    selection = HttpFixtureExecutionSelection(project_id=value.request.project_id, grant_id=metadata["record_id"],
        grant_digest=metadata["grant_digest"], operation=metadata["operation"])
    counts = Counter(live=0)
    for owner, name, key in ((value.service.recipes, "read", "recipes"), (value.plans, "read", "plans"),
            (value.records, "read", "environments"), (value.service.repository, "read", "grants"),
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
    expected = 2 if live else 1
    assert counts == Counter(recipes=expected, plans=expected, environments=expected, grants=expected, live=int(live))
    assert inputs.scope == HttpFixtureScope(**metadata["scope"])
    assert inputs.manifest == value.manifest
    assert inputs.native_environment == metadata["native_environment"]
    assert inputs.parent.run_plan_id == value.saved["metadata"]["run_plan_id"]
    assert inputs.parent.run_plan_artifact_hash == value.saved["metadata"]["artifact_hash"]
    assert (value.saved, value.manifest, value.environment, value.state["issued"]) == original
    inputs.manifest["setup_steps"].clear()
    assert value.manifest == original[1]
    value.service.execution_inputs(selection, live=live)
    assert counts["recipes"] == counts["plans"] == counts["environments"] == counts["grants"] == expected * 2


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
    with pytest.raises(RunPlanChanged):
        value.service.execution_inputs(selection, live=True)
    assert counts["plans"] == 2 and not counts["live"]


def test_final_source_revocation_after_live_permission_returns_no_execution_inputs(native_grant, monkeypatch):
    value = native_grant
    _, selection, counts = observed_reads(value, monkeypatch)
    original = value.service.repository.require_live
    def revoked(*args, **kwargs):
        original(*args, **kwargs)
        value.state["revoked"] = True
    monkeypatch.setattr(value.service.repository, "require_live", revoked)
    with pytest.raises(SourceAccessDenied):
        value.service.execution_inputs(selection, live=True)
    assert counts["live"] == 1 and len(value.state["issued"]) == 1


def test_parent_pair_failure_never_falls_back_to_old_reads(native_grant, monkeypatch):
    value = native_grant
    _, selection, _ = observed_reads(value, monkeypatch)
    error = RuntimeError("explicit original parent reader failure")
    def fail(*args):
        raise error
    monkeypatch.setattr(value.service.recipes, "read_with_plan", fail, raising=False)
    monkeypatch.setattr(value.service.recipes, "read", lambda *args: pytest.fail("failed parent cannot fall back"))
    with pytest.raises(RuntimeError) as raised:
        value.service.execution_inputs(selection, live=True)
    assert raised.value is error
