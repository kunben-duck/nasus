from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.api.app.domain.system_image.context_pack import CONTEXT_SCHEMA, ContextPackIntegrityError, canonical_bytes
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.system_image.context_pack_artifacts import ContextPackArtifacts


def test_context_artifact_requires_exact_namespace_and_verified_bounded_bytes():
    storage = Mock(config=SimpleNamespace(bucket="private-test"))
    artifacts = ContextPackArtifacts(storage)
    payload = {"schema": CONTEXT_SCHEMA, "project_id": "project", "source_text": "Private requirement"}
    digest = snapshot_digest(payload)
    ref = "s3://private-test/" + artifacts._key("project", digest)
    storage.put_bytes.return_value = SimpleNamespace(storage_ref=ref, content_hash=digest)
    storage.get_bytes.return_value = canonical_bytes(payload)
    assert artifacts.put("project", payload) == (ref, digest)
    assert artifacts.read("project", ref, digest) == payload
    storage.get_bytes.assert_called_with(ref, max_bytes=1024 * 1024)
    storage.get_bytes.reset_mock()
    for invalid in (ref.replace("private-test", "other-bucket"), "https://example.com/private", ref + "?token=secret"):
        with pytest.raises(ContextPackIntegrityError, match="namespace"):
            artifacts.read("project", invalid, digest)
    storage.get_bytes.assert_not_called()
    storage.get_bytes.return_value = canonical_bytes({**payload, "source_text": "tampered"})
    with pytest.raises(ContextPackIntegrityError, match="digest"):
        artifacts.read("project", ref, digest)
    storage.put_bytes.reset_mock()
    with pytest.raises(ValueError, match="1 MiB"):
        artifacts.put("project", {**payload, "source_text": "x" * (1024 * 1024)})
    storage.put_bytes.assert_not_called()
