from dataclasses import asdict, dataclass, replace

import pytest

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.object_provenance import ObjectProvenanceNode, OBJECT_PROVENANCE_POLICY
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def node(**kwargs):
    return ObjectProvenanceNode(**{"project_id": "project", "kind": "code", "artifact_id": "revision",
        "artifact_hash": "sha256:" + "a" * 64, "metadata_hash": "sha256:" + "b" * 64,
        "source_pins": (("binding", "source-revision"),), "parents": ("source:source-revision",), **kwargs})


def test_provenance_identity_and_registration_hash_include_the_exact_scope():
    value = node()
    assert value.key == "code:revision"
    assert value == node() and value.content_hash == node().content_hash
    for field, changed in (("project_id", "foreign"), ("metadata_hash", "sha256:" + "c" * 64),
                           ("source_pins", (("another", "source-revision"),))):
        assert replace(value, **{field: changed}).content_hash != value.content_hash
    assert replace(value, source_pins=(("binding", "other"),), parents=("source:other",)).content_hash != value.content_hash


@pytest.mark.parametrize("changed", [
    {"kind": "semantic_authority"}, {"project_id": ""}, {"artifact_hash": "wrong"},
    {"source_pins": ()}, {"source_pins": (["binding", "revision"],)},
    {"source_pins": (("binding", "revision"), ("binding", "revision"))},
    {"parents": (None,)}, {"parents": ("source:",)}, {"parents": ("source:two", "source:one")},
    {"parents": ()}, {"parents": ("code:revision",)}, {"parents": ("image_objects:image",)},
    {"kind": "image_objects", "parents": ("manifest:manifest",)},
    {"kind": "document", "parents": ("document:one", "document:two", "source:revision")},
    {"parents": ("source:other",)}, {"kind": "source", "parents": ()},
    {"kind": "member", "parents": ("code:one", "code:two")},
])
def test_provenance_refuses_bad_or_semantic_execution_ancestors(changed):
    with pytest.raises(ImageRevisionIntegrityError):
        node(**changed)


def test_negative_manifest_scope_and_unverified_legacy_members_are_not_invented_sources():
    manifest = node(kind="manifest", artifact_id="manifest", source_pins=(), parents=())
    legacy = node(kind="member", artifact_id="image/legacy", source_pins=(), parents=())
    assert manifest.parents == legacy.parents == ()
    root = node(kind="image_objects", artifact_id="image", source_pins=(),
        parents=("manifest:manifest", "member:image/legacy"))
    assert root.key == "image_objects:image"


@pytest.mark.parametrize("value", [
    node(), node(kind="source", artifact_id="source-revision", parents=()),
    node(kind="document", parents=("document:requirement", "source:source-revision")),
    node(kind="evidence"), node(kind="member", parents=("code:revision", "evidence:exact")),
    node(kind="manifest", parents=("source:source-revision",)),
    node(kind="member", source_pins=(), parents=()),
    node(kind="image_objects", artifact_id="image", parents=("manifest:manifest", *tuple(f"member:{i:04}" for i in range(730)))),
    node(project_id="project-\u4e2d\u6587-\U0001f986", artifact_id="quoted-\"-\\-\n-\u4e2d\u6587"),
])
def test_v1_digest_is_byte_identical_to_the_original_dataclass_formula(value):
    original = snapshot_digest({"policy_revision": OBJECT_PROVENANCE_POLICY, **asdict(value)})
    assert value.content_hash == original

    @dataclass(frozen=True)
    class FutureNode(ObjectProvenanceNode):
        future_metadata: str = "not a v1 field"

    extended = FutureNode(**asdict(value))
    assert extended.content_hash == original
    assert snapshot_digest({"policy_revision": OBJECT_PROVENANCE_POLICY, **asdict(extended)}) != original
