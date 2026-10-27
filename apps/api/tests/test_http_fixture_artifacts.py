"""Exact artifact codec specimens; production S3 is tested separately."""
from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.storage.http_fixture_artifacts import HttpFixtureExecutionArtifacts
from apps.api.tests.test_http_fixtures import manifest, scope, Runner


class Storage:
    def __init__(self):
        self.config = SimpleNamespace(s3_enabled=True, bucket="private-codec-specimen")
        self.objects = {}

    def put_bytes(self, key, body, *, content_type):
        ref = "s3://" + self.config.bucket + "/" + key
        self.objects[ref] = body
        return SimpleNamespace(storage_ref=ref, content_hash="sha256:" + hashlib.sha256(body).hexdigest())

    def get_bytes(self, ref, *, max_bytes):
        return self.objects[ref]


def specimen():
    current, recipe = scope(), manifest()
    command = HttpFixtureLifecycleApplicationService._command(current, "setup", tuple(recipe["setup_steps"]))
    execution = Runner().execute_owned_http(command, environment_id=current.environment_id,
        artifact_hash=current.artifact_hash, inventory_hash=current.inventory_hash, require_work=lambda: None)
    parent = {"project_id": current.project_id, "plan_digest": current.parent_digest, "kind": "explicit-protocol-specimen"}
    return HttpFixtureExecutionArtifacts(Storage()), parent, current, command, execution


def test_fixture_artifact_codec_preserves_original_wire_and_native_artifacts():
    artifacts, parent, current, command, execution = specimen()
    ref, digest = artifacts.put(parent, current, "setup", command, execution)
    actual = artifacts.read(parent, current, "setup", command, ref, digest)
    assert actual == execution and actual.result_body == execution.result_body and actual.request_body == execution.request_body
    assert ref.startswith("s3://private-codec-specimen/quality/http-fixture-journal/")


@pytest.mark.parametrize("fault", ["parent", "scope", "phase", "command", "ref", "digest", "bytes", "missing"])
def test_fixture_artifact_codec_rejects_rebinding_and_corruption(fault):
    artifacts, parent, current, command, execution = specimen()
    ref, digest = artifacts.put(parent, current, "setup", command, execution)
    phase = "setup"
    if fault == "parent": parent = {**parent, "plan_digest": acceptance_digest("different")}
    elif fault == "scope": current = replace(current, attempt_id="different")
    elif fault == "phase": phase = "cleanup:session"
    elif fault == "command": command = replace(command, timeout_ms=11000)
    elif fault == "ref": ref = ref.replace("quality/http-fixture-journal", "another-project")
    elif fault == "digest": digest = acceptance_digest("different")
    elif fault == "bytes": artifacts.storage.objects[ref] += b" "
    elif fault == "missing": artifacts.storage.objects.pop(ref)
    with pytest.raises(HttpFixtureInvalid): artifacts.read(parent, current, phase, command, ref, digest)


def test_backend_fixture_artifacts_cannot_fall_back_to_local_files():
    storage = Storage()
    storage.config.s3_enabled = False
    with pytest.raises(HttpFixtureInvalid): HttpFixtureExecutionArtifacts(storage)
