from dataclasses import replace

import pytest

from apps.api.app.domain.quality_loop.acceptance_specification import AcceptanceIntegrityError, acceptance_digest
from apps.api.app.domain.quality_loop.authority_provenance import AuthorityProvenanceAnchor


def anchor(**changes):
    value = AuthorityProvenanceAnchor("project", "acceptance", "revision", "ac", "sha256:" + "1" * 64,
        "sha256:" + "2" * 64, "image", "sha256:" + "3" * 64, "object", "binding", "source", "document",
        "sha256:" + "4" * 64, "invocation", "approved", 1, "sha256:" + "5" * 64,
        "sha256:" + "6" * 64, "sha256:" + "7" * 64, None, None)
    return replace(value, **changes)


def test_typed_authority_source_pins_and_predecessors_have_independent_stable_hashes():
    first = anchor()
    value = first.record_v1
    assert value["content_hash"] == "sha256:8914bcc00d63d254569c7faff342202ab4e6085db501e7086cc0992c36ad4b06"
    assert value["content_hash"] == acceptance_digest({k: v for k, v in value.items() if k != "content_hash"})
    assert value["acceptance_revision_id"] == "revision" and value["business_rule_revision_id"] is None
    assert value["member_node_key"] == "member:image/object" and value["document_node_key"] == "document:document"
    assert anchor(kind="business_rule").record_v1["content_hash"] != value["content_hash"]
    second = anchor(revision_id="second", status="withdrawn", sequence=2, previous_revision_id="revision",
        previous_registration_hash=value["content_hash"])
    assert second.record_v1["previous_registration_hash"] == value["content_hash"]
    assert first.record_v1 == value


@pytest.mark.parametrize("changes", [
    {"kind": "model_inferred"}, {"status": "proposed"}, {"sequence": True}, {"sequence": 1001},
    {"sequence": 2}, {"previous_revision_id": "other"}, {"previous_registration_hash": "sha256:" + "0" * 64},
    {"status": "withdrawn"}, {"metadata_hash": "sha256:" + "f" * 63}, {"image_provenance_hash": "private-body"},
    {"sequence": 2, "previous_revision_id": "revision", "previous_registration_hash": "sha256:" + "0" * 64},
])
def test_invalid_source_and_authority_lineage_pins_are_rejected(changes):
    with pytest.raises(AcceptanceIntegrityError):
        anchor(**changes)
