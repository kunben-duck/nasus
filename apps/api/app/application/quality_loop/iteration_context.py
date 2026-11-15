"""Expose a verified requirement confirmation to the context compiler."""
from .requirement_review_models import ReviewSelection
from ...domain.system_image.context_pack import ContextIterationChanged, ContextPackIntegrityError


class IterationContextApplicationService:
    def __init__(self, reviews, delivery):
        self.reviews, self.delivery = reviews, delivery

    def pin(self, request, *, historical=False):
        selected = request.iteration
        selection = ReviewSelection(project_id=request.project_id, version_id=selected.version_id,
            revision_id=selected.requirement_revision_id)
        scope, revision, delivery = self.reviews._scope(selection, latest=False)
        events = self.reviews.repository.events(selection)
        confirmation = next((event for event in events if event["event_id"] == selected.confirmation_id
            and event["kind"] == "confirmed"), None)
        if confirmation is None or confirmation["content_hash"] != selected.confirmation_hash:
            raise ContextPackIntegrityError("Requirement confirmation cannot be verified")
        payload = confirmation["payload"]
        projection = payload["projection"]
        if (projection["image_revision_id"], projection["image_artifact_hash"]) != (
                request.image_revision_id, request.image_artifact_hash):
            raise ContextPackIntegrityError("Requirement confirmation belongs to another image")
        evaluation = next((event for event in events if event["event_id"] == payload["evaluation_id"]
            and event["kind"] == "evaluated"), None)
        if (evaluation is None or evaluation["content_hash"] != payload["review_digest"]
                or evaluation["payload"]["projection"] != projection
                or confirmation["actor_id"] in {revision.actor_id, evaluation["actor_id"]}
                or any(q["blocking"] for q in evaluation["payload"]["assessment"]["questions"])
                or not payload["approvals"]
                or set(payload["approvals"]) != {criterion["object_id"] for criterion in projection["criteria"]}):
            raise ContextPackIntegrityError("Requirement confirmation lacks independent complete approval")
        self.reviews.images.frozen_header(request.project_id, request.image_revision_id)
        for object_id, approval_id in payload["approvals"].items():
            approved = self.reviews.acceptance.read(request.project_id, approval_id)
            row = approved["revision"]
            if (row["image_revision_id"] != request.image_revision_id or row["object_id"] != object_id
                    or row["image_artifact_hash"] != request.image_artifact_hash
                    or row["status"] != "approved" or row["authority_actor"] != confirmation["actor_id"]):
                raise ContextPackIntegrityError("Requirement approval lineage differs")
        if not historical:
            view = self.reviews.read(selection)
            if (view["status"] != "confirmed" or not view["current"]
                    or view["confirmation"]["event_id"] != confirmation["event_id"]
                    or delivery.iteration_image.image_revision_id != request.image_revision_id
                    or delivery.iteration_image.image_artifact_hash != request.image_artifact_hash):
                raise ContextIterationChanged("Requirement approval or iteration image changed; prepare a new context")
        self.reviews.images.authorization.require_current(scope)
        return {"project_id": request.project_id, **selected.model_dump(mode="json"),
            "us_id": revision.us_id, "requirement_hash": revision.content_hash,
            "image_revision_id": request.image_revision_id, "image_artifact_hash": request.image_artifact_hash,
            "manifest_id": projection["manifest_id"], "manifest_hash": projection["manifest_hash"],
            "approval_ids": dict(payload["approvals"]),
            "code_revisions": self._code(request)}

    def _code(self, request):
        _, members = self.delivery.images.frozen_source_members(request.project_id, request.image_revision_id)
        # Binding display labels can change without changing the captured code.
        # They must not alter an already archived context's immutable identity.
        fields = ("binding_id", "source_id", "source_revision_id", "external_revision", "commit_sha", "content_hash", "manifest_hash")
        return [{key: value[key] for key in fields}
            for value in self.delivery.repository.code_revisions(request.project_id, members)]
