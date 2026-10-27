"""Private archive protocol double; no actual MinIO availability claim."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.run_plan_case_execution import CASE_ARCHIVE_SCHEMA
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from apps.api.app.infrastructure.storage.run_plan_case_artifacts import RunPlanCaseArtifacts


class Storage:
    def __init__(self):
        self.config = SimpleNamespace(s3_enabled=True, bucket="explicit-private-specimen")
        self.values, self.writes, self.reads = {}, [], []

    def put_bytes(self, key, body, *, content_type):
        assert content_type == "application/json"
        ref = "s3://" + self.config.bucket + "/" + key
        self.values[ref] = body
        self.writes.append(ref)
        return SimpleNamespace(storage_ref=ref, content_hash="sha256:" + hashlib.sha256(body).hexdigest())

    def get_bytes(self, ref, *, max_bytes):
        self.reads.append((ref, max_bytes))
        return self.values[ref]


def archive():
    return {"schema": CASE_ARCHIVE_SCHEMA, "observation": {"project_id": "project", "case_id": "case"},
        "native_shape_specimen": ({"value": "原始响应"},)}


def test_archive_is_complete_content_addressed_and_never_public_or_local():
    storage = Storage()
    artifacts = RunPlanCaseArtifacts(storage)
    value = archive()
    ref, digest = artifacts.put("project", value)
    assert digest == acceptance_digest(value) and ref.startswith("s3://explicit-private-specimen/quality/run-plan-cases/")
    assert artifacts.read("project", ref, digest) == json.loads(json.dumps(value))
    assert len(storage.writes) == 1 and len(storage.reads) == 2


@pytest.mark.parametrize("fault", ["other_project", "other_bucket", "http_ref", "local_ref", "different_bytes",
    "non_bytes", "other_schema", "duplicate_keys", "non_json_constant", "unavailable"])
def test_private_read_rejects_foreign_or_corrupt_original_archive(fault):
    storage, value = Storage(), archive()
    artifacts = RunPlanCaseArtifacts(storage)
    ref, digest = artifacts.put("project", value)
    project = "project"
    if fault == "other_project": project = "other"
    elif fault == "other_bucket": ref = ref.replace("explicit-private-specimen", "other-bucket")
    elif fault == "http_ref": ref = "https://public.example/object.json"
    elif fault == "local_ref": ref = ref.replace("s3://", "local-object://")
    elif fault == "different_bytes": storage.values[ref] += b" "
    elif fault == "non_bytes": storage.values[ref] = "not-original-bytes"
    elif fault == "unavailable": storage.values.pop(ref)
    else:
        if fault == "other_schema": body = b'{"schema":"other","observation":{"project_id":"project"}}'
        elif fault == "duplicate_keys": body = b'{"schema":"nasus.run-plan-case-native-archive.v1","schema":"other","observation":{"project_id":"project"}}'
        else: body = b'{"schema":"nasus.run-plan-case-native-archive.v1","observation":{"project_id":"project"},"value":NaN}'
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        ref = "s3://" + storage.config.bucket + "/" + artifacts._key(project, digest)
        storage.values[ref] = body
    with pytest.raises(RunPlanCaseExecutionInvalid): artifacts.read(project, ref, digest)


@pytest.mark.parametrize("fault", ["local_fallback", "wrong_project", "invalid_json", "too_large", "wrong_storage_hash", "wrong_storage_ref"])
def test_archive_put_requires_full_private_bytes_before_journal_commit(monkeypatch, fault):
    import apps.api.app.infrastructure.storage.run_plan_case_artifacts as module
    storage, value = Storage(), archive()
    if fault == "local_fallback": storage.config.s3_enabled = False
    elif fault == "wrong_project": value["observation"]["project_id"] = "other"
    elif fault == "invalid_json": value["value"] = float("nan")
    elif fault == "too_large": monkeypatch.setattr(module, "MAX_CASE_ARCHIVE_BYTES", 1)
    else:
        original = storage.put_bytes
        def put(*args, **kwargs):
            result = original(*args, **kwargs)
            if fault == "wrong_storage_hash": result.content_hash = acceptance_digest("other")
            else: result.storage_ref = "https://public.example/object"
            return result
        storage.put_bytes = put
    with pytest.raises(RunPlanCaseExecutionInvalid): RunPlanCaseArtifacts(storage).put("project", value)
    assert len(storage.writes) == (1 if fault in {"wrong_storage_hash", "wrong_storage_ref"} else 0)
