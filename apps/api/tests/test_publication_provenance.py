from dataclasses import asdict, replace

import pytest

from apps.api.app.domain.system_image.publication import PublicationIntegrityError
from apps.api.app.domain.system_image.publication_provenance import PublicationProvenanceAnchor
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


H = "sha256:" + "1" * 64


def anchor():
    return PublicationProvenanceAnchor("project", "publication", "publication", "baseline", "image", H,
        "manifest", H, 1, H, H, "invocation", H, H, (("approval", "review", "review", H),))


def test_publication_anchor_freezes_metadata_and_exact_parent_hashes():
    value = anchor()
    record = value.record_v1
    assert record["dependencies_hash"] == snapshot_digest(value.dependencies)
    assert record["content_hash"] == snapshot_digest({k: v for k, v in record.items() if k != "content_hash"})
    assert record["publication_id"] == "publication" and record["review_id"] is None
    assert "authority" not in record and "status" not in record
    for key in asdict(value):
        if key == "dependencies":
            changed = replace(value, dependencies=(("approval", "review", "review", "sha256:" + "2" * 64),))
        elif key == "kind":
            continue
        else:
            item = getattr(value, key)
            changed = replace(value, **{key: item + 1 if type(item) is int else
                "sha256:" + "2" * 64 if key.endswith("hash") else item + "-changed"})
        assert changed.record_v1["content_hash"] != record["content_hash"], key


@pytest.mark.parametrize("changes", [
    {"kind": "release"}, {"sequence": True}, {"sequence": 0}, {"project_id": ""},
    {"metadata_hash": "not-a-hash"}, {"dependencies": []},
    {"dependencies": (("approval", "publication", "other", H),)},
    {"dependencies": (("previous_review", "review", "other", H),)},
    {"dependencies": (("previous_publication", "publication", "publication", H),)},
    {"dependencies": (("approval", "review", "other", "invalid"),)},
    {"dependencies": (("approval", "review", "r1", H), ("approval", "review", "r2", H))},
    {"dependencies": (("rollback_source", "publication", "old", H), ("approval", "review", "r", H))},
    {"dependencies": ((),)}, {"dependencies": (("approval",),)},
    {"dependencies": (None,)}, {"dependencies": ((None, "review", "r", H),)},
    {"dependencies": (["approval", "review", "r", H],)},
    {"dependencies": (("approval", "review", "r", H, "extra"),)},
])
def test_publication_anchor_rejects_invalid_pins(changes):
    with pytest.raises(PublicationIntegrityError):
        replace(anchor(), **changes)
