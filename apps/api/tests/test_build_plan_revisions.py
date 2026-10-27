from dataclasses import replace

import pytest

from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.build_plan_revisions import enriched_proposal
from apps.api.app.domain.system_image.source_snapshots import SourceManifestMember
from apps.api.tests.test_build_plan import manifest, plan


def inputs(*members):
    return replace(manifest(*members), manifest_id="enriched")


def test_enrichment_preserves_objective_budget_purpose_and_requires_new_consent():
    previous = plan()
    revised = enriched_proposal(previous, inputs(*previous.intent.sources,
        SourceManifestMember("doc", "us_doc", "doc-revision", "captured")))
    assert revised.intent.objective == previous.intent.objective
    assert revised.intent.budget == previous.intent.budget
    assert revised.intent.purpose == previous.intent.purpose
    assert revised.intent.mode == "enrich"
    assert revised.digest != previous.digest
    assert revised.execution_ready is False and revised.authorization_state == "not_granted"
    assert "us_doc_unavailable" not in {gap.code for gap in revised.gaps}


@pytest.mark.parametrize("change", ["same", "other-project", "drop-code", "replace-code", "pending", "nothing"])
def test_enrichment_rejects_changed_or_unverified_source_scope(change):
    previous = plan()
    code = previous.intent.sources[0]
    docs = SourceManifestMember("doc", "us_doc", "doc-revision", "captured")
    new = inputs(code, docs)
    if change == "same":
        new = replace(new, manifest_id=previous.intent.source_manifest_id)
    elif change == "other-project":
        new = replace(new, project_id="foreign")
    elif change == "drop-code":
        new = inputs(docs)
    elif change == "replace-code":
        new = inputs(replace(code, source_revision_id="changed"), docs)
    elif change == "pending":
        new = inputs(code, replace(docs, status="pending", source_revision_id=None))
    else:
        new = inputs(code)
    with pytest.raises(BuildPlanIntegrityError):
        enriched_proposal(previous, new)


def test_pending_binding_can_be_captured_without_replacing_other_source_pins():
    code = SourceManifestMember("code", "code", "revision", "captured")
    pending = SourceManifestMember("doc", "us_doc", None, "pending")
    previous = plan(manifest(code, pending))
    revised = enriched_proposal(previous, inputs(code, replace(pending, status="captured", source_revision_id="doc-r1")))
    assert revised.intent.sources[0] == code
