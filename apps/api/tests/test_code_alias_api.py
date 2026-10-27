from sqlalchemy import select, text, update

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.infrastructure.persistence.code_alias_models import CodeObjectAliasRecord as Alias
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.code_entity_repository import CodeEntityRepository
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.application.system_image.code_entity_registry import CodeEntityRegistrationService
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.tests.test_code_symbol_identity import external
from apps.api.tests.test_image_revision_api import selected
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy


def identities(v):
    _, image, image_url = selected(v)
    with session_scope() as session:
        alias = session.scalars(select(Alias).where(Alias.project_id == v["project_id"],
            Alias.entity_revision_id == v["obj"]["code_reference"]["entity_revision_id"])).first()
        assert alias is not None
        legacy_id = alias.legacy_object_id
    url = image_url + f"/objects/{legacy_id}/identity"
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    return image, image_url, legacy_id, response


def test_http_and_canonical_queries_resolve_old_ids_without_returning_source_text(evidence_api):
    v = evidence_api
    image, image_url, legacy_id, response = identities(v)
    identity = response.json()
    assert response.headers["cache-control"] == "private, no-store"
    assert identity["canonical_object_id"] == v["obj"]["id"] == "CODE-" + v["obj"]["code_reference"]["entity_id"]
    assert identity["frozen_object_id"] == identity["canonical_object_id"]
    assert identity["image_artifact_hash"] == image["artifact_hash"]
    assert identity["entity_revision_id"] == v["obj"]["code_reference"]["entity_revision_id"]
    assert all(value not in response.text for value in ("Orders", str(v["path"]), "s3://", "provider_node_id"))
    command = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "query.system_image.revisions.resolve_code_object",
        "input": {"project_id": v["project_id"], "image_revision_id": image["image_revision_id"], "object_id": legacy_id}})
    assert command.status_code == 200 and command.json()["status"] == "completed", command.text
    command = command.json()
    receipt = command["result"]["image_query"]
    assert receipt["operation"] == "code_identity"
    expanded = v["client"].get(f"/v1/tool-invocations/{command['id']}/image-query", headers=v["headers"])
    assert expanded.status_code == 200 and expanded.json() == identity, expanded.text
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(command["id"], v["project_id"]) == receipt
        snapshots = SourceSnapshotRepository()
        source = snapshots.materialization_sources(snapshots.latest_manifest(v["project_id"]))[0]
        units = app.state.container.system_image.lifecycle._operations.source_ingestion.extract_text_units(source)
        graph = TreeSitterCodeIntelligenceAdapter().analyze(units)
        # Explicit Provider-ID replacement fixture, not a real second Provider run.
        CodeEntityRegistrationService(CodeEntityRepository()).register(source,
            attach_symbol_keys(external(graph), graph), units, captured_at="2026-10-07T00:00:00Z")
    again = v["client"].get(f"/v1/tool-invocations/{command['id']}/image-query", headers=v["headers"])
    assert again.status_code == 200 and again.json() == identity, again.text
    assert v["client"].get(image_url + "/objects/unknown/identity", headers=v["headers"]).status_code == 404


def test_source_line_change_keeps_public_id_and_historical_evidence_revision(evidence_api):
    v = evidence_api
    _, image_url, legacy_id, before = identities(v)
    v["path"].write_text("# shifted\nclass Orders:\n    def submit(self):\n        return 'updated'\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    current = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"]).json()
    obj = next(item for item in current["objects"] if item["name"].startswith("Orders"))
    assert obj["id"] == v["obj"]["id"]
    assert obj["code_reference"]["entity_revision_id"] != before.json()["entity_revision_id"]
    old = v["client"].get(image_url + f"/objects/{legacy_id}/identity", headers=v["headers"])
    assert old.status_code == 200 and old.json() == before.json()
    page = v["client"].get(image_url + f"/objects/{old.json()['frozen_object_id']}/evidence/{v['evidence']['evidence_id']}", headers=v["headers"])
    assert page.status_code == 200 and "original" in page.json()["content"]


def test_alias_lookup_does_not_bypass_project_or_source_acl_and_rechecks_mid_read(evidence_api, monkeypatch):
    v = evidence_api
    _, image_url, legacy_id, _ = identities(v)
    url = image_url + f"/objects/{legacy_id}/identity"
    assert v["client"].get(url).status_code == 401
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    grant_member(v)
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 200
    policy(v)
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    policy(v, (v["member"]["id"],))
    repository = app.state.container.image_revisions.code_aliases
    original = repository.find_in_image
    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        policy(v)
        return result
    monkeypatch.setattr(repository, "find_in_image", revoke)
    changed = v["client"].get(url, headers=v["member_headers"])
    assert changed.status_code in (403, 409), changed.text
    assert "entity_revision_id" not in changed.text


def test_corrupted_alias_hash_is_a_sanitized_integrity_failure(evidence_api):
    v = evidence_api
    _, image_url, legacy_id, _ = identities(v)
    try:
        with session_scope() as session:
            session.execute(text("ALTER TABLE code_object_aliases DISABLE TRIGGER immutable_code_object_aliases"))
            session.execute(update(Alias).where(Alias.project_id == v["project_id"]).values(content_hash="sha256:" + "0" * 64))
        response = v["client"].get(image_url + f"/objects/{legacy_id}/identity", headers=v["headers"])
        assert response.status_code == 502, response.text
        assert response.json()["detail"]["error"]["code"] == "image_integrity_failed"
        assert "Orders" not in response.text and legacy_id not in response.text
        evidence = v["client"].get(v["url"], headers=v["headers"], params=v["params"])
        assert evidence.status_code == 502, evidence.text
        assert evidence.json()["detail"]["error"]["code"] == "evidence_integrity_failed"
    finally:
        with session_scope() as session:
            session.execute(text("ALTER TABLE code_object_aliases ENABLE TRIGGER immutable_code_object_aliases"))
