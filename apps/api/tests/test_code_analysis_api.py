from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import func, select

from apps.api.app.main import app
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.code_analysis_models import CodeAnalysisRecord
from apps.api.app.infrastructure.persistence.code_analysis_repository import CodeAnalysisRepository
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityRevisionRecord
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api


def endpoint(v):
    return f"/v1/projects/{v['project_id']}/system-image/source-analyses"


def listed(v, headers=None):
    response = v["client"].get(endpoint(v), headers=headers or v["headers"], params={"source_revision_id": v["revision"]})
    assert response.status_code == 200, response.text
    return response


def test_actual_tool_materialization_produces_revision_pinned_paginated_report(evidence_api):
    v = evidence_api
    response = listed(v)
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["next_after_id"] is None and len(data["items"]) == 1
    analysis = data["items"][0]
    assert analysis["summary"]["parsed"] == 1 and analysis["summary"]["failed"] == 0
    assert analysis["raw_inventory_available"] is True
    assert analysis["scope"] == "static_observations_not_business_or_runtime_acceptance"
    projection = analysis["projection"]
    assert projection["status"] == "partial"
    assert projection["providers"][0]["capabilities"]["operations"] == ["capabilities", "analyze", "analyze_controlled"]
    assert projection["providers"][0]["relationship_enumeration"] == "unknown"
    url = endpoint(v) + "/" + analysis["analysis_id"]
    params = {"source_revision_id": v["revision"], "limit": 1}
    page = v["client"].get(url, headers=v["headers"], params=params)
    assert page.status_code == 200 and page.headers["cache-control"] == "private, no-store"
    assert page.json()["items"][0]["relative_path"] == "orders.py"
    assert page.json()["items"][0]["status"] == "parsed"
    assert page.json()["analysis"]["projection"] == projection
    assert "s3://" not in page.text and "local-object://" not in page.text
    assert "return 'original'" not in page.text
    facts = v["client"].get(url, headers=v["headers"], params={**params, "section": "facts"})
    assert facts.status_code == 200 and facts.json()["items"][0]["kind"] == "module"
    assert v["client"].get(url, headers=v["headers"]).status_code == 422
    assert v["client"].get(url, headers=v["headers"], params={**params, "offset": 2}).status_code == 400
    assert v["client"].get(url, headers=v["headers"], params={**params, "limit": 101}).status_code == 422
    assert v["client"].get(url, headers=v["headers"], params={**params, "source_revision_id": "missing"}).status_code == 404
    other = v["client"].post("/v1/projects", headers=v["headers"], json={"name": "Other analysis scope"}).json()["id"]
    assert v["client"].get(f"/v1/projects/{other}/system-image/source-analyses/{analysis['analysis_id']}",
                            headers=v["headers"], params=params).status_code == 404
    v["invoke"]("system_image.context.materialize")
    assert listed(v).json() == data

    v["path"].write_text("class Broken:\n    def broken(\n")
    v["invoke"]("system_image.sources.ingest")
    invoked = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": "system_image.context.materialize",
        "input": {"project_id": v["project_id"]},
    })
    assert invoked.status_code == 200 and invoked.json()["status"] == "failed", invoked.text
    with session_scope() as session:
        reports = session.scalars(select(CodeAnalysisRecord).where(CodeAnalysisRecord.project_id == v["project_id"])).all()
        failed = next(row for row in reports if row.payload["summary"]["failed"] == 1)
        assert len(reports) == 2 and failed.source_revision_id != v["revision"]
        assert session.scalar(select(func.count()).select_from(CodeEntityRevisionRecord).where(
            CodeEntityRevisionRecord.source_revision_id == failed.source_revision_id)) == 0
        failed_id, failed_revision = failed.analysis_id, failed.source_revision_id
    failed_page = v["client"].get(endpoint(v) + "/" + failed_id, headers=v["headers"],
                                  params={"source_revision_id": failed_revision})
    assert failed_page.status_code == 200 and failed_page.json()["items"][0]["status"] == "failed"
    # Failure of a later extraction does not overwrite or lose the prior report.
    assert listed(v).json() == data
    assert v["client"].get(url, headers=v["headers"], params=params).json() == page.json()


def test_received_observations_are_archived_filtered_and_survive_source_changes(evidence_api):
    v = evidence_api
    analysis = listed(v).json()["items"][0]
    summary = analysis["observation_summary"]
    assert summary["basis"] == "received_projection_not_complete_native_graph"
    assert summary["entity_count"] > 0 and summary["relationship_count"] > 0
    url = endpoint(v) + "/" + analysis["analysis_id"]
    params = {"source_revision_id": v["revision"], "section": "entities", "limit": 1}
    first = v["client"].get(url, headers=v["headers"], params=params)
    assert first.status_code == 200, first.text
    assert first.json()["total"] == summary["entity_count"]
    assert first.headers["cache-control"] == "private, no-store"
    assert first.json()["next_offset"] == 1
    assert "artifact_ref" not in first.text and "evidence_refs" not in first.text
    assert "s3://" not in first.text and "local-object://" not in first.text
    assert "return 'original'" not in first.text
    remainder = v["client"].get(url, headers=v["headers"], params={**params, "offset": 1, "limit": 100})
    assert remainder.status_code == 200 and remainder.json()["next_offset"] is None
    entities = [*first.json()["items"], *remainder.json()["items"]]
    assert len({item["provider_node_id"] for item in entities}) == summary["entity_count"]
    for section, field, value in (("entities", "kind", "class"), ("entities", "status", "unresolved"),
                                  ("relationships", "kind", "belongs_to")):
        filtered = v["client"].get(url, headers=v["headers"], params={**params, "section": section, field: value})
        assert filtered.status_code == 200, filtered.text
        key = "identity_status" if field == "status" else "entity_kind" if section == "entities" else "relationship_kind"
        assert all(item[key] == value for item in filtered.json()["items"])
    relations = v["client"].get(url, headers=v["headers"], params={**params, "section": "relationships", "limit": 100})
    assert relations.status_code == 200 and relations.json()["total"] == summary["relationship_count"]
    assert all(item["from_provider_node_id"] in {e["provider_node_id"] for e in entities}
        and item["to_provider_node_id"] in {e["provider_node_id"] for e in entities} for item in relations.json()["items"])
    assert v["client"].get(url, headers=v["headers"], params={**params, "section": "relationships", "status": "unresolved"}).status_code == 400
    v["path"].write_text("class Changed:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    v["path"].unlink()
    assert v["client"].get(url, headers=v["headers"], params=params).json() == first.json()


def test_private_native_query_archive_is_verified_but_never_returned_by_public_pages(evidence_api):
    from copy import deepcopy
    from dataclasses import asdict
    from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
    from apps.api.app.infrastructure.system_image.code_native_query_observations import NativeQueryObservations
    from apps.api.app.infrastructure.system_image.code_observation_artifacts import ArchivedCodeObservations
    from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository

    v = evidence_api
    current = listed(v).json()["items"][0]
    with session_scope() as session:
        report = deepcopy(session.get(CodeAnalysisRecord, current["analysis_id"]).payload)
    archives = ArchivedCodeObservations(ObjectStorage())
    body = archives.read(report)
    queries = NativeQueryObservations(report["provider"], report["provider_version"])
    queries.record("private-static-query-fixture", {"project": "private-query-sentinel"},
        {"rows": [["private-native-kind", "private-source-sentinel"]]})
    body.update(schema="nasus.code-observation-archive.v2", native_queries=[asdict(item) for item in queries.items])
    report["observation_archive"] = archives.put(body)
    source = SystemImageRepository().load_raw_assets()[v["project_id"]][0]
    ident = CodeAnalysisRepository().record(source, report, captured_at=current["recorded_at"])
    assert archives.read(report) == body
    assert ident != current["analysis_id"]
    assert "private-query-sentinel" not in listed(v).text
    url = endpoint(v) + "/" + ident
    for section in ("files", "facts", "entities", "relationships"):
        response = v["client"].get(url, headers=v["headers"], params={"source_revision_id": v["revision"], "section": section})
        assert response.status_code == 200, response.text
        assert all(value not in response.text for value in ("private-query-sentinel", "private-native-kind",
            "private-source-sentinel", "native_queries", "response_json", "artifact_ref"))
    assert v["client"].get(url, headers=v["headers"], params={"source_revision_id": v["revision"], "section": "native_queries"}).status_code == 422


@pytest.mark.parametrize("change", ["missing", "body", "policy", "membership"])
def test_observation_archive_read_failure_and_revocation_hide_all_rows(evidence_api, monkeypatch, change):
    v = evidence_api
    analysis = listed(v).json()["items"][0]
    url = endpoint(v) + "/" + analysis["analysis_id"]
    params = {"source_revision_id": v["revision"], "section": "entities"}
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    observations = app.state.container.code_analysis.observations
    original, reads = observations.read, []

    def interrupted(report):
        reads.append(report["observation_archive"]["artifact_hash"])
        if change == "missing":
            raise ValueError("private storage secret")
        body = original(report)
        if change == "body":
            body["result"]["entities"][0]["name"] = "forged-private-name"
        elif change == "membership":
            assert v["client"].delete(membership, headers=v["headers"]).status_code == 200
        else:
            SourceAccessRepository().set_policy(v["project_id"], analysis["binding_id"], SourceAccessRule("restricted"),
                expected_epoch=0, changed_by=v["owner"]["id"], invocation_id="observation-revocation-test")
        return body

    # Inject at the live port even if an earlier instance patch restored a bound method.
    monkeypatch.setattr(observations, "read", interrupted)
    response = v["client"].get(url, headers=v["member_headers"], params=params)
    assert len(reads) == 1
    assert response.status_code == {"missing": 502, "body": 502, "policy": 409, "membership": 403}[change], response.text
    assert all(value not in response.text for value in ("orders.py", "forged-private-name", "storage secret", "s3://", "local-object://"))
    if change in {"policy", "membership"}:
        monkeypatch.setattr(observations, "read", lambda *a: pytest.fail("denied reads must not fetch archives"))
        assert v["client"].get(url, headers=v["member_headers"], params=params).status_code == 403


def test_new_and_legacy_reports_coexist_without_backfilling_capabilities(evidence_api):
    from copy import deepcopy
    from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository

    v = evidence_api
    current = listed(v).json()["items"][0]
    with session_scope() as session:
        row = session.get(CodeAnalysisRecord, current["analysis_id"])
        assert row.payload["schema"] == "nasus.code-analysis.v3"
        original = deepcopy(row.payload)
    legacy = {key: value for key, value in original.items() if key not in {"projection", "observation_archive"}}
    legacy["schema"] = "nasus.code-analysis.v1"
    source = SystemImageRepository().load_raw_assets()[v["project_id"]][0]
    repository = CodeAnalysisRepository()
    legacy_id = repository.record(source, legacy, captured_at=current["recorded_at"])
    assert repository.record(source, legacy, captured_at=current["recorded_at"]) == legacy_id
    legacy_v2 = {key: value for key, value in original.items() if key != "observation_archive"}
    legacy_v2["schema"] = "nasus.code-analysis.v2"
    legacy_v2_id = repository.record(source, legacy_v2, captured_at=current["recorded_at"])
    rows = listed(v).json()["items"]
    assert len(rows) == 3
    assert next(item for item in rows if item["analysis_id"] == legacy_id)["projection"] is None
    for ident, expected in ((current["analysis_id"], current["projection"]), (legacy_id, None),
                            (legacy_v2_id, current["projection"])):
        page = v["client"].get(endpoint(v) + "/" + ident, headers=v["headers"], params={"source_revision_id": v["revision"]})
        assert page.status_code == 200 and page.json()["analysis"]["projection"] == expected
    for ident in (legacy_id, legacy_v2_id):
        missing = v["client"].get(endpoint(v) + "/" + ident, headers=v["headers"],
            params={"source_revision_id": v["revision"], "section": "entities"})
        assert missing.status_code == 404 and "orders.py" not in missing.text
    with session_scope() as session:
        assert session.get(CodeAnalysisRecord, current["analysis_id"]).payload == original
        assert session.get(CodeAnalysisRecord, legacy_id).payload == legacy
        assert session.get(CodeAnalysisRecord, legacy_v2_id).payload == legacy_v2


def test_claiming_complete_with_partial_metadata_fails_closed(evidence_api, monkeypatch):
    from copy import deepcopy
    from apps.api.app.domain.system_image.source_snapshots import snapshot_digest

    v = evidence_api
    current = listed(v).json()["items"][0]
    original = CodeAnalysisRepository.read

    def forged(repository, *args, **kwargs):
        header, payload = original(repository, *args, **kwargs)
        payload = deepcopy(payload)
        payload["projection"]["status"] = "complete"
        return replace(header, report_hash=snapshot_digest(payload), projection=payload["projection"]), payload

    monkeypatch.setattr(CodeAnalysisRepository, "read", forged)
    response = v["client"].get(endpoint(v) + "/" + current["analysis_id"], headers=v["headers"],
                                params={"source_revision_id": v["revision"]})
    assert response.status_code == 502 and "orders.py" not in response.text


@pytest.mark.parametrize("operation", ["read", "list_for_revision"])
@pytest.mark.parametrize("change", ["policy", "membership"])
def test_analysis_reads_authorize_before_and_after_database_access(evidence_api, monkeypatch, operation, change):
    v = evidence_api
    analysis = listed(v).json()["items"][0]
    url = endpoint(v) + ("/" + analysis["analysis_id"] if operation == "read" else "")
    params = {"source_revision_id": v["revision"]}
    assert v["client"].get(url, params=params).status_code == 401
    assert v["client"].get(url, params=params, headers=v["member_headers"]).status_code == 403
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    assert v["client"].get(url, params=params, headers=v["member_headers"]).status_code == 200
    original = getattr(CodeAnalysisRepository, operation)

    def changed(repository, *args, **kwargs):
        result = original(repository, *args, **kwargs)
        if change == "membership":
            assert v["client"].delete(membership, headers=v["headers"]).status_code == 200
        else:
            SourceAccessRepository().set_policy(v["project_id"], analysis["binding_id"], SourceAccessRule("restricted"),
                expected_epoch=0, changed_by=v["owner"]["id"], invocation_id="analysis-revocation-test")
        return result

    monkeypatch.setattr(CodeAnalysisRepository, operation, changed)
    denied = v["client"].get(url, params=params, headers=v["member_headers"])
    assert denied.status_code == (403 if change == "membership" else 409), denied.text
    assert "orders.py" not in denied.text and analysis["analysis_id"] not in denied.text
    # A fresh denied request must not even fetch the report from its repository.
    def unexpected(*args, **kwargs):
        pytest.fail("unauthorized report repository access")
    monkeypatch.setattr(CodeAnalysisRepository, operation, unexpected)
    assert v["client"].get(url, params=params, headers=v["member_headers"]).status_code == 403


def test_analysis_tamper_and_response_size_are_explicit_failures(evidence_api, monkeypatch):
    v = evidence_api
    analysis = listed(v).json()["items"][0]
    original = CodeAnalysisRepository.read

    def tampered(repository, *args, **kwargs):
        header, payload = original(repository, *args, **kwargs)
        return header, {**payload, "files": [{"secret": "tampered-private-value"}]}

    monkeypatch.setattr(CodeAnalysisRepository, "read", tampered)
    url, params = endpoint(v) + "/" + analysis["analysis_id"], {"source_revision_id": v["revision"]}
    response = v["client"].get(url, params=params, headers=v["headers"])
    assert response.status_code == 502 and "tampered-private-value" not in response.text
    from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
    def oversized(repository, *args, **kwargs):
        header, payload = original(repository, *args, **kwargs)
        payload = {**payload, "files": [{"relative_path": "x" * 70000}]}
        return replace(header, report_hash=snapshot_digest(payload)), payload
    monkeypatch.setattr(CodeAnalysisRepository, "read", oversized)
    response = v["client"].get(url, params=params, headers=v["headers"])
    assert response.status_code == 413 and len(response.content) < 1000


def test_revision_selector_and_observation_filters_are_scope_bound(evidence_api):
    v = evidence_api
    url = f"/v1/projects/{v['project_id']}/system-image/code-source-revisions"
    assert v["client"].get(url).status_code == 401
    assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    response = v["client"].get(url, headers=v["headers"], params={"limit": 1})
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    revision = response.json()["items"][0]
    assert revision["source_revision_id"] == v["revision"] and revision["source_label"] == "orders.py"
    assert "manifest_ref" not in response.text and "local-object://" not in response.text
    report = listed(v).json()["items"][0]
    detail = endpoint(v) + "/" + report["analysis_id"]
    for section, field, value, expected in (("files", "status", "parsed", 1), ("files", "status", "failed", 0),
                                          ("facts", "kind", "module", 1), ("facts", "kind", "route", 0)):
        page = v["client"].get(detail, headers=v["headers"], params={"source_revision_id": v["revision"], "section": section, field: value})
        assert page.status_code == 200 and page.json()["total"] == expected
        assert all(item[field] == value for item in page.json()["items"])
    invalid = v["client"].get(detail, headers=v["headers"], params={"source_revision_id": v["revision"], "kind": "route"})
    assert invalid.status_code == 400
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    SourceAccessRepository().set_policy(v["project_id"], revision["binding_id"], SourceAccessRule("restricted"),
        expected_epoch=0, changed_by=v["owner"]["id"], invocation_id="analysis-selector-test")
    hidden = v["client"].get(url, headers=v["member_headers"])
    assert hidden.status_code == 200 and hidden.json() == {"items": [], "next_after_id": None}
    assert revision["source_label"] not in hidden.text


def test_revision_listing_revocation_during_query_does_not_return_old_names(evidence_api, monkeypatch):
    v = evidence_api
    report = listed(v).json()["items"][0]
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    original = CodeAnalysisRepository.list_source_revisions

    def changed(repository, *args, **kwargs):
        rows = original(repository, *args, **kwargs)
        SourceAccessRepository().set_policy(v["project_id"], report["binding_id"], SourceAccessRule("restricted"),
            expected_epoch=0, changed_by=v["owner"]["id"], invocation_id="analysis-selector-race")
        return rows

    monkeypatch.setattr(CodeAnalysisRepository, "list_source_revisions", changed)
    response = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/code-source-revisions", headers=v["member_headers"])
    assert response.status_code == 409 and "orders.py" not in response.text
