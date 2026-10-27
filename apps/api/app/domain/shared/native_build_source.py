"""Immutable byte inventory exchanged between source and target-build ports."""
from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import PurePosixPath


MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 8 * 1024 * 1024


def byte_digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def build_path(value):
    if type(value) is not str:
        raise ValueError("build path must be a string")
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or ".." in path.parts or ".git" in path.parts
            or "\\" in value or path.as_posix() != value or len(value.encode()) > 1024
            or any(ord(c) < 32 for c in value)):
        raise ValueError("unsafe build path")
    return value


@dataclass(frozen=True)
class NativeBuildSourcePin:
    project_id: str
    image_revision_id: str
    image_artifact_hash: str
    manifest_id: str
    manifest_hash: str
    binding_id: str
    source_revision_id: str
    source_id: str
    external_revision: str
    content_hash: str
    snapshot_manifest_hash: str

    def __post_init__(self):
        for key, value in asdict(self).items():
            if type(value) is not str or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
                raise ValueError("invalid native build source pin")
            if key.endswith("hash"):
                if not value.startswith("sha256:") or len(value) != 71 or any(c not in "0123456789abcdef" for c in value[7:]):
                    raise ValueError("invalid native build source hash")


@dataclass(frozen=True)
class NativeBuildFile:
    path: str
    body: bytes = field(repr=False)

    def __post_init__(self):
        build_path(self.path)
        if type(self.body) is not bytes or len(self.body) > MAX_SOURCE_FILE_BYTES:
            raise ValueError("invalid native build file size")

    def metadata(self):
        return {"path": self.path, "byte_count": len(self.body), "content_hash": byte_digest(self.body)}


@dataclass(frozen=True)
class FrozenNativeBuildSource:
    pin: NativeBuildSourcePin
    files: tuple[NativeBuildFile, ...] = field(repr=False)

    def __post_init__(self):
        if (not isinstance(self.pin, NativeBuildSourcePin) or type(self.files) is not tuple
                or not 1 <= len(self.files) <= 1000 or any(not isinstance(item, NativeBuildFile) for item in self.files)
                or len({item.path for item in self.files}) != len(self.files)
                or sum(len(item.body) for item in self.files) > MAX_SOURCE_BYTES):
            raise ValueError("invalid native build source inventory")
        digest = hashlib.sha256()
        for item in self.files:
            digest.update(item.path.encode())
            digest.update(b"\0")
            digest.update(item.body)
        if "sha256:" + digest.hexdigest() != self.pin.content_hash:
            raise ValueError("native build source bytes differ from the captured revision")

    def metadata(self):
        return {"pin": asdict(self.pin), "files": [item.metadata() for item in self.files],
                "file_mode_attested": False}
