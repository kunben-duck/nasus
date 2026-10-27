from dataclasses import asdict, dataclass
from typing import Optional, Protocol

from ...domain.system_image.publication import PublicationChanged, PublicationIntegrityError
from ...domain.system_image.source_access import SourceAccessScope
from ...domain.system_image.source_snapshots import CapturedSourceManifest
from .publication_read_models import ImageReadState, PublishedImagePin
from .system_image_models import BaselineRecord, ContextRelationship, KnowledgeObject, RawAssetRecord


class PublishedImageSelectionPort(Protocol):
    def read_selection(self, project_id: str, *, version_id: Optional[str] = None): ...


@dataclass(frozen=True)
class PublishedImageRead:
    scope: SourceAccessScope
    state: ImageReadState
    selection: dict
    manifest: Optional[CapturedSourceManifest] = None
    sources: tuple[RawAssetRecord, ...] = ()
    objects: tuple[KnowledgeObject, ...] = ()
    relationships: tuple[ContextRelationship, ...] = ()
    baselines: tuple[BaselineRecord, ...] = ()


class PublishedImageReadApplicationService:
    """Resolve one published head; never substitute newer draft facts on failure."""

    def __init__(self, images, manifests, authorization, selections: PublishedImageSelectionPort):
        self.images, self.manifests = images, manifests
        self.authorization, self.selections = authorization, selections

    def read(self, project_id: str, *, version_id: Optional[str] = None):
        scope = self.authorization.scope(project_id)
        selection = self.selections.read_selection(project_id, version_id=version_id)
        if selection is None:
            self.authorization.require_current(scope)
            return None
        head = selection["head"]
        if head is None:
            result = PublishedImageRead(scope, ImageReadState(mode="unpublished", version_id=version_id), selection)
        else:
            header, payload = self.images.frozen_snapshot(project_id, head["image_revision_id"])
            if (header.artifact_hash != head["image_artifact_hash"] or header.manifest_id != head["manifest_id"]
                    or header.manifest_hash != head["manifest_hash"] or head["project_id"] != project_id):
                raise PublicationIntegrityError("Published image pins do not match the frozen artifact")
            manifest = self.manifests.get_manifest(project_id, header.manifest_id)
            if (manifest.content_hash != header.manifest_hash
                    or [asdict(member) for member in manifest.members] != payload["source_members"]):
                raise PublicationIntegrityError("Published source manifest mismatch")
            sources = tuple(source.model_copy(deep=True, update={"content_ref": None, "credential_ref": None,
                "registered_from_invocation_id": None, "evidence_refs": [], "failure_reason": None})
                for source in self.manifests.materialization_sources(manifest))
            objects = tuple(KnowledgeObject.model_validate({**obj, "freshness": "published_snapshot"}) for obj in payload["objects"])
            relationships = tuple(ContextRelationship.model_validate(obj) for obj in payload["relationships"])
            pin = PublishedImagePin.model_validate({key: head[key] for key in PublishedImagePin.model_fields})
            baseline = selection["baseline"]
            result = PublishedImageRead(scope, ImageReadState(mode="published", pin=pin, version_id=version_id), selection,
                manifest, sources, objects, relationships, (BaselineRecord(id=baseline["baseline_id"], project_id=project_id,
                    kind=baseline["kind"], source_version_id=baseline["source_version_id"], status="promoted",
                    object_count=len(objects), relationship_count=len(relationships), updated_at=head["recorded_at"]),))
        self.require_current(result)
        return result

    def require_current(self, view: PublishedImageRead):
        self.authorization.require_current(view.scope)
        if self.selections.read_selection(view.scope.project_id, version_id=view.state.version_id) != view.selection:
            raise PublicationChanged("Published image head changed during read; reload")
        self.authorization.require_current(view.scope)

    def require_legacy(self, project_id, *, version_id=None):
        if self.selections.read_selection(project_id, version_id=version_id) is not None:
            raise PublicationChanged("Project adopted published images during read; reload")
