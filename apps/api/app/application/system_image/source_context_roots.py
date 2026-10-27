from dataclasses import asdict, dataclass
import json
from typing import Protocol

from ...domain.system_image.derivation_impact import DerivationImpactIntegrityError, DerivationImpactTooLarge
from ...domain.system_image.source_context_roots import MAX_ROOT_PAGE, ROOT_POLICY, SourceContextRootInventory
from ...domain.system_image.source_delta import SourceRevisionPin
from ...domain.system_image.source_access import StaleSourceAccessScope


class SourceContextRootInventoryPort(Protocol):
    def list(self, project_id, binding_id, source_revision_id, *, binding_ids, after_id, limit): ...


@dataclass(frozen=True)
class SourceContextRootsPage:
    project_id: str
    before: SourceRevisionPin
    after: SourceRevisionPin
    delta_hash: str
    inventory: SourceContextRootInventory
    source_change_requires_reinvestigation: bool
    source_scope_fingerprint: str
    schema_version: str = ROOT_POLICY
    discovery_scope: str = "authorized_archived_context_roots_at_observation"
    page_evidence_verified: bool = True
    downstream_dependency_graphs_verified: bool = False
    impact_complete: bool = False
    invalidation_applied: bool = False
    generation_authorized: bool = False
    execution_authorized: bool = False


class SourceContextRootApplicationService:
    def __init__(self, inventory: SourceContextRootInventoryPort, contexts, images, deltas, authorization):
        self.inventory, self.contexts, self.images = inventory, contexts, images
        self.deltas, self.authorization = deltas, authorization

    def read(self, project_id, before_revision_id, after_revision_id, *, after_id="", limit=20, pinned=None,
             pinned_scope_fingerprint=None):
        if (type(after_id) is not str or len(after_id) > 128
                or type(limit) is not int or not 1 <= limit <= MAX_ROOT_PAGE):
            raise ValueError("invalid reverse source dependency request")
        scope = self.authorization.scope(project_id)
        require_access = lambda: self.authorization.require_current(scope)
        try:
            if pinned is not None and scope.fingerprint != pinned_scope_fingerprint:
                raise StaleSourceAccessScope("reverse dependency observation scope changed")
            delta = self.deltas.compare(project_id, before_revision_id, after_revision_id)
            require_access()
            if (delta.before.project_id != project_id or delta.after.project_id != project_id
                    or delta.before.source_revision_id != before_revision_id
                    or delta.after.source_revision_id != after_revision_id
                    or delta.before.binding_id != delta.after.binding_id):
                raise DerivationImpactIntegrityError("reverse dependency source pins mismatch")
            scope.require_binding(delta.before.binding_id)
            page = (self.inventory.list(project_id, delta.before.binding_id, before_revision_id,
                        binding_ids=scope.binding_ids, after_id=after_id, limit=limit) if pinned is None else pinned)
            require_access()
            if type(page) is not SourceContextRootInventory:
                raise DerivationImpactIntegrityError("reverse dependency inventory is not typed")
            page.validate(after_id, limit)
            # Reuse each complete, authorized image read. Do not join mutable
            # workspace aliases or infer dependencies only from selected hits.
            images = {}
            for root in page.items:
                require_access()
                context = self.contexts.read(project_id, root.context_id)
                require_access()
                metadata = context["metadata"]
                if any(metadata.get(key) != value for key, value in (
                    ("project_id", project_id), ("context_id", root.context_id),
                    ("artifact_hash", root.context_artifact_hash),
                    ("image_revision_id", root.image_revision_id), ("image_artifact_hash", root.image_artifact_hash),
                )):
                    raise DerivationImpactIntegrityError("reverse dependency context pin mismatch")
                if root.image_revision_id not in images:
                    images[root.image_revision_id] = self.images.frozen_snapshot(project_id, root.image_revision_id)
                    require_access()
                header, image = images[root.image_revision_id]
                members = [item for item in image["source_members"] if item["binding_id"] == delta.before.binding_id]
                if (header.image_revision_id != root.image_revision_id or header.artifact_hash != root.image_artifact_hash
                        or len(members) != 1 or members[0]["status"] != "captured"
                        or members[0]["source_revision_id"] != before_revision_id):
                    raise DerivationImpactIntegrityError("reverse dependency is outside the frozen source membership")
                require_access()
            changed = (not delta.complete or delta.full_validation_required
                or any(delta.counts[kind] for kind in ("added", "modified", "deleted", "unresolved")))
            value = SourceContextRootsPage(project_id, delta.before, delta.after, delta.content_hash, page,
                bool(changed), scope.fingerprint)
            if len(json.dumps(asdict(value), ensure_ascii=False).encode("utf-8")) > 65536:
                raise DerivationImpactTooLarge("reverse source dependency page exceeds 64 KiB")
            require_access()
            return value
        except Exception:
            require_access()
            raise
