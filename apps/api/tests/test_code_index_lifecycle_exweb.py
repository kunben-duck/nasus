"""Opt-in canonical HTTP validation against archived, never executed exweb."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.application.system_image.code_index_lifecycle import CODE_INDEX_LIST_TOOL, CODE_INDEX_STATUS_TOOL
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexGenerationRecord
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_structure_build_api import request, submit, confirm
from apps.api.tests.test_code_index_lifecycle_api import tool, cancel, url


def test_fixed_exweb_canonical_structure_exposes_authorized_lifecycle_without_native_reads(evidence_api, monkeypatch, tmp_path):
    configured = os.environ.get("EXWEB_CODE_CONTROL_SOURCE")
    if not configured:
        pytest.skip("opt-in fixed exweb canonical lifecycle validation")
    v = evidence_api
    root = Path(configured).resolve()
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert revision == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert not subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(root)}]})
    v["invoke"]("system_image.sources.ingest")
    manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
    v["image"] = {**v["image"], "source_manifest": {"manifest_id": manifest.manifest_id}}
    calls = []
    class Recorder(CodeGraphProcessRunner):
        def run(self, args, **kwargs):
            calls.append("mcp/negotiate" if kwargs.get("dialogue") is not None else args[2] if len(args) > 2 else "--version")
            return super().run(args, **kwargs)
    native = CodebaseMemoryCodeIntelligenceAdapter(replace(CodeGraphConfig.from_env(), mode="required",
        binary=str(Path(__file__).resolve().parents[3] / ".venv/bin/codebase-memory-mcp"), cache_dir=tmp_path / "native",
        timeout_seconds=180, max_entities=20000, max_relationships=50000), process_runner=Recorder())
    extraction = app.state.container.structure_builds.preparation.extraction
    generations = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), extraction._source_reader, native)
    monkeypatch.setattr(extraction, "_source_code_intelligence", RegisteredCodeIntelligenceAdapter(
        CompositeCodeIntelligenceAdapter(TreeSitterCodeIntelligenceAdapter(), native, mode="required"), generations))
    original = submit(v, request(v))
    result = confirm(v, original)
    assert result["status"] == "completed", result
    with session_scope() as session:
        rows = session.scalars(select(CodeIndexGenerationRecord).join(SourceBindingRecord,
            SourceBindingRecord.binding_id == CodeIndexGenerationRecord.binding_id).where(
                CodeIndexGenerationRecord.invocation_id == original,
                SourceBindingRecord.external_identity == str(root))).all()
        assert len(rows) == 1
        pin = CodeIndexGenerationRepository._pin(rows[0])
    before = tuple(calls)
    response = v["client"].get(url(v, pin), headers=v["headers"])
    assert response.status_code == 200, response.text
    status = response.json()["status"]
    assert status["invocation_status"] == "completed" and status["worker_state"] == "none" and status["state"] == "idle"
    assert status["entity_count"] > 500 and status["relationship_count"] > 1000 and status["epoch"] == 1
    assert status["protocol"]["cli_version"] == "codebase-memory-mcp 0.8.1"
    saved = tool(v, CODE_INDEX_STATUS_TOOL, {"generation_id": pin.generation_id})
    page = tool(v, CODE_INDEX_LIST_TOOL, {"binding_id": pin.binding_id, "limit": 1})
    assert page["result"]["code_index"]["items"] == [asdict(pin)]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        described = app.state.container.tool_evidence.describe(saved["id"], v["project_id"])
    assert described["code_index"]["status"]["pin"]["content_hash"] == pin.content_hash
    assert cancel(v, pin)["result"]["code_index"]["outcome"] == "already_committed"
    assert confirm(v, original) == result
    assert tuple(calls) == before and calls.count("index_repository") == 2 and calls.count("mcp/negotiate") == 2
    assert not list((tmp_path / "native").rglob("*.db"))
    report = os.environ.get("EXWEB_LIFECYCLE_REPORT")
    if report:
        Path(report).write_text(json.dumps({"schema": "nasus.exweb-public-code-index-lifecycle.v1", "git_revision": revision,
            "generation": asdict(pin), "status": status, "native_index_calls": calls.count("index_repository"),
            "native_negotiations": calls.count("mcp/negotiate"), "code_sources": 2,
            "canonical_structure_status": result["status"], "post_commit_cancel": "already_committed",
            "lifecycle_queries_started_provider": False, "target_executed": False, "external_model_called": False,
            "business_gold": False, "object_storage": "isolated_local_adapter"}, indent=2) + "\n")
