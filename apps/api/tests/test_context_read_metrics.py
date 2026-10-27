from copy import deepcopy

import pytest

from apps.api.tests.context_read_metrics import summarize_read_samples


def samples():
    return [{"elapsed_seconds": seconds, "fact_writes": 0, "response_hash": "sha256:" + "a" * 64}
        for seconds in (5, 1, 3, 2, 4)]


def test_measurement_keeps_every_sample_in_original_order_and_does_not_claim_acceptance():
    original = samples()
    before = deepcopy(original)
    report = summarize_read_samples(original)
    assert original == before and report["samples"] == before
    assert report["sample_count"] == 5 and report["percentile_method"] == "nearest_rank"
    assert (report["min_seconds"], report["p50_seconds"], report["p95_seconds"], report["max_seconds"]) == (1, 3, 5, 5)
    assert report["identical_response_verified"] and report["fact_writes"] == 0
    assert report["capacity_or_p95_acceptance"] is False


def test_nearest_rank_is_explicit_for_thirty_samples():
    original = [{**samples()[0], "elapsed_seconds": seconds} for seconds in range(30, 0, -1)]
    report = summarize_read_samples(original)
    assert report["p50_seconds"] == 15 and report["p95_seconds"] == 29


@pytest.mark.parametrize("value", [0, -1, True, "1", None, float("nan"), float("inf"), float("-inf")])
def test_invalid_elapsed_time_cannot_become_a_performance_result(value):
    original = samples()
    original[2]["elapsed_seconds"] = value
    with pytest.raises(ValueError, match="finite positive"):
        summarize_read_samples(original)


@pytest.mark.parametrize("value", [1, -1, False, None])
def test_fact_write_or_missing_observation_is_not_reported_as_a_read_only_measurement(value):
    original = samples()
    original[1]["fact_writes"] = value
    with pytest.raises(ValueError, match="business facts"):
        summarize_read_samples(original)


def test_different_response_cannot_be_hidden_in_latency_statistics():
    original = samples()
    original[4]["response_hash"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="different responses"):
        summarize_read_samples(original)


@pytest.mark.parametrize("value", [None, True, "sha256:", "sha256:" + "x" * 64, "sha256:" + "a" * 65])
def test_invalid_response_identity_cannot_produce_verified_read_statistics(value):
    original = samples()
    original[0]["response_hash"] = value
    with pytest.raises(ValueError, match="verified response identities"):
        summarize_read_samples(original)


@pytest.mark.parametrize("count", [0, 4, 31])
def test_sample_budget_is_bounded_without_silently_truncating(count):
    original = [samples()[0] for _ in range(count)]
    with pytest.raises(ValueError, match="5..30"):
        summarize_read_samples(original)
