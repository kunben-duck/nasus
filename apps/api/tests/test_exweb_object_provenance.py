"""Real fixed exweb bytes and MinIO; companion requirements/cases are fixtures."""
from contextlib import nullcontext
from datetime import datetime, timezone
import cProfile
import json
import os
from time import perf_counter
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.app.application.system_image.context_extraction import ContextExtractionService
from apps.api.app.application.system_image.document_projections import DocumentProjectionApplicationService
from apps.api.app.application.system_image.image_candidates import ImageCandidateApplicationService
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_snapshots import SourceSnapshotArtifact, snapshot_digest
from apps.api.app.infrastructure.persistence.code_entity_repository import CodeEntityRepository
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityIdentityRecord, CodeEntityRevisionRecord
from apps.api.app.infrastructure.persistence.document_projection_repository import DocumentProjectionRepository
from apps.api.app.infrastructure.persistence.document_projection_models import (
    SourceDocumentIdentityRecord, SourceDocumentRevisionRecord, SourceDocumentEvidenceRecord,
)
from apps.api.app.infrastructure.persistence.image_revision_repository import ImageRevisionRepository
from apps.api.app.infrastructure.persistence.image_revision_models import ImageObjectMemberRecord
from apps.api.app.infrastructure.persistence.object_provenance_models import ObjectProvenanceNodeRecord as Node, ObjectProvenanceEdgeRecord as Edge
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import (
    SourceBindingRecord, SourceRevisionRecord, SourceManifestRecord, SourceManifestMemberRecord,
)
from apps.api.app.infrastructure.persistence.source_evidence_models import SourceEvidenceRecord, CodeEntityEvidenceRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.archived_document_projection import ArchivedDocumentProjection
from apps.api.app.infrastructure.system_image.document_artifacts import DocumentArtifacts
from apps.api.app.infrastructure.system_image.explicit_document_extractor import ExplicitDocumentExtractor
from apps.api.app.infrastructure.system_image.image_artifacts import ArchivedImageArtifacts
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter


def test_exweb_full_object_source_closure_and_frozen_companion_parents(tmp_path, monkeypatch):
    path = os.getenv("EXWEB_PROBE_REPORT")
    if not path or not os.getenv("EXWEB_MINIO_ENDPOINT"):
        pytest.skip("explicit archived exweb and local MinIO opt-in required")
    url = make_url(os.environ["NASUS_DATABASE_URL"])
    assert url.get_backend_name() == "postgresql" and url.database.startswith("nasus_test_")
    probe = json.loads(Path(path).read_text())
    assert probe["repository"] == "https://github.com/kunben-duck/exweb.git"
    assert probe["revision"] == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    config = ObjectStorageConfig(os.environ["EXWEB_MINIO_ENDPOINT"], os.environ["EXWEB_MINIO_BUCKET"],
        os.environ["EXWEB_MINIO_ACCESS_KEY"], os.environ["EXWEB_MINIO_SECRET_KEY"], "us-east-1", tmp_path)
    import boto3
    from botocore.exceptions import ClientError
    s3 = boto3.client("s3", endpoint_url=config.endpoint, aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key, region_name=config.region)
    storage = ObjectStorage(config)
    written = set()
    original_put = storage.put_bytes

    def put(key, body, **kwargs):
        if key not in written:
            try:
                s3.head_object(Bucket=config.bucket, Key=key)
            except ClientError as error:
                assert error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}
            else:
                raise AssertionError("Never overwrite a pre-existing MinIO object")
        result = original_put(key, body, **kwargs)
        written.add(result.key)
        assert result.backend == "s3"
        return result

    monkeypatch.setattr(storage, "put_bytes", put)
    snapshot = SourceSnapshotArtifact(**probe["source_snapshot"])
    source = RawAssetRecord(id=probe["source_id"], project_id=probe["project_id"], source_type="code",
        source_uri=probe["repository"], ingestion_status="indexed", content_ref=snapshot.manifest_ref, content_hash=snapshot.content_hash)
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "restored")
    sources = [source]
    snapshots = SourceSnapshotRepository()
    now = datetime.now(timezone.utc).isoformat()
    snapshots.record_capture(source, snapshot, captured_at=now)
    try:
        assert len(reader.extract_text_units(source)) == snapshot.file_count == 126
        for kind, filename in (("us_doc", "exweb-requirements.md"), ("test_asset", "exweb-test-cases.csv")):
            local = tmp_path / filename
            local.write_text(Path("tests/fixtures/system-image", filename).read_text())
            companion = RawAssetRecord(id="object-provenance-" + uuid4().hex, project_id=source.project_id,
                source_type=kind, source_uri=str(local))
            result = reader.ingest(companion)
            snapshots.record_capture(companion, result.snapshot, captured_at=now)
            sources.append(companion.model_copy(update={"ingestion_status": "indexed", "content_ref": result.content_ref,
                "content_hash": result.content_hash}))
            local.unlink()
        # Failed optional input remains in the frozen manifest, never fabricated as a revision.
        sources.append(RawAssetRecord(id="failed-optional-" + uuid4().hex, project_id=source.project_id,
            source_type="us_doc", source_uri="unavailable-optional-fixture", ingestion_status="failed"))
        manifest = snapshots.freeze_manifest(source.project_id, sources, captured_at=now)
        usable = snapshots.materialization_sources(manifest)
        extractor = ContextExtractionService(reader, TreeSitterCodeIntelligenceAdapter(), code_entity_registry=CodeEntityRepository(),
            document_projections=DocumentProjectionApplicationService(ExplicitDocumentExtractor(),
                ArchivedDocumentProjection(reader.snapshots, DocumentArtifacts(storage), DocumentProjectionRepository())))
        extracted = extractor.extract(project_id=source.project_id, project_name="exweb", baseline_id="exweb-object-provenance",
            sources=usable, version_id=None, captured_at=now)
        repository = ImageRevisionRepository()
        writer = ImageCandidateApplicationService(ArchivedImageArtifacts(storage), repository)
        image = writer.freeze(manifest, "exweb-object-provenance", objects=extracted.objects, relationships=extracted.relationships,
            invocation_id="object-provenance-fixture", recorded_at=now)
        assert image.code_member_count == 725
        profile_path = os.getenv("EXWEB_IMAGE_READ_PROFILE")
        profile = cProfile.Profile() if profile_path else None
        native_models = (CodeEntityIdentityRecord, CodeEntityRevisionRecord, SourceDocumentIdentityRecord,
            SourceDocumentRevisionRecord, SourceDocumentEvidenceRecord, ImageObjectMemberRecord,
            SourceBindingRecord, SourceRevisionRecord, SourceManifestRecord, SourceManifestMemberRecord,
            SourceEvidenceRecord, CodeEntityEvidenceRecord, Node, Edge)
        native_allocations = []

        def loaded_native(_session, instance):
            if isinstance(instance, native_models):
                native_allocations.append(type(instance))

        event.listen(Session, "loaded_as_persistent", loaded_native)
        try:
            with profile if profile is not None else nullcontext():
                header, ref, _ = repository.get(source.project_id, image.image_revision_id)
                artifact = writer.artifacts.read(source.project_id, ref, header.artifact_hash)
                from apps.api.app.domain.system_image.image_revision import verify_image_artifact
                verify_image_artifact(artifact, header)
        finally:
            event.remove(Session, "loaded_as_persistent", loaded_native)
        assert native_allocations == []
        if profile is not None:
            profile.dump_stats(profile_path)
        metadata_reads = []
        original_get = repository._get

        def counted_get(session, *args):
            metadata_reads.append(args)
            return original_get(session, *args)

        monkeypatch.setattr(repository, "_get", counted_get)
        started = perf_counter()
        with repository.verified_read_session():
            for _ in range(3):
                assert repository.get(source.project_id, image.image_revision_id)[0] == header
        snapshot_read_ms = (perf_counter() - started) * 1000
        assert len(metadata_reads) == 1 and repository._read_snapshot.get() is None
        with repository.verified_read_session():
            assert repository.get(source.project_id, image.image_revision_id)[0] == header
        assert len(metadata_reads) == 2
        from apps.api.app.application.system_image.document_queries import DocumentQueryApplicationService
        from apps.api.app.application.system_image.evidence_queries import EvidenceQueryApplicationService
        from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
        from apps.api.app.application.system_image.link_candidates import LinkCandidateQueryApplicationService
        from apps.api.app.application.system_image.semantic_link_inputs import SemanticLinkInputApplicationService
        from apps.api.app.application.system_image.source_access import SourceAccessApplicationService
        from apps.api.app.infrastructure.persistence.db_models import ProjectRecord
        from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
        from apps.api.app.infrastructure.persistence.source_evidence_repository import SourceEvidenceRepository
        from apps.api.app.infrastructure.system_image.evidence_source_reader import ArchivedEvidenceSourceReader
        with session_scope() as session:
            session.add(ProjectRecord(id=source.project_id, name="exweb", code="EXW", summary="Static source validation"))
        # Actor double only; native HTTP tests own RBAC and model-egress checks.
        actor = SimpleNamespace(
            current_actor=lambda: SimpleNamespace(id="exweb-provenance-reviewer", role="platform_admin"),
            effective_user_for_project=lambda *a, **kw: SimpleNamespace(id="exweb-provenance-reviewer", role="platform_admin"),
            require_project_access=lambda *a, **kw: None)
        authorization = SourceAccessApplicationService(SourceAccessRepository(), actor)
        evidence = EvidenceQueryApplicationService(SourceEvidenceRepository(), ArchivedEvidenceSourceReader(storage), actor, authorization)
        documents = DocumentQueryApplicationService(DocumentProjectionRepository(), DocumentArtifacts(storage), authorization)
        queries = ImageRevisionQueryApplicationService(repository, writer.artifacts, authorization, evidence, documents)
        target = next(item for item in artifact["members"] if item["kind"] == "source_document" and
            documents.read(source.project_id, item["document_revision_id"])["projection"]["kind"] == "acceptance_criterion")
        transports = []
        original_create = storage._create_s3_client

        class CountedClient:
            def __init__(self, client):
                self.client, self.reads, self.closed = client, 0, 0

            def get_object(self, **kwargs):
                self.reads += 1
                return self.client.get_object(**kwargs)

            def close(self):
                self.closed += 1
                self.client.close()

        def create(config):
            client = CountedClient(original_create(config))
            transports.append(client)
            return client

        monkeypatch.setattr(storage, "_create_s3_client", create)
        semantic_reads = {}
        for relation in ("implements", "asserts"):
            metadata_reads.clear()
            transports.clear()
            started = perf_counter()
            page = LinkCandidateQueryApplicationService(queries).read(source.project_id, image.image_revision_id,
                target["object_id"], relation=relation)
            recall_ms = (perf_counter() - started) * 1000
            assert page.items and len(metadata_reads) == 1
            assert repository._read_snapshot.get() is None and queries._verified_reads.get() is None
            assert len(transports) == 1 and transports[0].closed == 1 and transports[0].reads > 1
            recall_gets = transports[0].reads
            subject = page.items[0].endpoint.object_id
            metadata_reads.clear()
            transports.clear()
            started = perf_counter()
            input_value = SemanticLinkInputApplicationService(queries).prepare(source.project_id, image.image_revision_id,
                target["object_id"], relation=relation, subject_object_ids=(subject,), expected_image_hash=image.artifact_hash)
            preparation_ms = (perf_counter() - started) * 1000
            assert input_value.excerpts and len(metadata_reads) == 2
            assert repository._read_snapshot.get() is None and queries._verified_reads.get() is None
            assert len(transports) == 1 and transports[0].closed == 1 and transports[0].reads > 1
            prepare_gets = transports[0].reads
            metadata_reads.clear()
            transports.clear()
            assert SemanticLinkInputApplicationService(queries).prepare(source.project_id, image.image_revision_id,
                target["object_id"], relation=relation, subject_object_ids=(subject,), expected_image_hash=image.artifact_hash) == input_value
            assert len(metadata_reads) == 2
            assert len(transports) == 1 and transports[0].closed == 1 and transports[0].reads == prepare_gets
            assert storage._read_clients.get() is None
            semantic_reads[relation] = {"recall_native_verifications": 1, "input_native_verifications": 2,
                "next_preparation_reverified": True, "input_digest": input_value.digest,
                "evidence_span_count": len(input_value.excerpts), "snapshot_released_before_egress": True,
                "recall_s3_clients": 1, "recall_s3_gets": recall_gets, "recall_ms": round(recall_ms, 3),
                "preparation_s3_clients": 1, "preparation_s3_gets": prepare_gets,
                "preparation_ms": round(preparation_ms, 3), "next_preparation_transport_recreated": True}

        # Corrupt only a companion object created by this test, never the shared exweb archive.
        evidence_id = target["evidence_ids"][0]
        evidence_target = evidence.repository.get(source.project_id, evidence_id)
        key = evidence_target.evidence.object_ref.split("/", 3)[3]
        assert key in written
        with storage.read_session():
            original_body = storage.get_bytes(evidence_target.evidence.object_ref)
        transports.clear()
        with evidence.verified_read_session():
            assert evidence.read(source.project_id, evidence_id).integrity == "verified"
            s3.put_object(Bucket=config.bucket, Key=key, Body=b"tampered companion fixture")
            try:
                from apps.api.app.domain.system_image.evidence import EvidenceIntegrityError
                with pytest.raises(EvidenceIntegrityError):
                    evidence.read(source.project_id, evidence_id)
            finally:
                s3.put_object(Bucket=config.bucket, Key=key, Body=original_body)
            assert evidence.read(source.project_id, evidence_id).integrity == "verified"
        assert len(transports) == 1 and transports[0].reads == 4 and transports[0].closed == 1
        assert evidence.reader._manifests.get() is None and storage._read_clients.get() is None
        transport_integrity = {"raw_reads": 3, "manifest_reads": 1, "s3_clients": 1,
            "same_session_corruption_rejected": True, "owned_companion_only": True,
            "transport_closed_and_scope_reset": True}
        with session_scope() as session:
            from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
            projector = ObjectProvenanceProjectorV1()
            expected = projector.expected(session, session.get(ImageRevisionRecord, image.image_revision_id))
            assert projector.backfill(session) == 0
            nodes = session.scalars(select(Node).where(Node.project_id == source.project_id)).all()
            edges = session.scalars(select(Edge).where(Edge.project_id == source.project_id)).all()
            assert len(expected) == len(nodes)
            kinds = {kind: sum(n.kind == kind for n in expected.values()) for kind in {n.kind for n in expected.values()}}
            assert kinds["source"] == 3 and kinds["document"] == 4 and kinds["code"] == 725
            frozen_evidence = {eid for member in artifact["members"] for eid in member["evidence_ids"]}
            assert {n.artifact_id for n in expected.values() if n.kind == "evidence"} == frozen_evidence
            assert frozen_evidence and kinds["member"] == image.object_count
            assert all(member["evidence_ids"] for member in artifact["members"] if member["kind"] != "legacy_observation")
            root = expected["image_objects:" + image.image_revision_id]
            assert len(root.source_pins) == 3 and len(artifact["source_members"]) == 4
            assert sum(m["status"] == "failed" for m in artifact["source_members"]) == 1
            assert sum(n.kind == "document" and any(p.startswith("document:") for p in n.parents) for n in expected.values()) == 2
            assert all(p in expected for n in expected.values() for p in n.parents)
            graph_values = [projector._values(n, n.content_hash) for n in expected.values()]
            assert "s3://" not in str(graph_values) and "ChatController" not in str(graph_values)
            report = {"verified_at": datetime.now(timezone.utc).isoformat(), "repository": probe["repository"],
                "git_revision": probe["revision"], "source_file_count": snapshot.file_count, "postgresql": True, "minio": True,
                "image_revision_id": image.image_revision_id, "image_artifact_hash": image.artifact_hash,
                "root_registration_hash": root.content_hash, "node_count": len(nodes), "edge_count": len(edges), "kinds": kinds,
                "graph_registration_digest": snapshot_digest(sorted(n.content_hash for n in expected.values())),
                "failed_optional_input_retained": True, "exact_evidence_parents": True, "backfill_idempotent": True,
                "snapshot_reads": 3, "snapshot_native_verifications": 1,
                "next_compilation_reverified": True, "snapshot_read_ms": round(snapshot_read_ms, 3),
                "native_metadata_orm_allocations": len(native_allocations),
                "semantic_input_reads": semantic_reads,
                "transport_integrity": transport_integrity,
                "semantic_authority_registered": False, "external_model_called": False, "target_executed": False,
                "requirements_and_cases": "explicit_companion_fixtures_not_maintainer_business_gold",
                "note": "Object-source subgraph only; disposable DB and newly written owned MinIO objects."}
        if os.getenv("EXWEB_OBJECT_PROVENANCE_REPORT"):
            Path(os.environ["EXWEB_OBJECT_PROVENANCE_REPORT"]).write_text(json.dumps(report, indent=2) + "\n")
    finally:
        for offset in range(0, len(written), 1000):
            keys = sorted(written)[offset:offset + 1000]
            removed = s3.delete_objects(Bucket=config.bucket, Delete={"Objects": [{"Key": key} for key in keys]})
            assert not removed.get("Errors"), "Only newly written verification objects may be removed"
