"""HTTP image/knowledge projection over actual PG source policy and identity data."""
from __future__ import annotations

import pytest

from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository
from apps.api.app.infrastructure.system_image import source_read_projection
from apps.api.app.main import app
from apps.api.app.store import get_runtime_assembly
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_scoped_agent_context import set_policy
from apps.api.tests.test_source_scoped_memory_retriever import scoped_project


def test_image_and_knowledge_api_share_safe_facts_and_mark_withheld_totals(scoped_project):
    v = scoped_project
    before = v.repository.load_project_snapshot(v.project_id)
    response = v.client.get(f"/v1/projects/{v.project_id}/system-image", headers=v.member_headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    image = response.json()
    assert image["visibility"]["mode"] == "source_filtered"
    assert image["build_state"]["status"] == "visibility_limited"
    assert image["build_state"]["stage_index"] is None
    assert "unavailable" in image["summary"]
    assert image["project"]["progress"] is None and image["project"]["system_image_status"] is None
    assert image["source_manifest"] is None
    for field in image["visibility"]["withheld_sections"]:
        if field in image and field != "source_manifest":
            assert image[field] == []
    assert "RestrictedPaymentSecret" not in response.text and v.hidden_source.id not in response.text
    assert "s3://" not in response.text and "local-object://" not in response.text
    assert image["sources"] and all(item["content_ref"] is None and item["credential_ref"] is None for item in image["sources"])
    assert image["chunks"] and all(item["content_ref"] is None and item["metadata"] == {} for item in image["chunks"])

    listed = v.client.get(f"/v1/projects/{v.project_id}/knowledge", headers=v.member_headers)
    assert listed.status_code == 200 and listed.json() == image["objects"]
    assert listed.headers["cache-control"] == "private, no-store"
    assert image["objects"] and any("Orders" in item["name"] for item in image["objects"])
    for obj in image["objects"]:
        assert obj["code_reference"] and obj["evidence"] == [] and obj["relations"] == []
        detail = v.client.get(f"/v1/projects/{v.project_id}/knowledge/{obj['id']}", headers=v.member_headers)
        assert detail.status_code == 200 and detail.json() == obj
        assert detail.headers["cache-control"] == "private, no-store"
    hidden = next(item for item in before.knowledge_objects if not item.code_reference)
    denied = v.client.get(f"/v1/projects/{v.project_id}/knowledge/{hidden.id}", headers=v.member_headers)
    assert denied.status_code == 404 and hidden.name not in denied.text
    assert v.repository.load_project_snapshot(v.project_id) == before


def test_project_only_view_preserves_legacy_contract(scoped_project):
    v = scoped_project
    set_policy(v, SourceAccessRule())
    with actor_scope(v.actor):
        expected = get_runtime_assembly().system_image_service.get(v.project_id).model_dump(mode="json")
    response = v.client.get(f"/v1/projects/{v.project_id}/system-image", headers=v.member_headers)
    assert response.status_code == 200 and response.json() == expected
    assert response.json()["visibility"]["mode"] == "project"
    assert v.hidden_source.id in response.text


@pytest.mark.parametrize("path", ["system-image", "knowledge"])
def test_corrupt_alias_projection_returns_sanitized_integrity_error(scoped_project, monkeypatch, path):
    v = scoped_project
    verify = source_read_projection.verified_code_alias

    def corrupt_detached_record(row):
        row.content_hash = "sha256:" + "0" * 64
        return verify(row)

    monkeypatch.setattr(source_read_projection, "verified_code_alias", corrupt_detached_record)
    response = v.client.get(f"/v1/projects/{v.project_id}/{path}", headers=v.member_headers)
    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "source_projection_integrity_failed"
    assert "Orders" not in response.text and "RestrictedPaymentSecret" not in response.text
    assert "entity_revision_id" not in response.text


@pytest.mark.parametrize("path", ["system-image", "knowledge", "knowledge/object"])
@pytest.mark.parametrize("change", ["policy", "membership"])
def test_read_during_access_change_is_rejected_without_old_payload(scoped_project, monkeypatch, path, change):
    v = scoped_project
    original = SystemImageRepository.load_project_snapshot

    def read_then_change(repository, project_id):
        result = original(repository, project_id)
        if project_id == v.project_id:
            if change == "policy":
                set_policy(v, SourceAccessRule("restricted", (v.actor.id,)))
            else:
                assert v.client.delete(v.membership_url, headers=v.headers).status_code == 200
        return result

    monkeypatch.setattr(SystemImageRepository, "load_project_snapshot", read_then_change)
    response = v.client.get(f"/v1/projects/{v.project_id}/{path}", headers=v.member_headers)
    assert response.status_code == (409 if change == "policy" else 403), response.text
    assert "RestrictedPaymentSecret" not in response.text and "Orders" not in response.text


def test_fresh_status_summaries_do_not_append_unproven_long_term_memory(scoped_project):
    v = scoped_project
    with actor_scope(v.actor):
        # This checks the read-model summary, not the later Chat egress/replay path.
        from apps.api.app.application.platform.read_models import ReadModelSummaryService
        from types import SimpleNamespace
        summaries = ReadModelSummaryService(SimpleNamespace(get_system_image=app.state.container.system_image.get_system_image))
        for summary in (summaries.system_image_status_summary(v.project_id), summaries.knowledge_status_summary(v.project_id)):
            assert "unavailable" in summary and "RestrictedPaymentSecret" not in summary
            assert "0 relationships" not in summary
