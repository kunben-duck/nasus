"""Native PG/private MinIO source reads, and explicitly enabled offline exweb build."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from threading import Event
import time
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.system_image.native_build_sources import ImageNativeBuildSources
from apps.api.app.application.quality_loop.native_build_execution import execute_native_build
from apps.api.app.domain.quality_loop.native_build import NativeBuildRequest
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.runner.native_maven_build import OfflineMavenNativeBuild, bounded_command
from apps.api.app.infrastructure.storage.native_build_artifacts import NativeBuildArtifacts
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
from apps.api.app.infrastructure.system_image.source_snapshot_archive import SourceSnapshotArchive
from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_image_revision_api import selected
from apps.api.tests.test_source_access_api import grant_member, policy


def source_service():
    return ImageNativeBuildSources(app.state.container.image_revisions, SourceSnapshotRepository(),
                                   SourceSnapshotArchive(ObjectStorage()))


def selection(v, summary, member):
    return {"project_id": v["project_id"], "image_revision_id": summary["image_revision_id"],
        "image_artifact_hash": summary["artifact_hash"], "binding_id": member["binding_id"],
        "source_revision_id": member["source_revision_id"]}


def test_native_source_port_preserves_deleted_checkout_and_rejects_wrong_pin(evidence_api):
    v = evidence_api
    _, summary, _ = selected(v)
    service = source_service()
    request = selection(v, summary, v["evidence"])
    original = v["path"].read_bytes()
    v["path"].unlink()
    with actor_scope(UserProfile(**v["owner"])):
        value = service.read(**request)
        assert value.files[0].body == original and value.pin.source_revision_id == v["revision"]
        assert value.pin.manifest_id == summary["manifest_id"]
        with pytest.raises(ImageRevisionIntegrityError):
            service.read(**{**request, "source_revision_id": "different-source"})


def test_native_source_port_checks_access_before_private_file_read_and_after(evidence_api, monkeypatch):
    v = evidence_api
    _, summary, _ = selected(v)
    grant_member(v)
    service = source_service()
    request = selection(v, summary, v["evidence"])
    read, calls = service.archive.verified_files, []
    def counted(*args, **kwargs):
        calls.append(1)
        return read(*args, **kwargs)
    monkeypatch.setattr(service.archive, "verified_files", counted)
    policy(v)
    with actor_scope(UserProfile(**v["member"])):
        with pytest.raises(SourceAccessDenied):
            service.read(**request)
    assert not calls
    policy(v, (v["member"]["id"],))
    def revoke(*args, **kwargs):
        value = read(*args, **kwargs)
        policy(v)
        return value
    monkeypatch.setattr(service.archive, "verified_files", revoke)
    with actor_scope(UserProfile(**v["member"])):
        with pytest.raises((SourceAccessDenied, StaleSourceAccessScope)):
            service.read(**request)


def fixed_exweb_native_input(evidence_api, tmp_path):
    if os.environ.get("EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD") != "1":
        pytest.skip("explicit reviewed exweb native build required")
    root, cache, image_id = (os.environ.get(key) for key in
        ("EXWEB_SOURCE_REFRESH_GIT_ROOT", "EXWEB_NATIVE_MAVEN_CACHE", "EXWEB_NATIVE_MAVEN_IMAGE_ID"))
    assert root and cache and image_id
    assert os.environ.get("NASUS_TEST_OBJECT_STORAGE_MODE") == "minio"
    database = make_url(os.environ["NASUS_DATABASE_URL"])
    assert database.get_backend_name() == "postgresql" and database.database.startswith("nasus_test_")
    v = evidence_api
    files, tree_hash, _ = read_git_tree(Path(root), AFTER)
    assert len(files) == 126
    exported = tmp_path / "fixed-reviewed-exweb"
    exported.mkdir()
    for name, body in files:
        target = exported / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(exported)}]})
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    repository = SourceSnapshotRepository()
    manifest = repository.latest_manifest(v["project_id"])
    listed = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/revisions", headers=v["headers"])
    assert listed.status_code == 200, listed.text
    summary = next(item for item in listed.json()["items"] if item["manifest_id"] == manifest.manifest_id)
    archived = repository.materialization_sources(manifest)
    source = next(item for item in archived if item.source_uri == str(exported))
    snapshot = app.state.container.image_revisions.authorization.repository.load_snapshot(v["project_id"])
    binding = next(item for item in snapshot.bindings if item.source_id == source.id)
    member = next(item for item in manifest.members if item.binding_id == binding.binding_id)
    # Delete only this test's owned checkout before asking the application port for bytes.
    shutil.rmtree(exported)
    service = source_service()
    with actor_scope(UserProfile(**v["owner"])):
        fixed = service.read(**selection(v, summary, {"binding_id": member.binding_id,
                                                    "source_revision_id": member.source_revision_id}))
    assert not exported.exists() and {item.path: item.body for item in fixed.files} == dict(files)
    assert fixed.pin.content_hash == tree_hash
    request = NativeBuildRequest(fixed, "target/FinanceEXChatService-1.0.0-RELEASE.jar")
    return request, files, tree_hash, cache, image_id


def test_fixed_exweb_native_build_reads_only_private_archive_and_roundtrips_actual_jar(evidence_api, tmp_path):
    request, files, tree_hash, cache, image_id = fixed_exweb_native_input(evidence_api, tmp_path)
    output = asyncio.run(execute_native_build(OfflineMavenNativeBuild(image_id=image_id, maven_cache=Path(cache)),
        request, require_work=lambda: None))
    assert output.artifact[:2] == b"PK" and len(output.artifact) > 50 * 1024 * 1024
    assert output.runtime_inventory["runtime_library_count"] == 109
    assert output.runtime_inventory["compiled_class_count"] == 121
    build_id = str(uuid4())
    archive = NativeBuildArtifacts(ObjectStorage())
    saved = archive.put(build_id, request, output)
    assert saved["artifact_ref"].startswith("s3://")
    replay = archive.read(build_id, request, artifact_ref=saved["artifact_ref"], artifact_hash=saved["artifact_hash"])
    assert replay["artifact"] == output.artifact and replay["log"] == output.log
    assert replay["receipt"]["native_build_verified"] and not replay["receipt"]["execution_authorized"]
    assert replay["receipt"]["executed_on_target_count"] == replay["receipt"]["passed_count"] == 0
    report_path = os.environ.get("EXWEB_NATIVE_BUILD_REPORT")
    if report_path:
        report = {"recorded_at": datetime.now(timezone.utc).isoformat(), "repository": "https://github.com/kunben-duck/exweb.git",
            "reviewed_git_commit": AFTER, "git_tree_hash": tree_hash, "source_file_count": len(request.source.files),
            "private_archive_only_build": True, "source_checkout_deleted_before_read": True,
            "actual_docker_offline_build": True, "private_minio_artifact_roundtrip": True,
            "receipt": replay["receipt"], "nasus_canonical_build_command": False, "native_target_execution": False,
            "maintainer_business_gold_verified": False, "full_quality_closure_verified": False,
            "artifact_storage": "isolated_test_private_minio_removed_after_suite"}
        with Path(report_path).open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)


@pytest.mark.parametrize("mode", ["cancel", "revoke"])
def test_fixed_exweb_native_build_cancellation_waits_for_actual_container_cleanup(evidence_api, tmp_path, mode):
    request, files, tree_hash, cache, image_id = fixed_exweb_native_input(evidence_api, tmp_path)
    v = evidence_api
    authorization = source_service().images.authorization
    membership = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    if mode == "revoke":
        assert v["client"].put(membership, headers=v["headers"], json={"role": "project_admin"}).status_code == 200
    actor = UserProfile(**v["member" if mode == "revoke" else "owner"])
    entered, names = Event(), []

    def command(args, **kwargs):
        if args[1] == "run":
            name = args[args.index("--name") + 1]
            names.append(name)
            if args[-1] == "verify":
                entered.set()
        return bounded_command(args, **kwargs)

    async def scenario():
        builder = OfflineMavenNativeBuild(image_id=image_id, maven_cache=Path(cache), command=command)
        scope = authorization.scope(v["project_id"])
        task = asyncio.create_task(execute_native_build(builder, request,
            require_work=lambda: authorization.require_current(scope)))
        try:
            assert await asyncio.to_thread(entered.wait, 15)
            compile_name = names[-1]
            running = False
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not task.done():
                code, state = await asyncio.to_thread(bounded_command,
                    ["docker", "container", "inspect", "--format", "{{json .State}}", compile_name],
                    timeout=5, max_bytes=65536)
                if not code and json.loads(state).get("Running") is True:
                    running = True
                    break
                await asyncio.sleep(0.05)
            assert running, "cancel must interrupt a verified running native container, not only a pending thread"
            started = time.monotonic()
            if mode == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                response = await asyncio.to_thread(v["client"].delete, membership, headers=v["headers"])
                assert response.status_code == 200
                with pytest.raises((PlatformApplicationError, SourceAccessDenied, StaleSourceAccessScope)):
                    await task
            elapsed = time.monotonic() - started
            assert elapsed < 15
            return elapsed
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    with actor_scope(actor):
        elapsed = asyncio.run(scenario())
    assert len(names) == 2
    for name in names:
        code, body = bounded_command(["docker", "container", "inspect", name], timeout=5, max_bytes=65536)
        assert code and b"No such" in body and name.encode() in body
    report_path = os.environ.get("EXWEB_NATIVE_CANCEL_REPORT" if mode == "cancel" else "EXWEB_NATIVE_REVOCATION_REPORT")
    if report_path:
        report = {"recorded_at": datetime.now(timezone.utc).isoformat(),
            "repository": "https://github.com/kunben-duck/exweb.git", "reviewed_git_commit": AFTER,
            "git_tree_hash": tree_hash, "source_file_count": len(files), "private_archive_only_input": True,
            "interruption": mode, "live_source_authorization_checked": True,
            "real_membership_revocation": mode == "revoke",
            "actual_running_docker_build_observed": True, "all_owned_containers_removed_before_ack": True,
            "cancellation_latency_seconds": elapsed, "successful_output_returned": False,
            "nasus_canonical_build_command": False, "durable_cancellation_verified": False,
            "native_target_execution": False, "full_quality_closure_verified": False}
        with Path(report_path).open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
