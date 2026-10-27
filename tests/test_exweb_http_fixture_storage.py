"""Explicit original exweb replay into disposable MinIO; never target execution."""
import json
import os
from pathlib import Path

import pytest

from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.infrastructure.runner.http_fixture_verifier import OwnedHttpFixtureObservationVerifier
from apps.api.app.infrastructure.storage.http_fixture_artifacts import HttpFixtureExecutionArtifacts
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from scripts.exweb_http_fixture_probe import ProbeFixtureJournal, read_original, replay_exweb_http_fixtures


def test_original_exweb_six_fixture_phases_round_trip_private_minio_without_reexecution():
    source = os.environ.get("EXWEB_HTTP_FIXTURE_REPORT")
    if not source:
        pytest.skip("requires an explicitly selected original exweb report and disposable private MinIO")
    report = json.loads(read_original(Path(source), 16 * 1024 * 1024))
    replay = replay_exweb_http_fixtures(report)
    assert replay["target_reexecuted"] is replay["formal_coverage_verified"] is False
    artifacts = HttpFixtureExecutionArtifacts(ObjectStorage())
    phases, assertions, passed, failed = 0, 0, 0, 0
    for case in report["http_runner"]["http_fixtures"]["cases"]:
        scope = HttpFixtureScope(**case["scope"])
        journal = ProbeFixtureJournal(Path(case["manifest_archive"]).parent, readonly=True)
        parent = {"kind": "original_developer_probe_not_saved_runplan", "project_id": scope.project_id,
            "plan_digest": scope.parent_digest}
        for original in case["phases"]:
            phase = journal.inspect(scope, original["phase"])
            ref, digest = artifacts.put(parent, scope, original["phase"], phase.command, phase.execution)
            actual = artifacts.read(parent, scope, original["phase"], phase.command, ref, digest)
            assert actual == phase.execution and actual.result_body == phase.execution.result_body
            receipt = OwnedHttpFixtureObservationVerifier().verify(phase.command, actual,
                environment_id=scope.environment_id, inventory_hash=scope.inventory_hash)
            assert actual.result.status == original["status"]
            assertions += receipt["observed_assertion_count"]
            passed += receipt["passed_assertion_count"]
            failed += receipt["failed_assertion_count"]
            phases += 1
    assert (phases, assertions, passed, failed) == (6, 13, 11, 2)
    assert replay_exweb_http_fixtures(report) == replay
