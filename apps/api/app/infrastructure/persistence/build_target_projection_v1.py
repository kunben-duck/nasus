"""Transaction-local validation of a v3 plan's original target, never repinning."""
from sqlalchemy import select

from ...domain.system_image.build_plan import BuildPlanIntegrityError, TargetedBuildIntent
from .db_models import BaselineRecord, VersionRecord
from .image_publication_models import ImagePublicationHeadRecord, ImagePublicationRecord


def require_build_target_scope(session, target, *, lock=True):
    baseline_query = select(BaselineRecord).where(BaselineRecord.id == target.target_baseline_id)
    baseline = session.scalar(baseline_query.with_for_update() if lock else baseline_query)
    if (baseline is None or baseline.project_id != target.project_id
            or baseline.source_version_id != target.target_version_id):
        raise BuildPlanIntegrityError("Build target baseline or version changed.")
    if target.target_version_id is not None:
        version_query = select(VersionRecord).where(VersionRecord.id == target.target_version_id)
        version = session.scalar(version_query.with_for_update() if lock else version_query)
        if version is None or version.project_id != target.project_id:
            raise BuildPlanIntegrityError("Build target version belongs to another project.")


def require_current_build_target(session, proposal, *, baseline_id=None):
    intent = proposal.intent
    if not isinstance(intent, TargetedBuildIntent):
        return
    target = intent.target
    if baseline_id is not None and baseline_id != target.target_baseline_id:
        raise BuildPlanIntegrityError("Work target differs from the original build intent.")
    require_build_target_scope(session, target)
    head = session.scalar(select(ImagePublicationHeadRecord).where(
        ImagePublicationHeadRecord.project_id == target.project_id,
        ImagePublicationHeadRecord.baseline_id == target.target_baseline_id).with_for_update())
    if (head.publication_id if head else None) != target.expected_head_id:
        raise BuildPlanIntegrityError("Build target publication head changed.")
    if head is not None:
        publication = session.get(ImagePublicationRecord, head.publication_id)
        if (publication is None or publication.project_id != target.project_id
                or publication.baseline_id != target.target_baseline_id or publication.sequence != head.sequence):
            raise BuildPlanIntegrityError("Build target publication failed integrity verification.")
        from .image_publication_repository import ImagePublicationRepository
        value = ImagePublicationRepository._value(publication, session=session)
        if value.get("image_artifact_hash") != target.expected_head_hash:
            raise BuildPlanIntegrityError("Build target publication image differs from the original intent.")
