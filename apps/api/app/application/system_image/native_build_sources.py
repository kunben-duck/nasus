"""Source-domain port for exact image members, independent of a build engine."""
from dataclasses import asdict
from typing import Protocol

from ...domain.shared.native_build_source import (
    FrozenNativeBuildSource, NativeBuildFile, NativeBuildSourcePin,
    MAX_SOURCE_BYTES, MAX_SOURCE_FILE_BYTES,
)
from ...domain.system_image.image_revision import ImageRevisionIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from .source_snapshot_ports import SourceSnapshotRepositoryPort


class NativeSourceArchivePort(Protocol):
    def verified_files(self, ref, *, project_id, source_id, content_hash, manifest_hash,
                       max_files, max_bytes, max_file_bytes): ...


class ImageNativeBuildSources:
    def __init__(self, images, repository: SourceSnapshotRepositoryPort, archive: NativeSourceArchivePort):
        self.images, self.repository, self.archive = images, repository, archive

    def read(self, *, project_id, image_revision_id, image_artifact_hash, binding_id, source_revision_id):
        scope = self.images.authorization.scope(project_id)
        scope.require_binding(binding_id)
        with self.images.verified_read_session(reuse=True):
            header, payload = self.images.frozen_snapshot(project_id, image_revision_id)
            if header.artifact_hash != image_artifact_hash:
                raise ImageRevisionIntegrityError("native build image digest differs")
            matches = [item for item in payload["source_members"] if item["binding_id"] == binding_id
                and item["source_revision_id"] == source_revision_id and item["source_type"] == "code"
                and item["status"] == "captured"]
            if len(matches) != 1:
                raise ImageRevisionIntegrityError("native build source is not an exact captured code member")
            manifest = self.repository.get_manifest(project_id, header.manifest_id)
            if (manifest.content_hash != header.manifest_hash or manifest.project_id != project_id
                    or manifest.manifest_id != header.manifest_id
                    or sorted((asdict(item) for item in manifest.members), key=lambda item: item["binding_id"])
                    != sorted(payload["source_members"], key=lambda item: item["binding_id"])):
                raise ImageRevisionIntegrityError("native build manifest digest differs")
            revision = self.repository.build_source_revision(project_id, binding_id, source_revision_id)
            scope.require_binding(binding_id)
            self.images.authorization.require_current(scope)
            archive, files = self.archive.verified_files(revision["manifest_ref"], project_id=project_id,
                source_id=revision["source_id"], content_hash=revision["content_hash"],
                manifest_hash=revision["manifest_hash"], max_files=1000,
                max_bytes=MAX_SOURCE_BYTES, max_file_bytes=MAX_SOURCE_FILE_BYTES)
            if (archive["external_revision"] != revision["external_revision"]
                    or len(files) != revision["file_count"]
                    or sum(len(body) for _, body in files) != revision["byte_count"]):
                raise ImageRevisionIntegrityError("native build archive differs from its stored revision")
            value = FrozenNativeBuildSource(NativeBuildSourcePin(project_id, image_revision_id,
                image_artifact_hash, header.manifest_id, header.manifest_hash, binding_id,
                source_revision_id, revision["source_id"], revision["external_revision"],
                revision["content_hash"], snapshot_digest(archive)),
                tuple(NativeBuildFile(path, body) for path, body in files))
        self.images.authorization.require_current(scope)
        return value
