"""Real PG/MinIO publication probe; synthetic reviewer, never business approval."""
from datetime import datetime, timezone
from uuid import uuid4

from apps.api.app.application.system_image.publications import (
    ImagePublicationApplicationService, PublicationTarget, PublicationReviewInput, PublicationPublishInput,
)
from apps.api.app.domain.system_image.publication import PUBLICATION_REVIEW_TOOL
from apps.api.app.infrastructure.persistence.db_models import BaselineRecord, ToolInvocationRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.image_publication_repository import ImagePublicationRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def publish_exweb_fixture(image_queries, snapshots, authorization, header):
    now = datetime.now(timezone.utc).isoformat()
    actor_id = authorization.scope(header.project_id).actor_id
    with session_scope() as session:
        session.add(BaselineRecord(id=header.baseline_id, project_id=header.project_id, kind="official", updated_at=now))
        session.add(UserIdentityRecord(user_id=actor_id, email="exweb-publication-fixture@example.invalid",
            display_name="Explicit fixture reviewer", role="platform_admin", password_hash="disabled-fixture-account",
            status="active", created_at=now, updated_at=now))
    service = ImagePublicationApplicationService(image_queries, snapshots, authorization, ImagePublicationRepository())
    target = PublicationTarget(project_id=header.project_id, image_revision_id=header.image_revision_id,
        image_artifact_hash=header.artifact_hash, target_baseline_id=header.baseline_id, expected_head_id=None)
    before = image_queries.frozen_snapshot(header.project_id, header.image_revision_id)
    preview = service.preview(target)
    assert preview["head"] is None and preview["review"] is None
    review_request = PublicationReviewInput(**target.model_dump(), expected_preview_digest=preview["preview_digest"],
        expected_review_id=None, decision="approve", reason="Static exweb knowledge fixture; not maintainer or business acceptance")
    review_invocation = str(uuid4())
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=review_invocation, tool_id=PUBLICATION_REVIEW_TOOL, status="running",
            summary="Explicit fixture publication review", input_payload={**review_request.model_dump(mode="json"), "confirmed_by_user": True}))
    review = service.review(review_request, invocation_id=review_invocation, recorded_at=now)
    assert service.history(header.project_id, header.baseline_id)["head"] is None
    publish_request = PublicationPublishInput(**target.model_dump(), expected_preview_digest=preview["preview_digest"],
        approval_id=review["review_id"])
    invocation = str(uuid4())
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation, tool_id="baseline.promote", status="running",
            summary="Publish exact fixture snapshot", input_payload=publish_request.model_dump(mode="json")))
    head = service.publish(publish_request, invocation_id=invocation, recorded_at=now)
    assert service.publish(publish_request, invocation_id=invocation, recorded_at=now) == head
    assert service.history(header.project_id, header.baseline_id)["head"] == head
    assert head["image_artifact_hash"] == header.artifact_hash and head["manifest_hash"] == header.manifest_hash
    assert head["sequence"] == 1 and head["quality_generation_authorized"] is False and head["release_authorized"] is False
    assert image_queries.frozen_snapshot(header.project_id, header.image_revision_id) == before
    return service, target, head


def advance_exweb_publication(service, target, header):
    """Publish another actual frozen candidate to the same explicit fixture target."""
    now = datetime.now(timezone.utc).isoformat()
    head = service.history(header.project_id, target.target_baseline_id)["head"]
    target = target.model_copy(update={"image_revision_id": header.image_revision_id,
        "image_artifact_hash": header.artifact_hash, "expected_head_id": head["publication_id"]})
    preview = service.preview(target)
    review = PublicationReviewInput(**target.model_dump(), expected_preview_digest=preview["preview_digest"],
        expected_review_id=None, decision="approve", reason="Explicit updated companion fixture; not real business acceptance")
    review_id = str(uuid4())
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=review_id, tool_id=PUBLICATION_REVIEW_TOOL, status="running",
            summary="Review next fixture publication", input_payload={**review.model_dump(mode="json"), "confirmed_by_user": True}))
    approved = service.review(review, invocation_id=review_id, recorded_at=now)
    request = PublicationPublishInput(**target.model_dump(), expected_preview_digest=preview["preview_digest"],
        approval_id=approved["review_id"])
    invocation = str(uuid4())
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation, tool_id="baseline.promote", status="running",
            summary="Publish next fixture knowledge image", input_payload=request.model_dump(mode="json")))
    return service.publish(request, invocation_id=invocation, recorded_at=now)
