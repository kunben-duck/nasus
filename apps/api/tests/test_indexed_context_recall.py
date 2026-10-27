from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.system_image.context_pack_inputs import ContextPreviewInput
from apps.api.app.application.system_image.indexed_context_recall import IndexedContextRecall, INDEXED_RECALL_METHOD
from apps.api.app.domain.system_image.context_pack import ContextPackIntegrityError
from apps.api.app.domain.system_image.context_partition import INDEXED_CONTEXT_POLICY
from apps.api.tests.test_screened_link_candidates import RegisteredImages, service, review, DIGEST


def request(**changes):
    return ContextPreviewInput(project_id="p", image_revision_id="i", image_artifact_hash=DIGEST,
        publication_id="published", policy_revision=INDEXED_CONTEXT_POLICY, retrieval_bindings={"ac": "trace"}, **changes)


def replay(images):
    return {"retrieval_id": "trace", "artifact_hash": DIGEST, "generation_id": "generation", "index_artifact_hash": DIGEST,
        "query_hash": DIGEST, "model": {"config_id": "explicit-model", "config_digest": DIGEST},
        "pool_may_be_truncated": True, "embedding_fallback_reason": None,
        "candidates": [{"document": {"object_id": member["object_id"], "revision_id": member["entity_revision_id"],
            "source_revision_id": member["source_revision_id"], "kind": member["kind"], "binding_id": "code-binding",
            "evidence_id": member["evidence_ids"][0]}} for member in images.members.values() if member["kind"] == "code_entity"]}


def test_index_only_candidates_are_screened_before_top_one_and_history_replays_fixed_heads():
    images = RegisteredImages()
    for obj in images.objects:
        if obj["id"].startswith("code-"):
            obj["name"] = "Zqxv.uniqueSymbol"  # No AC label overlap; only the trace recalls these.
    query = service(images, lambda subjects: tuple(review(s.object_id, "rejected_same_revisions") for s in subjects[:-1]))
    assert not query.recall.collect("p", "i", "ac", relation="implements").ranked
    reader = IndexedContextRecall(None, query)
    saved = replay(images)
    receipt, page = reader.read(request(candidate_limit=1), "ac", "implements", saved)
    assert page.method_version == INDEXED_RECALL_METHOD
    assert len(page.items) == 1 and page.items[0].endpoint.object_id == "code-39"
    assert page.pre_review_matched_count == 40 and page.excluded["historical_review"] == 39
    assert page.items[0].signals == ("frozen_index_trace",) and page.items[0].calibrated_probability is None
    assert receipt["truncated"] and not receipt["fallback_used"]
    original = query.screening.screen_endpoints
    def historical(*args, **kwargs):
        assert kwargs["pinned_heads"] == tuple(tuple(pin) for pin in receipt["review_heads"])
        return original(*args, **kwargs)
    query.screening.screen_endpoints = historical
    assert reader.read(request(candidate_limit=1), "ac", "implements", saved, pinned=receipt) == (receipt, page)
    altered = deepcopy(receipt)
    altered["result_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ContextPackIntegrityError, match="receipt"):
        reader.read(request(candidate_limit=1), "ac", "implements", saved, pinned=altered)


@pytest.mark.parametrize("field,value", [("revision_id", "other"), ("source_revision_id", "other"),
    ("binding_id", "other"), ("evidence_id", "other"), ("kind", "source_document")])
def test_trace_candidate_must_match_frozen_member(field, value):
    images = RegisteredImages()
    saved = replay(images)
    saved["candidates"][0]["document"][field] = value
    with pytest.raises(ContextPackIntegrityError, match="frozen member"):
        IndexedContextRecall(None, service(images, lambda _: ())).read(request(), "ac", "implements", saved)


def test_v5_opt_in_does_not_add_fields_to_v1_through_v4_requests():
    payload = request().model_dump()
    for version in (1, 2, 3, 4):
        old = {key: value for key, value in payload.items() if key not in {"retrieval_bindings", "publication_id"}}
        old["policy_revision"] = f"nasus.test-design-context.v{version}"
        if version == 4:
            old["publication_id"] = "published"
        assert ContextPreviewInput.model_validate(old).model_dump() == old
        with pytest.raises(ValidationError):
            ContextPreviewInput.model_validate({**old, "retrieval_bindings": {}})
    for value in (None, {"": "trace"}, {"ac": ""}, {"ac": 12}, {str(i): "trace" for i in range(257)}):
        with pytest.raises(ValidationError):
            ContextPreviewInput.model_validate({**payload, "retrieval_bindings": value})


def test_one_derivation_reuses_same_trace_but_next_derivation_revalidates():
    calls = []
    port = SimpleNamespace(replay_candidates=lambda *args, **kwargs: calls.append((args, kwargs)) or {"retrieval_id": "trace"})
    reader = IndexedContextRecall(port, None)
    selection = request().model_copy(update={"retrieval_bindings": {"ac": "trace", "second-ac": "trace"}})
    assert reader.load(selection, {"publication_id": "published"}) == {"ac": {"retrieval_id": "trace"}, "second-ac": {"retrieval_id": "trace"}}
    assert len(calls) == 1
    reader.load(selection, {"publication_id": "published"}, historical=True)
    assert len(calls) == 2 and calls[-1][1] == {"historical": True}
