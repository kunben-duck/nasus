"""Real canonical tools/PG; synthetic model responses do not prove semantic quality."""
import json

from apps.api.app.main import app
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_semantic_review_api import semantic, documents, evidence_api, evaluate, submit, completed
from apps.api.tests.test_semantic_evaluations_api import invoke, confirm
from apps.api.tests.test_document_projection_api import CASE, REQUIREMENT
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_source_access_api import grant_member
from sqlalchemy import select


TOOL = "query.system_image.links.screened_candidates"


def recall(v, *, image=None, limit=1, raw=False):
    image = image or candidate(v)
    request = dict(project_id=v["project_id"], image_revision_id=image["image_revision_id"],
        target_object_id=v["selection"]["target_object_id"], relation="asserts", limit=limit)
    result = completed(invoke(v, "query.system_image.links.candidates" if raw else TOOL, request))
    response = expand(v, result)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return result, response.json()


def expand(v, invocation, **kwargs):
    return v["client"].get(f"/v1/tool-invocations/{invocation['id']}/image-query", headers=kwargs.get("headers", v["headers"]))


def selection(v, invocation, page):
    return {**v["selection"], "image_revision_id": page["image_revision_id"], "expected_image_hash": page["image_artifact_hash"],
        "recall_limit": page["requested_limit"], "recall_invocation_id": invocation["id"],
        "subject_object_ids": [page["items"][0]["endpoint"]["object_id"]]}


def set_request(v, invocation, page):
    v["selection"] = selection(v, invocation, page)
    v["request"] = completed(invoke(v, "query.system_image.links.evaluation_preview", v["selection"]))["result"]["semantic_preview"]["request"]


def test_filter_precedes_limit_and_pinned_receipts_survive_new_decisions(semantic, monkeypatch):
    v = semantic
    v["case_path"].write_text(CASE + "\n" + CASE.replace("TC-9", "TC-10"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    first, original = recall(v)
    raw, raw_page = recall(v, raw=True)
    assert original["pre_review_matched_count"] == original["matched_count"] == 2
    assert original["items"][0]["endpoint"] == raw_page["items"][0]["endpoint"]
    assert first["result"]["image_query"]["review_heads"] == []
    set_request(v, first, original)
    url, review, _ = evaluate(v)
    completed(submit(v, review))
    head = v["client"].get(url, headers=v["headers"]).json()["head_decision_id"]
    second, filtered = recall(v)
    assert filtered["pre_review_matched_count"] == 2 and filtered["matched_count"] == 1
    assert len(filtered["items"]) == 1 and not filtered["truncated"]
    assert filtered["excluded"]["historical_review"] == 1
    assert filtered["items"][0]["endpoint"] != raw_page["items"][0]["endpoint"]
    assert filtered["review_screening"][0]["head_decision_id"] == head
    assert expand(v, first).json() == original and expand(v, raw).json() == raw_page
    blocked = completed(invoke(v, "query.system_image.links.evaluation_preview", v["selection"]))["result"]["semantic_preview"]
    assert blocked["review_screening"][0]["status"] == "rejected_same_revisions"
    pending = invoke(v, "system_image.links.evaluate", blocked["request"]).json()
    assert confirm(v, pending).json()["status"] == "failed"
    # The replacement lies beyond raw top-1, but is valid with its canonical v2 receipt.
    set_request(v, second, filtered)
    other_url, other_review, _ = evaluate(v)
    completed(submit(v, other_review))
    empty, empty_page = recall(v)
    assert not empty_page["items"] and empty_page["excluded"]["historical_review"] == 2
    completed(submit(v, {**review, "decision": "defer", "expected_previous_decision_id": head}))
    latest, latest_page = recall(v)
    assert latest_page["items"][0]["endpoint"] == original["items"][0]["endpoint"]
    assert latest_page["items"][0]["review_status"] == "reviewed_not_approved"
    assert expand(v, second).json() == filtered and expand(v, empty).json() == empty_page
    assert len(v["calls"]) == 2
    # Historical evaluation proof must be bounded, not a recursive expansion of
    # every review/evaluation that preceded its screened recall.
    def forbidden(*args):
        raise AssertionError("historical evaluation recursively expanded a recall")
    monkeypatch.setattr(app.state.container.tool_images.images, "expand", forbidden)
    assert v["client"].get(other_url, headers=v["headers"]).status_code == 200


def test_changed_source_requires_revalidation_and_old_query_stays_excluded(semantic):
    v = semantic
    _, review, _ = evaluate(v)
    completed(submit(v, review))
    old, excluded = recall(v)
    assert not excluded["items"]
    v["requirement_path"].write_text(REQUIREMENT.replace("400", "422"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    new, page = recall(v)
    assert page["excluded"]["historical_review"] == 0
    assert page["items"][0]["review_status"] == "requires_revalidation"
    assert page["review_screening"][0]["status"] == "stale_requires_review"
    assert expand(v, old).json() == excluded
    set_request(v, new, page)
    evaluate(v)
    assert len(v["calls"]) == 2


def test_screened_receipt_is_body_free_and_permission_checked(semantic):
    v = semantic
    _, review, _ = evaluate(v)
    completed(submit(v, review))
    result, page = recall(v)
    receipt = result["result"]["image_query"]
    assert receipt["operation"] == "screened_link_candidates" and receipt["excluded_by_review"] == 1
    assert receipt["review_scope"] == "pinned_query_heads_not_live"
    assert expand(v, result, headers=v["member_headers"]).status_code == 403
    grant_member(v)
    assert expand(v, result, headers=v["member_headers"]).json() == page
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()
        assert events
        persisted = json.dumps(session.get(ToolInvocationRecord, result["id"]).result_payload) + json.dumps([e.event_payload for e in events])
    for text in ("Empty input", "No independently approved oracle", "HTTP 400", "s3://", "local-object://"):
        assert text not in persisted
    images = app.state.container.image_revisions
    original = images.authorization.require_current
    from apps.api.app.domain.system_image.source_access import SourceAccessDenied
    def revoked(*args):
        raise SourceAccessDenied("revoked during pinned recall")
    images.authorization.require_current = revoked
    try:
        response = expand(v, result)
        assert response.status_code == 403 and "Empty input" not in response.text
    finally:
        images.authorization.require_current = original


def test_wrong_receipt_scope_and_tampering_cannot_select_model_input(semantic):
    v = semantic
    result, page = recall(v)
    raw, _ = recall(v, raw=True)
    valid = selection(v, result, page)
    for change in ({"recall_invocation_id": raw["id"]}, {"recall_limit": 2}, {"recall_invocation_id": "missing"}):
        response = invoke(v, "query.system_image.links.evaluation_preview", {**valid, **change})
        assert response.json()["status"] == "failed", response.text
    set_request(v, result, page)
    url, _, _ = evaluate(v)
    assert v["client"].get(url, headers=v["headers"]).status_code == 200
    with session_scope() as session:
        record = session.get(ToolInvocationRecord, result["id"])
        changed = {**record.result_payload, "image_query": {**record.result_payload["image_query"], "result_hash": "sha256:" + "0" * 64}}
        record.result_payload = changed
    assert expand(v, result).status_code == 502
    # Even without expanding head dependencies, the archived evaluation binds
    # the entire receipt and must fail if any receipt metadata changes.
    assert v["client"].get(url, headers=v["headers"]).status_code == 502
    assert len(v["calls"]) == 1
