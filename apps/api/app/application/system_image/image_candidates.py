from __future__ import annotations

from dataclasses import asdict

from ...domain.system_image.image_revision import build_image_artifact, member_payload
from .image_revision_ports import ImageArtifactPort, ImageRevisionRepositoryPort


class ImageCandidateApplicationService:
    def __init__(self, artifacts: ImageArtifactPort, repository: ImageRevisionRepositoryPort):
        self.artifacts, self.repository = artifacts, repository

    def freeze(self, manifest, baseline_id, *, objects, relationships, invocation_id, recorded_at, build_commit=None):
        if build_commit:
            build_commit.require_current()
        payload, members = build_image_artifact(manifest, baseline_id,
            [item.model_dump(mode="json") for item in objects], [item.model_dump(mode="json") for item in relationships])
        members = self.repository.pin_evidence(manifest.project_id, members)
        payload["members"] = [member_payload(member) for member in members]
        artifact_ref, artifact_hash = self.artifacts.put(manifest.project_id, payload)
        extra = {"build_commit": build_commit} if build_commit is not None else {}
        return self.repository.record(manifest, baseline_id, artifact_ref=artifact_ref, artifact_hash=artifact_hash,
            members=members, relationship_count=len(relationships), invocation_id=invocation_id, recorded_at=recorded_at, **extra)
