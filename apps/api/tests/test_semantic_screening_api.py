import asyncio

import pytest

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence.semantic_evaluation_models import SemanticCallReservationRecord, SemanticEvaluationRecord
from apps.api.tests.test_semantic_applicability_api import setup
from apps.api.tests.test_semantic_review_api import semantic, documents, evidence_api, evaluate, submit, completed
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm, count
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_document_projection_api import REQUIREMENT


def preview(v, image=None):
    selection = dict(v["selection"])
    if image:
        selection.update(image_revision_id=image["image_revision_id"], expected_image_hash=image["artifact_hash"])
    return completed(invoke(v, "query.system_image.links.evaluation_preview", selection))["result"]["semantic_preview"]


def execute(v, request):
    pending = invoke(v, "system_image.links.evaluate", request).json()
    assert pending["status"] == "waiting_confirmation", pending
    return confirm(v, pending)


def test_discovered_rejection_cannot_be_reset_by_new_image_or_forged_consent(semantic):
    v = semantic
    url, review, page, image = setup(v)
    saved = v["client"].get(url, headers=v["headers"]).json()
    selection = preview(v, image)
    assert len(selection["review_screening"]) == 1
    hit = selection["review_screening"][0]
    assert hit["head_decision_id"] == page["head_decision_id"] and hit["status"] == "rejected_same_revisions"
    assert hit["source_image_revision_id"] != image["image_revision_id"]
    for request in (selection["request"], v["request"], {**selection["request"], "review_scope_digest": "sha256:" + "0" * 64}):
        assert execute(v, request).json()["status"] == "failed"
    assert len(v["calls"]) == count(v, SemanticCallReservationRecord) == count(v, SemanticEvaluationRecord) == 1
    completed(submit(v, {**review, "decision": "defer", "expected_previous_decision_id": page["head_decision_id"]}))
    fresh = preview(v, image)
    assert fresh["review_screening"][0]["status"] == "same_revisions_review_required"
    assert fresh["request"]["review_scope_digest"] != selection["request"]["review_scope_digest"]
    completed(execute(v, fresh["request"]))
    assert len(v["calls"]) == 2
    historical = v["client"].get(url, headers=v["headers"], params={"through_decision_id": page["head_decision_id"]})
    assert historical.json() == saved


def test_changed_registered_endpoint_is_flagged_for_new_review_not_inherited(semantic):
    v = semantic
    _, _, page, _ = setup(v)
    v["requirement_path"].write_text(REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    image = candidate(v)
    selection = preview(v, image)
    item, = selection["review_screening"]
    assert item["head_decision_id"] == page["head_decision_id"]
    assert item["decision"] == "reject" and item["status"] == "stale_requires_review"
    completed(execute(v, selection["request"]))
    assert len(v["calls"]) == 2


@pytest.mark.parametrize("stage", ["reserve", "before_send", "during_call", "complete"])
def test_review_head_races_prevent_new_admission_and_never_retry(semantic, monkeypatch, stage):
    v = semantic
    _, review, _ = evaluate(v)
    service = v["service"]
    request = preview(v)["request"]
    changed = []
    def reject():
        if not changed:
            changed.append(True)
            completed(submit(v, review))
    if stage in {"reserve", "before_send"}:
        reserve = service.repository.reserve
        def race(*args, **kwargs):
            if stage == "reserve":
                reject()
            result = reserve(*args, **kwargs)
            if stage == "before_send":
                reject()
            return result
        monkeypatch.setattr(service.repository, "reserve", race)
    elif stage == "during_call":
        generate = service.provider.generate
        async def race(*args):
            result = await generate(*args)
            await asyncio.to_thread(reject)
            return result
        monkeypatch.setattr(service.provider, "generate", race)
    else:
        put = service.artifacts.put
        def race(*args):
            result = put(*args)
            reject()
            return result
        monkeypatch.setattr(service.artifacts, "put", race)
    result = execute(v, request).json()
    assert result["status"] == "failed" and changed
    assert count(v, SemanticCallReservationRecord) == (1 if stage == "reserve" else 2)
    assert count(v, SemanticEvaluationRecord) == 1
    calls = len(v["calls"])
    assert calls == (1 if stage in {"reserve", "before_send"} else 2)
    assert confirm(v, result).json()["status"] == "failed" and len(v["calls"]) == calls


def test_screening_head_query_failure_is_closed_not_an_empty_history(semantic, monkeypatch):
    v = semantic
    def fail(*args):
        raise ImageRevisionIntegrityError("injected incomplete review index")
    monkeypatch.setattr(v["service"].decision_guard.heads, "matching_heads", fail)
    assert invoke(v, "query.system_image.links.evaluation_preview", v["selection"]).json()["status"] == "failed"
    assert execute(v, v["request"]).json()["status"] == "failed"
    assert not v["calls"] and count(v, SemanticCallReservationRecord) == 0
