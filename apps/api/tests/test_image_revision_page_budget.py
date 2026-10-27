"""Real frozen semantic payloads retain the HTTP/query byte-budget contract."""
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.image_query_models import ImagePageInput
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.domain.system_image.image_revision import build_image_artifact, ImageRevisionPageTooLarge
from apps.api.app.domain.system_image.semantic_membership import (
    ImageSemanticMember, build_semantic_artifact, semantic_membership_digest,
)
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.domain.system_image.source_access import SourceAccessScope
from apps.api.tests.test_image_revision import candidate
from apps.api.tests.test_semantic_membership import frozen


def semantic_pages():
    _, summary, original, _ = frozen()
    manifest, objects, relationships = candidate()
    objects.append({"id": "requirement", "name": "Requirement", "document_reference": {
        "document_revision_id": "requirement-v1", "source_revision_id": "source-revision"}})
    for index in range(25):
        objects.append({"id": f"test-{index:02}", "name": f"Test {index}", "document_reference": {
            "document_revision_id": f"test-{index:02}-v1", "source_revision_id": "source-revision"}})
    parent, _ = build_image_artifact(manifest, "baseline", objects, relationships)
    for member in parent["members"]:
        if member["kind"] == "source_document":
            member["evidence_ids"] = [member["object_id"] + "-evidence"]
    selected = []
    for index in range(25):
        assertion = replace(original.assertion, subject_object_id=f"test-{index:02}",
            subject_revision_id=f"test-{index:02}-v1", subject_evidence_ids=(f"test-{index:02}-evidence",))
        decision = replace(original.decision, decision_id=f"review-{index}", claim_id=assertion.claim_id,
            assertion_id=assertion.assertion_id, assertion_digest=assertion.digest, reason="\u6d4b\u8bd5\U0001f642" * 650)
        selected.append(ImageSemanticMember(assertion, decision))
    payload = build_semantic_artifact(parent, "parent", snapshot_digest(parent), tuple(selected))
    summary = replace(summary, parent_revision_id="parent", parent_artifact_hash=snapshot_digest(parent),
        artifact_hash=snapshot_digest(payload), object_count=len(objects), assertion_count=len(selected),
        membership_hash=semantic_membership_digest(payload["members"], [], payload["semantic_assertion_members"]))
    calls = []
    authorization = SimpleNamespace(
        scope=lambda project_id: SourceAccessScope(project_id, "page-reviewer", "project_admin", 0,
            frozenset({"binding"}), frozenset({"source"}), "page-fixture-scope", False),
        require_current=lambda _: calls.append("authorize"),
    )
    service = ImageRevisionQueryApplicationService(
        SimpleNamespace(get=lambda *_: (summary, "private-archive", frozenset({"binding"}))),
        SimpleNamespace(read=lambda *_: payload), authorization)
    return service, payload, summary, calls


def test_long_unicode_reviews_require_smaller_pages_without_losing_frozen_members():
    service, payload, summary, calls = semantic_pages()
    kwargs = {"section": "semantic_assertion_members"}
    with pytest.raises(ImageRevisionPageTooLarge):
        service.read("project", summary.image_revision_id, **kwargs, limit=25)
    offset, collected = 0, []
    while offset is not None:
        page = service.read("project", summary.image_revision_id, **kwargs, offset=offset, limit=3)
        assert len(json.dumps(asdict(page), ensure_ascii=False).encode("utf-8")) <= 65536
        assert page.total == 25 and page.items
        collected.extend(page.items)
        offset = page.next_offset
    assert collected == payload["semantic_assertion_members"]
    assert len({item["decision"]["claim_id"] for item in collected}) == 25
    assert calls[-1] == "authorize"


def test_small_page_receipt_replays_identical_full_reviews_without_storing_reason():
    service, _, summary, _ = semantic_pages()
    tools = ImageQueryToolApplicationService(service)
    selection = ImagePageInput(project_id="project", image_revision_id=summary.image_revision_id,
        section="semantic_assertion_members", offset=3, limit=3)
    receipt = tools.execute(selection)
    assert receipt.next_offset == 6 and len(receipt.item_ids) == 3
    assert "reason" not in receipt.model_dump_json() and "private-archive" not in receipt.model_dump_json()
    assert tools.expand(receipt) == service.read("project", summary.image_revision_id,
        section="semantic_assertion_members", offset=3, limit=3)
