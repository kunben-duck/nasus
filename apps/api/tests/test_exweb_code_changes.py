"""Mutation contract tests are not native provider or business-gold evidence."""
import json
import os
from pathlib import Path

import pytest

from apps.api.app.application.system_image.source_ports import SourceTextUnit
from apps.api.app.domain.system_image.evidence import text_digest
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.exweb_code_changes import (
    ADDED_BODY, ADDED_PATH, BASE_COMMIT, CHANGE_POLICY, CHAT_PATH, DELETED_PATH,
    change_inventory, controlled_code_change,
)
from apps.api.tests.exweb_git_trees import git_bytes, read_git_tree


def files():
    return ((CHAT_PATH, b'class ChatController {\n'
        b'@PostMapping(value = "/stream", produces = NDJSON)\n'
        b'void chatStream(@RequestBody Request request) {}\n'
        b'void chatSse() { toCommand(request, "sse", tenantId, userId); }\n}\n'),
        (DELETED_PATH, b'class DocumentUploadController {}\n'),
        ("unchanged.java", b'class Unchanged {}\n'))


def test_controlled_change_has_exact_modified_added_deleted_bytes_without_mutating_input():
    original = files()
    changed = controlled_code_change(original)
    before, after = dict(original), dict(changed)
    assert original == files() and changed == tuple(sorted(changed))
    assert len(after) == len(before) and set(before) - set(after) == {DELETED_PATH}
    assert set(after) - set(before) == {ADDED_PATH} and after[ADDED_PATH] == ADDED_BODY
    assert after["unchanged.java"] == before["unchanged.java"]
    assert b"chatStream(" not in after[CHAT_PATH] and b"streamChat(" in after[CHAT_PATH]
    assert b'"/stream"' not in after[CHAT_PATH] and b'"/stream-v2"' in after[CHAT_PATH]
    assert b'"fixture_sse"' in after[CHAT_PATH]
    assert controlled_code_change(original) == changed
    old_hash, old_inventory = change_inventory(tuple(sorted(original)))
    new_hash, new_inventory = change_inventory(changed)
    assert old_hash != new_hash and old_inventory.enumeration_complete and new_inventory.enumeration_complete
    assert {entry.path for entry in new_inventory.entries if entry.kind == "file"} == set(after)
    assert change_inventory(changed) == (new_hash, new_inventory)


@pytest.mark.parametrize("fault", ["missing_chat", "missing_deleted", "duplicate", "added_exists",
                                  "missing_anchor", "duplicate_anchor"])
def test_controlled_change_rejects_drift_instead_of_silently_generating_a_different_fixture(fault):
    original = files()
    if fault == "missing_chat":
        original = tuple(item for item in original if item[0] != CHAT_PATH)
    elif fault == "missing_deleted":
        original = tuple(item for item in original if item[0] != DELETED_PATH)
    elif fault == "duplicate":
        original += (original[0],)
    elif fault == "added_exists":
        original += ((ADDED_PATH, ADDED_BODY),)
    else:
        body = original[0][1]
        body = body.replace(b"chatStream(", b"other(") if fault == "missing_anchor" else body + b"chatStream(@RequestBody"
        original = ((CHAT_PATH, body), *original[1:])
    with pytest.raises(ValueError):
        controlled_code_change(original)


def test_reviewed_exweb_tree_and_controlled_change_have_exact_syntax_routes_and_calls():
    configured = os.environ.get("EXWEB_CODE_CHANGE_SOURCE")
    if not configured:
        pytest.skip("set EXWEB_CODE_CHANGE_SOURCE to the approved fixed Git object store")
    root = Path(configured).resolve()
    status = git_bytes(root, "status", "--porcelain")
    original, _, _ = read_git_tree(root, BASE_COMMIT)
    assert len(original) == 126 and sum(len(body) for _, body in original) == 180868
    changed = controlled_code_change(original)
    assert {path for path in dict(original).keys() & dict(changed).keys()
            if dict(original)[path] != dict(changed)[path]} == {CHAT_PATH}
    projections = []
    for data in (original, changed):
        units = [SourceTextUnit(path, body.decode("utf-8"), len(body), text_digest(body.decode("utf-8")))
                 for path, body in data]
        projections.append(TreeSitterCodeIntelligenceAdapter().analyze(units))
    before, after = projections
    methods = lambda result, path: {node.name: node for node in result.entities
        if node.relative_path == path and node.entity_kind == "method"}
    old_method, new_method = methods(before, CHAT_PATH)["chatStream"], methods(after, CHAT_PATH)["streamChat"]
    assert (old_method.start_line, old_method.end_line) == (38, 44)
    assert (new_method.start_line, new_method.end_line) == (40, 46)
    assert old_method.symbol_key != new_method.symbol_key
    assert "chatStream" not in methods(after, CHAT_PATH) and "streamChat" not in methods(before, CHAT_PATH)
    assert methods(before, CHAT_PATH)["chatSse"].symbol_key == methods(after, CHAT_PATH)["chatSse"].symbol_key
    routes = lambda result: {(fact.relative_path, fact.method, fact.route_path, fact.start_line)
                             for fact in result.structural_facts if fact.kind == "route" and fact.status == "observed"}
    assert (CHAT_PATH, "POST", "/api/v1/finance/chat/stream", 38) in routes(before)
    assert (CHAT_PATH, "POST", "/api/v1/finance/chat/stream-v2", 40) in routes(after)
    assert not any(path == DELETED_PATH or route == "/api/v1/finance/chat/stream"
                   for path, _, route, _ in routes(after))
    assert any(node.relative_path == DELETED_PATH for node in before.entities)
    assert not any(node.relative_path == DELETED_PATH for node in after.entities)
    added = methods(after, ADDED_PATH)
    assert (added["health"].start_line, added["health"].end_line) == (5, 7)
    assert (added["value"].start_line, added["value"].end_line) == (9, 11)
    assert any(edge.relationship_kind == "calls" and edge.from_provider_node_id == added["health"].provider_node_id
               and edge.to_provider_node_id == added["value"].provider_node_id for edge in after.relationships)
    assert git_bytes(root, "status", "--porcelain") == status
    destination = os.environ.get("EXWEB_CODE_CHANGE_SYNTAX_REPORT")
    if destination:
        path = Path(destination)
        assert not path.exists(), "do not overwrite earlier validation evidence"
        original_hash, _ = change_inventory(tuple(original))
        changed_hash, _ = change_inventory(changed)
        report = {"scope": "controlled_exweb_code_change_static_syntax_not_native_identity_or_business_gold",
            "base_commit": BASE_COMMIT, "change_policy": CHANGE_POLICY,
            "original_content_hash": original_hash, "changed_content_hash": changed_hash,
            "original_files": len(original), "changed_files": len(changed),
            "original_bytes": sum(len(body) for _, body in original), "changed_bytes": sum(len(body) for _, body in changed),
            "modified_paths": [CHAT_PATH], "deleted_paths": [DELETED_PATH], "added_paths": [ADDED_PATH],
            "old_method_span": [old_method.start_line, old_method.end_line],
            "new_method_span": [new_method.start_line, new_method.end_line],
            "old_method_key": old_method.symbol_key.fingerprint, "new_method_key": new_method.symbol_key.fingerprint,
            "unchanged_method_key": methods(after, CHAT_PATH)["chatSse"].symbol_key.fingerprint,
            "new_call_spans": {name: [node.start_line, node.end_line] for name, node in added.items()},
            "routes_before": sorted(routes(before)), "routes_after": sorted(routes(after)),
            "parser": before.provider, "parser_version": before.provider_version,
            "original_git_status_unchanged": True, "rename_lineage_inferred": False,
            "target_executed": False, "external_model_calls": 0, "upstream_change": False,
            "native_providers_verified": False, "persistence_verified": False, "gold_accuracy_or_p95_verified": False}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
