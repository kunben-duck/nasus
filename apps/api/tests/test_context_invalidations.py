import asyncio
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.context_invalidations import ContextInvalidateInput, ContextInvalidationApplicationService, context_invalidation_query_keys
from apps.api.app.application.quality_loop.test_design_mapping_pins import mapping_review_query_keys
from apps.api.app.application.platform.tool_handlers.context_invalidations import ContextInvalidationToolHandler
from apps.api.app.domain.system_image.context_invalidation import ContextInvalidationChanged, ContextInvalidationIntegrityError, invalidation_metadata
from apps.api.app.domain.system_image.derivation_impact import DerivationNode
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_derivation_impact import impact_app, HASH, delta


@pytest.fixture
def invalidation(impact_app):
    impacts, selection, nodes, _, _ = impact_app
    impact = impacts.read(**selection.model_dump())
    request = ContextInvalidateInput(**selection.model_dump(), expected_impact_hash=snapshot_digest(asdict(impact)),
        reason="Independently confirmed source change fixture")
    return impacts, request, impact, nodes


def metadata(request, impact):
    return invalidation_metadata(request, impact, invalidation_id="invalidation", actor_id="actor",
        invocation_id="invocation", recorded_at="2026-10-07T10:00:00+00:00")


def test_complete_graph_creates_a_separate_stale_fact_not_authority_or_rewritten_content(invalidation):
    _, request, impact, _ = invalidation
    before = asdict(impact)
    result = metadata(request, impact)
    assert result["dependency_count"] == 6 and result["invalidation_applied"]
    assert result["invalidation_scope"] == "image_current_use"
    assert not result["impact_complete"] and not result["generation_authorized"] and not result["execution_authorized"]
    assert result["graph_hash"] == impact.assessment.graph_hash and asdict(impact) == before


@pytest.mark.parametrize("changes", [{"context_id": "other"}, {"before_revision_id": "other"},
    {"after_revision_id": "other"}, {"expected_impact_hash": HASH}, {"context_artifact_hash": snapshot_digest("changed")}])
def test_changed_preview_or_root_pins_require_new_confirmation(invalidation, changes):
    _, request, impact, _ = invalidation
    with pytest.raises((ContextInvalidationChanged, ValueError)):
        metadata(request.model_copy(update=changes), impact)


@pytest.mark.parametrize("changes", [{"affected_keys": ()}, {"dependency_count": 1},
    {"dependency_closure_complete": False}, {"generation_authorized": True}, {"impact_complete": True}])
def test_partial_or_authority_bearing_impact_cannot_be_persisted(invalidation, changes):
    _, request, impact, _ = invalidation
    altered = replace(impact, assessment=replace(impact.assessment, **changes))
    request = request.model_copy(update={"expected_impact_hash": snapshot_digest(asdict(altered))})
    with pytest.raises(ContextInvalidationIntegrityError):
        metadata(request, altered)


def test_complete_unchanged_source_does_not_create_a_stale_record(invalidation):
    impacts, request, _, _ = invalidation
    impacts.deltas.compare = lambda *args: delta("unchanged")
    impact = impacts.read(**request.model_dump(exclude={"expected_impact_hash", "reason", "policy_revision", "invalidation_scope"}))
    with pytest.raises(ContextInvalidationIntegrityError):
        metadata(request.model_copy(update={"expected_impact_hash": snapshot_digest(asdict(impact))}), impact)


def test_commit_callback_rechecks_full_inventory_not_just_preview_hash(invalidation):
    impacts, request, _, nodes = invalidation
    def record(*args, require_current, **kwargs):
        nodes.append(DerivationNode("scope", "new", HASH, ("context:ctx",)))
        require_current()
        pytest.fail("changed graph must not commit")
    repo = SimpleNamespace(committed=lambda *a, **kw: None, record=record)
    auth = SimpleNamespace(scope=lambda p: SimpleNamespace(actor_id="actor", effective_project_role="qa_lead"),
        require_current=lambda scope: None)
    with pytest.raises(ContextInvalidationChanged):
        ContextInvalidationApplicationService(impacts, auth, repo).invalidate(request, invocation_id="invocation", recorded_at="now")


def test_non_reviewer_cannot_invalidate_even_with_a_valid_preview(invalidation):
    impacts, request, _, _ = invalidation
    auth = SimpleNamespace(scope=lambda p: SimpleNamespace(actor_id="viewer", effective_project_role="viewer"))
    with pytest.raises(SourceAccessDenied):
        ContextInvalidationApplicationService(impacts, auth, SimpleNamespace()).invalidate(request, invocation_id="invocation", recorded_at="now")


@pytest.mark.parametrize("changes", [{"execution_authorized": True}, {"dependency_pins": []},
    {"reason": "   "}, {"confirmed_actor_id": "actor"}, {"expected_impact_hash": "invalid"},
    {"invalidation_scope": "all_projects"}])
def test_request_does_not_accept_self_attested_authority_or_blank_reason(invalidation, changes):
    _, request, _, _ = invalidation
    with pytest.raises(ValueError):
        ContextInvalidateInput.model_validate({**request.model_dump(), **changes})


def test_revocation_precedes_repository_failure_diagnostics(invalidation):
    impacts, _, _, _ = invalidation
    def denied(scope):
        raise StaleSourceAccessScope("revoked")
    def broken(*args):
        raise ValueError("private graph")
    auth = SimpleNamespace(scope=lambda p: "scope", require_current=denied)
    with pytest.raises(StaleSourceAccessScope):
        ContextInvalidationApplicationService(impacts, auth, SimpleNamespace(get=broken)).read("project", "invalidation")


@pytest.mark.parametrize("failure", [None, ContextInvalidationChanged("private fixture"), PermissionError("private fixture")])
def test_canonical_handler_refreshes_all_project_consumers_only_after_verified_commit(invalidation, failure):
    _, request, _, _ = invalidation
    emitted = []
    async def emit(*args):
        emitted.append(args)
    def invalidate(value, **kwargs):
        assert value == request and kwargs["invocation_id"] == "invocation"
        if failure is not None:
            raise failure
        return {"invalidation_id": "invalidation"}
    handler = ContextInvalidationToolHandler(SimpleNamespace(invalidate=invalidate),
        SimpleNamespace(emit_tool_status=emit), SimpleNamespace(require_invocation_project_scope=lambda invocation: None))
    asyncio.run(handler.handle(SimpleNamespace(id="invocation", input_payload=request.model_dump(mode="json"))))
    assert emitted[0][1] == "running" and emitted[0][3] == []
    final = emitted[-1]
    assert final[1] == ("completed" if failure is None else "failed")
    assert final[3] == (context_invalidation_query_keys(request.project_id) if failure is None else [])
    assert "private fixture" not in final[2]
    if failure is None:
        assert len(final[3]) == 13 and all(key[1] == request.project_id for key in final[3])
        assert ["automation-input", request.project_id] in final[3]
        assert ["test-design-scope", request.project_id] in final[3]


@pytest.mark.parametrize("query_keys", [context_invalidation_query_keys, mapping_review_query_keys])
def test_upstream_change_revalidates_all_script_input_history_and_review_consumers(query_keys):
    keys = query_keys("exact-project")
    for kind in ("automation-input", "automation-script-input", "automation-script-revisions", "automation-script-reviews"):
        assert [kind, "exact-project"] in keys
    assert len({tuple(key) for key in keys}) == len(keys)
    assert all(len(key) == 2 and key[1] == "exact-project" for key in keys)
