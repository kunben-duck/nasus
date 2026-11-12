"""Compile captured Python in an offline pinned runtime and archive exact source."""
import io
import json
from pathlib import Path
import re
import stat
import tempfile
from uuid import uuid4
import zipfile

from ...domain.quality_loop.build_profiles import PYTHON_BUILD
from ...domain.quality_loop.native_build import MAX_ARTIFACT_BYTES, MAX_BUILD_LOG_BYTES, NativeBuildOutput, build_receipt
from ...domain.shared.native_build_source import build_path, byte_digest
from ...domain.system_image.source_snapshots import snapshot_digest
from .native_maven_build import NativeBuildFailure, OfflineMavenNativeBuild, bounded_command


ENTRYPOINT = b'''import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, sys.argv[0] + "/apps")
from django.core.management import execute_from_command_line
execute_from_command_line(["manage.py", *sys.argv[1:]])
'''
COMPILER = '''import hashlib, importlib.metadata, json, pathlib, sys, tomllib
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
assert sys.version_info[:2] == (3, 12)
project = tomllib.loads(pathlib.Path("/source/pyproject.toml").read_text())["project"]
assert str(sys.version.split()[0]) in SpecifierSet(project.get("requires-python", ""))
for item in project.get("dependencies", []):
    requirement = Requirement(item)
    assert requirement.url is None, "URL dependencies need a separately registered profile"
    if requirement.marker is None or requirement.marker.evaluate():
        assert importlib.metadata.version(requirement.name) in requirement.specifier, "runtime dependency differs"
files = sorted(pathlib.Path("/source").rglob("*.py"))
for path in files:
    compile(path.read_bytes(), str(path.relative_to("/source")), "exec")
packages = sorted((d.metadata["Name"].lower(), d.version) for d in importlib.metadata.distributions())
lock = json.dumps(packages, separators=(",", ":"), ensure_ascii=True).encode()
print(json.dumps({"python": "3.12", "version": sys.version, "compiled": len(files), "dependencies_checked": True,
    "dependency_lock_hash": "sha256:" + hashlib.sha256(lock).hexdigest()}))
'''


def python_archive(source):
    if not {"manage.py", "config/settings.py", "pyproject.toml"}.issubset({f.path for f in source.files}):
        raise ValueError("registered Python profile requires a Django management entrypoint")
    output = io.BytesIO()
    entries = {item.path: item.body for item in source.files}
    if "__main__.py" in entries:
        raise ValueError("reserved Python archive entrypoint")
    entries["__main__.py"] = ENTRYPOINT
    directories = {str(parent) + "/" for path in entries for parent in Path(path).parents if str(parent) != "."}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directories | set(entries)):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = (0o40555 if path.endswith("/") else 0o100444) << 16
            archive.writestr(info, entries.get(path, b""))
    body = output.getvalue()
    if len(body) > MAX_ARTIFACT_BYTES:
        raise ValueError("Python artifact exceeds the archive bound")
    return body


def runtime_python_inventory(body):
    if type(body) is not bytes or not 0 < len(body) <= MAX_ARTIFACT_BYTES:
        raise ValueError("invalid Python artifact size")
    entries = []
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        members = archive.infolist()
        if (not members or len(members) > 8192 or len({m.filename for m in members}) != len(members)
                or sum(m.file_size for m in members) > MAX_ARTIFACT_BYTES):
            raise ValueError("invalid Python artifact inventory")
        for member in members:
            build_path(member.filename.rstrip("/"))
            if member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("unsafe Python artifact member")
            if not member.is_dir():
                data = archive.read(member)
                entries.append({"path": member.filename, "byte_count": len(data), "content_hash": byte_digest(data)})
        if archive.read("__main__.py") != ENTRYPOINT:
            raise ValueError("Python artifact entrypoint differs")
    entries.sort(key=lambda entry: entry["path"])
    return {"entries": entries, "inventory_hash": snapshot_digest(entries),
            "python_file_count": sum(item["path"].endswith(".py") for item in entries)}


class OfflinePythonNativeBuild:
    def __init__(self, *, image_id, dependency_lock_hash, command=bounded_command, timeout=180):
        if (not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", dependency_lock_hash)
                or type(timeout) is not int or not 1 <= timeout <= 300):
            raise ValueError("Python build requires a pinned image, dependency lock and bounded timeout")
        self.image_id, self.dependency_lock_hash = image_id, dependency_lock_hash
        self.command, self.timeout = command, timeout

    def build(self, request, *, require_work=None):
        if request.adapter != PYTHON_BUILD:
            raise ValueError("Python builder cannot accept another profile")
        def current():
            if require_work is not None:
                require_work()
        def command(args, **kwargs):
            current()
            result = self.command(args, **kwargs, **({"require_work": current} if require_work is not None else {}))
            current()
            return result
        current()
        artifact = python_archive(request.source)
        owner = uuid4().hex
        name = "nasus-native-build-" + owner + "-python"
        with tempfile.TemporaryDirectory(prefix="nasus-python-build-") as directory:
            workspace = Path(directory) / "source"
            workspace.mkdir(mode=0o755)
            for item in request.source.files:
                target = workspace / item.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(item.body)
                target.chmod(0o444)
            args = ["docker", "run", "--rm", "--pull=never", "--name", name,
                "--label", "nasus.native-build-owner=" + owner, "--network", "none", "--read-only",
                "--user", "65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--pids-limit=128", "--memory=512m", "--cpus=1", "--tmpfs", "/tmp:rw,size=64m",
                "--mount", "type=bind,src=" + str(workspace) + ",dst=/source,readonly",
                "--entrypoint", "python", self.image_id, "-I", "-c", COMPILER]
            if any(c in str(workspace) for c in ",\r\n"):
                raise ValueError("unsafe Python build workspace")
            try:
                code, log = command(args, timeout=self.timeout, max_bytes=MAX_BUILD_LOG_BYTES)
                if code:
                    raise NativeBuildFailure("native_python_compile_failed", log)
                facts = json.loads(log)
                if (facts.get("python") != "3.12" or facts.get("dependencies_checked") is not True
                        or facts.get("dependency_lock_hash") != self.dependency_lock_hash
                        or facts.get("compiled") != sum(f.path.endswith(".py") for f in request.source.files)):
                    raise NativeBuildFailure("native_python_toolchain_mismatch")
                OfflineMavenNativeBuild._source_unchanged(workspace, request.source, require_work=current)
                output = NativeBuildOutput(request.digest, artifact, log,
                    {"python": "3.12", "zipapp": "1", "image_id": self.image_id, "network": "none",
                     "dependency_cache": "operator_read_only", "dependency_lock_hash": self.dependency_lock_hash,
                     "version_output_hash": byte_digest(log)}, runtime_python_inventory(artifact), PYTHON_BUILD)
                build_receipt(request, output)
                current()
                return output
            finally:
                # Same owner-checked cleanup on success, failure and cancellation.
                OfflineMavenNativeBuild._cleanup(self, name, owner)


def runtime_inventory(adapter, body):
    from ...domain.quality_loop.build_profiles import JAVA_BUILD
    from .native_maven_build import runtime_jar_inventory
    if adapter == JAVA_BUILD:
        return runtime_jar_inventory(body)
    if adapter == PYTHON_BUILD:
        return runtime_python_inventory(body)
    raise ValueError("unsupported artifact profile")
