from copy import deepcopy

import pytest

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.retrieval_provenance import retrieval_registration


HASH = "sha256:" + "a" * 64


def arguments():
    return dict(project_id="project", kind="generation", artifact_id="index", metadata_hash=HASH,
        publication_pin=dict(baseline_id="baseline", publication_id="publication", image_revision_id="image",
            image_artifact_hash=HASH), publication_registration_hash=HASH,
        parent=("reservation", "index", HASH), documents=(("doc", HASH, HASH),))


def test_registration_is_deterministic_and_does_not_carry_text_or_authority():
    value = arguments()
    original = deepcopy(value)
    record = retrieval_registration(**value)
    assert value == original and record == retrieval_registration(**value)
    assert record["document_count"] == 1 and record["parent_kind"] == "reservation"
    assert not {"text", "query", "oracle", "quality_generation_authorized", "release_authorized"} & record.keys()
    assert record["content_hash"].startswith("sha256:")
    for field, replacement in (("metadata_hash", "sha256:" + "b" * 64),
                               ("publication_registration_hash", "sha256:" + "b" * 64),
                               ("parent", ("reservation", "index", "sha256:" + "b" * 64)),
                               ("documents", (("doc", HASH, "sha256:" + "b" * 64),))):
        assert retrieval_registration(**{**value, field: replacement})["content_hash"] != record["content_hash"]


@pytest.mark.parametrize("change", [
    {"documents": ()}, {"documents": []}, {"documents": (("doc", HASH, HASH), ("doc", HASH, HASH))},
    {"documents": (("z", HASH, HASH), ("a", HASH, HASH))}, {"documents": (("doc", "bad", HASH),)},
    {"parent": None}, {"parent": ("retrieval", "trace", HASH)}, {"metadata_hash": "bad"},
    {"kind": "script"}, {"project_id": ""}, {"parent": ("reservation", "index", "bad")},
    {"kind": []}, {"publication_pin": None}, {"publication_pin": {}},
    {"publication_pin": {"baseline_id": "baseline"}}, {"documents": (("", HASH, HASH),)},
    {"documents": (("x" * 129, HASH, HASH),)},
])
def test_incomplete_or_ambiguous_dependencies_are_rejected(change):
    with pytest.raises(ImageRevisionIntegrityError):
        retrieval_registration(**{**arguments(), **change})


def test_only_generation_has_document_dependencies_and_parent_kind_is_fixed():
    value = arguments()
    reservation = retrieval_registration(**{**value, "kind": "reservation", "parent": None, "documents": ()})
    trace = retrieval_registration(**{**value, "kind": "retrieval", "artifact_id": "trace",
        "parent": ("generation", "index", reservation["content_hash"]), "documents": ()})
    assert reservation["parent_id"] is None and trace["parent_id"] == "index"
    for kind in ("reservation", "retrieval"):
        with pytest.raises(ImageRevisionIntegrityError):
            retrieval_registration(**{**value, "kind": kind})
