from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.tool_models import ToolResult
from apps.api.app.application.system_image.image_query_models import SourceContextRootsInput, SourceContextRootsReceipt
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.application.system_image.source_context_roots import SourceContextRootApplicationService
from apps.api.app.domain.system_image.derivation_impact import DerivationImpactIntegrityError
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessScope, StaleSourceAccessScope
from apps.api.app.domain.system_image.source_context_roots import SourceContextRoot, SourceContextRootInventory
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_derivation_impact import delta


HASH = snapshot_digest("root fixture")


@pytest.fixture
def roots_app():
    changes, roots, contexts, images, calls = delta(), [], {}, {}, []
    def add_root(ident, image_id):
        root = SourceContextRoot(ident, snapshot_digest(ident), image_id, snapshot_digest(image_id))
        roots.append(root)
        contexts[ident] = {"metadata": {"project_id": "project", "context_id": ident,
            "artifact_hash": root.context_artifact_hash, "image_revision_id": image_id,
            "image_artifact_hash": root.image_artifact_hash}, "context": {"facts": ["private source text"]}}
        images[image_id] = (SimpleNamespace(image_revision_id=image_id, artifact_hash=root.image_artifact_hash),
            {"source_members": [{"binding_id": "binding", "source_revision_id": "one", "status": "captured"}]})
    add_root("a", "image-1")
    add_root("b", "image-2")
    def inventory(project, binding, revision, *, binding_ids, after_id, limit):
        assert binding_ids == frozenset({"binding"})
        calls.append(("inventory", project, binding, revision))
        selected = sorted((root for root in roots if root.context_id > after_id), key=lambda root: root.context_id)
        return SourceContextRootInventory(tuple(selected[:limit]), len(roots),
            selected[limit - 1].context_id if len(selected) > limit else None)
    def context(project, ident):
        calls.append(("context", project, ident))
        return contexts[ident]
    def image(project, ident):
        calls.append(("image", project, ident))
        return images[ident]
    scope = SourceAccessScope("project", "actor", "project_admin", 0, frozenset({"binding"}),
        frozenset({"source"}), HASH, False)
    authorization = SimpleNamespace(scope=lambda project: scope, require_current=lambda scope: None)
    app = SourceContextRootApplicationService(SimpleNamespace(list=inventory), SimpleNamespace(read=context),
        SimpleNamespace(frozen_snapshot=image), SimpleNamespace(compare=lambda *args: changes), authorization)
    return app, roots, contexts, images, calls, add_root


def request(**changes):
    return SourceContextRootsInput(project_id="project", before_revision_id="one", after_revision_id="two", **changes)


def test_source_reverse_lookup_includes_multiple_images_and_never_inspects_selected_hits(roots_app):
    app, roots, _, _, calls, add_root = roots_app
    add_root("c", "image-1")
    result = app.read(**request().model_dump())
    assert result.inventory.items == tuple(roots) and result.inventory.total == 3
    assert result.source_change_requires_reinvestigation and result.page_evidence_verified
    assert not result.downstream_dependency_graphs_verified and not result.impact_complete
    assert not result.invalidation_applied and not result.generation_authorized and not result.execution_authorized
    assert len([call for call in calls if call[0] == "image"]) == 2
    assert "private source text" not in str(asdict(result))


def test_canonical_receipt_preserves_observed_roots_and_count_not_future_inventory(roots_app):
    app, _, _, _, calls, add_root = roots_app
    tools = ImageQueryToolApplicationService(SimpleNamespace(), source_context_roots=app)
    receipt, observation = tools.execute_with_observation(request(limit=1))
    assert receipt.total == 2 and receipt.next_after_id == "a" and receipt.roots[0].context_id == "a"
    durable = ToolResult(invocation_id="invocation", status="completed", summary="Root discovery", image_query=receipt)
    restored = ToolResult.model_validate_json(durable.model_dump_json()).image_query
    assert restored == receipt
    add_root("c", "image-3")
    prior_queries = len([call for call in calls if call[0] == "inventory"])
    assert tools.expand(restored) == observation
    assert len([call for call in calls if call[0] == "inventory"]) == prior_queries
    assert tools.execute(request()).total == 3
    assert tools.execute(request(after_id="a", limit=1)).roots[0].context_id == "b"
    for forbidden in ("private source text", "oracle", "source_fields", "artifact_ref", "s3://", "facts"):
        assert forbidden not in durable.model_dump_json()


def test_empty_page_and_unchanged_source_keep_explicit_no_business_impact_claims(roots_app):
    app, roots, _, _, _, _ = roots_app
    app.deltas.compare = lambda *args: delta("unchanged")
    page = app.read(**request(after_id="z").model_dump())
    assert page.inventory.items == () and page.inventory.total == 2
    assert not page.source_change_requires_reinvestigation and not page.impact_complete
    roots.clear()
    assert app.read(**request().model_dump()).inventory.total == 0


@pytest.mark.parametrize("fields", [
    {"context_id": True}, {"image_revision_id": ""}, {"context_artifact_hash": None}, {"image_artifact_hash": "invalid"},
])
def test_root_pins_require_exact_typed_ids_and_digests(fields):
    with pytest.raises(DerivationImpactIntegrityError):
        SourceContextRoot(**{"context_id": "ctx", "context_artifact_hash": HASH,
            "image_revision_id": "image", "image_artifact_hash": HASH, **fields})


@pytest.mark.parametrize("page", [
    SourceContextRootInventory((), True, None),
    SourceContextRootInventory((), 2, None),
    SourceContextRootInventory((SourceContextRoot("a", HASH, "image", HASH),) * 2, 2, None),
    SourceContextRootInventory((SourceContextRoot("b", HASH, "image", HASH), SourceContextRoot("a", HASH, "image", HASH)), 2, None),
    SourceContextRootInventory((SourceContextRoot("a", HASH, "image", HASH),), 2, None),
    SourceContextRootInventory((SourceContextRoot("a", HASH, "image", HASH),), 2, "wrong-cursor"),
])
def test_inventory_shape_cannot_omit_roots_or_fabricate_pagination(page):
    with pytest.raises(DerivationImpactIntegrityError):
        page.validate("", 1)


@pytest.mark.parametrize("fields", [
    {"limit": True}, {"limit": "1"}, {"limit": 0}, {"limit": 51}, {"after_id": 1},
    {"before_revision_id": 1}, {"after_revision_id": ""}, {"source_uri": "/private"}, {"invalidation_applied": True},
])
def test_request_rejects_coercion_unpinned_sources_and_authority(fields):
    with pytest.raises(ValueError):
        SourceContextRootsInput.model_validate({"project_id": "project", "before_revision_id": "one",
            "after_revision_id": "two", **fields})


@pytest.mark.parametrize("field", ["project_id", "context_id", "artifact_hash", "image_revision_id", "image_artifact_hash"])
def test_verified_context_must_match_every_reverse_lookup_pin(roots_app, field):
    app, _, contexts, _, _, _ = roots_app
    contexts["a"]["metadata"][field] = "wrong"
    with pytest.raises(DerivationImpactIntegrityError, match="context pin"):
        app.read(**request().model_dump())


@pytest.mark.parametrize("mutation", ["missing", "wrong_revision", "duplicate", "uncaptured", "wrong_hash"])
def test_image_source_membership_is_reverified_not_trusted_from_join(roots_app, mutation):
    app, _, _, images, _, _ = roots_app
    header, image = images["image-1"]
    if mutation == "missing":
        image["source_members"] = []
    elif mutation == "duplicate":
        image["source_members"] *= 2
    elif mutation == "wrong_revision":
        image["source_members"][0]["source_revision_id"] = "later"
    elif mutation == "uncaptured":
        image["source_members"][0]["status"] = "failed"
    else:
        header.artifact_hash = snapshot_digest("other image")
    with pytest.raises(DerivationImpactIntegrityError, match="source membership"):
        app.read(**request().model_dump())


@pytest.mark.parametrize("operation", ["inventory", "context", "image"])
def test_acl_change_during_read_or_diagnostic_discards_the_entire_page(roots_app, operation):
    app, _, _, _, _, _ = roots_app
    revoked = []
    def current(scope):
        if revoked:
            raise StaleSourceAccessScope("revoked")
    app.authorization.require_current = current
    target, name = {"inventory": (app.inventory, "list"), "context": (app.contexts, "read"),
                    "image": (app.images, "frozen_snapshot")}[operation]
    def fail(*args, **kwargs):
        revoked.append(True)
        raise RuntimeError("private diagnostic")
    setattr(target, name, fail)
    with pytest.raises(StaleSourceAccessScope):
        app.read(**request().model_dump())


@pytest.mark.parametrize("fields", [{"delta_hash": snapshot_digest("wrong")}, {"result_hash": snapshot_digest("wrong")},
    {"before_manifest_hash": snapshot_digest("wrong")}, {"after_manifest_hash": snapshot_digest("wrong")},
    {"total": 3}, {"next_after_id": "a"}])
def test_receipt_full_recomputation_rejects_tampering(roots_app, fields):
    app, _, _, _, _, _ = roots_app
    tools = ImageQueryToolApplicationService(SimpleNamespace(), source_context_roots=app)
    receipt = tools.execute(request())
    with pytest.raises((DerivationImpactIntegrityError, ImageRevisionIntegrityError)):
        tools.expand(receipt.model_copy(update=fields))


def test_old_receipt_cannot_leak_hidden_root_counts_after_scope_changes_even_on_empty_pages(roots_app):
    app, _, _, _, _, _ = roots_app
    tools = ImageQueryToolApplicationService(SimpleNamespace(), source_context_roots=app)
    receipt = tools.execute(request(after_id="z"))
    assert receipt.total == 2 and receipt.roots == []
    scope = app.authorization.scope("project")
    app.authorization.scope = lambda project: replace(scope, fingerprint=snapshot_digest("new ACL epoch"))
    with pytest.raises(StaleSourceAccessScope):
        tools.expand(receipt)
    assert tools.execute(request(after_id="z")).source_scope_fingerprint != receipt.source_scope_fingerprint


def test_receipt_is_strict_at_nested_pins_and_cannot_claim_downstream_authority(roots_app):
    app, _, _, _, _, _ = roots_app
    receipt = ImageQueryToolApplicationService(SimpleNamespace(), source_context_roots=app).execute(request()).model_dump()
    for extra in ({"oracle": "private"}, {"context_id": True}, {"context_artifact_hash": "bad"}):
        with pytest.raises(ValueError):
            SourceContextRootsReceipt.model_validate({**receipt, "roots": [{**receipt["roots"][0], **extra}]})
    for field in ("impact_complete", "invalidation_applied", "generation_authorized", "execution_authorized",
                  "downstream_dependency_graphs_verified"):
        with pytest.raises(ValueError):
            SourceContextRootsReceipt.model_validate({**receipt, field: True})


def test_no_configured_port_cannot_fall_back_to_mutable_workspace():
    with pytest.raises(ValueError, match="Unsupported image query"):
        ImageQueryToolApplicationService(SimpleNamespace()).execute(request())


def test_source_pair_scope_is_checked_even_for_an_empty_inventory(roots_app):
    app, _, _, _, _, _ = roots_app
    changes = delta()
    app.deltas.compare = lambda *args: replace(changes, before=replace(changes.before, project_id="other-project"))
    with pytest.raises(DerivationImpactIntegrityError, match="source pins"):
        app.read(**request().model_dump())
