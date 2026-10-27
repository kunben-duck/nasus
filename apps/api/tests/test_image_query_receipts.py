from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.image_query_models import ImagePageInput, ImageDocumentInput
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionPage
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge, build_image_artifact
from apps.api.tests.test_image_revision import candidate, header
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def test_legacy_image_receipt_hash_survives_additive_v2_header_fields():
    payload, _ = build_image_artifact(candidate()[0], "baseline", *candidate()[1:])
    page = ImageRevisionPage(header(payload), "members", tuple(payload["members"]), 2, None)
    historical = asdict(page)
    for key in ("parent_revision_id", "parent_artifact_hash", "assertion_count"):
        historical["revision"].pop(key)
    service = ImageQueryToolApplicationService(SimpleNamespace(read=lambda **kwargs: page))
    receipt = service.execute(ImagePageInput(project_id="project", image_revision_id="image", section="members"))
    assert receipt.result_hash == snapshot_digest(historical)
    assert service.expand(receipt) == page


def test_receipt_has_a_separate_serialized_size_limit():
    payload, _ = build_image_artifact(candidate()[0], "baseline", *candidate()[1:])
    # A misbehaving query port cannot make the durable event payload unbounded.
    oversized = ImageRevisionPage(header(payload), "objects", tuple({"id": "x" * 1000} for _ in range(100)), 100, None)
    queries = SimpleNamespace(read=lambda **kwargs: oversized)
    service = ImageQueryToolApplicationService(queries)
    with pytest.raises(ImageRevisionPageTooLarge, match="receipt"):
        service.execute(ImagePageInput(project_id="project", image_revision_id="image", limit=100))


def test_member_receipt_replay_cannot_replace_frozen_evidence_handles():
    payload, _ = build_image_artifact(candidate()[0], "baseline", *candidate()[1:])
    payload["members"][0]["evidence_ids"] = ["frozen-evidence"]
    page = ImageRevisionPage(header(payload), "members", tuple(payload["members"]), 2, None)
    service = ImageQueryToolApplicationService(SimpleNamespace(read=lambda **kwargs: page))
    request = ImagePageInput(project_id="project", image_revision_id="image", section="members")
    receipt = service.execute(request)
    assert receipt.frozen_members[0].evidence_ids == ("frozen-evidence",)
    assert service.expand(receipt) == page
    changed = receipt.model_copy(update={"frozen_members": [replace(receipt.frozen_members[0], evidence_ids=("new-evidence",))]})
    with pytest.raises(ImageRevisionIntegrityError, match="receipt"):
        service.expand(changed)


def test_document_receipt_contains_no_fields_and_replay_checks_bodies_and_pins():
    page = {"document": {"document_revision_id": "document-v1", "source_revision_id": "source-v1"},
            "payload_hash": "sha256:" + "a" * 64, "projection": {"kind": "requirement"},
            "fields": [{"name": "description", "value": "untrusted requirement text"}],
            "total_fields": 2, "next_offset": 1, "evidence": [{"evidence_id": "evidence-v1"}]}
    service = ImageQueryToolApplicationService(SimpleNamespace(read_document=lambda **kwargs: page))
    receipt = service.execute(ImageDocumentInput(project_id="project", image_revision_id="image", object_id="document", limit=1))
    assert receipt.operation == "document" and receipt.next_offset == 1
    assert receipt.evidence_ids == ["evidence-v1"]
    assert "untrusted" not in receipt.model_dump_json() and "description" not in receipt.model_dump_json()
    assert service.expand(receipt).fields == tuple(page["fields"])
    for changed in (receipt.model_copy(update={"document_revision_id": "different-document"}),
                    receipt.model_copy(update={"evidence_ids": ["unfrozen-evidence"]})):
        with pytest.raises(ImageRevisionIntegrityError, match="receipt"):
            service.expand(changed)
    page["fields"][0]["value"] = "changed after receipt"
    with pytest.raises(ImageRevisionIntegrityError, match="receipt"):
        service.expand(receipt)


@pytest.mark.parametrize("changed", [{"offset": True}, {"offset": -1}, {"limit": 91}, {"limit": "1"}, {"source_uri": "/tmp/private"}])
def test_document_query_requires_strict_bounded_input(changed):
    with pytest.raises(ValueError):
        ImageDocumentInput.model_validate({"project_id": "project", "image_revision_id": "image", "object_id": "document", **changed})
