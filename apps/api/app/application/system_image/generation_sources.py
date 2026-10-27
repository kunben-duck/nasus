"""Read-only bounded-context adapter for a generation egress inventory."""
from typing import ContextManager, Protocol

from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionSummary


class FrozenImageSourcePort(Protocol):
    def verified_read_session(self, *, reuse: bool = False) -> ContextManager[object]: ...
    def frozen_source_members(self, project_id: str, image_revision_id: str) -> tuple[ImageRevisionSummary, tuple[dict, ...]]: ...


class ImageGenerationSourceInventory:
    def __init__(self, images: FrozenImageSourcePort):
        self.images = images

    def verified_read_session(self):
        return self.images.verified_read_session(reuse=True)

    def _frozen_sources(self, prepared):
        pin = prepared["context_pin"]
        header, members = self.images.frozen_source_members(prepared["project_id"], pin["image_revision_id"])
        if header.project_id != prepared["project_id"] or header.image_revision_id != pin["image_revision_id"]:
            raise ImageRevisionIntegrityError("generation source inventory differs from the fixed image scope")
        return header, members

    def bindings(self, prepared):
        context = prepared["context"]
        header, members = self._frozen_sources(prepared)
        if (header.artifact_hash != prepared["context_pin"]["image_artifact_hash"]
                or header.manifest_id != context["source_manifest_id"] or header.manifest_hash != context["source_manifest_hash"]):
            raise ImageRevisionIntegrityError("generation inventory differs from the fixed image")
        # Consent covers the fixed manifest, including source provenance of facts
        # and mandatory fields. It never grants access to later project sources.
        return tuple(sorted(member["binding_id"] for member in members if member["status"] == "captured"))

    def automation_bindings(self, prepared):
        header, members = self._frozen_sources(prepared)
        if header.artifact_hash != prepared["context_pin"]["image_artifact_hash"]:
            raise ImageRevisionIntegrityError("automation inventory differs from the original image")
        return tuple(sorted(member["binding_id"] for member in members if member["status"] == "captured"))

    def run_plan_sources(self, prepared):
        header, members = self._frozen_sources(prepared)
        if header.artifact_hash != prepared["context_pin"]["image_artifact_hash"]:
            raise ImageRevisionIntegrityError("RunPlan source scope differs from the original image")
        return {"project_id": prepared["project_id"], "image_revision_id": header.image_revision_id,
            "image_artifact_hash": header.artifact_hash, "manifest_id": header.manifest_id,
            "manifest_hash": header.manifest_hash, "source_members": list(members)}
