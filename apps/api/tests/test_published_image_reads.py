"""Published consumers read fixed members, not later compatibility projections."""
import asyncio
from uuid import uuid4

import pytest

from apps.api.app.main import app
from apps.api.app.application.agent.agent_models import ConversationSession
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.system_image.publication import PublicationChanged
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.tests.test_image_publications_api import publication, review, review_request, publish_request, history, inspect
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_semantic_evaluations_api import completed, invoke
from apps.api.tests.test_source_access_api import grant_member


def publish(v):
    approval, _ = review(v)
    completed(invoke(v, "baseline.promote", publish_request(v, approval), key=uuid4().hex))
    return history(v)["head"]


def read(v, **params):
    result = v["client"].get(v["image_url"], headers=v["headers"], params=params)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "private, no-store"
    return result.json()


def test_current_api_knowledge_memory_and_retrieval_stay_on_published_image(publication, monkeypatch):
    v = publication
    assert read(v)["read_state"]["mode"] == "legacy_draft"
    head = publish(v)
    first = read(v)
    assert first["read_state"]["pin"]["publication_id"] == head["publication_id"]
    assert first["read_state"]["pin"]["quality_generation_authorized"] is False
    assert first["candidate_revision"] is None and first["objects"]
    assert all(item["content_ref"] is None for item in first["sources"])
    v["path"].write_text(v["path"].read_text().replace("original", "later unpublished source"))
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    current = read(v)
    assert current == first
    working = read(v, view="working")
    assert working["read_state"] == {"mode": "working_draft", "pin": None, "version_id": None}
    assert working["source_manifest"]["manifest_id"] != first["source_manifest"]["manifest_id"]
    knowledge = v["client"].get(f"/v1/projects/{v['project_id']}/knowledge", headers=v["headers"])
    assert knowledge.json() == first["objects"]
    def forbidden(*args, **kwargs):
        raise AssertionError("Published read accessed mutable projection/index")
    service = app.state.container
    memory = service.agent._memory
    retriever = memory.system_image_retriever
    monkeypatch.setattr(type(retriever._system_images), "load_project_snapshot", forbidden)
    monkeypatch.setattr(type(retriever._retrieval_index), "search", forbidden)
    assert read(v) == first
    conversation = ConversationSession.model_validate({**v["conversation"].json(), "version_id": None})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        sections = memory.system_image_memory_context.context_sections(v["project_id"])
        assert head["image_revision_id"] in "\n".join(sections)
        assert "later unpublished source" not in "\n".join(sections)
        result = asyncio.run(retriever.search_project_memory(conversation,
            first["objects"][0]["name"], trace=True))
        assert result.image_read_state.pin.publication_id == head["publication_id"]
        assert result.hits and not result.retrieval_run_refs
        assert all(hit.ref.startswith("image_revision:" + head["image_revision_id"] + ":") for hit in result.hits)
        assert "unversioned_index_withheld" in result.strategy


def test_published_version_gap_never_inherits_official_or_reads_draft(publication):
    v = publication
    publish(v)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        view = app.state.container.system_image.snapshots._reader.published.read(v["project_id"], version_id="unpublished-version")
        assert view.state.mode == "unpublished" and not view.objects and view.state.pin is None
        conversation = ConversationSession.model_validate({**v["conversation"].json(), "version_id": "unpublished-version"})
        result = asyncio.run(app.state.container.agent._memory.system_image_retriever.search_project_memory(conversation, "original"))
        assert not result.hits and result.image_read_state.mode == "unpublished"


def test_corrupt_published_artifact_fails_without_fallback(publication, monkeypatch):
    v = publication
    publish(v)
    storage = app.state.container.image_revisions.artifacts.storage
    monkeypatch.setattr(storage, "get_bytes", lambda *args, **kwargs: b"corrupt unpublished text")
    for url in (v["image_url"], f"/v1/projects/{v['project_id']}/knowledge"):
        response = v["client"].get(url, headers=v["headers"])
        assert response.status_code == 502, response.text
        assert "corrupt unpublished text" not in response.text


def test_source_revocation_hides_entire_published_view(publication):
    v = publication
    publish(v)
    grant_member(v)
    assert v["client"].get(v["image_url"], headers=v["member_headers"]).status_code == 200
    repo = SourceAccessRepository()
    binding = inspect(v, {**v["target"], "expected_head_id": history(v)["head"]["publication_id"]})["source_members"][0]["binding_id"]
    snapshot = repo.load_snapshot(v["project_id"])
    repo.set_policy(v["project_id"], binding, SourceAccessRule("restricted"), expected_epoch=snapshot.acl_epoch,
        changed_by=v["owner"]["id"], invocation_id="published-read-revocation")
    response = v["client"].get(v["image_url"], headers=v["member_headers"])
    assert response.status_code == 403 and "objects" not in response.text


def test_head_movement_during_read_is_a_conflict(publication, monkeypatch):
    v = publication
    publish(v)
    reader = app.state.container.system_image.snapshots._reader.published
    original = reader.selections.read_selection
    calls = 0
    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls > 1:
            result["head"]["publication_id"] = "concurrent-publication"
        return result
    monkeypatch.setattr(reader.selections, "read_selection", changed)
    response = v["client"].get(v["image_url"], headers=v["headers"])
    assert response.status_code == 409 and response.json()["error"]["code"] == "publication_changed"


def test_new_publication_switches_consumers_and_rejects_old_context_pin(publication):
    v = publication
    first = publish(v)
    memory = app.state.container.agent._memory.system_image_memory_context
    reader = app.state.container.system_image.snapshots._reader.published
    with actor_scope(UserProfile.model_validate(v["owner"])):
        original = reader.read(v["project_id"])
    v["path"].write_text(v["path"].read_text() + "\nclass NewUnpublishedFeature:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    image = candidate(v)
    assert image["artifact_hash"] != first["image_artifact_hash"]
    target = {**v["target"], "expected_head_id": first["publication_id"],
        "image_revision_id": image["image_revision_id"], "image_artifact_hash": image["artifact_hash"]}
    approval, _ = review(v, review_request(v, target=target))
    completed(invoke(v, "baseline.promote", publish_request(v, approval, target), key=uuid4().hex))
    response = read(v)
    assert response["read_state"]["pin"]["sequence"] == 2
    assert any("NewUnpublishedFeature" in item["name"] for item in response["objects"])
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PublicationChanged):
            reader.require_current(original)
        with pytest.raises(PublicationChanged):
            memory.context_sections(v["project_id"], expected_state=original.state)
        assert image["image_revision_id"] in "\n".join(memory.context_sections(v["project_id"]))


def test_version_publication_does_not_publish_official_target(publication):
    from apps.api.app.infrastructure.persistence.db_models import BaselineRecord
    from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
    v = publication
    baseline_id = str(uuid4())
    with session_scope() as session:
        session.add(BaselineRecord(id=baseline_id, project_id=v["project_id"], kind="version_working",
            source_version_id="version-fixture", updated_at="2026-09-19T00:00:00Z"))
    target = {**v["target"], "target_baseline_id": baseline_id}
    approval, _ = review(v, review_request(v, target=target))
    completed(invoke(v, "baseline.promote", publish_request(v, approval, target)))
    response = read(v)
    assert response["read_state"]["mode"] == "unpublished" and not response["objects"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        reader = app.state.container.system_image.snapshots._reader.published
        version = reader.read(v["project_id"], version_id="version-fixture")
        assert version.state.pin.baseline_id == baseline_id and version.objects
    with session_scope() as session:
        session.add(BaselineRecord(id=str(uuid4()), project_id=v["project_id"], kind="version_working",
            source_version_id="version-fixture", updated_at="2026-09-19T00:00:00Z"))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PublicationChanged, match="Ambiguous"):
            reader.read(v["project_id"], version_id="version-fixture")


def test_retrieval_rechecks_head_after_model_wait(publication, monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    v = publication
    publish(v)
    retriever = app.state.container.agent._memory.system_image_retriever
    original = retriever._published.selections.read_selection
    moved = False
    def selection(*args, **kwargs):
        value = deepcopy(original(*args, **kwargs))
        if moved:
            value["head"]["publication_id"] = "moved-during-rerank"
        return value
    async def rerank(**kwargs):
        nonlocal moved
        moved = True
        return SimpleNamespace(ranked_indices=[0])
    monkeypatch.setattr(retriever._published.selections, "read_selection", selection)
    monkeypatch.setattr(retriever._workspace, "rerank_candidates", rerank)
    conversation = ConversationSession.model_validate({**v["conversation"].json(), "version_id": None})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(PublicationChanged):
            asyncio.run(retriever.search_project_memory(conversation, read(v)["objects"][0]["name"]))


def test_agent_memory_http_reports_same_published_pin_and_retrieval_limitation(publication):
    v = publication
    head = publish(v)
    response = v["client"].get("/v1/agent-memory/context", headers=v["headers"],
        params={"conversation_id": v["conversation"].json()["id"]})
    assert response.status_code == 200, response.text
    value = response.json()
    state = value["retrieved_context"]["image_read_state"]
    assert state["pin"]["publication_id"] == head["publication_id"]
    assert state == value["project_long_term_memory"]["image_read_state"]
    assert value["retrieved_context"]["strategy"] in {"empty_query", "published_lexical_rerank_unversioned_index_withheld"}
    assert value["project_long_term_memory"]["memory_items"] == []
    assert response.headers["cache-control"] == "private, no-store"
