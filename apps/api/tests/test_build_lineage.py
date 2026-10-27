from dataclasses import asdict, replace

import pytest

from apps.api.app.application.system_image.build_lineage import CodeExtractionReceipt, NativeCodeExecutionPin
from apps.api.app.application.system_image.build_lineage import LINEAGE_SCHEMA, validate_lineage_payload
from apps.api.app.application.system_image.source_ports import code_projection_payload
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.code_index_generation import CodeIndexGenerationPin
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.tests.test_code_observation_archives import received


def execution_pin():
    values = dict(generation_id="generation", project_id="project", binding_id="binding", source_revision_id="source",
        source_manifest_hash=snapshot_digest("manifest"), snapshot_hash=snapshot_digest("snapshot"),
        provider_fingerprint=snapshot_digest("provider"), invocation_id="invocation")
    generation = CodeIndexGenerationPin(**values, content_hash=snapshot_digest(values))
    return NativeCodeExecutionPin(generation, snapshot_digest("projection"), snapshot_digest("protocol"))


def test_execution_receipts_do_not_change_existing_projection_or_observation_digests():
    from apps.api.app.application.system_image.code_observations import received_code_observations
    manifest, projection, archived = received()
    pinned = replace(projection, execution_pin=execution_pin())
    assert code_projection_payload(pinned) == code_projection_payload(projection)
    assert received_code_observations(manifest, pinned) == archived
    assert "execution_pin" not in code_projection_payload(pinned)
    assert asdict(CodeExtractionReceipt("source", "analysis", snapshot_digest(code_projection_payload(pinned)), pinned.execution_pin))["native"]


@pytest.mark.parametrize("values", [("", "analysis"), ("source", ""), ("source", " " * 3),
                                    ("s" * 129, "analysis"), ("source\n", "analysis"), ("source", "a\x00")])
def test_invalid_extraction_receipt_identity_is_rejected(values):
    with pytest.raises(BuildPlanIntegrityError):
        CodeExtractionReceipt(*values, snapshot_digest("projection"))


@pytest.mark.parametrize("field", ["projection_hash", "protocol_hash"])
def test_native_execution_fingerprints_are_strict(field):
    with pytest.raises(ImageRevisionIntegrityError):
        replace(execution_pin(), **{field: "not-a-digest"})


def lineage_payload():
    return {"schema": LINEAGE_SCHEMA, "project_id": "project", "plan_id": "plan",
        "plan_digest": snapshot_digest("plan"), "target_baseline_id": "baseline", "invocation_id": "invocation",
        "executor_version": "executor", "image_revision_id": "image", "image_artifact_hash": snapshot_digest("image"),
        "manifest_id": "manifest", "manifest_hash": snapshot_digest("manifest"), "analyses": [{
            "binding_id": "binding", "source_revision_id": "source", "analysis_id": "analysis",
            "report_hash": snapshot_digest("report"), "observation_archive_hash": snapshot_digest("archive"),
            "merged_projection_hash": snapshot_digest("projection"), "native": None, "unused_native_generations": []}]}


@pytest.mark.parametrize("native_kind", ["none", "consumed", "unused"])
def test_complete_lineage_envelope_accepts_only_the_fixed_native_receipt_shape(native_kind):
    payload = lineage_payload()
    analysis = payload["analyses"][0]
    if native_kind == "consumed":
        analysis["native"] = asdict(execution_pin())
    elif native_kind == "unused":
        analysis["unused_native_generations"] = [asdict(execution_pin().generation)]
    validate_lineage_payload(payload)


@pytest.mark.parametrize("damage", ["root_missing", "root_extra", "root_digest", "source_missing", "source_extra",
    "source_identity", "source_digest", "duplicate", "empty", "native_extra", "native_digest", "native_generation",
    "unused_generation", "unused_many", "consumed_and_unused"])
def test_corrupt_lineage_schema_is_a_typed_integrity_failure(damage):
    payload = lineage_payload()
    item = payload["analyses"][0]
    if damage == "root_missing":
        del payload["manifest_id"]
    elif damage == "root_extra":
        payload["storage_ref"] = "private"
    elif damage == "root_digest":
        payload["plan_digest"] = "broken"
    elif damage == "source_missing":
        del item["native"]
    elif damage == "source_extra":
        item["unexpected"] = "private"
    elif damage == "source_identity":
        item["binding_id"] = "binding\n"
    elif damage == "source_digest":
        item["observation_archive_hash"] = "broken"
    elif damage == "duplicate":
        payload["analyses"].append(dict(item))
    elif damage == "empty":
        payload["analyses"] = []
    elif damage.startswith("native_"):
        item["native"] = asdict(execution_pin())
        if damage == "native_extra":
            item["native"]["private"] = "unexpected"
        elif damage == "native_digest":
            item["native"]["projection_hash"] = "broken"
        else:
            item["native"]["generation"]["content_hash"] = snapshot_digest("substitute")
    else:
        pin = asdict(execution_pin().generation)
        item["unused_native_generations"] = [pin]
        if damage == "unused_generation":
            pin["content_hash"] = "broken"
        elif damage == "unused_many":
            item["unused_native_generations"].append(dict(pin))
        else:
            item["native"] = asdict(execution_pin())
    with pytest.raises(BuildPlanIntegrityError, match="invalid schema"):
        validate_lineage_payload(payload)
