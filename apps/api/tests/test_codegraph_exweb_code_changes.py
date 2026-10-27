"""Actual native providers over an explicitly controlled, non-upstream change."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select

from apps.api.app.application.system_image.source_ports import code_projection_payload
from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.domain.system_image.code_member_delta import compare_code_members
from apps.api.app.domain.system_image.image_revision import (
    IMAGE_POLICY, ImageRevisionSummary, build_image_artifact, member_payload,
)
from apps.api.app.infrastructure.persistence.code_entity_models import CodeEntityRevisionRecord
from apps.api.app.infrastructure.persistence.source_evidence_models import SourceEvidenceRecord, CodeEntityEvidenceRecord
from apps.api.app.infrastructure.system_image.image_artifacts import ArchivedImageArtifacts
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.app.infrastructure.system_image.code_graph_observation_validation import validate_java_imports
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.source_snapshot_archive import SourceSnapshotArchive
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.exweb_code_changes import (
    ADDED_PATH, BASE_COMMIT, CHANGE_POLICY, CHAT_PATH, DELETED_PATH,
    change_inventory, controlled_code_change,
)
from apps.api.tests.test_codegraph_exweb import exweb_sdk_input, pg_repo, register, registry
from apps.api.tests.test_code_graph_enrichment import _config


def named(result, name, path):
    matches = [item for item in result.entities if item.name == name and item.relative_path == path
               and item.entity_kind == "method"]
    assert len(matches) == 1, (result.provider, name, len(matches))
    return matches[0]


def native_local_rows(result, path):
    rows = []
    for observation in result.native_query_observations:
        payload = json.loads(observation.response_json)
        if payload.get("columns") == ["a.qualified_name", "a.file_path", "type(r)", "b.qualified_name",
                                      "b.file_path", "r.confidence", "r.strategy", "r.candidates"]:
            rows.extend(row for row in payload["rows"] if row[1] == path)
    return rows


def archive_comparison_image(manifest, result, registered, sessions, storage, ordinal):
    """Actual PG identity/evidence pins in test images, not public candidate rows."""
    objects = [{"id": "comparison_" + ref.entity_id, "name": node.name,
        "code_reference": asdict(ref)} for node in result.entities
        if (ref := registered.get(node.provider_node_id)) is not None]
    payload, members = build_image_artifact(manifest, "comparison-baseline", objects, [])
    evidence = {}
    with sessions() as session:
        for revision_id, evidence_id in session.execute(select(
                CodeEntityEvidenceRecord.entity_revision_id, CodeEntityEvidenceRecord.evidence_id).where(
                CodeEntityEvidenceRecord.project_id == manifest.project_id,
                CodeEntityEvidenceRecord.entity_revision_id.in_([member.entity_revision_id for member in members]))):
            evidence.setdefault(revision_id, []).append(evidence_id)
    members = tuple(replace(member, evidence_ids=tuple(sorted(evidence[member.entity_revision_id]))) for member in members)
    payload["members"] = [member_payload(member) for member in members]
    archive = ArchivedImageArtifacts(storage)
    ref, digest = archive.put(manifest.project_id, payload)
    header = ImageRevisionSummary("comparison-" + str(ordinal) + "-" + result.provider, manifest.project_id,
        "comparison-baseline", manifest.manifest_id, manifest.content_hash, digest,
        snapshot_digest(payload["members"]), IMAGE_POLICY, "2026-10-08T00:00:00Z", len(members), len(members), 0)
    return header, archive.read(manifest.project_id, ref, digest)


def test_native_provider_code_changes_keep_old_evidence_and_do_not_infer_rename_lineage(registry, tmp_path, exweb_sdk_input):
    source, captured, units, storage, graph, git = exweb_sdk_input
    service, snapshots, sessions = registry
    assert captured.snapshot.external_revision == BASE_COMMIT
    original_files = tuple(sorted((unit.relative_path, unit.text.encode("utf-8")) for unit in units))
    assert all(unit.text_is_lossless for unit in units)
    changed_files = controlled_code_change(original_files)
    changed_hash, inventory = change_inventory(changed_files)
    fixture_revision = CHANGE_POLICY + ":" + changed_hash
    artifact = SourceSnapshotArchive(storage).capture(project_id=source.project_id, source_id=source.id,
        files=changed_files, content_hash=changed_hash, external_revision=fixture_revision,
        excluded_directories=[], inventory=inventory)
    changed_source = source.model_copy(update={"content_ref": artifact.manifest_ref,
        "content_hash": artifact.content_hash,
        "evidence_refs": ["base-git-revision:" + BASE_COMMIT, "controlled-change:" + CHANGE_POLICY]})
    original_revision = snapshots.record_capture(source, captured.snapshot, captured_at="2026-10-08T00:00:00Z")
    original_manifest = snapshots.freeze_manifest(source.project_id, [source], captured_at="2026-10-08T00:00:00Z")
    changed_revision = snapshots.record_capture(changed_source, artifact, captured_at="2026-10-08T00:01:00Z")
    changed_manifest = snapshots.freeze_manifest(source.project_id, [changed_source], captured_at="2026-10-08T00:01:00Z")
    assert original_revision != changed_revision and artifact.external_revision != BASE_COMMIT
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "changed-restored")
    changed_units = reader.extract_text_units(changed_source)
    assert tuple(sorted((unit.relative_path, unit.text.encode("utf-8")) for unit in changed_units)) == changed_files
    assert len(changed_units) == len(units) == 126
    assert {unit.relative_path for unit in changed_units} != {unit.relative_path for unit in units}

    syntaxes, syntax_ids = [], []
    for item, texts in ((source, units), (changed_source, changed_units)):
        syntax = TreeSitterCodeIntelligenceAdapter().analyze(texts)
        ids = register(service, item, texts, syntax)
        syntaxes.append(syntax)
        syntax_ids.append({node.symbol_key: ids[node.provider_node_id] for node in syntax.entities
                           if node.provider_node_id in ids})
    before, after = syntax_ids
    shared = set(before) & set(after)
    assert shared and all(before[key].entity_id == after[key].entity_id for key in shared)
    assert all(before[key].entity_revision_id != after[key].entity_revision_id for key in shared)
    old_method = named(syntaxes[0], "chatStream", CHAT_PATH)
    new_method = named(syntaxes[1], "streamChat", CHAT_PATH)
    assert old_method.symbol_key not in after and new_method.symbol_key not in before
    assert before[old_method.symbol_key].entity_id != after[new_method.symbol_key].entity_id
    assert not any(node.relative_path == DELETED_PATH for node in syntaxes[1].entities)
    assert any(key.relative_path == DELETED_PATH for key in before)

    cbm = CodebaseMemoryCodeIntelligenceAdapter(replace(_config(Path(__file__).resolve().parents[3] / ".venv/bin/codebase-memory-mcp"),
        mode="required", cache_dir=tmp_path / "cbm-code-changes", timeout_seconds=180,
        max_entities=20000, max_relationships=50000, page_size=500))
    reports, comparison_images = [], []
    for ordinal, (item, texts, syntax) in enumerate(((source, units, syntaxes[0]),
                                                  (changed_source, changed_units, syntaxes[1]))):
        providers, images = {}, {}
        for provider in (cbm, graph):
            raw = attach_symbol_keys(provider.analyze(texts), syntax)
            admitted = validate_java_imports(raw, syntax)
            actual = register(service, item, texts, admitted)
            assert register(service, item, texts, admitted) == actual
            assert all(ref.entity_id == syntax_ids[ordinal][node.symbol_key].entity_id
                for node in admitted.entities if (ref := actual.get(node.provider_node_id)) is not None)
            expected = named(admitted, "chatStream" if ordinal == 0 else "streamChat", CHAT_PATH)
            assert expected.location_precision == "exact" and expected.provider_node_id in actual
            assert (expected.start_line, expected.end_line) == ((38, 44) if ordinal == 0 else (40, 46))
            assert actual[expected.provider_node_id].entity_id == syntax_ids[ordinal][expected.symbol_key].entity_id
            assert not any(node.name == ("streamChat" if ordinal == 0 else "chatStream")
                           and node.relative_path == CHAT_PATH for node in admitted.entities)
            if ordinal:
                assert not any(node.relative_path == DELETED_PATH for node in admitted.entities)
                health, value = named(admitted, "health", ADDED_PATH), named(admitted, "value", ADDED_PATH)
                assert {health.provider_node_id, value.provider_node_id}.issubset(actual)
                assert (health.start_line, health.end_line, value.start_line, value.end_line) == (5, 7, 9, 11)
                assert any(edge.relationship_kind == "calls" and edge.from_provider_node_id == health.provider_node_id
                           and edge.to_provider_node_id == value.provider_node_id for edge in admitted.relationships), json.dumps({
                    "provider": admitted.provider, "health": health.provider_node_id, "value": value.provider_node_id,
                    "raw_local_edges": [asdict(edge) for edge in raw.relationships
                        if edge.from_provider_node_id == health.provider_node_id
                        and edge.to_provider_node_id == value.provider_node_id],
                    "admitted_local_edges": [asdict(edge) for edge in admitted.relationships
                        if edge.from_provider_node_id == health.provider_node_id
                        and edge.to_provider_node_id == value.provider_node_id],
                    "native_local_rows": native_local_rows(raw, ADDED_PATH),
                    "gaps": [asdict(gap) for observation in admitted.provider_observations for gap in observation.gaps],
                }, sort_keys=True)
            providers[raw.provider] = {"version": raw.provider_version,
                "raw_projection_hash": snapshot_digest(code_projection_payload(raw)),
                "admitted_projection_hash": snapshot_digest(code_projection_payload(admitted)),
                "raw_entities": len(raw.entities), "raw_relationships": len(raw.relationships),
                "registered_entities": len(actual), "method_entity_id": actual[expected.provider_node_id].entity_id,
                "method_source_revision_id": actual[expected.provider_node_id].source_revision_id,
                "observations": [asdict(observation) for observation in admitted.provider_observations]}
            images[raw.provider] = archive_comparison_image((original_manifest, changed_manifest)[ordinal],
                admitted, actual, sessions, storage, ordinal)
        assert providers["codebase-memory"]["method_entity_id"] == providers["codegraph"]["method_entity_id"]
        reports.append(providers)
        comparison_images.append(images)
    assert reports[0]["codegraph"]["method_entity_id"] != reports[1]["codegraph"]["method_entity_id"]
    delta_reports = {}
    for provider in ("codebase-memory", "codegraph"):
        delta = compare_code_members(*comparison_images[0][provider], *comparison_images[1][provider])
        changes = {item.entity_id: item for item in delta.changes}
        old_id, new_id = reports[0][provider]["method_entity_id"], reports[1][provider]["method_entity_id"]
        assert changes[old_id].kind == "removed_member" and changes[new_id].kind == "added_member"
        assert delta.counts["revision_changed"] > 0 and not delta.source_scope_changed
        assert not delta.source_deletions_verified and not delta.rename_lineage_transferred
        assert not delta.impact_complete and not delta.approval_transferred
        assert compare_code_members(*comparison_images[0][provider], *comparison_images[1][provider]) == delta
        delta_reports[provider] = {"delta_hash": delta.content_hash, "counts": delta.counts,
            "before_image_hash": delta.before_image_hash, "after_image_hash": delta.after_image_hash,
            "old_method_kind": changes[old_id].kind, "new_method_kind": changes[new_id].kind,
            "scope": "private_test_images_with_actual_pg_registered_native_members_not_public_image_rows"}

    evidence_reads = 0
    with sessions() as session:
        old_rows = session.scalars(select(CodeEntityRevisionRecord).where(
            CodeEntityRevisionRecord.source_revision_id == original_revision)).all()
        new_rows = session.scalars(select(CodeEntityRevisionRecord).where(
            CodeEntityRevisionRecord.source_revision_id == changed_revision)).all()
        assert before[old_method.symbol_key].entity_revision_id in {row.entity_revision_id for row in old_rows}
        assert before[old_method.symbol_key].entity_id not in {row.entity_id for row in new_rows}
        deleted_ids = {ref.entity_id for key, ref in before.items() if key.relative_path == DELETED_PATH}
        assert deleted_ids and deleted_ids.issubset({row.entity_id for row in old_rows})
        assert not deleted_ids & {row.entity_id for row in new_rows}
        evidence = session.scalars(select(SourceEvidenceRecord).where(
            SourceEvidenceRecord.source_revision_id.in_([original_revision, changed_revision]))).all()
        assert {row.source_revision_id for row in evidence} == {original_revision, changed_revision}
        for row in evidence:
            body = storage.get_bytes(row.object_ref)
            assert "sha256:" + hashlib.sha256(body).hexdigest() == row.file_hash
            if row.precision == "exact":
                assert text_digest("".join(source_lines(body.decode("utf-8"))[row.start_line - 1:row.end_line])) == row.snippet_hash
            evidence_reads += 1
    assert not list(graph.config.cache_dir.iterdir())
    assert git("rev-parse", "HEAD") == BASE_COMMIT and not git("status", "--porcelain")
    report = {"scope": "controlled_exweb_code_change_native_identity_and_archived_evidence_not_upstream_or_gold",
        "base_commit": BASE_COMMIT, "changed_external_revision": fixture_revision,
        "original_manifest_hash": captured.snapshot.manifest_hash, "changed_manifest_hash": artifact.manifest_hash,
        "original_source_revision_id": original_revision, "changed_source_revision_id": changed_revision,
        "modified_paths": [CHAT_PATH], "deleted_paths": [DELETED_PATH], "added_paths": [ADDED_PATH],
        "source_files_per_revision": [len(units), len(changed_units)], "shared_keys": len(shared),
        "stable_ids_reused": True, "rename_lineage_inferred": False, "deleted_old_evidence_retained": True,
        "minio_evidence_reads": evidence_reads, "providers_by_revision": reports,
        "runtime_hash": graph.config.expected_runtime_hash, "provider_runs_per_revision": 1,
        "code_member_delta": delta_reports,
        "target_executed": False, "external_model_calls": 0, "upstream_change": False,
        "automatic_delta_verified": False, "gold_accuracy_or_p95_verified": False}
    path = os.environ.get("EXWEB_CODEGRAPH_CODE_CHANGE_REPORT")
    if path:
        destination = Path(path)
        assert not destination.exists(), "do not overwrite earlier native validation evidence"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n")
