from dataclasses import dataclass, replace

import pytest

from apps.api.app.domain.system_image.context_pack import ContextPackIntegrityError
from apps.api.app.domain.system_image.context_provenance import (
    ANCHOR_FIELDS, CONTEXT_PROVENANCE_POLICY, ContextProvenanceAnchor,
)
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def anchor():
    return ContextProvenanceAnchor("project", "context", snapshot_digest("registration"), "image",
        snapshot_digest("image"), snapshot_digest("ancestry"), "manifest", snapshot_digest("manifest"),
        snapshot_digest("input"), snapshot_digest("query"))


def test_bridge_has_explicit_version_and_keeps_future_fields_out_of_v1_hash():
    original = anchor()

    @dataclass(frozen=True)
    class FutureAnchor(ContextProvenanceAnchor):
        future_metadata: str = "not part of the historical v1 formula"

    future = FutureAnchor(**original.payload_v1)
    assert future.record_v1 == original.record_v1
    assert original.content_hash == snapshot_digest({"policy_revision": CONTEXT_PROVENANCE_POLICY, **original.payload_v1})
    assert original.record_v1["context_node_key"] == "context:context"
    assert original.record_v1["image_node_key"] == "image_objects:image"


@pytest.mark.parametrize("field", ANCHOR_FIELDS)
def test_every_fixed_pin_participates_in_bridge_hash(field):
    original = anchor()
    changed = replace(original, **{field: "different" if field in
        {"project_id", "context_id", "image_revision_id", "manifest_id"} else snapshot_digest("different")})
    assert changed.content_hash != original.content_hash


@pytest.mark.parametrize("field", ANCHOR_FIELDS)
@pytest.mark.parametrize("value", [None, "", 1])
def test_invalid_identity_or_digest_is_rejected(field, value):
    with pytest.raises(ContextPackIntegrityError):
        replace(anchor(), **{field: value})
