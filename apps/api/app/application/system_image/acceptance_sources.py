from ...domain.quality_loop.acceptance_specification import AcceptanceIntegrityError
from ...domain.system_image.image_revision import ImageRevisionPageTooLarge
from .image_revision_queries import ImageRevisionQueryApplicationService


class FrozenRequirementSourceApplicationService:
    """Source proof for quality_loop; source projections themselves never become approved."""

    def __init__(self, images: ImageRevisionQueryApplicationService, *, kind):
        self.images = images
        if kind not in {"acceptance_criterion", "business_rule"}:
            raise ValueError("unsupported requirement authority source")
        self.kind = kind

    def inspect(self, project_id, image_revision_id, image_hash, object_id):
        # Reuse only this operation's fixed image, including an enclosing compiler.
        with self.images.verified_read_session(reuse=True):
            return self._inspect(project_id, image_revision_id, image_hash, object_id)

    def _inspect(self, project_id, image_revision_id, image_hash, object_id):
        scope = self.images.authorization.scope(project_id)
        header, payload = self.images.frozen_snapshot(project_id, image_revision_id)
        if header.artifact_hash != image_hash:
            raise AcceptanceIntegrityError("acceptance image digest mismatch")
        member = next((item for item in payload["members"] if item["object_id"] == object_id), None)
        if not member or member["kind"] != "source_document":
            raise ValueError("acceptance authority requires a frozen source AC")
        page = self.images.read_document(project_id, image_revision_id, object_id, limit=90)
        if page["next_offset"] is not None or len(page["fields"]) != page["total_fields"]:
            raise ImageRevisionPageTooLarge("acceptance source must fit one complete field page")
        document, projection, fields = page["document"], page["projection"], page["fields"]
        if (document["kind"] != self.kind or not document.get("parent_document_revision_id")
                or not fields or any(f["name"] != self.kind or not f["value"].strip() for f in fields)):
            raise ValueError("authority source must have the exact explicit requirement component kind")
        evidence = []
        for field in fields:
            match = [e for e in page["evidence"] if (e["start_line"], e["end_line"], e["snippet_hash"]) ==
                     (field["start_line"], field["end_line"], field["snippet_hash"])]
            if not match:
                raise AcceptanceIntegrityError("acceptance source field has no frozen evidence")
            evidence.extend(e["evidence_id"] for e in match)
        evidence_ids = sorted(set(evidence))
        self.images.verify_evidence_selection(project_id, image_revision_id, tuple((object_id, e) for e in evidence_ids))
        result = {"project_id": project_id, "image_revision_id": image_revision_id, "image_artifact_hash": image_hash,
                  "object_id": object_id, "document_revision_id": document["document_revision_id"],
                  "parent_document_revision_id": document["parent_document_revision_id"], "entity_id": document["entity_id"],
                  "binding_id": document["binding_id"], "source_revision_id": document["source_revision_id"],
                  "payload_hash": page["payload_hash"], "evidence_ids": evidence_ids, "fields": fields,
                  "source_authority": "unapproved_source_projection", "locator": projection["locator"]}
        if len(str(result).encode()) > 24576:
            raise ImageRevisionPageTooLarge("acceptance source exceeds 24 KiB approval budget")
        self.images.authorization.require_current(scope)
        return result


class FrozenAcceptanceSourceApplicationService(FrozenRequirementSourceApplicationService):
    def __init__(self, images):
        super().__init__(images, kind="acceptance_criterion")


class FrozenBusinessRuleSourceApplicationService(FrozenRequirementSourceApplicationService):
    def __init__(self, images):
        super().__init__(images, kind="business_rule")
