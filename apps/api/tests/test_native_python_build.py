"""Python profile protocol tests, distinct from live RealWorld acceptance."""
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4

import pytest

from apps.api.app.domain.quality_loop.build_profiles import PYTHON_BUILD, artifact_profile
from apps.api.app.domain.quality_loop.native_build import NativeBuildRequest, build_receipt
from apps.api.app.domain.shared.native_build_source import NativeBuildFile, NativeBuildSourcePin, FrozenNativeBuildSource, byte_digest
from apps.api.app.infrastructure.runner.native_python_build import OfflinePythonNativeBuild, runtime_python_inventory
from apps.api.app.infrastructure.storage.native_build_artifacts import NativeBuildArtifacts
from apps.api.tests.test_native_build import local_storage


@pytest.fixture
def source_request():
    files = tuple(NativeBuildFile(path, body) for path, body in sorted({
        "pyproject.toml": b'[project]\nname="fixture"\n',
        "manage.py": b"print('must not execute on host')\n",
        "config/settings.py": b"DEBUG = False\n",
    }.items()))
    content_hash = byte_digest(b"".join(f.path.encode() + b"\0" + f.body for f in files))
    pin = NativeBuildSourcePin("project", "image", byte_digest(b"image"), "manifest", byte_digest(b"manifest"),
        "binding", "revision", "source", "fixed-sha", content_hash, byte_digest(b"snapshot"))
    return NativeBuildRequest(FrozenNativeBuildSource(pin, files), "target/application.pyz", adapter=PYTHON_BUILD)


def fake_command(fail=False):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["container", "inspect"]:
            return 1, ("No such object: " + args[-1]).encode()
        if fail:
            return 1, b"SyntaxError"
        return 0, json.dumps({"python": "3.12", "compiled": 2, "version": "3.12.test",
                             "dependencies_checked": True,
                             "dependency_lock_hash": byte_digest(b"lock")}).encode()
    return run, calls


def test_python_build_is_offline_and_replayable(source_request, tmp_path):
    command, calls = fake_command()
    builder = OfflinePythonNativeBuild(image_id="sha256:" + "a" * 64,
        dependency_lock_hash=byte_digest(b"lock"), command=command)
    output = builder.build(source_request)
    assert output == builder.build(source_request)
    assert not build_receipt(source_request, output)["execution_authorized"]
    assert runtime_python_inventory(output.artifact)["python_file_count"] == 3
    args = calls[0]
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--user") + 1] == "65534:65534"
    assert "--read-only" in args and "--pull=never" in args
    mount = args[args.index("--mount") + 1]
    assert mount.endswith(",dst=/source,readonly")
    assert not Path(mount.split("src=", 1)[1].split(",dst=", 1)[0]).exists()
    storage = NativeBuildArtifacts(local_storage(tmp_path))
    ident = str(uuid4())
    saved = storage.put(ident, source_request, output)
    replay = storage.read(ident, source_request, artifact_ref=saved["artifact_ref"], artifact_hash=saved["artifact_hash"])
    assert replay["receipt"] == build_receipt(source_request, output)


def test_python_lock_mismatch_and_compile_failure_cannot_commit(source_request):
    for fail in (True, False):
        command, calls = fake_command(fail)
        builder = OfflinePythonNativeBuild(image_id="sha256:" + "a" * 64,
            dependency_lock_hash=byte_digest(b"wrong lock"), command=command)
        with pytest.raises(RuntimeError):
            builder.build(source_request)
        assert calls[-1][1:3] == ["container", "inspect"]


@pytest.mark.parametrize("path", ["target/app.exe", "app.pyz", "target/app.zip"])
def test_unregistered_artifact_rejected(path):
    with pytest.raises(ValueError):
        artifact_profile(path)


def test_python_adapter_cannot_accept_a_java_request(source_request):
    with pytest.raises(ValueError):
        replace(source_request, adapter="unknown")
    with pytest.raises(ValueError):
        replace(source_request, artifact_path="target/app.jar")


def test_self_consistent_python_archive_cannot_replace_the_captured_source(source_request, tmp_path):
    from apps.api.app.infrastructure.runner.native_python_build import python_archive
    from apps.api.app.domain.system_image.source_snapshots import snapshot_digest

    command, _ = fake_command()
    output = OfflinePythonNativeBuild(image_id="sha256:" + "a" * 64,
        dependency_lock_hash=byte_digest(b"lock"), command=command).build(source_request)
    files = tuple(replace(item, body=b"DEBUG = True\n") if item.path == "config/settings.py" else item
                  for item in source_request.source.files)
    pin = replace(source_request.source.pin,
        content_hash=byte_digest(b"".join(item.path.encode() + b"\0" + item.body for item in files)))
    artifact = python_archive(FrozenNativeBuildSource(pin, files))
    changed = replace(output, artifact=artifact, runtime_inventory=runtime_python_inventory(artifact))
    storage = NativeBuildArtifacts(local_storage(tmp_path))
    with pytest.raises(ValueError, match="captured source"):
        storage.put(str(uuid4()), source_request, changed)
    # Also reject a consistently re-hashed archive during replay, not only initial writes.
    ident = str(uuid4())
    saved = storage.put(ident, source_request, output)
    receipt = build_receipt(source_request, changed)
    prefix = storage._prefix(ident, source_request)
    key = prefix + "/artifact/" + byte_digest(artifact)[7:]
    stored = storage.storage.put_bytes(key, artifact, content_type="application/zip")
    payload = {"build_id": ident, "receipt": receipt, "refs": {"artifact": stored.storage_ref,
        "log": storage._ref(prefix + "/log/" + byte_digest(output.log)[7:])}}
    digest = snapshot_digest(payload)
    archived = storage.storage.put_json(prefix + "/receipts/" + digest[7:] + ".json", payload)
    with pytest.raises(ValueError, match="captured source"):
        storage.read(ident, source_request, artifact_ref=archived.storage_ref, artifact_hash=digest)
