import json

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.agent.observation_receipts import observation_receipt_fingerprint
from apps.api.app.application.platform.tool_models import ToolResult
from apps.api.app.application.system_image.context_retrieval_inputs import CONTEXT_RETRIEVAL_PREVIEW_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.tests.test_frozen_indexes_api import indexed, publication, documents, evidence_api, build, grant_member, publish
from apps.api.tests.test_semantic_evaluations_api import completed, invoke


def planned(v):
    done = build(v)
    selection = {"project_id": v["project_id"], "publication_id": v["index_head"]["publication_id"], "generation_id": done["id"]}
    result = completed(invoke(v, CONTEXT_RETRIEVAL_PREVIEW_TOOL, selection))
    url = v["image_url"] + f"/indexes/{done['id']}/context-query-plan"
    return selection, result, url


def test_canonical_query_plan_is_deterministic_body_free_and_model_free(indexed):
    v = indexed
    selection, result, url = planned(v)
    calls = len(v["index_calls"])
    preview = result["result"]["context_retrieval_preview"]
    assert preview["query_count"] == 1 and preview["max_model_calls"] == 1
    assert preview["state"] == "prepared" and preview["input_bytes"] > 0
    assert preview["model_calls_made"] == 0 and preview["execution_available"]
    assert preview["publication_pin"]["publication_id"] == selection["publication_id"]
    response = v["client"].get(url, params={"publication_id": selection["publication_id"]}, headers=v["headers"])
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    assert response.json() == preview
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(result["id"], v["project_id"]) == preview
    with session_scope() as session:
        record = session.get(ToolInvocationRecord, result["id"])
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()
        stored = json.dumps(record.result_payload) + json.dumps([event.event_payload for event in events])
        assert events and not any(secret in stored for secret in ("Empty input", "Search the code catalog", "private-index-key", "s3://", "local-object://"))
    assert len(v["index_calls"]) == calls
    assert v["client"].get(url, params={"publication_id": selection["publication_id"]}).status_code == 401
    grant_member(v)
    assert v["client"].get(url, params={"publication_id": selection["publication_id"]}, headers=v["member_headers"]).status_code == 403


@pytest.mark.parametrize("change", ["head", "model", "acl"])
def test_query_plan_rechecks_inputs_after_reading_source_bytes(indexed, monkeypatch, change):
    v = indexed
    selection, result, url = planned(v)
    service = v["index_service"]
    original = service.images.verify_evidence_selection
    mutated = []
    def verify(*args, **kwargs):
        value = original(*args, **kwargs)
        if not mutated:
            mutated.append(True)
            if change == "head":
                v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"]}
                publish(v)
            elif change == "model":
                service.models.repository.save_model_config(v["index_config"].model_copy(update={"updated_at": "changed"}), v["index_encrypted"])
            else:
                repository = SourceAccessRepository()
                scope = repository.load_snapshot(v["project_id"])
                repository.set_policy(v["project_id"], scope.bindings[0].binding_id, SourceAccessRule("restricted"),
                    expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="query-plan-race")
        return value
    monkeypatch.setattr(service.images, "verify_evidence_selection", verify)
    calls = len(v["index_calls"])
    response = v["client"].get(url, params={"publication_id": selection["publication_id"]}, headers=v["headers"])
    assert response.status_code in (403, 409, 502), response.text
    assert "plan_digest" not in response.text and "Empty input" not in response.text
    assert len(v["index_calls"]) == calls and mutated


def test_plan_does_not_accept_an_index_from_another_publication(indexed):
    v = indexed
    selection, _, url = planned(v)
    v["target"] = {**v["target"], "expected_head_id": v["index_head"]["publication_id"]}
    head = publish(v)
    response = v["client"].get(url, params={"publication_id": head["publication_id"]}, headers=v["headers"])
    assert response.status_code == 502 and "plan_digest" not in response.text
    response = invoke(v, CONTEXT_RETRIEVAL_PREVIEW_TOOL, {**selection, "publication_id": head["publication_id"]})
    assert response.json()["status"] == "failed"


def test_agent_revalidates_query_plan_receipts_instead_of_trusting_saved_results(indexed):
    v = indexed
    _, result, _ = planned(v)
    receipt = ToolResult.model_validate(result["result"])
    original = observation_receipt_fingerprint(receipt)
    forged = {**receipt.context_retrieval_preview, "plan_digest": "sha256:" + "0" * 64}
    receipt.context_retrieval_preview = forged
    assert original != observation_receipt_fingerprint(receipt)
    with session_scope() as session:
        record = session.get(ToolInvocationRecord, result["id"])
        record.result_payload = {**record.result_payload, "context_retrieval_preview": forged}
    calls = len(v["index_calls"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PlatformApplicationError, match="preview changed"):
            app.state.container.tool_evidence.describe(result["id"], v["project_id"])
    assert len(v["index_calls"]) == calls


def test_oversized_query_returns_explicit_no_truncation_error(indexed, monkeypatch):
    v = indexed
    selection, _, url = planned(v)
    service = v["index_service"]
    original = service.images.read_document
    def oversized(*args, **kwargs):
        page = original(*args, **kwargs)
        if page["projection"]["kind"] == "acceptance_criterion":
            page = {**page, "fields": [{**field, "value": "oversized-private-source" * 4096} for field in page["fields"]]}
        return page
    monkeypatch.setattr(service.images, "read_document", oversized)
    calls = len(v["index_calls"])
    result = v["client"].get(url, params={"publication_id": selection["publication_id"]}, headers=v["headers"])
    assert result.status_code == 413 and result.json()["detail"]["error"]["code"] == "context_retrieval_over_budget", result.text
    assert "No AC or field was omitted" in result.text and "oversized-private-source" not in result.text
    assert len(v["index_calls"]) == calls
