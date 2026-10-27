"""Publication selects an immutable knowledge snapshot, not a quality verdict."""
from datetime import datetime, timezone

from .source_snapshots import snapshot_digest


PUBLICATION_POLICY = "nasus.image-publication.v1"
PUBLICATION_REVIEW_TOOL = "system_image.revisions.review_publication"
PUBLICATION_QUERY_TOOL = "query.system_image.publication"
PUBLICATION_HEAD_TOOL = "query.system_image.publication.head"
ROLLBACK_POLICY = "nasus.image-rollback.v1"
ROLLBACK_QUERY_TOOL = "query.system_image.publication.rollback"
ROLLBACK_REVIEW_TOOL = "system_image.revisions.review_rollback"
ROLLBACK_TOOL = "baseline.rollback"
APPROVAL_SECONDS = 1800


class PublicationChanged(ValueError):
    pass


class PublicationIntegrityError(ValueError):
    pass


def publication_claim(request):
    return snapshot_digest(request)


def require_live_approval(approval, *, claim, previous_review_id, now=None, policy=PUBLICATION_POLICY):
    if (approval["claim_digest"] != claim or approval["review_id"] != previous_review_id
            or approval["decision"] != "approve" or approval["policy_revision"] != policy):
        raise PublicationChanged("Publication approval does not match the current reviewed proposal")
    age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(approval["recorded_at"])).total_seconds()
    if not 0 <= age <= APPROVAL_SECONDS:
        raise PublicationChanged("Publication approval expired; review again")
