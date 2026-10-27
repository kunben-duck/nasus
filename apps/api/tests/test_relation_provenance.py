from dataclasses import dataclass, replace

import pytest

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.relation_provenance import RELATION_PROVENANCE_POLICY, RelationProvenanceNode
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


HASH = "sha256:" + "1" * 64


def root():
    return RelationProvenanceNode("project", "image_relations", "image", HASH, HASH,
        ("object_pin:image_objects:image", "relation_member:image/semantic/claim"))


def test_explicit_v1_digest_ignores_future_dataclass_fields():
    node = root()
    expected = {key: getattr(node, key) for key in ("project_id", "kind", "artifact_id", "artifact_hash",
        "metadata_hash", "parents", "object_node_key", "object_node_hash")}
    assert node.content_hash == snapshot_digest({"policy_revision": RELATION_PROVENANCE_POLICY, **expected})

    @dataclass(frozen=True)
    class Future(RelationProvenanceNode):
        future_label: str = "not a v1 field"

    assert Future(**expected).content_hash == node.content_hash
    assert Future(**expected, future_label="changed").content_hash == node.content_hash


@pytest.mark.parametrize("change", [{"project_id": "other"}, {"artifact_id": "other"},
    {"artifact_hash": "sha256:" + "2" * 64}, {"metadata_hash": "sha256:" + "2" * 64},
    {"parents": ("object_pin:image_objects:image",)}])
def test_each_real_v1_pin_changes_the_registration(change):
    assert replace(root(), **change).content_hash != root().content_hash


@pytest.mark.parametrize("change", [{"kind": "approved"}, {"project_id": ""}, {"artifact_hash": "bad"},
    {"metadata_hash": "bad"}, {"parents": []}, {"parents": ()}, {"parents": ("object_pin:a", "object_pin:a")},
    {"parents": ("relation_member:a", "object_pin:a")}, {"parents": ("image_relations:image",)},
    {"parents": ("object_pin:a", "run:executed")}, {"object_node_key": "image_objects:image"},
    {"object_node_hash": HASH}])
def test_malformed_or_authority_like_nodes_are_rejected(change):
    with pytest.raises((ImageRevisionIntegrityError, ValueError)):
        replace(root(), **change)


@pytest.mark.parametrize("kind", ["reference_decision", "semantic_decision"])
def test_predecessor_is_optional_but_only_one_same_kind_predecessor_is_permitted(kind):
    assertion_kind = kind.replace("decision", "assertion")
    base = RelationProvenanceNode("project", kind, "decision", HASH, HASH, (assertion_kind + ":assertion",))
    predecessor = tuple(sorted((assertion_kind + ":assertion", kind + ":previous")))
    assert replace(base, parents=predecessor).content_hash != base.content_hash
    with pytest.raises(ImageRevisionIntegrityError):
        replace(base, parents=tuple(sorted((*predecessor, kind + ":other"))))


def test_native_pin_is_exact_and_cannot_borrow_other_kind_or_hash():
    node = RelationProvenanceNode("project", "object_pin", "member:image/object", HASH, HASH, (),
        "member:image/object", HASH)
    assert node.key == "object_pin:member:image/object"
    for change in ({"object_node_hash": "sha256:" + "2" * 64}, {"object_node_key": None},
                   {"artifact_id": "source:revision", "object_node_key": "source:revision"},
                   {"parents": ("object_pin:member:image/other",)}):
        with pytest.raises(ImageRevisionIntegrityError):
            replace(node, **change)
