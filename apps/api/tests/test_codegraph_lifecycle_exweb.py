"""Opt-in public canonical exweb build with real SDK, PG and private MinIO."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.application.system_image.code_index_lifecycle import CODE_INDEX_LIST_TOOL, CODE_INDEX_STATUS_TOOL
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexGenerationRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.code_intelligence_factory import configured_code_graph
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_codegraph_exweb import exweb_sdk_input
from apps.api.tests.test_codegraph_index_generations import NativeRunner
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request, submit, confirm
from apps.api.tests.test_code_index_lifecycle_api import tool, cancel, url


def test_public_exweb_sdk_structure_build_lifecycle_and_read_authorization(evidence_api, exweb_sdk_input, monkeypatch, tmp_path):
    v = evidence_api
    source, capture, _, storage, initial, git = exweb_sdk_input
    assert os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio" and storage.config.endpoint
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": source.source_uri}]})
    v["invoke"]("system_image.sources.ingest")
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    v["image"] = {**v["image"], "source_manifest": {"manifest_id": manifest.manifest_id}}
    extraction = app.state.container.structure_builds.preparation.extraction
    operator_config = replace(CodeGraphConfig.from_env(), mode="required", provider="codegraph",
        sdk_package_path=initial.config.package_path, sdk_platform_path=initial.config.platform_path,
        sdk_runtime_hash=initial.config.expected_runtime_hash, cache_dir=tmp_path / "public-native",
        timeout_seconds=180, max_entities=20000, max_relationships=50000)
    native = configured_code_graph(operator_config, max_files=extraction._source_reader.max_files,
        max_source_bytes=extraction._source_reader.max_bytes)
    native.runner = NativeRunner()
    generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
    monkeypatch.setattr(extraction, "_source_code_intelligence", RegisteredCodeIntelligenceAdapter(
        CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations))
    invocation = submit(v, request(v))
    result = confirm(v, invocation)
    assert result["status"] == "completed", result
    with session_scope() as session:
        rows = session.scalars(select(CodeIndexGenerationRecord).join(SourceBindingRecord,
            SourceBindingRecord.binding_id == CodeIndexGenerationRecord.binding_id).where(
                CodeIndexGenerationRecord.invocation_id == invocation,
                SourceBindingRecord.external_identity == source.source_uri)).all()
        assert len(rows) == 1
        pin = CodeIndexGenerationRepository._pin(rows[0])
    count_before = len(native.runner.calls)
    assert count_before == 2  # Existing Orders source and full immutable exweb, each prepared once.
    response = v["client"].get(url(v, pin), headers=v["headers"])
    assert response.status_code == 200, response.text
    status = response.json()["status"]
    assert status["state"] == "idle" and status["invocation_status"] == "completed" and status["worker_state"] == "none"
    assert status["entity_count"] == 526 and status["relationship_count"] == 580
    assert status["protocol"]["schema"] == "nasus.code-provider-sdk-contract.v1"
    assert status["protocol"]["entry_point"] == "package_public_entry" and "protocol_version" not in status["protocol"]
    assert response.headers["cache-control"] == "private, no-store" and response.json()["can_cancel"] is False
    assert v["client"].get(url(v, pin)).status_code == 401
    assert v["client"].get(url(v, pin), headers=v["member_headers"]).status_code == 403
    saved = tool(v, CODE_INDEX_STATUS_TOOL, {"generation_id": pin.generation_id})
    page = tool(v, CODE_INDEX_LIST_TOOL, {"binding_id": pin.binding_id, "limit": 1})
    assert page["result"]["code_index"]["items"] == [asdict(pin)]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        described = app.state.container.tool_evidence.describe(saved["id"], v["project_id"])
    assert json.loads(json.dumps(described["code_index"]["status"]["protocol"])) == status["protocol"]
    assert cancel(v, pin)["result"]["code_index"]["outcome"] == "already_committed"
    assert confirm(v, invocation) == result and len(native.runner.calls) == count_before
    assert not list(native.config.cache_dir.iterdir())
    assert not any(key in response.text for key in (str(tmp_path), "local-object://", "owner_id", "storage_ref"))
    assert not git("status", "--porcelain")
    report = {"schema": "nasus.exweb-public-sdk-lifecycle.v1", "source_revision": capture.snapshot.external_revision,
        "generation": asdict(pin), "status": status, "canonical_structure_status": "completed",
        "native_preparations": count_before, "public_queries_or_replay_started_provider": False,
        "unauthenticated_denied": True, "nonmember_denied": True, "post_commit_cancel": "already_committed",
        "storage": "isolated_postgresql_and_private_minio", "target_executed": False,
        "external_model_called": False, "semantic_quality_gold": False, "production_default_changed": False,
        "scope": "canonical_inline_structure_not_temporal_worker_replacement"}
    if os.environ.get("EXWEB_CODEGRAPH_PUBLIC_REPORT"):
        path = Path(os.environ["EXWEB_CODEGRAPH_PUBLIC_REPORT"])
        path.parent.mkdir(parents=True, exist_ok=True)
        assert not path.exists()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
