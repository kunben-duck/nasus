from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.code_member_deltas import CodeMemberDeltaApplicationService
from apps.api.app.application.system_image.image_query_models import ImageCodeDeltaInput, ImageCodeDeltaReceipt
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.domain.system_image.code_member_delta import compare_code_members
from apps.api.app.domain.system_image.image_revision import (
    IMAGE_POLICY, ImageRevisionIntegrityError, ImageRevisionPageTooLarge, ImageRevisionSummary, build_image_artifact,
)
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.app.domain.system_image.source_snapshots import CapturedSourceManifest, SourceManifestMember, snapshot_digest


def image(ident, entries, *, project="project", sources=None):
    sources = sources or (SourceManifestMember("binding", "code", "source", "captured"),)
    manifest = CapturedSourceManifest("manifest-" + ident, project, snapshot_digest([asdict(item) for item in sources]), "now", sources)
    objects = [{"id": obj, "name": name, "code_reference": {"entity_id": entity,
        "entity_revision_id": revision, "source_revision_id": source}} for obj, entity, revision, source, name in entries]
    if not objects:
        objects = [{"id": "legacy", "name": "not registered code"}]
    payload, _ = build_image_artifact(manifest, "baseline", objects, [])
    summary = ImageRevisionSummary(ident, project, "baseline", manifest.manifest_id, manifest.content_hash,
        snapshot_digest(payload), snapshot_digest(payload["members"]), IMAGE_POLICY, "now", len(objects), len(entries), 0)
    return summary, payload


def pair():
    before = image("before", [("old_alias", "alias", "a1", "source", "old provider label"),
        ("keep", "keep", "k1", "source", "Keep"), ("edit", "edit", "e1", "source", "Edit"),
        ("removed", "removed", "r1", "source", "Removed")])
    after = image("after", [("new_alias", "alias", "a1", "source", "new provider label"),
        ("keep", "keep", "k1", "source", "Keep"), ("edit", "edit", "e2", "source", "Edit"),
        ("added", "added", "n1", "source", "Added")])
    return before, after


def fake_images(before, after):
    reads, current = [], []
    scope = object()
    def read(project, revision):
        reads.append((project, revision))
        return {before[0].image_revision_id: before, after[0].image_revision_id: after}[revision]
    return SimpleNamespace(authorization=SimpleNamespace(scope=lambda project: scope,
        require_current=lambda observed: current.append(observed)),
        verified_read_session=lambda **kw: nullcontext(), frozen_snapshot=read), reads, current


def request(before, after, **kwargs):
    return ImageCodeDeltaInput(project_id="project", before_image_revision_id=before[0].image_revision_id,
        before_image_hash=before[0].artifact_hash, after_image_revision_id=after[0].image_revision_id,
        after_image_hash=after[0].artifact_hash, **kwargs)


def test_stable_registered_ids_distinguish_revision_and_compatibility_projection():
    before, after = pair()
    delta = compare_code_members(*before, *after)
    assert delta.counts == {"added_member": 1, "removed_member": 1, "revision_changed": 1, "projection_changed": 1, "unchanged": 1}
    changes = {item.entity_id: item for item in delta.changes}
    assert changes["alias"].before.object_id == "old_alias" and changes["alias"].after.object_id == "new_alias"
    assert changes["alias"].kind == "projection_changed"
    assert changes["edit"].kind == "revision_changed"
    assert changes["removed"].after is None and changes["added"].before is None
    assert not any(getattr(delta, key) for key in ("source_scope_changed", "source_deletions_verified",
        "rename_lineage_transferred", "impact_complete", "approval_transferred", "execution_authorized"))
    assert delta == compare_code_members(*before, *after)
    same = compare_code_members(*before, *before)
    assert same.counts["unchanged"] == 4 and sum(same.counts.values()) == 4


def test_removing_source_scope_does_not_prove_deleted_code():
    sources = (SourceManifestMember("binding", "code", "source", "captured"),
               SourceManifestMember("other-binding", "code", "other-source", "captured"))
    before = image("before", [("one", "one", "one-v1", "source", "One"),
        ("two", "two", "two-v1", "other-source", "Two")], sources=sources)
    after = image("after", [("one", "one", "one-v1", "source", "One")])
    delta = compare_code_members(*before, *after)
    assert delta.source_scope_changed and delta.counts["removed_member"] == 1
    assert not delta.source_deletions_verified
    assert not compare_code_members(*image("empty", []), *image("empty", [])).changes


@pytest.mark.parametrize("change", ["project", "duplicate", "binding", "revision_scope", "tamper", "same_header"])
def test_ambiguous_or_inconsistent_identity_pins_fail_closed(change):
    before, after = pair()
    if change == "project":
        after = image("after", [("keep", "keep", "k1", "source", "Keep")], project="other")
    elif change == "duplicate":
        after = image("after", [("one", "keep", "k1", "source", "One"), ("two", "keep", "k1", "source", "Two")])
    elif change == "binding":
        after = image("after", [("keep", "keep", "k2", "other", "Keep")],
            sources=(SourceManifestMember("other-binding", "code", "other", "captured"),))
    elif change == "revision_scope":
        after = image("after", [("keep", "keep", "k1", "other", "Keep")],
            sources=(SourceManifestMember("binding", "code", "other", "captured"),))
    elif change == "same_header":
        after = (replace(after[0], image_revision_id=before[0].image_revision_id), after[1])
    else:
        after[1]["objects"][0]["name"] = "private tamper"
    with pytest.raises((ValueError, ImageRevisionIntegrityError)):
        compare_code_members(*before, *after)


def test_application_receipts_page_exact_pair_and_do_not_expose_labels():
    before, after = pair()
    images, reads, current = fake_images(before, after)
    service = ImageQueryToolApplicationService(images)
    query = request(before, after, limit=2)
    receipt, page = service.execute_with_observation(query)
    assert receipt.operation == "code_member_delta" and page.total == 5 and page.next_offset == 2
    assert reads == [("project", "before"), ("project", "after")] and len(current) == 2
    assert "provider label" not in receipt.model_dump_json() and "provider label" not in str(asdict(page))
    assert service.expand(receipt) == page
    filtered = service.execute_with_observation(request(before, after, kind="revision_changed"))[1]
    assert filtered.total == 1 and filtered.items[0].entity_id == "edit" and filtered.next_offset is None
    assert filtered.content_hash == page.content_hash
    empty = service.execute_with_observation(request(before, after, offset=5))[1]
    assert empty.total == 5 and not empty.items and empty.next_offset is None
    bad = receipt.model_copy(update={"result_hash": "sha256:" + "0" * 64})
    with pytest.raises(ImageRevisionIntegrityError, match="receipt"):
        service.expand(bad)
    assert ImageCodeDeltaReceipt.model_validate_json(receipt.model_dump_json()) == receipt


@pytest.mark.parametrize("change", [{"limit": True}, {"limit": 101}, {"limit": "1"}, {"offset": -1},
    {"offset": True}, {"kind": "deleted"}, {"file_path": "/private"}, {"before_image_hash": "latest"}])
def test_delta_requests_are_fixed_strict_and_bounded(change):
    before, after = pair()
    with pytest.raises(ValueError):
        ImageCodeDeltaInput.model_validate({**request(before, after).model_dump(), **change})


@pytest.mark.parametrize("change", [{"limit": True}, {"offset": -1}, {"kind": "deleted"},
    {"offset": 6}, {"before_image_hash": "sha256:" + "0" * 64}, {"after_image_revision_id": "missing"}])
def test_application_rejects_bad_pages_and_hashes(change):
    before, after = pair()
    images, _, _ = fake_images(before, after)
    with pytest.raises((ValueError, KeyError, ImageRevisionIntegrityError)):
        CodeMemberDeltaApplicationService(images).read(**{**request(before, after).model_dump(), **change})


@pytest.mark.parametrize("when", [1, 2])
def test_changed_authorization_discards_entire_result(when):
    before, after = pair()
    images, _, current = fake_images(before, after)
    def revoked(scope):
        current.append(scope)
        if len(current) == when:
            raise StaleSourceAccessScope("changed")
    images.authorization.require_current = revoked
    with pytest.raises(StaleSourceAccessScope):
        CodeMemberDeltaApplicationService(images).read(**request(before, after).model_dump())


def test_page_size_limit_never_truncates_evidence_ids():
    before = image("before", [("one", "one", "one-v1", "source", "One")])
    after = deepcopy(before)
    payload = after[1]
    payload["members"][0]["evidence_ids"] = [str(i) + "x" * 1000 for i in range(100)]
    after = (replace(after[0], image_revision_id="after", artifact_hash=snapshot_digest(payload),
        membership_hash=snapshot_digest(payload["members"])), payload)
    images, _, _ = fake_images(before, after)
    with pytest.raises(ImageRevisionPageTooLarge):
        CodeMemberDeltaApplicationService(images).read(**request(before, after).model_dump())
