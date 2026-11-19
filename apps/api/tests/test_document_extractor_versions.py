"""Version compatibility with real artifact/router code and memory-only ports."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.engine import Engine

from apps.api.app.application.system_image.document_queries import DocumentQueryApplicationService
from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.domain.system_image import document_components, document_projection
from apps.api.app.domain.system_image.document_components import (
    DocumentComponent, component_payloads, requirement_components, validate_component_payload,
)
from apps.api.app.domain.system_image.document_projection import (
    DOCUMENT_EXTRACTOR, OPENAPI_DOCUMENT_EXTRACTOR, DocumentField, DocumentObservation,
)
from apps.api.app.domain.system_image.evidence import EvidenceIntegrityError, text_digest
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.system_image.archived_document_projection import ArchivedDocumentProjection
from apps.api.app.infrastructure.system_image.document_artifacts import DocumentArtifacts
from apps.api.app.infrastructure.system_image.explicit_document_extractor import ExplicitDocumentExtractor
from apps.api.app.interface.http.routers.source_documents import router


V1 = "nasus.explicit-document.v1"
V2 = "nasus.explicit-document.v2"
LEGACY_TEXT = "# US-1 Search\nAcceptance criteria: AC-1: Empty returns 400.\n"
OPENAPI_TEXT = """openapi: 3.1.0
info: {title: Version fixture, version: '1'}
paths:
  /articles:
    get:
      responses:
        '200': {description: Candidate only}
"""
# Captured from the unchanged serializers before adding per-observation versions.
PARENT_HASHES = {
    V1: "sha256:fd443266e9a87103ca2deab8b5b1ec11120f0acc0e2b5a678fe950bfdfd41935",
    V2: "sha256:53c474057168d6163f0a89e37f33caba79f3744d049aea89409ec8805ac3195a",
}
CHILD_HASHES = {
    (V1, V1): "sha256:0040d0bf1374e95bf516c1b3f9f8accadcf3924d58ad002aa923c80c61aea8a5",
    (V1, V2): "sha256:3d3ef21536b7bdc714ee567065612818b9d2f29f4639b8b8609d204ecc1a958a",
    (V2, V1): "sha256:8299736792ca87a4237b20f2a8fd9c93fd6e4018c06bd61f396341f9cf0d78c9",
    (V2, V2): "sha256:a46dd0013ae5be17f95b7e79d0cc9887525ecb3bbbe2e5eceb19718ea316581b",
}


@pytest.fixture(autouse=True)
def no_database_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Version contracts must not connect to a database")
    monkeypatch.setattr(Engine, "connect", forbidden)


def unit(text, path="requirements.md"):
    return SourceTextUnit(path, text, len(text.encode()), text_digest(text))


def manifest(units):
    return {"files": [{"path": u.relative_path, "byte_count": u.byte_count, "content_hash": u.content_hash} for u in units]}


def legacy_pair(parent_version=V2, child_version=V2):
    source = unit(LEGACY_TEXT)
    row, = ExplicitDocumentExtractor().extract("us_doc", [source]).observations
    row = replace(row, extractor_version=parent_version)
    parent = {**row.payload(source.text, source.content_hash), "project_id": "project", "source_id": "source",
              "source_manifest_hash": snapshot_digest(manifest([source]))}
    key, child = next(component_payloads(row, parent, source.text))
    child = {**child, "extractor_version": child_version}
    return row, parent, key, child


class MemoryStorage:
    def __init__(self):
        self.config = SimpleNamespace(bucket="version-tests")
        self.bodies = {}

    def put_bytes(self, key, body, **kwargs):
        ref = f"local-object://{self.config.bucket}/{key}"
        assert ref not in self.bodies or self.bodies[ref] == body
        self.bodies[ref] = body
        return SimpleNamespace(storage_ref=ref, content_hash=text_digest(body.decode()))

    def get_bytes(self, ref, *, max_bytes):
        assert len(self.bodies[ref]) <= max_bytes
        return self.bodies[ref]


class MemoryRegistry:
    def __init__(self, artifacts):
        self.artifacts, self.documents, self.reports = artifacts, {}, {}

    def add_document(self, payload, *, parent_id=None):
        ref, digest = self.artifacts.put("project", payload)
        document_id = digest[7:39]
        header = {"document_revision_id": document_id, "project_id": "project", "binding_id": "binding",
                  "source_revision_id": "frozen-source", "source_manifest_hash": payload["source_manifest_hash"],
                  "title": payload["title"], "kind": payload["kind"]}
        if parent_id is not None:
            header["parent_document_revision_id"] = parent_id
        spans = [payload["locator"], *payload["fields"]]
        evidence = [{"evidence_id": str(index), "start_line": span["start_line"], "end_line": span["end_line"],
                     "snippet_hash": span.get("snippet_hash", payload["snippet_hash"])} for index, span in enumerate(spans)]
        self.documents[document_id] = header, ref, digest, evidence
        return document_id

    def add_report(self, report):
        ref, digest = self.artifacts.put("project", report)
        report_id = digest[7:39]
        header = {"extraction_id": report_id, "source_manifest_hash": report["source_manifest_hash"],
                  "summary": report["summary"]}
        self.reports[report_id] = header, ref, digest
        return report_id

    def record(self, source, items, *, report_ref, report_hash, **kwargs):
        ids, parents = [], {}
        for key, payload, _, digest in items:
            pin = payload.get("parent")
            parent_id = parents[pin["payload_hash"]] if pin else None
            ids.append(self.add_document(payload, parent_id=parent_id))
            parents[digest] = ids[-1]
        self.add_report(self.artifacts.read(source.project_id, report_ref, report_hash))
        return tuple(ids)

    def get(self, project_id, document_id, **kwargs):
        return deepcopy(self.documents[document_id])

    def get_extraction(self, project_id, extraction_id, **kwargs):
        return deepcopy(self.reports[extraction_id])


class Contract:
    def __init__(self):
        self.storage = MemoryStorage()
        self.artifacts = DocumentArtifacts(self.storage)
        self.registry = MemoryRegistry(self.artifacts)
        self.checks = []
        authorization = SimpleNamespace(scope=lambda project: SimpleNamespace(binding_ids=frozenset({"binding"})),
                                         require_current=lambda scope: self.checks.append(scope))
        self.service = DocumentQueryApplicationService(self.registry, self.artifacts, authorization)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.state.container = SimpleNamespace(source_documents=self.service)

    def freeze(self, units, result=None):
        snapshot = manifest(units)
        source = SimpleNamespace(project_id="project", id="source", content_ref="memory:frozen",
                                 content_hash=snapshot_digest(snapshot))
        archive = SimpleNamespace(owns_ref=lambda ref: ref == "memory:frozen", read_manifest=lambda *a, **kw: snapshot)
        result = result or ExplicitDocumentExtractor().extract("us_doc", units)
        return ArchivedDocumentProjection(archive, self.artifacts, self.registry).record(
            source, result, units, captured_at="synthetic-time")


@pytest.mark.parametrize("parent_version", [V1, V2])
@pytest.mark.parametrize("child_version", [V1, V2])
def test_legacy_stored_versions_roundtrip_with_original_hashes_and_semantics(parent_version, child_version, monkeypatch):
    row, parent, key, child = legacy_pair(parent_version, child_version)
    assert snapshot_digest(parent) == PARENT_HASHES[parent_version]
    assert snapshot_digest(child) == CHILD_HASHES[parent_version, child_version]
    assert validate_component_payload(child, parent, snapshot_digest(row.identity_key)) == key
    assert DocumentObservation.from_payload(parent).payload(LEGACY_TEXT, text_digest(LEGACY_TEXT)) == {
        k: v for k, v in parent.items() if k not in {"project_id", "source_id", "source_manifest_hash"}}
    c = Contract()
    parent_id = c.registry.add_document(parent)
    child_id = c.registry.add_document(child, parent_id=parent_id)
    original_bytes = dict(c.storage.bodies)
    # Reads must not depend on a future build's global writer constant.
    monkeypatch.setattr(document_projection, "DOCUMENT_EXTRACTOR", "nasus.explicit-document.future")
    monkeypatch.setattr(document_components, "DOCUMENT_EXTRACTOR", "nasus.explicit-document.future")
    with TestClient(c.app) as client:
        for document_id, expected in ((parent_id, parent), (child_id, child)):
            response = client.get(f"/v1/projects/project/system-image/source-documents/{document_id}")
            assert response.status_code == 200, response.text
            page = response.json()
            assert response.headers["cache-control"] == "private, no-store"
            assert page["payload_hash"] == snapshot_digest(expected)
            assert page["projection"] == {k: v for k, v in expected.items() if k not in {"fields", "source_id"}}
            assert page["fields"] == expected["fields"]
            assert "local-object://" not in response.text
    assert c.storage.bodies == original_bytes


def test_default_v2_archive_parent_component_and_report_are_byte_compatible():
    assert DOCUMENT_EXTRACTOR == V2
    c = Contract()
    ids = c.freeze([unit(LEGACY_TEXT)])
    assert {c.registry.documents[i][2] for i in ids} == {PARENT_HASHES[V2], CHILD_HASHES[V2, V2]}
    report_id, = c.registry.reports
    _, ref, digest = c.registry.reports[report_id]
    assert digest == "sha256:ad0e9c686152507b0e8f32ae53df533976f0564802075979b25b3741188dfe52"
    report = c.artifacts.read("project", ref, digest)
    assert report["extractor_version"] == V2 and "extractor_versions" not in report
    assert "extractor_versions" not in c.service.read_extraction("project", report_id)


def test_pre_component_v1_report_and_document_remain_readable_without_new_keys():
    _, parent, _, _ = legacy_pair(V1)
    report = {"schema": "nasus.source-document-extraction.v1", "project_id": "project", "source_id": "source",
        "source_manifest_hash": parent["source_manifest_hash"], "extractor_version": V1,
        "files": [{"path": "requirements.md", "status": "parsed", "entity_count": 1}],
        "summary": {"file_count": 1, "entity_count": 1, "parsed": 1, "unsupported": 0, "failed": 0, "not_analyzed": 0},
        "payload_hashes": [snapshot_digest(parent)]}
    c = Contract()
    doc_id = c.registry.add_document(parent)
    report_id = c.registry.add_report(report)
    before = dict(c.storage.bodies)
    assert snapshot_digest(report) == "sha256:60fd6d19a4aa9b81b371320944f445d6d05bd26ecdaa7671257d8374ac5a6ed8"
    with TestClient(c.app) as client:
        response = client.get(f"/v1/projects/project/system-image/source-document-extractions/{report_id}")
        assert response.status_code == 200 and "extractor_versions" not in response.json()
        assert response.json()["report_hash"] == snapshot_digest(report)
        response = client.get(f"/v1/projects/project/system-image/source-documents/{doc_id}")
        assert response.status_code == 200 and response.json()["projection"]["extractor_version"] == V1
    assert c.storage.bodies == before


@pytest.mark.parametrize("mixed", [False, True])
def test_openapi_archive_and_api_expose_actual_adapter_versions_without_ac_children(mixed):
    c = Contract()
    units = [unit(OPENAPI_TEXT, "openapi.yml")]
    if mixed:
        units.insert(0, unit(LEGACY_TEXT))
    ids = c.freeze(units)
    before = dict(c.storage.bodies)
    expected_versions = [V2, OPENAPI_DOCUMENT_EXTRACTOR] if mixed else [OPENAPI_DOCUMENT_EXTRACTOR]
    report_id, = c.registry.reports
    _, ref, digest = c.registry.reports[report_id]
    report = c.artifacts.read("project", ref, digest)
    assert report["extractor_version"] == V2
    assert report["extractor_versions"] == expected_versions
    with TestClient(c.app) as client:
        page = client.get(f"/v1/projects/project/system-image/source-document-extractions/{report_id}")
        assert page.status_code == 200 and page.json()["extractor_versions"] == expected_versions
        openapi_count = 0
        for doc_id in ids:
            response = client.get(f"/v1/projects/project/system-image/source-documents/{doc_id}")
            assert response.status_code == 200, response.text
            value = response.json()
            if value["projection"]["extractor_version"] == OPENAPI_DOCUMENT_EXTRACTOR:
                openapi_count += 1
                assert value["projection"]["kind"] == "requirement_document"
                assert "parent_document_revision_id" not in value["document"]
                assert all(field["name"] == "description" for field in value["fields"])
                assert value["evidence"]
        assert openapi_count == 2
    assert c.storage.bodies == before
    assert c.freeze(units) == ids
    assert c.storage.bodies == before


@pytest.mark.parametrize("version", [None, "", "nasus.openapi-document.v2", "nasus.explicit-document.v3", [], {}])
def test_unknown_versions_fail_closed_at_construction_and_api_even_with_valid_hash(version):
    row, parent, _, _ = legacy_pair()
    with pytest.raises(ValueError, match="version"):
        replace(row, extractor_version=version)
    c = Contract()
    doc_id = c.registry.add_document({**parent, "extractor_version": version})
    with TestClient(c.app) as client:
        response = client.get(f"/v1/projects/project/system-image/source-documents/{doc_id}")
        assert response.status_code == 502 and "document_integrity_failed" in response.text
        assert "Empty returns" not in response.text


@pytest.mark.parametrize("change", [
    {"kind": "requirement"}, {"kind": "test_case"}, {"kind": "test_script"},
    {"external_id": "US-1"}, {"references": ["US-1"]}, {"identity_status": "explicit_id"},
    {"field_name": "acceptance_criterion"}, {"field_name": "business_rule"}, {"field_name": "expected_result"},
    {"authority_status": "approved"}, {"parent": {}}, {"semantic_status": "approved"},
])
def test_openapi_version_cannot_be_used_to_smuggle_requirements_or_authority(change):
    c = Contract()
    doc_id = c.freeze([unit(OPENAPI_TEXT, "openapi.yml")])[0]
    _, ref, digest, _ = c.registry.get("project", doc_id)
    payload = c.artifacts.read("project", ref, digest)
    if "field_name" in change:
        payload["fields"][0]["name"] = change["field_name"]
    else:
        payload.update(change)
    bad_id = c.registry.add_document(payload)
    with TestClient(c.app) as client:
        response = client.get(f"/v1/projects/project/system-image/source-documents/{bad_id}")
        assert response.status_code == 502 and "document_integrity_failed" in response.text


@pytest.mark.parametrize("parent_version,child_version", [
    ("unknown", V2), (V2, "unknown"), (OPENAPI_DOCUMENT_EXTRACTOR, V2), (V2, OPENAPI_DOCUMENT_EXTRACTOR),
])
def test_component_read_rejects_nonlegacy_parent_or_child_versions(parent_version, child_version):
    row, parent, _, child = legacy_pair()
    parent["extractor_version"] = parent_version
    child["extractor_version"] = child_version
    child["parent"]["payload_hash"] = snapshot_digest(parent)
    with pytest.raises(ValueError):
        validate_component_payload(child, parent, snapshot_digest(row.identity_key))
    c = Contract()
    parent_id = c.registry.add_document(parent)
    child_id = c.registry.add_document(child, parent_id=parent_id)
    with TestClient(c.app) as client:
        response = client.get(f"/v1/projects/project/system-image/source-documents/{child_id}")
        assert response.status_code == 502


def test_openapi_observations_cannot_emit_components_even_through_direct_component_builder():
    row = ExplicitDocumentExtractor().extract("us_doc", [unit(OPENAPI_TEXT, "openapi.yml")]).observations[0]
    assert requirement_components(row) == ()
    with pytest.raises(ValueError):
        replace(row, kind="requirement", fields=(DocumentField("acceptance_criterion", "AC-1: forged", 1, 1),))
    with pytest.raises(ValueError):
        DocumentComponent(row, (0,), None, "source_occurrence").payload(row.payload(OPENAPI_TEXT, text_digest(OPENAPI_TEXT)))


@pytest.mark.parametrize("update", [
    {"extractor_version": "unknown"}, {"extractor_version": OPENAPI_DOCUMENT_EXTRACTOR},
    {"extractor_versions": []}, {"extractor_versions": [V2]}, {"extractor_versions": ["unknown"]},
    {"extractor_versions": [OPENAPI_DOCUMENT_EXTRACTOR, OPENAPI_DOCUMENT_EXTRACTOR]},
    {"extractor_versions": [OPENAPI_DOCUMENT_EXTRACTOR, V2]},
    {"extractor_versions": [None]}, {"extractor_versions": {}},
])
def test_extraction_report_version_claims_fail_closed(update):
    c = Contract()
    c.freeze([unit(OPENAPI_TEXT, "openapi.yml")])
    report_id, = c.registry.reports
    _, ref, digest = c.registry.reports[report_id]
    report = c.artifacts.read("project", ref, digest)
    report.update(update)
    bad_id = c.registry.add_report(report)
    with pytest.raises(EvidenceIntegrityError):
        c.service.read_extraction("project", bad_id)
    with TestClient(c.app) as client:
        response = client.get(f"/v1/projects/project/system-image/source-document-extractions/{bad_id}")
        assert response.status_code == 502


def test_new_openapi_projection_does_not_rewrite_previously_stamped_v2_bytes():
    c = Contract()
    source = unit(OPENAPI_TEXT, "openapi.yml")
    current = ExplicitDocumentExtractor().extract("us_doc", [source])
    legacy = replace(current, observations=tuple(replace(row, extractor_version=V2) for row in current.observations),
                     files=tuple({key: value for key, value in file.items() if key != "extractor_version"} for file in current.files))
    old_ids = c.freeze([source], legacy)
    old_pages = [c.service.read("project", doc_id) for doc_id in old_ids]
    old_bodies = dict(c.storage.bodies)
    new_ids = c.freeze([source], current)
    assert set(old_ids).isdisjoint(new_ids)
    assert old_pages == [c.service.read("project", doc_id) for doc_id in old_ids]
    assert all(c.storage.bodies[ref] == body for ref, body in old_bodies.items())
    for old, new_id in zip(old_pages, new_ids):
        new = c.service.read("project", new_id)
        assert old["projection"]["source_file_hash"] == new["projection"]["source_file_hash"]
        assert old["projection"]["snippet_hash"] == new["projection"]["snippet_hash"]
        assert old["fields"] == new["fields"] and old["payload_hash"] != new["payload_hash"]


def test_failed_openapi_parse_still_reports_attempted_adapter_without_observations():
    c = Contract()
    assert c.freeze([unit("openapi: [", "broken.yml")]) == ()
    report_id, = c.registry.reports
    page = c.service.read_extraction("project", report_id)
    assert page["extractor_versions"] == [OPENAPI_DOCUMENT_EXTRACTOR]
    assert page["files"] == [{"path": "broken.yml", "status": "failed", "reason": "invalid_openapi_structure",
                              "extractor_version": OPENAPI_DOCUMENT_EXTRACTOR}]
    assert page["extraction"]["summary"]["entity_count"] == 0


def test_missing_or_unknown_per_file_report_version_fails_closed_before_pagination():
    c = Contract()
    c.freeze([unit(LEGACY_TEXT), unit("openapi: [", "broken.yml")])
    report_id, = c.registry.reports
    _, ref, digest = c.registry.reports[report_id]
    report = c.artifacts.read("project", ref, digest)
    del report["extractor_versions"]
    bad_id = c.registry.add_report(report)
    with pytest.raises(EvidenceIntegrityError):
        c.service.read_extraction("project", bad_id, limit=1)
    report["extractor_versions"] = [V2, OPENAPI_DOCUMENT_EXTRACTOR]
    report["files"][-1]["extractor_version"] = "unknown"
    bad_id = c.registry.add_report(report)
    with pytest.raises(EvidenceIntegrityError):
        c.service.read_extraction("project", bad_id, limit=1)


def test_unknown_file_adapter_cannot_be_archived():
    c = Contract()
    source = unit(OPENAPI_TEXT, "openapi.yml")
    result = ExplicitDocumentExtractor().extract("us_doc", [source])
    result = replace(result, files=tuple({**file, "extractor_version": "unknown"} for file in result.files))
    with pytest.raises(ValueError, match="version"):
        c.freeze([source], result)
    assert not c.storage.bodies


def test_openapi_file_cannot_downgrade_its_rows_to_legacy_ac_generation():
    c = Contract()
    source = unit(OPENAPI_TEXT, "openapi.yml")
    result = ExplicitDocumentExtractor().extract("us_doc", [source])
    row = result.observations[0]
    downgraded = replace(row, extractor_version=V2, kind="requirement", external_id="US-1", identity_status="explicit_id",
                         fields=(DocumentField("acceptance_criterion", "AC-1: forged", row.start_line, row.start_line),))
    with pytest.raises(ValueError, match="adapter version mismatch"):
        c.freeze([source], replace(result, observations=(downgraded,)))
    assert not c.storage.bodies
