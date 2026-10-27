import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PERSISTENCE = ROOT / "apps/api/app/infrastructure/persistence"


def test_fact_projection_is_metadata_only_in_the_callers_transaction():
    source = (PERSISTENCE / "relation_fact_provenance_v1.py").read_text()
    for forbidden in ("artifact_ref", "ObjectStorage", "session_scope", "LLMCall", "generation_authorized"):
        assert forbidden not in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "session":
                assert node.func.attr not in {"commit", "rollback", "delete", "update", "merge"}
    for event in ("references.proposed", "link.reviewed", "semantic.evaluated", "semantic.reviewed"):
        assert event in source
    assert "write=False" in source and '"unknown"' not in source


def test_normal_relation_read_paths_validate_fact_registry_without_new_api_or_authority():
    for path in ("reference_link_repository.py", "link_decision_repository.py", "semantic_evaluation_repository.py", "semantic_review_repository.py"):
        source = (PERSISTENCE / path).read_text()
        assert "RelationFactProvenanceProjectorV1().facts" in source and "write=False" in source
    outbox = (PERSISTENCE / "event_outbox_repository.py").read_text()
    assert "RelationFactProvenanceProjectorV1().project_event(session, event)" in outbox


def test_fact_migration_reuses_append_only_graph_without_schema_or_hash_rewrites():
    source = (ROOT / "apps/api/migrations/versions/0073_relation_fact_provenance.py").read_text()
    assert 'down_revision = "0072_relation_provenance"' in source
    assert ".backfill(session)" in source and "Cannot discard" in source
    for forbidden in ("create_table", "drop_table", "drop_constraint", "UPDATE", "DELETE"):
        assert forbidden not in source


def test_existing_reference_requires_read_verification_without_an_event_or_write_projection():
    module = ast.parse((PERSISTENCE / "reference_link_repository.py").read_text())
    record = next(node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == "record")
    reuse = next(node for node in ast.walk(record) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "reused" for target in node.targets))
    assert isinstance(reuse.value, ast.Compare) and isinstance(reuse.value.left, ast.Name)
    assert reuse.value.left.id == "row" and isinstance(reuse.value.ops[0], ast.IsNot)
    assert isinstance(reuse.value.comparators[0], ast.Constant) and reuse.value.comparators[0].value is None
    replay = next(node for node in ast.walk(record) if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name) and node.test.id == "reused")
    calls = [node for statement in replay.body for node in ast.walk(statement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    projection, = [call for call in calls if call.func.attr == "facts"]
    assert any(keyword.arg == "write" and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False for keyword in projection.keywords)
    assert not any(call.func.attr in {"append", "project_event"} for call in calls)


def test_proposal_event_reuse_uses_durable_invocations_not_retained_outbox():
    source = (PERSISTENCE / "relation_fact_provenance_v1.py").read_text()
    assert "ReferenceProposalInvocationRecord as ProposalInvocation" in source
    assert "ProposalInvocation.project_id == row.project_id" in source
    assert "ProposalInvocation.proposal_id == row.proposal_id" in source
    assert "SSEEventOutboxRecord" not in source and "previous_events" not in source
