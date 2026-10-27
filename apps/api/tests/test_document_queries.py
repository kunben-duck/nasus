from types import SimpleNamespace
import json
import pytest

from apps.api.app.application.system_image.document_queries import DocumentQueryApplicationService
from apps.api.app.domain.system_image.document_projection import DocumentObservation, DocumentField
from apps.api.app.domain.system_image.evidence import text_digest
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError


def test_long_fields_are_byte_paginated_without_truncation_or_unrelated_field_evidence():
    values = [character * 30000 for character in ("a", "b", "c")]
    text = "\n".join(values) + "\n"
    observation = DocumentObservation("requirement", "Long requirement", "US-LONG", "requirements.md", 1, 3,
        tuple(DocumentField("description", value, i, i) for i, value in enumerate(values, 1)))
    payload = {**observation.payload(text, text_digest(text)), "project_id": "project", "source_manifest_hash": "manifest"}
    digest = snapshot_digest(payload)
    header = {"project_id": "project", "title": observation.title, "kind": observation.kind, "source_manifest_hash": "manifest"}
    evidence = [{"evidence_id": "whole", "start_line": 1, "end_line": 3, "snippet_hash": payload["snippet_hash"]}]
    evidence += [{"evidence_id": f"field-{index}", "start_line": field["start_line"], "end_line": field["end_line"],
                  "snippet_hash": field["snippet_hash"]} for index, field in enumerate(payload["fields"])]
    checks = []
    service = DocumentQueryApplicationService(
        SimpleNamespace(get=lambda *args, **kwargs: (header, "ref", digest, evidence)),
        SimpleNamespace(read=lambda *args: payload),
        SimpleNamespace(scope=lambda project: SimpleNamespace(binding_ids=frozenset({"binding"})),
                        require_current=lambda scope: checks.append(scope)))
    offset, seen = 0, []
    while offset is not None:
        page = service.read("project", "document", offset=offset, limit=20)
        assert len(json.dumps(page, ensure_ascii=False).encode()) <= 65536
        assert page["fields"] and page["total_fields"] == 3
        seen.extend(field["value"] for field in page["fields"])
        assert {item["evidence_id"] for item in page["evidence"]} == {"whole", *(
            f"field-{field['start_line'] - 1}" for field in page["fields"])}
        offset = page["next_offset"]
    assert seen == values and len(checks) == 4


@pytest.mark.parametrize("parent_source", [None, "another-source"])
def test_frozen_component_query_cannot_read_a_parent_outside_membership(parent_source, monkeypatch):
    member = {"object_id": "component", "kind": "source_document", "document_revision_id": "ac-rev",
              "source_revision_id": "source", "evidence_ids": ["evidence"]}
    parent = {"object_id": "parent", "kind": "source_document", "document_revision_id": "parent-rev",
              "source_revision_id": parent_source}
    page = {"document": {"document_revision_id": "ac-rev", "source_revision_id": "source",
                         "parent_document_revision_id": "parent-rev"}, "evidence": []}
    authorization = SimpleNamespace(scope=lambda project: None, require_current=lambda scope: None)
    service = ImageRevisionQueryApplicationService(None, None, authorization,
        documents=SimpleNamespace(read=lambda *args, **kwargs: page))
    monkeypatch.setattr(service, "_verified_payload", lambda *args: (None,
        {"members": [member, parent] if parent_source else [member]}))
    with pytest.raises(ImageRevisionIntegrityError, match="parent is outside"):
        service.read_document("project", "image", "component")
