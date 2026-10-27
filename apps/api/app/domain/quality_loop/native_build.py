"""Fixed build inputs and receipts; a build is not permission to execute a target."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy

from ..system_image.source_snapshots import snapshot_digest
from ..system_image.image_revision import require_digest
from ..shared.native_build_source import FrozenNativeBuildSource, build_path, byte_digest


NATIVE_BUILD_SCHEMA = "nasus.native-build.v1"
NATIVE_BUILD_ADAPTER = "nasus.offline-java21-maven3911.v1"
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_BUILD_LOG_BYTES = 2 * 1024 * 1024


class NativeBuildExecutionFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeBuildRequest:
    source: FrozenNativeBuildSource
    artifact_path: str
    expected_artifact_hash: str | None = None
    adapter: str = NATIVE_BUILD_ADAPTER

    def __post_init__(self):
        build_path(self.artifact_path)
        if (self.adapter != NATIVE_BUILD_ADAPTER or not self.artifact_path.startswith("target/")
                or not self.artifact_path.endswith(".jar") or "pom.xml" not in {item.path for item in self.source.files}
                or self.artifact_path in {item.path for item in self.source.files}):
            raise ValueError("unsupported native Maven build input")
        if self.expected_artifact_hash is not None:
            require_digest(self.expected_artifact_hash)

    @property
    def digest(self):
        return snapshot_digest({"source": self.source.metadata(), "artifact_path": self.artifact_path,
            "expected_artifact_hash": self.expected_artifact_hash, "adapter": self.adapter})


@dataclass(frozen=True)
class NativeBuildOutput:
    request_digest: str
    artifact: bytes = field(repr=False)
    log: bytes = field(repr=False)
    toolchain: dict
    runtime_inventory: dict

    def __post_init__(self):
        require_digest(self.request_digest)
        if (type(self.artifact) is not bytes or not 1 <= len(self.artifact) <= MAX_ARTIFACT_BYTES
                or type(self.log) is not bytes or not 1 <= len(self.log) <= MAX_BUILD_LOG_BYTES):
            raise ValueError("native build output exceeds its bound")
        if (type(self.toolchain) is not dict or self.toolchain.get("maven") != "3.9.11"
                or self.toolchain.get("java") != "21" or self.toolchain.get("network") != "none"
                or self.toolchain.get("dependency_cache") != "operator_read_only"):
            raise ValueError("native build output toolchain differs")
        require_digest(self.toolchain.get("image_id", ""))
        require_digest(self.toolchain.get("version_output_hash", ""))


def build_receipt(request, output):
    if output.request_digest != request.digest:
        raise ValueError("native build output differs from the original request")
    digest = byte_digest(output.artifact)
    if request.expected_artifact_hash is not None and digest != request.expected_artifact_hash:
        raise ValueError("native build artifact differs from the declared target")
    return {"schema": NATIVE_BUILD_SCHEMA, "request_digest": request.digest, "adapter": request.adapter,
        "source": request.source.metadata(), "artifact": {"path": request.artifact_path,
            "content_hash": digest, "byte_count": len(output.artifact)},
        "log": {"content_hash": byte_digest(output.log), "byte_count": len(output.log)},
        "toolchain": deepcopy(output.toolchain), "runtime_inventory": deepcopy(output.runtime_inventory),
        "native_build_verified": True, "execution_authorized": False, "executed_on_target_count": 0,
        "passed_count": 0, "reproducible_build_verified": False, "dependency_supply_chain_verified": False}
