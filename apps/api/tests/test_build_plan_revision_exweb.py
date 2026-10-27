"""Fixed exweb + native CBM, private PG/MinIO; enrichment is not business gold."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.infrastructure.config.code_graph_config import CodeGraphConfig
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexGenerationRecord, CodeIndexProjectionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.registered_code_intelligence import RegisteredCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_agent_investigation_continuation import replace_graph, start_structure
from apps.api.tests.test_build_plan_revision_api import body, prepare, confirm, history
from apps.api.tests.exweb_storage_evidence import verify_exweb_storage


@pytest.mark.skipif(not os.getenv("EXWEB_CODE_CONTROL_SOURCE"), reason="requires an explicitly enabled clean fixed exweb checkout")
def test_fixed_exweb_retains_original_goal_and_native_artifact_across_requirement_and_test_enrichment(evidence_api, monkeypatch, tmp_path):
    v = evidence_api
    root = Path(os.environ["EXWEB_CODE_CONTROL_SOURCE"]).resolve()
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
    replace_graph(monkeypatch, "langgraph_postgres")
    fixed, goal = start_structure(v, authorized=True)
    structural = next(step for step in goal["steps"] if step["selected_tool_id"] == "system_image.build.structure")
    command = v["client"].get(f"/v1/tool-invocations/{structural['tool_invocation_id']}", headers=v["headers"]).json()
    image_id = next(ref.split(":", 1)[1] for ref in command["result"]["object_refs"] if ref.startswith("image_revision:"))
    before = tuple(calls)
    items = []
    previous_plan, previous_digest = fixed["plan_id"], fixed["plan_digest"]
    previous = None
    for number, (kind, filename) in enumerate((("us_doc", "exweb-requirements.md"), ("test_asset", "exweb-test-cases.csv")), 1):
        destination = tmp_path / filename
        shutil.copyfile(Path(__file__).resolve().parents[3] / "tests/fixtures/system-image" / filename, destination)
        v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": kind, "source_uri": str(destination)}]})
        v["invoke"]("system_image.sources.ingest")
        new_manifest = SourceSnapshotRepository().latest_manifest(v["project_id"])
        payload = body(v, fixed, goal, new_manifest.manifest_id, from_plan_id=previous_plan,
            from_plan_digest=previous_digest, parent_revision_id=previous["revision"]["revision_id"] if previous else None,
            parent_revision_hash=previous["revision_hash"] if previous else None)
        pending = prepare(v, payload, key=f"exweb-enrichment-{number}")
        assert pending["status"] == "waiting_confirmation"
        saved = confirm(v, pending)
        assert saved["status"] == "completed", saved
        records = history(v, fixed, goal).json()
        assert records[:number - 1] == items
        items = records
        previous = items[-1]
        previous_plan, previous_digest = previous["revision"]["plan_id"], previous["revision"]["plan_digest"]
        updated = v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"])
        assert updated.json() == goal
        assert tuple(calls) == before  # Draft revision never reindexes or runs the target.
    for _ in range(2):
        assert history(v, fixed, goal).json() == items
    assert tuple(calls) == before
    storage = verify_exweb_storage(v["project_id"], image_id)
    with session_scope() as session:
        generation = session.scalars(select(CodeIndexGenerationRecord).join(SourceBindingRecord,
            SourceBindingRecord.binding_id == CodeIndexGenerationRecord.binding_id).where(
                CodeIndexGenerationRecord.invocation_id == structural["tool_invocation_id"],
                SourceBindingRecord.external_identity == str(root))).one()
        projection = session.get(CodeIndexProjectionRecord, generation.generation_id)
        native_projection = {"entity_count": projection.entity_count, "relationship_count": projection.relationship_count,
                             "projection_hash": projection.projection_hash}
    report = {"git_revision": revision, "goal_id": goal["id"], "same_goal": True,
        "revision_count": len(items), "revisions": items, "original_image_revision_id": image_id,
        "native_projection": native_projection,
        "native_index_calls": before.count("index_repository"), "native_mcp_negotiations": before.count("mcp/negotiate"),
        "extra_native_calls_from_enrichment_or_replay": len(calls) - len(before),
        "goal_steps_and_original_authorization_unchanged": True, "new_work_executed": False,
        "target_repository_executed": False, "external_model_calls": 0, "business_gold": False,
        "storage": storage}
    assert report["native_index_calls"] == report["native_mcp_negotiations"] == 2
    assert native_projection["entity_count"] == 755 and native_projection["relationship_count"] == 1425
    if os.getenv("EXWEB_PLAN_REVISION_REPORT"):
        Path(os.environ["EXWEB_PLAN_REVISION_REPORT"]).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
