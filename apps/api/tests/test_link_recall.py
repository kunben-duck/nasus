from dataclasses import replace

import pytest
from pydantic import ValidationError

from apps.api.app.domain.system_image.link_recall import LinkRecallInput, recall_terms, rank_link_candidates
from apps.api.app.application.system_image.image_query_models import ImageLinkCandidatesInput


def test_mixed_language_symbols_and_identifiers_are_separate_channels():
    assert {"http", "chat", "stream", "400"} <= recall_terms("HTTPChatStream returns HTTP 400")
    assert "支付" in recall_terms("支付失败应返回错误") & recall_terms("处理支付退款")
    assert recall_terms("US-17 REQ-2 AC-abc BR-1 RULE-A TC-99") == frozenset()
    assert "chat" in recall_terms("Ｃｈａｔ_stream")


def test_reference_only_is_retrieval_signal_not_assertion_or_probability():
    values = (LinkRecallInput("ref", "Something unrelated", True), LinkRecallInput("no", "US-17"),
              LinkRecallInput("match", "Empty input returns HTTP 400"))
    results = rank_link_candidates("US-17 AC-1 Empty input returns HTTP 400", values)
    assert [item.object_id for item in results] == ["match", "ref"]
    assert results[1].signals == ("explicit_requirement_reference",)
    assert results[1].matched_terms == ()
    assert results == rank_link_candidates("US-17 AC-1 Empty input returns HTTP 400", tuple(reversed(values)))


def test_duplicate_words_do_not_boost_retrieval_and_ties_are_stable():
    a = LinkRecallInput("a", "ChatController.stream")
    b = replace(a, object_id="b", text="ChatController.stream " * 10)
    results = rank_link_candidates("chat stream", (b, a))
    assert [item.object_id for item in results] == ["a", "b"]
    assert results[0].retrieval_score == results[1].retrieval_score
    assert rank_link_candidates("支付处理失败", (LinkRecallInput("pay", "支付失败时重试"),))
    assert not rank_link_candidates("a the to", (a, b))


@pytest.mark.parametrize("values,query", [((LinkRecallInput("x", "a"),) * 2, "a"),
    ((LinkRecallInput("x", "a" * 65537),), "a"), ((), "a" * 65537),
    (tuple(LinkRecallInput(str(i), "a" * 65536) for i in range(129)), "a"),
    (tuple(LinkRecallInput(str(i), "a") for i in range(10001)), "a")])
def test_recall_budget_fails_instead_of_silently_truncating_inputs(values, query):
    with pytest.raises(ValueError):
        rank_link_candidates(query, values)


@pytest.mark.parametrize("changes", [{"limit": True}, {"limit": "30"}, {"limit": 101}, {"limit": 0},
    {"relation": "covers"}, {"relation": "references"}, {"method_version": "latest"}, {"confidence": .99},
    {"image_revision_id": ""}, {"target_object_id": 1}])
def test_recall_request_rejects_unpinned_or_unbounded_input(changes):
    with pytest.raises(ValidationError):
        ImageLinkCandidatesInput(**{"project_id": "p", "image_revision_id": "i", "target_object_id": "a",
                                    "relation": "asserts", **changes})
