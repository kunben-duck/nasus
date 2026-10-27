"""Protocol/security tests. Real Docker/PG/MinIO evidence has a separate test."""
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
from uuid import uuid4
import zipfile

import pytest

from apps.api.app.domain.shared.native_build_source import (
    FrozenNativeBuildSource, NativeBuildFile, NativeBuildSourcePin, byte_digest, build_path,
)
from apps.api.app.domain.quality_loop.native_build import NativeBuildRequest, NativeBuildOutput, build_receipt
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.runner.native_maven_build import (
    OfflineMavenNativeBuild, NativeBuildFailure, bounded_command, runtime_jar_inventory,
)
from apps.api.app.infrastructure.storage.native_build_artifacts import NativeBuildArtifacts
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.source_snapshot_archive import SourceSnapshotArchive


@pytest.fixture
def request_value():
    body = b"<project>Protocol specimen only.</project>"
    pin = NativeBuildSourcePin("project", "image", byte_digest(b"image"), "manifest", byte_digest(b"manifest"),
        "binding", "revision", "source", "fixed-revision", byte_digest(b"pom.xml\0" + body), byte_digest(b"snapshot"))
    return NativeBuildRequest(FrozenNativeBuildSource(pin, (NativeBuildFile("pom.xml", body),)), "target/app.jar")


def protocol_jar():
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr("BOOT-INF/classes/Example.class", b"protocol class, not executable Java")
        archive.writestr("BOOT-INF/lib/protocol.jar", b"protocol library")
        archive.writestr("META-INF/MANIFEST.MF", b"protocol manifest")
    return body.getvalue()


def protocol_commands(action=None, version=b"Apache Maven 3.9.11\nJava version: 21.0.4, vendor: protocol\n"):
    calls = []
    def command(args, **kwargs):
        calls.append((args, kwargs))
        if args[1:3] == ["image", "inspect"]:
            return 0, args[-1].encode()
        if args[1:3] == ["container", "inspect"]:
            return 1, ("Error: No such object: " + args[-1]).encode()
        if args[-1] == "--version":
            return 0, version
        workspace = next(value for value in args if value.startswith("type=bind,src=") and value.endswith("dst=/work"))
        path = Path(workspace.split("src=", 1)[1].split(",dst=", 1)[0])
        if action:
            return action(path)
        (path / "target").mkdir()
        (path / "target/app.jar").write_bytes(protocol_jar())
        return 0, b"Protocol successful build."
    return command, calls


def builder(tmp_path, command):
    return OfflineMavenNativeBuild(image_id="sha256:" + "a" * 64, maven_cache=tmp_path, command=command)


def local_storage(tmp_path):
    return ObjectStorage(ObjectStorageConfig(None, "private-protocol-bucket", None, None, "us-east-1", tmp_path))


def test_native_protocol_builder_uses_isolation_and_preserves_zero_target_authority(request_value, tmp_path):
    command, calls = protocol_commands()
    result = builder(tmp_path, command).build(request_value)
    receipt = build_receipt(request_value, result)
    assert receipt["native_build_verified"] and not receipt["execution_authorized"]
    assert receipt["executed_on_target_count"] == receipt["passed_count"] == 0
    assert not receipt["dependency_supply_chain_verified"] and not receipt["reproducible_build_verified"]
    assert not receipt["source"]["file_mode_attested"]
    args = next(args for args, _ in calls if args[-1] == "verify")
    assert args[args.index("--network") + 1] == "none" and "--read-only" in args
    assert "--cap-drop=ALL" in args and "--security-opt=no-new-privileges" in args and "--offline" in args
    assert "--pull=never" in args and args[args.index("--entrypoint") + 1] == "mvn"
    mounts = [args[index + 1] for index, value in enumerate(args) if value == "--mount"]
    assert len(mounts) == 2 and mounts[1].endswith("dst=/cache,readonly")
    assert not any(flag in args for flag in ("--env", "--env-file", "--publish", "--privileged", "--volume"))
    assert not Path(mounts[0].split("src=", 1)[1].split(",dst=", 1)[0]).exists()
    assert result.runtime_inventory["compiled_class_count"] == result.runtime_inventory["runtime_library_count"] == 1
    assert len(result.runtime_inventory["entries"]) == 3


@pytest.mark.parametrize("path", ["../a", "/a", "a/../b", "a\\b", "a//b", "a\nb", ".git/config", ""])
def test_native_paths_reject_traversal_and_ambiguous_names(path):
    with pytest.raises(ValueError):
        build_path(path)


def test_native_source_and_target_hashes_cannot_be_substituted(request_value, tmp_path):
    with pytest.raises(ValueError):
        replace(request_value.source, files=(NativeBuildFile("pom.xml", b"changed"),))
    command, _ = protocol_commands()
    with pytest.raises(ValueError, match="declared target"):
        builder(tmp_path, command).build(replace(request_value, expected_artifact_hash=byte_digest(b"different jar")))
    with pytest.raises(ValueError):
        replace(request_value, artifact_path="pom.xml")


@pytest.mark.parametrize("mode", ["modified_source", "source_symlink", "artifact_symlink", "failure", "timeout"])
def test_native_build_faults_cleanup_without_accepting_output(request_value, tmp_path, mode):
    def action(workspace):
        if mode == "failure":
            return 1, b"protocol compile failure"
        if mode == "timeout":
            raise NativeBuildFailure("native_build_timeout")
        (workspace / "target").mkdir()
        (workspace / "target/app.jar").write_bytes(protocol_jar())
        if mode == "modified_source":
            (workspace / "pom.xml").write_bytes(b"modified by build")
        elif mode == "source_symlink":
            (workspace / "pom.xml").unlink()
            (workspace / "pom.xml").symlink_to(tmp_path / "missing")
        elif mode == "artifact_symlink":
            (workspace / "target/app.jar").unlink()
            (workspace / "target/app.jar").symlink_to(tmp_path / "missing")
        return 0, b"protocol output"
    command, calls = protocol_commands(action)
    with pytest.raises(NativeBuildFailure):
        builder(tmp_path, command).build(request_value)
    assert len([args for args, _ in calls if args[1:3] == ["container", "inspect"]]) == 2
    workspace = next(value for args, _ in calls for value in args if value.startswith("type=bind,src=") and value.endswith("dst=/work"))
    assert not Path(workspace.split("src=", 1)[1].split(",dst=", 1)[0]).exists()


def test_native_toolchain_and_mutable_image_are_rejected(request_value, tmp_path):
    with pytest.raises(ValueError):
        OfflineMavenNativeBuild(image_id="maven:latest", maven_cache=tmp_path)
    command, calls = protocol_commands(version=b"Apache Maven 3.9.10\nJava version: 17.0.4\n")
    with pytest.raises(NativeBuildFailure, match="toolchain_mismatch"):
        builder(tmp_path, command).build(request_value)
    assert not any(args[-1] == "verify" for args, _ in calls)


@pytest.mark.parametrize("fault", ["../unsafe", "duplicate", "symlink"])
def test_native_zip_inventory_rejects_unsafe_or_duplicate_members(fault):
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr("BOOT-INF/classes/Example.class", b"protocol")
        archive.writestr("BOOT-INF/lib/protocol.jar", b"protocol")
        if fault == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("BOOT-INF/classes/Example.class", b"duplicate")
        elif fault == "symlink":
            info = zipfile.ZipInfo("BOOT-INF/classes/link")
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "outside")
        else:
            archive.writestr(fault, b"unsafe")
    with pytest.raises(ValueError):
        runtime_jar_inventory(body.getvalue())


def test_native_private_archive_rechecks_every_byte_and_project_scope(request_value, tmp_path, monkeypatch):
    storage = local_storage(tmp_path)
    archive = NativeBuildArtifacts(storage)
    command, _ = protocol_commands()
    output = builder(tmp_path, command).build(request_value)
    build_id = str(uuid4())
    saved = archive.put(build_id, request_value, output)
    replay = archive.read(build_id, request_value, artifact_ref=saved["artifact_ref"], artifact_hash=saved["artifact_hash"])
    assert replay["artifact"] == output.artifact and replay["receipt"] == build_receipt(request_value, output)
    other = replace(request_value, source=replace(request_value.source, pin=replace(request_value.source.pin, project_id="other")))
    get = storage.get_bytes
    reads = []
    def counted(*args, **kwargs):
        reads.append(args[0])
        return get(*args, **kwargs)
    monkeypatch.setattr(storage, "get_bytes", counted)
    with pytest.raises(ValueError, match="scope"):
        archive.read(build_id, other, artifact_ref=saved["artifact_ref"], artifact_hash=saved["artifact_hash"])
    assert not reads
    def corrupt(ref, **kwargs):
        return b"corrupt" if "/artifact/" in ref else get(ref, **kwargs)
    monkeypatch.setattr(storage, "get_bytes", corrupt)
    with pytest.raises(ValueError, match="bytes differ"):
        archive.read(build_id, request_value, artifact_ref=saved["artifact_ref"], artifact_hash=saved["artifact_hash"])
    with pytest.raises(ValueError):
        archive.put(str(uuid4()), request_value, replace(output, runtime_inventory={}))


def test_native_archive_rejects_changed_source_before_loading_artifact(request_value, tmp_path, monkeypatch):
    storage = local_storage(tmp_path)
    archive = NativeBuildArtifacts(storage)
    command, _ = protocol_commands()
    output = builder(tmp_path, command).build(request_value)
    build_id = str(uuid4())
    saved = archive.put(build_id, request_value, output)
    changed = replace(request_value, source=replace(request_value.source,
        pin=replace(request_value.source.pin, image_revision_id="different-image")))
    get, reads = storage.get_bytes, []
    def counted(ref, **kwargs):
        reads.append(ref)
        return get(ref, **kwargs)
    monkeypatch.setattr(storage, "get_bytes", counted)
    with pytest.raises(ValueError, match="fixed input"):
        archive.read(build_id, changed, artifact_ref=saved["artifact_ref"], artifact_hash=saved["artifact_hash"])
    assert reads == [saved["artifact_ref"]]
    with pytest.raises(ImageRevisionIntegrityError):
        archive.read(build_id, request_value, artifact_ref=saved["artifact_ref"], artifact_hash="sha256:../unsafe")


def test_native_cleanup_never_removes_a_container_with_another_owner(request_value, tmp_path):
    original, calls = protocol_commands()
    def command(args, **kwargs):
        if args[1:3] == ["container", "inspect"]:
            calls.append((args, kwargs))
            return 0, json.dumps({"nasus.native-build-owner": "different-owner"}).encode()
        return original(args, **kwargs)
    with pytest.raises(NativeBuildFailure, match="cleanup_unverified"):
        builder(tmp_path, command).build(request_value)
    assert not any(args[1:3] == ["rm", "--force"] for args, _ in calls)


def test_source_archive_verifies_files_without_local_cache(request_value, tmp_path, monkeypatch):
    storage = local_storage(tmp_path)
    archive = SourceSnapshotArchive(storage)
    pin = request_value.source.pin
    saved = archive.capture(project_id=pin.project_id, source_id=pin.source_id,
        files=[(item.path, item.body) for item in request_value.source.files], content_hash=pin.content_hash,
        external_revision=pin.external_revision, excluded_directories=[])
    args = dict(project_id=pin.project_id, source_id=pin.source_id, content_hash=pin.content_hash,
        manifest_hash=saved.manifest_hash, max_files=10, max_bytes=4096, max_file_bytes=4096)
    payload, files = archive.verified_files(saved.manifest_ref, **args)
    assert payload["external_revision"] == pin.external_revision and files == (("pom.xml", request_value.source.files[0].body),)
    get = storage.get_bytes
    monkeypatch.setattr(storage, "get_bytes", lambda ref, **kwargs: b"tampered" if "/files/" in ref else get(ref, **kwargs))
    with pytest.raises(ValueError, match="file hash"):
        archive.verified_files(saved.manifest_ref, **args)


def test_bounded_command_limits_bytes_time_and_host_environment(monkeypatch):
    monkeypatch.setenv("PRIVATE_MODEL_KEY", "must-not-enter-build")
    code, body = bounded_command([sys.executable, "-c", "import os;print(os.getenv('PRIVATE_MODEL_KEY', 'absent'))"], timeout=3, max_bytes=1024)
    assert code == 0 and body.strip() == b"absent"
    with pytest.raises(NativeBuildFailure, match="log_limit"):
        bounded_command([sys.executable, "-c", "print('x'*10000)"], timeout=3, max_bytes=100)
    with pytest.raises(NativeBuildFailure, match="timeout"):
        bounded_command([sys.executable, "-c", "import time;time.sleep(10)"], timeout=0.1, max_bytes=100)
