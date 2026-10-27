"""Real archived exweb bytes/PG/MinIO; replay the previously captured CBM graph."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from apps.api.app.application.system_image.context_extraction import ContextExtractionService
from apps.api.app.application.system_image.code_entity_registry import legacy_code_object_id
from apps.api.app.application.system_image.image_candidates import ImageCandidateApplicationService
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.application.system_image.image_query_models import ImageCodeIdentityInput
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.application.system_image.source_ports import CodeEntityCandidate, CodeIntelligenceResult, CodeRelationshipCandidate
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_access import SourceAccessScope
from apps.api.app.domain.system_image.source_snapshots import SourceSnapshotArtifact, snapshot_digest
from apps.api.app.infrastructure.persistence.code_alias_models import CodeObjectAliasRecord as Alias
from apps.api.app.infrastructure.persistence.code_alias_projection_v1 import CodeAliasProjectorV1
from apps.api.app.infrastructure.persistence.code_alias_repository import CodeObjectAliasRepository
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.app.infrastructure.system_image.image_artifacts import ArchivedImageArtifacts
from apps.api.tests.test_code_entity_registry import registry, pg_repo, register
from apps.api.tests.test_image_revision_repository import image_repo


def test_exweb_source_pinned_canonical_ids_and_both_providers_legacy_aliases(registry, image_repo, tmp_path, monkeypatch):
    report_path = os.getenv("EXWEB_PROBE_REPORT")
    if not report_path or not os.getenv("EXWEB_MINIO_ENDPOINT"):
        pytest.skip("explicit archived exweb probe and local MinIO opt-in required")
    probe_path = Path(report_path)
    probe = json.loads(probe_path.read_text())
    assert probe["status"] == "passed" and probe["repository"] == "https://github.com/kunben-duck/exweb.git"
    assert probe["revision"] == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    snapshot = SourceSnapshotArtifact(**probe["source_snapshot"])
    source = RawAssetRecord(id=probe["source_id"], project_id=probe["project_id"], source_type="code",
        source_uri=probe["repository"], ingestion_status="indexed", content_ref=snapshot.manifest_ref,
        content_hash=snapshot.content_hash)
    config = ObjectStorageConfig(os.environ["EXWEB_MINIO_ENDPOINT"], os.environ["EXWEB_MINIO_BUCKET"],
        os.environ["EXWEB_MINIO_ACCESS_KEY"], os.environ["EXWEB_MINIO_SECRET_KEY"], "us-east-1", tmp_path)
    import boto3
    from botocore.exceptions import ClientError
    s3 = boto3.client("s3", endpoint_url=config.endpoint, aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key, region_name=config.region)
    storage = ObjectStorage(config)
    written = set()
    put = storage.put_bytes
    def tracked(key, body, **kwargs):
        if key not in written:
            try:
                s3.head_object(Bucket=config.bucket, Key=key)
            except ClientError as error:
                assert error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}
            else:
                raise AssertionError("This test must not overwrite pre-existing MinIO artifacts")
        result = put(key, body, **kwargs)
        assert result.backend == "s3"
        written.add(result.key)
        return result
    monkeypatch.setattr(storage, "put_bytes", tracked)
    try:
        reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "restored")
        units = reader.extract_text_units(source)
        assert len(units) == snapshot.file_count == 126
        primary = TreeSitterCodeIntelligenceAdapter().analyze(units)
        graph = json.loads((probe_path.parent / "normalized-graph.json").read_text())
        assert graph["provider"] == "codebase-memory" and graph["provider_version"] == "codebase-memory-mcp 0.8.1"
        replay = CodeIntelligenceResult(provider=graph["provider"], provider_version=graph["provider_version"],
            entities=tuple(CodeEntityCandidate(**{**node, "evidence_refs": tuple(node["evidence_refs"])}) for node in graph["entities"]),
            relationships=tuple(CodeRelationshipCandidate(**{**edge, "evidence_refs": tuple(edge["evidence_refs"])}) for edge in graph["relationships"]),
            evidence_refs=tuple(graph["evidence_refs"]))
        replacement = attach_symbol_keys(replay, primary)
        service, snapshots, sessions = registry
        captured_at = datetime.now(timezone.utc).isoformat()
        snapshots.record_capture(source, snapshot, captured_at=captured_at)
        first = register(service, source, units, primary)
        second = register(service, source, units, replacement)
        assert len(first) == 725 and len(second) >= 100
        manifest = snapshots.freeze_manifest(source.project_id, [source], captured_at=captured_at)
        scope = SourceAccessScope(source.project_id, "identity-fixture-reviewer", "viewer", 0,
            frozenset(member.binding_id for member in manifest.members), frozenset({source.id}), "explicit-test-port-scope", False)
        authorization = SimpleNamespace(scope=lambda _: scope, require_current=lambda _: None)
        artifacts = ArchivedImageArtifacts(storage)
        writer = ImageCandidateApplicationService(artifacts, image_repo[0])
        queries = ImageRevisionQueryApplicationService(image_repo[0], artifacts, authorization,
            code_aliases=CodeObjectAliasRepository())
        tools = ImageQueryToolApplicationService(queries)
        records = []
        symbols = {}
        for number, (analysis, registered) in enumerate(((primary, first), (replacement, second))):
            extracted = ContextExtractionService(reader, SimpleNamespace(analyze=lambda _, value=analysis: value),
                code_entity_registry=service.repository).extract(project_id=source.project_id, project_name="exweb",
                baseline_id="exweb-code-identity", sources=[source], version_id=None, captured_at=captured_at)
            code = [obj for obj in extracted.objects if obj.code_reference]
            assert len(code) == len(registered)
            assert {obj.id for obj in code} == {"CODE-" + ref.entity_id for ref in registered.values()}
            ids = {obj.id for obj in extracted.objects}
            assert all(edge.from_object_id in ids and edge.to_object_id in ids for edge in extracted.relationships)
            image = writer.freeze(manifest, "exweb-code-identity", objects=extracted.objects, relationships=extracted.relationships,
                invocation_id="exweb-alias-image-" + str(number), recorded_at=captured_at)
            records.append({"provider": analysis.provider, "registered": len(registered),
                "image_revision_id": image.image_revision_id, "artifact_hash": image.artifact_hash})
            for name in ("ChatController", "DocumentUploadController", "ToolGatewayApplicationService"):
                node = next(node for node in analysis.entities if node.name == name and node.entity_kind == "class")
                ref = registered[node.provider_node_id]
                old_id = legacy_code_object_id(source.project_id, source.id, node.provider_node_id)
                receipt = tools.execute(ImageCodeIdentityInput(project_id=source.project_id,
                    image_revision_id=image.image_revision_id, object_id=old_id))
                resolved = tools.expand(receipt)
                assert resolved.canonical_object_id == resolved.frozen_object_id == "CODE-" + ref.entity_id
                assert resolved.entity_revision_id == ref.entity_revision_id
                assert resolved.source_revision_id == ref.source_revision_id
                assert name not in receipt.model_dump_json() and "s3://" not in receipt.model_dump_json()
                symbols.setdefault(name, []).append(asdict(resolved))
        for views in symbols.values():
            assert views[0]["canonical_object_id"] == views[1]["canonical_object_id"]
            assert views[0]["requested_object_id"] != views[1]["requested_object_id"]
        with sessions.begin() as session:
            assert CodeAliasProjectorV1().backfill(session) == 0
            aliases = session.scalars(select(Alias).where(Alias.project_id == source.project_id)).all()
            hashes = sorted(row.content_hash for row in aliases)
        output = {"verified_at": datetime.now(timezone.utc).isoformat(), "repository": probe["repository"],
            "git_revision": probe["revision"], "source_manifest_hash": snapshot.manifest_hash,
            "source_file_count": snapshot.file_count, "postgresql": True, "minio": True,
            "codebase_memory_input": "replay_of_previously_archived_real_0.8.1_graph_not_new_provider_execution",
            "current_primary_parser": primary.provider, "images": records, "symbols": symbols,
            "alias_count": len(aliases), "alias_hashes_digest": snapshot_digest(hashes),
            "canonical_ids_provider_neutral": True, "old_ids_resolved_only_at_exact_image_and_source_revision": True,
            "backfill_idempotent": True, "authorization_scope": "explicit_test_port_real_http_rbac_verified_separately",
            "external_model_called": False, "target_executed": False, "rename_move_lineage_complete": False,
            "note": "UUIDs belong to a disposable PostgreSQL test schema; only newly written image artifacts are removed."}
        if os.getenv("EXWEB_CODE_ALIAS_REPORT"):
            Path(os.environ["EXWEB_CODE_ALIAS_REPORT"]).write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    finally:
        keys = sorted(written)
        for start in range(0, len(keys), 1000):
            removed = s3.delete_objects(Bucket=config.bucket, Delete={"Objects": [{"Key": key} for key in keys[start:start + 1000]]})
            assert not removed.get("Errors"), "Cleanup must affect only this test's newly archived image artifacts"
