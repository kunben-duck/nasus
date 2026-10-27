"""Canonical confirmation, source ACL, native transport and real PostgreSQL persistence."""
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.system_image.semantic_evaluations import SEMANTIC_PREVIEW_TOOL, SEMANTIC_EVALUATE_TOOL
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.llm.semantic_link_model import HTTPSemanticLinkModel
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.llm_call_repository import SQLAlchemyLLMCallRepository
from apps.api.app.infrastructure.persistence.semantic_evaluation_models import SemanticCallReservationRecord, SemanticEvaluationRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_source_access_api import grant_member
from apps.api.tests.test_semantic_link_model import saved_config, native_reply


def unknown_output(payload):
    target = payload["target"]
    return {"schema_version": "nasus.semantic-link-output.v1", "input_digest": payload["input_digest"], "judgments": [
        {"subject_object_id": subject["object_id"], "subject_revision_id": subject["revision_id"],
         "target_object_id": target["object_id"], "target_revision_id": target["revision_id"], "relation": payload["relation"],
         "assessment": "unknown", "reason_summary": "Contract fixture only, not business acceptance.",
         "evidence": [], "counterevidence": [], "unknowns": ["Requires independent semantic review."], "oracle": None}
        for subject in payload["subjects"]]}


def invoke(v, tool, payload, *, headers=None, key=None):
    return v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": tool, "conversation_id": v["conversation"].json()["id"], "input": payload, "idempotency_key": key})


def completed(response):
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    return response.json()


def confirm(v, pending):
    return v["client"].post(f"/v1/tool-invocations/{pending['id']}/confirm", headers=v["headers"])


def count(v, model):
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(model).where(model.project_id == v["project_id"]))


@pytest.fixture
def semantic(documents, monkeypatch):
    v = documents
    service = app.state.container.semantic_evaluations
    config = saved_config(config_id=uuid4().hex)
    encrypted = service.models.secrets.encrypt_api_key("private-provider-key")
    service.models.repository.save_model_config(config, encrypted)
    calls = []
    def handle(request):
        calls.append(request)
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(200, json=native_reply("openai_compatible", json.dumps(unknown_output(payload))))
    monkeypatch.setattr(service, "provider", HTTPSemanticLinkModel(transport=httpx.MockTransport(handle)))
    image = candidate(v)
    selection = dict(project_id=v["project_id"], image_revision_id=image["image_revision_id"],
        expected_image_hash=image["artifact_hash"], relation="asserts", model_config_id=config.config_id,
        target_object_id=next(o["id"] for o in v["document_objects"] if o["type"] == "SourceAcceptanceCriterion"),
        subject_object_ids=[next(o["id"] for o in v["document_objects"] if o["type"] == "TestCase")])
    preview_result = completed(invoke(v, SEMANTIC_PREVIEW_TOOL, selection))
    preview = preview_result["result"]["semantic_preview"]
    assert not calls and preview["max_model_calls"] == 1 and preview["cost_estimate_available"] is False
    assert preview["destination"] == config.base_url and len(preview["source_binding_ids"]) == 2
    v.update(service=service, config=config, encrypted=encrypted, calls=calls, preview=preview,
             selection=selection, preview_result=preview_result, request=preview["request"])
    return v


def test_preview_confirm_native_call_and_private_replay_without_source_in_events(semantic):
    v = semantic
    key = uuid4().hex
    pending = invoke(v, SEMANTIC_EVALUATE_TOOL, {**v["request"], "confirmed_by_user": True}, key=key)
    assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
    assert not v["calls"] and count(v, SemanticCallReservationRecord) == 0
    result = completed(confirm(v, pending.json()))
    assert len(v["calls"]) == 1 and result["result"]["object_refs"] == [f"semantic_evaluation:{result['id']}"]
    assert completed(invoke(v, SEMANTIC_EVALUATE_TOOL, v["request"], key=key))["id"] == result["id"]
    assert completed(confirm(v, pending.json()))["id"] == result["id"] and len(v["calls"]) == 1
    url = f"{v['image_url']}/semantic-evaluations/{result['id']}"
    read = v["client"].get(url, headers=v["headers"])
    assert read.status_code == 200, read.text
    assert read.headers["cache-control"] == "private, no-store"
    evaluation = read.json()["evaluation"]
    assert read.json()["request"] == v["request"]
    assert len(read.json()["spans"]) == 2
    assert {span["basis"] for span in read.json()["spans"]} == {"projected_field"}
    assert all("raw_text" not in span and "text" not in span and span["evidence_id"] for span in read.json()["spans"])
    assert evaluation["status"] == "proposed" and evaluation["authority_status"] == "pending_confirmation"
    assert evaluation["judgments"][0]["assessment"] == "unknown"
    assert evaluation["calibrated_probability"] is None
    assert "artifact_ref" not in read.text and "private-provider-key" not in read.text
    assert count(v, SemanticCallReservationRecord) == count(v, SemanticEvaluationRecord) == 1
    calls = SQLAlchemyLLMCallRepository().list_llm_calls(project_id=v["project_id"])
    calls = [call for call in calls if call.tool_invocation_id == result["id"]]
    assert len(calls) == 1 and calls[0].runtime_mode == "live" and calls[0].outcome == "success"
    assert calls[0].model_calls == 1 and calls[0].input_token_count == 123
    with session_scope() as session:
        reservation = session.get(SemanticCallReservationRecord, result["id"])
        assert reservation.payload["authorized_by"] == v["owner"]["id"]
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == result["id"])).all()
        assert {event.event_type for event in events} >= {"system_image.semantic.call_reserved", "system_image.semantic.evaluated"}
        persisted = json.dumps(reservation.payload) + json.dumps([event.event_payload for event in events])
    for secret in ("Empty input", "HTTP 400", "US-17", "private-provider-key", "local-object://"):
        assert secret not in persisted + json.dumps(result) + json.dumps(v["preview_result"])
    # Reads use original evidence, not current source contents or the active model.
    v["requirement_path"].unlink()
    v["case_path"].unlink()
    v["service"].models.repository.save_model_config(v["config"].model_copy(update={"model_name": "changed"}), v["encrypted"])
    assert v["client"].get(url, headers=v["headers"]).json() == read.json()
    assert v["client"].get(url).status_code == 401
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    for model in (SemanticCallReservationRecord, SemanticEvaluationRecord):
        for statement in (delete(model).where(model.project_id == v["project_id"]),
                          update(model).where(model.project_id == v["project_id"]).values(project_id="changed")):
            with pytest.raises(IntegrityError, match="append-only"):
                with session_scope() as session:
                    session.execute(statement)
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(SemanticEvaluationRecord(invocation_id=uuid4().hex, project_id=v["project_id"],
                artifact_ref="unreserved", artifact_hash="sha256:" + "a" * 64))
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0047_semantic_evaluations.py"
    spec = importlib.util.spec_from_file_location("semantic_evaluation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with pytest.raises(RuntimeError, match="egress reservations exist"):
        with session_scope() as session:
            migration.op = Operations(MigrationContext.configure(session.connection()))
            migration.downgrade()


@pytest.mark.parametrize("change", ["model", "key", "input_digest", "image_hash", "subject"])
def test_changed_consent_pins_do_not_send_source(semantic, change):
    v = semantic
    request = dict(v["request"])
    if change in {"model", "key"}:
        config = v["config"].model_copy(update={"model_name": "changed"}) if change == "model" else v["config"]
        key = v["service"].models.secrets.encrypt_api_key("rotated") if change == "key" else v["encrypted"]
        v["service"].models.repository.save_model_config(config, key)
    elif change == "subject":
        request["subject_object_ids"] = ["foreign-object"]
    else:
        request["input_digest" if change == "input_digest" else "expected_image_hash"] = "sha256:" + "a" * 64
    pending = invoke(v, SEMANTIC_EVALUATE_TOOL, request).json()
    assert pending["status"] == "waiting_confirmation"
    result = confirm(v, pending)
    assert result.status_code == 200 and result.json()["status"] == "failed", result.text
    assert not v["calls"] and count(v, SemanticCallReservationRecord) == count(v, SemanticEvaluationRecord) == 0


@pytest.mark.parametrize("failure", ["provider", "schema", "acl", "outbox_before", "outbox_after"])
def test_failure_reservations_prevent_duplicate_egress_and_atomic_outbox_rolls_back(semantic, monkeypatch, failure):
    v = semantic
    if failure in {"provider", "schema", "acl"}:
        def handle(request):
            v["calls"].append(request)
            if failure == "provider":
                return httpx.Response(503, text="secret-provider-response")
            if failure == "acl":
                repo = SourceAccessRepository()
                snapshot = repo.load_snapshot(v["project_id"])
                repo.set_policy(v["project_id"], v["preview"]["source_binding_ids"][0], SourceAccessRule("restricted"),
                    expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="revoke-during-egress")
            payload = json.loads(json.loads(request.content)["messages"][1]["content"])
            output = "invalid-secret-source" if failure == "schema" else json.dumps(unknown_output(payload))
            return httpx.Response(200, json=native_reply("openai_compatible", output))
        monkeypatch.setattr(v["service"], "provider", HTTPSemanticLinkModel(transport=httpx.MockTransport(handle)))
    else:
        original = EventOutboxRepository.append
        def append(self, event, **kwargs):
            wanted = "system_image.semantic.call_reserved" if failure == "outbox_before" else "system_image.semantic.evaluated"
            if event.event_type == wanted:
                raise RuntimeError("injected transactional outbox error")
            return original(self, event, **kwargs)
        monkeypatch.setattr(EventOutboxRepository, "append", append)
    pending = invoke(v, SEMANTIC_EVALUATE_TOOL, v["request"]).json()
    result = confirm(v, pending)
    assert result.status_code == 200 and result.json()["status"] == "failed", result.text
    expected_calls = 0 if failure == "outbox_before" else 1
    assert len(v["calls"]) == count(v, SemanticCallReservationRecord) == expected_calls
    assert count(v, SemanticEvaluationRecord) == 0
    assert "invalid-secret-source" not in result.text and "secret-provider-response" not in result.text
    confirm(v, pending)
    assert len(v["calls"]) == expected_calls
    assert v["client"].get(f"{v['image_url']}/semantic-evaluations/{pending['id']}", headers=v["headers"]).status_code == 404


def test_concurrent_confirmation_sends_once_and_later_acl_revocation_hides_result(semantic):
    v = semantic
    pending = invoke(v, SEMANTIC_EVALUATE_TOOL, v["request"]).json()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm(v, pending), range(2)))
    assert all(result.status_code == 200 for result in results)
    assert any(result.json()["status"] == "completed" for result in results)
    assert len(v["calls"]) == 1
    url = f"{v['image_url']}/semantic-evaluations/{pending['id']}"
    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    denied = invoke(v, SEMANTIC_PREVIEW_TOOL, v["selection"], headers=v["member_headers"])
    assert denied.status_code == 403 or denied.json()["status"] in {"denied", "failed"}
    repo = SourceAccessRepository()
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], v["preview"]["source_binding_ids"][0], SourceAccessRule("restricted"),
        expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="revoke-after-evaluation")
    assert v["client"].get(url, headers=v["member_headers"]).status_code in {403, 404, 409}
    assert len(v["calls"]) == 1


def test_repository_rechecks_confirmation_ttl_scope_and_canonical_payload(semantic, monkeypatch):
    v = semantic
    reserve = v["service"].repository.reserve
    for mutation in ("expired", "unconfirmed", "payload", "scope", "not_running"):
        def changed(request, preview, prepared, *, invocation_id, **kwargs):
            with session_scope() as session:
                record = session.get(ToolInvocationRecord, invocation_id)
                payload = dict(record.input_payload)
                if mutation == "expired":
                    payload["confirmed_at"] = "2000-01-01T00:00:00+00:00"
                elif mutation == "unconfirmed":
                    payload["confirmed_by_user"] = False
                elif mutation == "payload":
                    payload["model_config_digest"] = "sha256:" + "b" * 64
                elif mutation == "scope":
                    payload["agent_goal_id"] = "foreign-goal"
                else:
                    record.status = "pending"
                record.input_payload = payload
            return reserve(request, preview, prepared, invocation_id=invocation_id, **kwargs)
        monkeypatch.setattr(v["service"].repository, "reserve", changed)
        pending = invoke(v, SEMANTIC_EVALUATE_TOOL, v["request"]).json()
        result = confirm(v, pending)
        assert result.status_code == 200 and result.json()["status"] == "failed", result.text
        assert not v["calls"] and count(v, SemanticCallReservationRecord) == 0


def test_history_is_scoped_paginated_body_free_and_rechecks_revocation(semantic, monkeypatch):
    v = semantic
    url = f"{v['image_url']}/revisions/{v['request']['image_revision_id']}/semantic-evaluations"
    params = {"target_object_id": v["request"]["target_object_id"], "relation": "asserts", "limit": 1}
    assert v["client"].get(url, params=params, headers=v["headers"]).json()["items"] == []
    first = completed(confirm(v, invoke(v, SEMANTIC_EVALUATE_TOOL, v["request"]).json()))
    async def fail(*args):
        raise RuntimeError("unknown outcome")
    monkeypatch.setattr(v["service"].provider, "generate", fail)
    second = confirm(v, invoke(v, SEMANTIC_EVALUATE_TOOL, v["request"]).json()).json()
    assert second["status"] == "failed"
    response = v["client"].get(url, params=params, headers=v["headers"])
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    page = response.json()
    assert len(page["items"]) == 1 and page["next_after_id"]
    next_page = v["client"].get(url, params={**params, "after_id": page["next_after_id"]}, headers=v["headers"]).json()
    assert next_page["next_after_id"] is None
    rows = page["items"] + next_page["items"]
    assert {item["invocation_id"] for item in rows} == {first["id"], second["id"]}
    assert {item["state"] for item in rows} == {"archived", "incomplete"}
    for secret in ("Empty input", "HTTP 400", "US-17", "private-provider-key", "local-object://"):
        assert secret not in json.dumps(rows)
    assert v["client"].get(url, params={**params, "relation": "implements"}, headers=v["headers"]).json()["items"] == []
    assert v["client"].get(url, params={**params, "target_object_id": "foreign"}, headers=v["headers"]).status_code == 404
    assert v["client"].get(url, params=params).status_code == 401
    grant_member(v)
    assert v["client"].get(url, params=params, headers=v["member_headers"]).status_code == 200
    original = v["service"].repository.list_for_target
    def revoke(*args):
        result = original(*args)
        repo = SourceAccessRepository()
        snapshot = repo.load_snapshot(v["project_id"])
        repo.set_policy(v["project_id"], v["preview"]["source_binding_ids"][0], SourceAccessRule("restricted"),
            expected_epoch=snapshot.acl_epoch, changed_by=v["owner"]["id"], invocation_id="revoke-history-read")
        return result
    monkeypatch.setattr(v["service"].repository, "list_for_target", revoke)
    denied = v["client"].get(url, params=params, headers=v["member_headers"])
    assert denied.status_code in {403, 409} and first["id"] not in denied.text
