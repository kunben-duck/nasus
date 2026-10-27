"""Diagnostic control flow only; metrics here are explicit specimens, not PG."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from apps.api.tests import fixture_parent_read_probe as probe


def samples():
    value = {"response_hash": "response", "response_contract_hash": "contract", "response_bytes": 100,
        "distinct_objects": 4, "distinct_read_inventory_hash": "original-four-bodies", "fact_writes": 0,
        "object_reads": 20, "returned_object_bytes": 2000,
        "connections": {"business": {"statements": 40}, "live": {"checkout": 1, "begin": 1,
            "read_only_setups": 1, "rollback": 1, "authorization_queries": 10}}}
    after = deepcopy(value)
    after.update(object_reads=12, returned_object_bytes=1200)
    after["connections"]["business"]["statements"] = 25
    return value, after


@pytest.mark.parametrize("failure", [None, "control", "objects", "response", "connection"])
def test_opt_in_pair_restores_real_method_and_rejects_weaker_verification(monkeypatch, tmp_path, failure):
    path = tmp_path / "diagnostic.json"
    monkeypatch.setenv("FIXTURE_PARENT_READ_REPORT", str(path))
    original = lambda: None
    recipes = SimpleNamespace(read_with_plan=original)
    monkeypatch.setattr(probe, "_grant_service", lambda: SimpleNamespace(recipes=recipes))
    before, after = samples()
    if failure == "objects": after["distinct_read_inventory_hash"] = "missing-body"
    elif failure == "response": after["response_hash"] = "different"
    elif failure == "connection": after["connections"]["live"]["commit"] = 1
    calls = []
    def observed(*args):
        calls.append(recipes.read_with_plan)
        if len(calls) == 1:
            assert recipes.read_with_plan is None
            if failure == "control": raise RuntimeError("explicit control read failure")
            return before
        assert recipes.read_with_plan is original
        return after
    monkeypatch.setattr(probe, "measure_context_http_read", observed)
    if failure is None:
        probe.measure_fixture_parent_reuse({}, "private", {}, monkeypatch)
        report = json.loads(path.read_text())
        assert report["control"] == before and report["production"] == after
        assert report["sample_order"] == "control_then_production_one_pair"
        assert report["capacity_or_p95_acceptance"] is report["business_gold"] is False
    else:
        with pytest.raises(RuntimeError if failure == "control" else AssertionError):
            probe.measure_fixture_parent_reuse({}, "private", {}, monkeypatch)
        assert not path.exists()
    assert recipes.read_with_plan is original
