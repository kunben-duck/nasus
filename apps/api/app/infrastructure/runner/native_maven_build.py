"""Offline, pinned-image build adapter. It does not dispatch an application target."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from uuid import uuid4
import zipfile

from ...domain.quality_loop.native_build import (
    MAX_ARTIFACT_BYTES, MAX_BUILD_LOG_BYTES, NativeBuildOutput, NativeBuildExecutionFailed, build_receipt,
)
from ...domain.shared.native_build_source import build_path, byte_digest
from ...domain.system_image.source_snapshots import snapshot_digest


class NativeBuildFailure(NativeBuildExecutionFailed):
    def __init__(self, code, log=b""):
        super().__init__(code)
        self.code, self.log = code, log


def bounded_command(args, *, timeout, max_bytes, require_work=None, input_body=None):
    if require_work is not None:
        require_work()
    if input_body is not None and (type(input_body) is not bytes or len(input_body) > 1024 * 1024):
        raise ValueError("bounded subprocess input is invalid")
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "TMPDIR"}}
    # An anonymous file avoids a full stdin pipe deadlocking against stdout.
    with tempfile.TemporaryFile() as stdin:
        if input_body is not None:
            stdin.write(input_body)
            stdin.seek(0)
        if require_work is not None:
            require_work()
        process = subprocess.Popen(args, env=env, stdin=stdin if input_body is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, bufsize=0)
    output = bytearray()
    deadline = time.monotonic() + timeout
    completed = False
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if require_work is not None:
                    require_work()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NativeBuildFailure("native_build_timeout", bytes(output))
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), min(65536, max_bytes - len(output) + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if len(output) + len(chunk) > max_bytes:
                        raise NativeBuildFailure("native_build_log_limit", bytes(output))
                    output.extend(chunk)
        # A child may close stdout and continue running. Retain the fence and
        # cancellation checks during the remaining wait, not just pipe reads.
        while process.poll() is None:
            if require_work is not None:
                require_work()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeBuildFailure("native_build_timeout", bytes(output))
            try:
                process.wait(timeout=min(remaining, 0.1))
            except subprocess.TimeoutExpired:
                pass
        code = process.returncode
        if require_work is not None:
            require_work()
        completed = True
        return code, bytes(output)
    finally:
        if not completed or process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        process.stdout.close()


def runtime_jar_inventory(body, *, require_work=None):
    if require_work is not None:
        require_work()
    if type(body) is not bytes or not 1 <= len(body) <= MAX_ARTIFACT_BYTES:
        raise ValueError("native artifact size is invalid")
    entries = []
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        members = archive.infolist()
        if (not members or len(members) > 8192 or len({item.filename for item in members}) != len(members)
                or sum(item.file_size for item in members) > 512 * 1024 * 1024):
            raise ValueError("native artifact inventory exceeds its bound")
        for item in sorted(members, key=lambda item: item.filename):
            if require_work is not None:
                require_work()
            build_path(item.filename[:-1] if item.is_dir() else item.filename)
            if (item.file_size > MAX_ARTIFACT_BYTES or item.flag_bits & 1
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("native artifact member is unsafe")
            if item.is_dir():
                continue
            content = archive.read(item)
            if len(content) != item.file_size:
                raise ValueError("native artifact member size differs")
            entries.append({"path": item.filename, "byte_count": len(content), "content_hash": byte_digest(content)})
    libraries = sum(item["path"].startswith("BOOT-INF/lib/") and item["path"].endswith(".jar") for item in entries)
    classes = sum(item["path"].startswith("BOOT-INF/classes/") and item["path"].endswith(".class") for item in entries)
    if not libraries or not classes:
        raise ValueError("native adapter requires an executable Spring Boot archive")
    return {"entries": entries, "inventory_hash": snapshot_digest(entries),
            "runtime_library_count": libraries, "compiled_class_count": classes}


class OfflineMavenNativeBuild:
    def __init__(self, *, image_id, maven_cache: Path, command=bounded_command, timeout=180):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) or type(timeout) is not int or not 1 <= timeout <= 300:
            raise ValueError("operator-pinned image and bounded timeout are required")
        cache = Path(maven_cache)
        if not cache.is_absolute() or not cache.is_dir():
            raise ValueError("operator Maven cache must be an existing absolute directory")
        cache = cache.resolve()
        if any(c in str(cache) for c in ",\r\n"):
            raise ValueError("unsafe Maven cache mount")
        self.image_id, self.maven_cache, self.command, self.timeout = image_id, cache, command, timeout

    def _args(self, name, owner, *, workspace=None):
        args = ["docker", "run", "--rm", "--pull=never", "--name", name,
            "--label", "nasus.native-build-owner=" + owner, "--network", "none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=256", "--memory=2g",
            "--cpus=2", "--tmpfs", "/tmp:rw,size=512m"]
        if workspace is not None:
            if any(c in str(workspace) for c in ",\r\n"):
                raise ValueError("unsafe build workspace mount")
            args += ["--mount", "type=bind,src=" + str(workspace) + ",dst=/work",
                "--mount", "type=bind,src=" + str(self.maven_cache) + ",dst=/cache,readonly", "--workdir", "/work"]
        return args + ["--entrypoint", "mvn", self.image_id]

    def _cleanup(self, name, owner):
        args = ["docker", "container", "inspect", "--format", "{{json .Config.Labels}}", name]
        code, body = self.command(args, timeout=15, max_bytes=65536)
        if code:
            if b"No such" in body and name.encode() in body:
                return
            raise NativeBuildFailure("native_build_cleanup_unverified")
        if json.loads(body).get("nasus.native-build-owner") != owner:
            raise NativeBuildFailure("native_build_cleanup_owner_mismatch")
        code, _ = self.command(["docker", "rm", "--force", "--volumes", name], timeout=15, max_bytes=65536)
        if code:
            raise NativeBuildFailure("native_build_cleanup_failed")
        code, body = self.command(args, timeout=15, max_bytes=65536)
        if not code or b"No such" not in body or name.encode() not in body:
            raise NativeBuildFailure("native_build_cleanup_unverified")

    @staticmethod
    def _source_unchanged(workspace, source, *, require_work=None):
        for item in source.files:
            if require_work is not None:
                require_work()
            target = workspace
            for part in PurePosixPath(item.path).parts:
                target = target / part
                if target.is_symlink():
                    raise NativeBuildFailure("native_build_source_modified")
            if (not target.is_file() or target.stat().st_size != len(item.body)
                    or byte_digest(target.read_bytes()) != byte_digest(item.body)):
                raise NativeBuildFailure("native_build_source_modified")

    def build(self, request, *, require_work=None):
        def current():
            if require_work is not None:
                require_work()

        def command(args, **kwargs):
            current()
            # Preserve the unguarded command signature for existing callers.
            result = self.command(args, **kwargs, **({"require_work": current} if require_work is not None else {}))
            current()
            return result

        current()
        request_digest = request.digest
        owner = uuid4().hex
        names = ["nasus-native-build-" + owner + suffix for suffix in ("-version", "-compile")]
        code, body = command(["docker", "image", "inspect", "--format", "{{.Id}}", self.image_id],
                                  timeout=15, max_bytes=65536)
        if code or body.decode().strip() != self.image_id:
            raise NativeBuildFailure("native_build_image_unavailable")
        created = []
        with tempfile.TemporaryDirectory(prefix="nasus-native-build-") as directory:
            workspace = Path(directory) / "source"
            workspace.mkdir()
            for item in request.source.files:
                current()
                target = workspace / item.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(item.body)
                target.chmod(0o644)
            try:
                created.append(names[0])
                code, version = command(self._args(names[0], owner) + ["--version"], timeout=30, max_bytes=65536)
                text = re.sub(r"\x1b\[[0-9;]*m", "", version.decode("utf-8", errors="replace"))
                if (code or not re.search(r"Apache Maven 3\.9\.11(?:\s|$)", text)
                        or not re.search(r"Java version: 21(?:\.|\s|,)", text)):
                    raise NativeBuildFailure("native_build_toolchain_mismatch")
                self._source_unchanged(workspace, request.source, require_work=current)
                created.append(names[1])
                code, log = command(self._args(names[1], owner, workspace=workspace) + ["--batch-mode", "--offline",
                    "-Duser.home=/tmp", "-Dmaven.repo.local=/cache", "verify"], timeout=self.timeout, max_bytes=MAX_BUILD_LOG_BYTES)
                if code:
                    raise NativeBuildFailure("native_build_compile_failed", log)
                self._source_unchanged(workspace, request.source, require_work=current)
                target = workspace
                for part in PurePosixPath(request.artifact_path).parts:
                    target = target / part
                    if target.is_symlink():
                        raise NativeBuildFailure("native_build_artifact_symlink")
                if not target.is_file() or not 1 <= target.stat().st_size <= MAX_ARTIFACT_BYTES:
                    raise NativeBuildFailure("native_build_artifact_missing_or_oversized")
                artifact = target.read_bytes()
                current()
                if request.digest != request_digest:
                    raise NativeBuildFailure("native_build_request_changed")
                output = NativeBuildOutput(request_digest, artifact, log,
                    {"image_id": self.image_id, "maven": "3.9.11", "java": "21", "version_output_hash": byte_digest(version),
                     "network": "none", "dependency_cache": "operator_read_only"},
                    runtime_jar_inventory(artifact, require_work=current))
                build_receipt(request, output)
                current()
                return output
            finally:
                failures = []
                for name in reversed(created):
                    try:
                        self._cleanup(name, owner)
                    except Exception as exc:
                        failures.append(exc)
                if failures:
                    raise NativeBuildFailure("native_build_cleanup_unverified") from failures[0]
                current()
