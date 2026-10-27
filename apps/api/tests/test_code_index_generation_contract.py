from dataclasses import replace

import pytest

from apps.api.app.domain.system_image.code_index_generation import CodeIndexGenerationPin, CodeIndexLease
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest


def pin():
    metadata = dict(generation_id="cgen_example", project_id="project", binding_id="binding", source_revision_id="source",
        source_manifest_hash="sha256:" + "a" * 64, snapshot_hash="sha256:" + "b" * 64,
        provider_fingerprint="sha256:" + "c" * 64, invocation_id="invocation")
    return CodeIndexGenerationPin(**metadata, content_hash=snapshot_digest(metadata))


@pytest.mark.parametrize("key", ["generation_id", "project_id", "binding_id", "source_revision_id", "invocation_id",
                                 "source_manifest_hash", "snapshot_hash", "provider_fingerprint", "content_hash"])
def test_every_frozen_pin_field_participates_in_its_digest(key):
    value = pin()
    changed = "sha256:" + "d" * 64 if "hash" in key or key == "provider_fingerprint" else "changed"
    with pytest.raises(ValueError):
        replace(value, **{key: changed})


@pytest.mark.parametrize("changes", [{"epoch": True}, {"epoch": 0}, {"epoch": 1.5}, {"owner_id": ""}, {"owner_id": None}])
def test_invalid_worker_fence_cannot_be_constructed(changes):
    with pytest.raises(ValueError):
        replace(CodeIndexLease(pin(), 1, "worker"), **changes)
