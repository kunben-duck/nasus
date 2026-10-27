"""Fixed source identity and archived spans, not runtime or semantic coverage."""
from collections import Counter
import json

from sqlalchemy import select

from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityIdentityRecord, CodeEntityRevisionRecord
from apps.api.app.infrastructure.persistence.code_analysis_models import CodeAnalysisRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageObjectMemberRecord, ImageRevisionRecord
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.source_evidence_repository import SourceEvidenceRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord, SourceManifestMemberRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.app.infrastructure.system_image.evidence_source_reader import ArchivedEvidenceSourceReader
from apps.api.app.infrastructure.system_image.code_observation_artifacts import ArchivedCodeObservations
from apps.api.app.infrastructure.system_image.code_graph_relationship_scan import RELATIONSHIP_COLUMNS


def verify_exweb_structural_evidence(project_id, image_id, source_uri):
    with session_scope() as session:
        image = session.get(ImageRevisionRecord, image_id)
        assert image is not None and image.project_id == project_id
        members = session.scalars(select(ImageObjectMemberRecord).where(
            ImageObjectMemberRecord.project_id == project_id, ImageObjectMemberRecord.image_revision_id == image_id)).all()
        assert len(members) == image.object_count and all(
            member.kind in {"code_entity", "source_document"} and member.evidence_ids for member in members)
        manifest = session.scalars(select(SourceManifestMemberRecord).where(
            SourceManifestMemberRecord.project_id == project_id,
            SourceManifestMemberRecord.manifest_id == image.manifest_id)).all()
        source_pins = tuple(sorted((member.binding_id, member.source_revision_id)
            for member in manifest if member.status == "captured"))
        projector = ObjectProvenanceProjectorV1()
        nodes = projector.expected(session, image, members)
        assert projector.image(session, image, write=False, members=members) == 0
        root = nodes["image_objects:" + image_id]
        assert root.source_pins == source_pins
        assert root.parents == tuple(sorted(("manifest:" + image.manifest_id,
            *("member:" + image_id + "/" + member.object_id for member in members))))
        assert all((member.binding_id, member.source_revision_id) in source_pins for member in members)
        manifest_root = {"manifest_id": image.manifest_id, "manifest_hash": image.manifest_hash,
            "image_members": len(members), "captured_sources": len(source_pins),
            "legacy_members": 0, "provenance_nodes": len(nodes),
            "persisted_provenance_verified": True, "root_content_hash": root.content_hash}
        rows = session.execute(select(ImageObjectMemberRecord, CodeEntityIdentityRecord.kind,
            CodeEntityRevisionRecord.payload, CodeEntityRevisionRecord.payload_hash).join(
                CodeEntityRevisionRecord, CodeEntityRevisionRecord.entity_revision_id == ImageObjectMemberRecord.entity_revision_id
            ).join(CodeEntityIdentityRecord, CodeEntityIdentityRecord.entity_id == CodeEntityRevisionRecord.entity_id
            ).join(SourceBindingRecord, SourceBindingRecord.binding_id == ImageObjectMemberRecord.binding_id).where(
                ImageObjectMemberRecord.project_id == project_id, ImageObjectMemberRecord.image_revision_id == image_id,
                SourceBindingRecord.project_id == project_id, SourceBindingRecord.external_identity == source_uri)).all()
        reports = session.scalars(select(CodeAnalysisRecord).where(CodeAnalysisRecord.project_id == project_id,
            CodeAnalysisRecord.source_revision_id.in_({row[0].source_revision_id for row in rows}))).all()
        observation_reports = [(report.analysis_id, report.report_hash, report.payload) for report in reports]
    expected = {"module": 126, "dependency": 160, "class": 86, "method": 306,
                "interface": 25, "enum": 9, "api_route": 13}
    assert dict(Counter(kind for _, kind, _, _ in rows)) == expected
    repository = SourceEvidenceRepository()
    storage = ObjectStorage()
    observation_archive = ArchivedCodeObservations(storage)
    received = []
    for analysis_id, report_hash, report in observation_reports:
        assert snapshot_digest(report) == report_hash and report["schema"] == "nasus.code-analysis.v3"
        body = observation_archive.read(report)
        summary = report["observation_archive"]["summary"]
        assert summary["entity_count"] >= len(rows) and summary["identity_counts"]["unresolved"] > 0
        assert any(item["identity_status"] == "unresolved" and item["symbol_key"] is None for item in body["result"]["entities"])
        assert body["result"]["provider_observations"] == report["projection"]["providers"]
        assert body["schema"] == "nasus.code-observation-archive.v2" and body["native_queries"]
        kinds, operations = Counter(), Counter()
        for query in body["native_queries"]:
            assert query["provider"] == "codebase-memory"
            assert query["basis"] == "decoded_query_response_not_complete_native_graph"
            operations[query["operation"]] += 1
            response = json.loads(query["response_json"])
            if response.get("columns") == list(RELATIONSHIP_COLUMNS):
                kinds.update(row[2] for row in response["rows"])
        assert operations["search_graph"] > 0 and operations["query_graph"] > 0
        assert "DEFINES_METHOD" in kinds and len(kinds) > 4
        received.append({"analysis_id": analysis_id, "report_hash": report_hash,
            "artifact_hash": report["observation_archive"]["artifact_hash"], **summary,
            "native_query_count": len(body["native_queries"]), "native_query_operations": dict(operations),
            "received_native_relation_rows_by_kind": dict(sorted(kinds.items())),
            "native_row_counts_include_partition_probes": True,
            "complete_native_graph_claimed": False})
    assert received
    reader = ArchivedEvidenceSourceReader(storage)
    verified_spans = 0
    file_only = 0
    with reader.verified_read_session():
        for member, kind, payload, digest in rows:
            assert member.kind == "code_entity" and member.evidence_ids
            assert payload["symbol"]["kind"] == kind and snapshot_digest(payload) == digest
            targets = repository.get_many(project_id, tuple(member.evidence_ids))
            expected_spans = [{**payload["locator"], "decoded_snippet_hash": payload["decoded_snippet_hash"]}]
            if payload["schema"] == "nasus.code-entity-observation.v3":
                expected_spans.extend(payload["supporting_locators"])
                if kind == "api_route":
                    assert payload["observation_basis"] == "static_route_declaration"
                    assert {span["role"] for span in payload["supporting_locators"]} == {"controller", "class_mapping"}
                elif kind == "dependency":
                    assert payload["observation_basis"] == "static_import_not_resolved_runtime_dependency"
                else:
                    assert kind == "module" and payload["observation_basis"] == "source_file_not_parsed_symbols"
                    file_only += 1
            assert {(span["relative_path"], span["start_line"], span["end_line"], span["decoded_snippet_hash"]) for span in expected_spans} == {
                (target.evidence.locator.relative_path, target.evidence.locator.start_line,
                 target.evidence.locator.end_line, target.evidence.snippet_hash) for target in targets}
            for target in targets:
                evidence = target.evidence
                assert evidence.source_revision_id == member.source_revision_id
                assert evidence.file_hash == payload["source_file_hash"] and evidence.locator.precision == "exact"
                body = reader.read(target)
                lines = source_lines(body.decode("utf-8"))
                assert text_digest("".join(lines[evidence.locator.start_line - 1:evidence.locator.end_line])) == evidence.snippet_hash
                verified_spans += 1
    assert file_only == 6 and verified_spans == 751
    return {"canonical_members": len(rows), "kinds": expected, "verified_archive_spans": verified_spans,
        "route_supporting_spans": 26, "unsupported_file_identities": file_only,
        "manifest_root": manifest_root,
        "received_observation_archives": received,
        "storage_backend": "minio_s3" if storage.config.s3_enabled else "local_isolated_adapter",
        "runtime_dependencies_resolved": False, "business_coverage_verified": False}
