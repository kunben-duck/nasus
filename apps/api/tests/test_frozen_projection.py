from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.domain.system_image.frozen_projection import require_frozen_projection
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.materialization import InsufficientSystemImageEvidenceError
from apps.api.app.domain.system_image.source_snapshots import (
    CapturedSourceManifest, SourceManifestMember, snapshot_digest,
)


def manifest(*members):
    values = members or (SourceManifestMember("code", "code", "source-code", "captured"),)
    return CapturedSourceManifest("manifest", "project",
        snapshot_digest([asdict(item) for item in sorted(values, key=lambda m: m.binding_id)]), "now", tuple(values))


def code_object(ident="code-object", revision="source-code"):
    return SimpleNamespace(id=ident, evidence=["evidence:code"], document_reference=None,
        code_reference=SimpleNamespace(entity_id="entity", entity_revision_id="entity-revision", source_revision_id=revision))


def document_object():
    return SimpleNamespace(id="document", evidence=["evidence:document"], code_reference=None,
        document_reference=SimpleNamespace(document_revision_id="document-revision", source_revision_id="source-doc"))


def metric(**changes):
    return SimpleNamespace(**{"project_id": "project", "baseline_id": "baseline",
        "metric_group": "code_quality", "evidence_refs": ["source:code"], **changes})


def relationship(**changes):
    return SimpleNamespace(**{"id": "edge", "project_id": "project", "baseline_id": "baseline",
        "from_object_id": "code-object", "to_object_id": "second", "source_refs": ["evidence:code"], **changes})


def validate(objects=None, relationships=(), metrics=None, source_manifest=None):
    return require_frozen_projection(source_manifest or manifest(), "baseline",
        objects=[code_object()] if objects is None else objects,
        relationships=relationships, metrics=[metric()] if metrics is None else metrics)


def test_manifest_is_the_root_and_zero_edges_are_valid():
    result = validate()
    assert result.ready and result.object_count == 1 and result.relationship_count == 0


def test_optional_failed_source_stays_explicit_without_becoming_a_fake_member():
    frozen = manifest(SourceManifestMember("code", "code", "source-code", "captured"),
        SourceManifestMember("doc", "us_doc", None, "failed"))
    assert validate(source_manifest=frozen).ready


@pytest.mark.parametrize("changes", [{"code_reference": None}, {"evidence": []},
    {"evidence": ["seeded-fixture"]}, {"id": ""}, {"document_reference": document_object().document_reference}])
def test_unpinned_or_synthetic_objects_fail_closed(changes):
    item = code_object()
    for key, value in changes.items():
        setattr(item, key, value)
    with pytest.raises(ImageRevisionIntegrityError):
        validate([item])


@pytest.mark.parametrize("changes", [{"entity_id": ""}, {"entity_revision_id": ""},
    {"source_revision_id": "foreign"}])
def test_incomplete_code_pins_are_not_replaced_by_names_or_counts(changes):
    item = code_object()
    for key, value in changes.items():
        setattr(item.code_reference, key, value)
    with pytest.raises(ImageRevisionIntegrityError):
        validate([item])


def test_document_and_code_sources_cannot_be_interchanged():
    frozen = manifest(SourceManifestMember("code", "code", "source-code", "captured"),
        SourceManifestMember("doc", "us_doc", "source-doc", "captured"))
    assert validate([code_object(), document_object()], source_manifest=frozen).object_count == 2
    with pytest.raises(ImageRevisionIntegrityError):
        validate([code_object(revision="source-doc")], source_manifest=frozen)
    doc = document_object()
    doc.document_reference.source_revision_id = "source-code"
    with pytest.raises(ImageRevisionIntegrityError):
        validate([code_object(), doc], source_manifest=frozen)


@pytest.mark.parametrize("changes", [{"project_id": "other"}, {"baseline_id": "other"},
    {"from_object_id": "invented-root"}, {"to_object_id": "outside"}, {"source_refs": []},
    {"source_refs": ["system-image:fallback"]}])
def test_edges_must_be_closed_over_the_exact_projection(changes):
    with pytest.raises(ImageRevisionIntegrityError):
        validate([code_object(), code_object("second")], relationships=[relationship(**changes)])


def test_duplicate_objects_and_relationships_are_not_counted_twice():
    with pytest.raises(ImageRevisionIntegrityError):
        validate([code_object(), code_object()])
    with pytest.raises(ImageRevisionIntegrityError):
        validate([code_object(), code_object("second")], relationships=[relationship(), relationship()])


@pytest.mark.parametrize("changes", [{"project_id": "other"}, {"baseline_id": "other"},
    {"evidence_refs": []}, {"evidence_refs": ["synthetic-fixture"]}])
def test_metrics_cannot_smuggle_another_scope_or_fixture(changes):
    with pytest.raises(ImageRevisionIntegrityError):
        validate(metrics=[metric(**changes)])


def test_missing_code_or_code_metric_blocks_delivery_not_by_inventing_a_root():
    for kwargs in ({"objects": []}, {"metrics": []}, {"metrics": [metric(metric_group="test_quality")]}):
        with pytest.raises(InsufficientSystemImageEvidenceError):
            validate(**kwargs)


def test_corrupt_or_duplicate_manifest_revisions_are_rejected():
    with pytest.raises(ImageRevisionIntegrityError):
        validate(source_manifest=replace(manifest(), content_hash="sha256:" + "0" * 64))
    with pytest.raises(ImageRevisionIntegrityError):
        validate(source_manifest=manifest(SourceManifestMember("code", "code", "source-code", "captured"),
            SourceManifestMember("other", "code", "source-code", "captured")))
