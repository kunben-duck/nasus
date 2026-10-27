from types import SimpleNamespace
from dataclasses import asdict, dataclass, replace

import pytest

from apps.api.app.domain.system_image.derivation_impact import (
    DerivationImpactIntegrityError, DerivationImpactTooLarge, DerivationNode, assess_derivation_impact,
)
from apps.api.app.domain.system_image.source_delta import compare_source_snapshots
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.app.application.system_image.context_change_impact import ContextChangeImpactApplicationService
from apps.api.app.application.system_image.image_query_models import ImageContextImpactInput, ImageContextImpactReceipt
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.application.platform.tool_models import ToolResult
from apps.api.tests.test_source_delta import snapshot


HASH = snapshot_digest("private fixture")


def graph():
    return (DerivationNode("context", "ctx", HASH, ()),
        DerivationNode("scope", "scope", HASH, ("context:ctx",)),
        DerivationNode("generation", "gen", HASH, ("scope:scope",)),
        DerivationNode("case", "gen/case", HASH, ("generation:gen",)),
        DerivationNode("coverage", "gen", HASH, ("generation:gen",)),
        DerivationNode("mapping", "review", HASH, ("generation:gen",)))


def delta(kind="added"):
    before = snapshot("one", {"selected.py": "same"})
    files = {"selected.py": "different"} if kind == "modified" else {"selected.py": "same"}
    if kind in {"added", "unresolved"}:
        files["unselected.py"] = "new"
    if kind == "deleted":
        before = snapshot("one", {"selected.py": "same", "old.py": "old"})
    return compare_source_snapshots(before, snapshot("two", files, legacy=kind == "unresolved"))


@pytest.mark.parametrize("kind", ["added", "modified", "deleted", "unresolved"])
def test_change_propagates_to_every_derived_artifact_including_negative_retrieval(kind):
    nodes = graph()
    value = assess_derivation_impact(nodes, "context:ctx", delta(kind), HASH)
    assert set(value.affected_keys) == {node.key for node in nodes}
    assert value.dependency_closure_complete and value.dependency_count == 6
    assert not value.impact_complete and not value.invalidation_applied
    assert not value.generation_authorized and not value.execution_authorized
    assert ("source_inventory_incomplete" if kind == "unresolved" else "query_scope_changed") in value.reason_codes
    assert assess_derivation_impact(tuple(reversed(nodes)), "context:ctx", delta(kind), HASH) == value


def test_identical_file_contents_do_not_invalidate_existing_artifacts():
    result = assess_derivation_impact(graph(), "context:ctx", delta("unchanged"), HASH)
    assert result.affected_keys == result.reason_codes == () and result.dependency_closure_complete


def test_v1_impact_graph_digest_keeps_original_bytes_and_ignores_future_node_fields():
    nodes = graph()
    original = snapshot_digest([asdict(node) for node in sorted(nodes, key=lambda node: node.key)])
    result = assess_derivation_impact(nodes, "context:ctx", delta(), HASH)
    assert result.graph_hash == original

    @dataclass(frozen=True)
    class FutureNode(DerivationNode):
        future_metadata: str = "not a v1 graph field"

    extended = tuple(FutureNode(**asdict(node)) for node in nodes)
    assert snapshot_digest([asdict(node) for node in sorted(extended, key=lambda node: node.key)]) != original
    assert assess_derivation_impact(extended, "context:ctx", delta(), HASH) == result
    changed = (*nodes[:-1], replace(nodes[-1], artifact_hash=snapshot_digest("changed review")))
    assert assess_derivation_impact(changed, "context:ctx", delta(), HASH).graph_hash != original


@pytest.mark.parametrize("bad", [
    graph() + (graph()[1],), graph()[1:], graph()[:-1] + (DerivationNode("mapping", "review", HASH, ("generation:missing",)),),
    graph() + (DerivationNode("mapping", "orphan", HASH, ()),),
    (graph()[0], DerivationNode("scope", "scope", HASH, ("generation:gen",)), graph()[2]),
])
def test_duplicate_missing_or_cyclic_ancestors_never_return_a_partial_closure(bad):
    with pytest.raises(DerivationImpactIntegrityError):
        assess_derivation_impact(bad, "context:ctx", delta(), HASH)


def test_expansion_budget_is_a_hard_failure_not_top_k_impact():
    nodes = (graph()[0], *(DerivationNode("scope", str(i), HASH, ("context:ctx",)) for i in range(128)))
    with pytest.raises(DerivationImpactTooLarge):
        assess_derivation_impact(nodes, "context:ctx", delta(), HASH)


@pytest.mark.parametrize("kind,parents", [("generation", ("context:ctx",)),
    ("case", ("scope:scope",)), ("coverage", ("context:ctx",)),
    ("mapping", ("context:ctx", "generation:gen"))])
def test_dependencies_cannot_skip_their_typed_derivation_parent(kind, parents):
    nodes = graph() + (DerivationNode(kind, "wrong-parent", HASH, parents),)
    with pytest.raises(DerivationImpactIntegrityError, match="edge types"):
        assess_derivation_impact(nodes, "context:ctx", delta(), HASH)


def test_valid_edge_types_still_reject_a_predecessor_cycle():
    nodes = (graph()[0], DerivationNode("scope", "one", HASH, ("context:ctx", "scope:two")),
             DerivationNode("scope", "two", HASH, ("context:ctx", "scope:one")))
    with pytest.raises(DerivationImpactIntegrityError, match="cyclic"):
        assess_derivation_impact(nodes, "context:ctx", delta(), HASH)


@pytest.mark.parametrize("extra", [{"artifact_hash": "not-a-digest"}, {"artifact_id": True}, {"kind": []},
    {"dependencies": ["context:ctx"]}, {"dependencies": ("context:ctx", "context:ctx")}])
def test_invalid_node_identity_hash_or_dependency_shape_fails_closed(extra):
    with pytest.raises(DerivationImpactIntegrityError):
        DerivationNode(**{"kind": "scope", "artifact_id": "scope", "artifact_hash": HASH,
                          "dependencies": ("context:ctx",), **extra})


@pytest.fixture
def impact_app():
    changes, quality_nodes = delta(), list(graph()[1:])
    context = {"metadata": {"artifact_hash": HASH, "image_revision_id": "image", "image_artifact_hash": HASH,
                            "input_digest": HASH}}
    header = SimpleNamespace(artifact_hash=HASH, image_revision_id="image")
    image = {"source_members": [{"binding_id": "binding", "source_revision_id": "one", "status": "captured"}]}
    calls = []
    def quality(project_id, context_id, *, pinned=None):
        calls.append(pinned)
        if pinned is None:
            return tuple(quality_nodes)
        selected = set(pinned)
        return tuple(n for n in quality_nodes if n.kind not in {"scope", "generation", "mapping"}
                     or (n.kind, n.artifact_id) in selected)
    authorization = SimpleNamespace(scope=lambda p: "scope", require_current=lambda s: None)
    app = ContextChangeImpactApplicationService(SimpleNamespace(read=lambda *a: context),
        SimpleNamespace(frozen_snapshot=lambda *a: (header, image)),
        SimpleNamespace(compare=lambda *a: changes), SimpleNamespace(read=quality), authorization)
    request = ImageContextImpactInput(project_id="project", context_id="ctx", context_artifact_hash=HASH,
                                      before_revision_id="one", after_revision_id="two")
    return app, request, quality_nodes, calls, image


def test_canonical_receipt_round_trip_pins_existing_graph_and_has_no_source_content(impact_app):
    app, request, nodes, calls, _ = impact_app
    query = ImageQueryToolApplicationService(SimpleNamespace(), context_impacts=app)
    receipt, result = query.execute_with_observation(request)
    assert isinstance(receipt, ImageContextImpactReceipt) and receipt.dependency_count == receipt.affected_count == 6
    tool_result = ToolResult(invocation_id="tool", status="completed", summary="Prospective only", image_query=receipt)
    restored = ToolResult.model_validate_json(tool_result.model_dump_json()).image_query
    nodes.append(DerivationNode("scope", "later", HASH, ("context:ctx",)))
    assert query.expand(restored) == result
    assert calls[-1] == (("generation", "gen"), ("mapping", "review"), ("scope", "scope"))
    assert query.execute(request).dependency_count == 7
    for forbidden in ("selected.py", "unselected.py", "private fixture", "artifact_ref", "source_fields"):
        assert forbidden not in receipt.model_dump_json()


@pytest.mark.parametrize("mutation", [{"graph_hash": snapshot_digest("wrong")}, {"affected_count": 0},
    {"dependency_pins": []}, {"delta_hash": snapshot_digest("wrong")}])
def test_tampered_receipts_cannot_replay(impact_app, mutation):
    from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
    app, request, _, _, _ = impact_app
    query = ImageQueryToolApplicationService(SimpleNamespace(), context_impacts=app)
    receipt = query.execute(request)
    with pytest.raises((DerivationImpactIntegrityError, ImageRevisionIntegrityError)):
        query.expand(receipt.model_copy(update=mutation))


def test_wrong_context_digest_or_source_revision_fails_before_quality_reads(impact_app):
    app, request, _, calls, image = impact_app
    with pytest.raises(DerivationImpactIntegrityError):
        app.read(**request.model_copy(update={"context_artifact_hash": snapshot_digest("other")}).model_dump())
    image["source_members"][0]["source_revision_id"] = "another"
    with pytest.raises(DerivationImpactIntegrityError):
        app.read(**request.model_dump())
    assert not calls


def test_acl_revocation_after_quality_verification_discards_the_entire_impact(impact_app):
    app, request, _, calls, _ = impact_app
    def current(scope):
        if calls:
            raise StaleSourceAccessScope("fixture revoke")
    app.authorization.require_current = current
    with pytest.raises(StaleSourceAccessScope):
        app.read(**request.model_dump())


@pytest.mark.parametrize("extra", [{"invalidation_applied": True}, {"dependency_pins": []},
                                 {"execution_authorized": True}, {"context_artifact_hash": "bad"}])
def test_fresh_inputs_never_accept_replay_pins_or_authority_fields(extra):
    with pytest.raises(ValueError):
        ImageContextImpactInput.model_validate({"project_id": "p", "context_id": "c", "context_artifact_hash": HASH,
            "before_revision_id": "one", "after_revision_id": "two", **extra})
