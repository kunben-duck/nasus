from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.system_image.structure_builds import STRUCTURE_EXECUTOR, StructureBuildTarget, StructureBuildCancelled
from ...application.platform.tool_models import EventPayload
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from .build_plan_repository import BuildPlanRepository
from .build_plan_models import BuildPlanRecord
from .db_models import AgentGoalRecord, BaselineRecord, ConversationRecord, ProjectRecord, ToolInvocationRecord, VersionRecord
from .image_revision_models import ImageRevisionRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_repository import SourceSnapshotRepository
from .structure_build_models import StructureBuildArtifactRecord
from .code_index_generation_models import CodeIndexGenerationRecord, CodeIndexWorkerLeaseRecord
from .build_authorization_repository import BuildAuthorizationRepository
from .unit_of_work import session_scope
from .build_target_projection_v1 import require_current_build_target


class StructureBuildRepository:
    @staticmethod
    def validate_in_session(session, binding):
        # Lock the invocation through candidate commit; cancellation cannot
        # interleave between validating the running command and saving facts.
        invocation = session.scalar(select(ToolInvocationRecord).where(
            ToolInvocationRecord.id == binding.invocation_id).with_for_update())
        if invocation is not None and invocation.status == "cancelled":
            raise StructureBuildCancelled("Structural invocation was cancelled.")
        if (binding.executor_version != STRUCTURE_EXECUTOR or invocation is None
                or invocation.tool_id != "system_image.build.structure" or invocation.status != "running"):
            raise BuildPlanIntegrityError("Structural work requires a running, confirmed canonical invocation.")
        from .structure_job_repository import StructureJobRepository
        StructureJobRepository.require_not_cancelled_in_session(session, invocation)
        cancelled_index = session.scalar(select(CodeIndexWorkerLeaseRecord).join(CodeIndexGenerationRecord,
            CodeIndexGenerationRecord.generation_id == CodeIndexWorkerLeaseRecord.generation_id).where(
                CodeIndexGenerationRecord.invocation_id == binding.invocation_id,
                CodeIndexWorkerLeaseRecord.state.in_(("cancel_requested", "cancelled"))).order_by(
                    CodeIndexWorkerLeaseRecord.generation_id).limit(1).with_for_update(of=CodeIndexWorkerLeaseRecord))
        if cancelled_index is not None:
            raise StructureBuildCancelled("Structural native code indexing was cancelled.")
        for key in ("project_id", "plan_id", "plan_digest", "target_baseline_id"):
            if invocation.input_payload.get(key) != getattr(binding, key):
                raise BuildPlanIntegrityError("Structural work differs from the confirmed request.")
        grant = BuildAuthorizationRepository.validate_grant_in_session(session, invocation)
        if grant is None and invocation.input_payload.get("confirmed_by_user") is not True:
            raise BuildPlanIntegrityError("Structural work requires confirmation or reserved execution consent.")
        confirmed_at = grant.confirmed_at if grant is not None else invocation.input_payload.get("confirmed_at")
        try:
            if datetime.fromisoformat(confirmed_at).tzinfo is None:
                raise ValueError("missing timezone")
        except (TypeError, ValueError):
            raise BuildPlanIntegrityError("Structural work has no valid confirmation timestamp.")
        if invocation.conversation_id:
            conversation = session.get(ConversationRecord, invocation.conversation_id)
            if conversation is None or conversation.project_id != binding.project_id:
                raise BuildPlanIntegrityError("Structural work conversation mismatch.")
        goal_id = invocation.input_payload.get("agent_goal_id")
        if goal_id:
            goal = session.scalar(select(AgentGoalRecord).where(AgentGoalRecord.id == goal_id).with_for_update())
            if (goal is None or goal.project_id != binding.project_id or goal.conversation_id != invocation.conversation_id
                    or goal.status not in {"running", "waiting_confirmation"}):
                raise BuildPlanIntegrityError("Structural work goal is no longer executable.")
        plan_row = session.get(BuildPlanRecord, binding.plan_id)
        if plan_row is None or plan_row.project_id != binding.project_id:
            raise BuildPlanIntegrityError("Structural work plan mismatch.")
        plan = BuildPlanRepository._stored(session, plan_row)
        if plan.plan_digest != binding.plan_digest:
            raise BuildPlanIntegrityError("Structural work plan digest mismatch.")
        require_current_build_target(session, plan.proposal, baseline_id=binding.target_baseline_id)
        if grant is not None and (grant.source_manifest_id != plan.proposal.intent.source_manifest_id
                                 or grant.source_manifest_hash != plan.proposal.intent.source_manifest_hash):
            raise BuildPlanIntegrityError("Structural source scope differs from execution consent.")
        project = session.scalar(select(ProjectRecord).where(ProjectRecord.id == binding.project_id).with_for_update())
        baseline = session.scalar(select(BaselineRecord).where(BaselineRecord.id == binding.target_baseline_id).with_for_update())
        if project is None or baseline is None or baseline.project_id != binding.project_id:
            raise BuildPlanIntegrityError("Structural work requires an existing project baseline target.")
        if baseline.source_version_id:
            version = session.scalar(select(VersionRecord).where(VersionRecord.id == baseline.source_version_id).with_for_update())
            if version is None or version.project_id != binding.project_id:
                raise BuildPlanIntegrityError("Structural work version mismatch.")
        return StructureBuildTarget(project.name, baseline.source_version_id, confirmed_at,
                                    grant.budget.max_active_seconds if grant is not None else None), plan

    def validate(self, binding):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, binding.project_id)
            return self.validate_in_session(session, binding)[0]

    @staticmethod
    def existing_in_session(session, binding):
        row = session.get(StructureBuildArtifactRecord, binding.invocation_id)
        if row is not None and any(getattr(row, key) != value for key, value in asdict(binding).items()):
            raise BuildPlanIntegrityError("Structural invocation already belongs to a different artifact.")
        return row

    def completed(self, binding):
        with session_scope() as session:
            row = self.existing_in_session(session, binding)
            if row is None:
                return None
            image = session.get(ImageRevisionRecord, row.image_revision_id)
            if image is None or image.project_id != binding.project_id or image.baseline_id != binding.target_baseline_id:
                raise BuildPlanIntegrityError("Structural artifact target mismatch.")
            from .image_revision_repository import ImageRevisionRepository
            return ImageRevisionRepository._summary(image)

    @classmethod
    def attach(cls, session, commit, candidate):
        binding = commit.binding
        existing = cls.existing_in_session(session, binding)
        if existing is not None:
            if existing.image_revision_id != candidate.image_revision_id:
                raise BuildPlanIntegrityError("Structural invocation already produced a different candidate.")
        else:
            session.add(StructureBuildArtifactRecord(**asdict(binding), image_revision_id=candidate.image_revision_id,
                target_version_id=commit.target.version_id, confirmed_at=commit.target.confirmed_at, lineage_required=True))
            EventOutboxRepository().append(EventPayload(
                event_id=str(uuid4()), event_type="system_image.build.structure.completed", occurred_at=datetime.now(timezone.utc).isoformat(),
                correlation_id=binding.project_id, entity_type="image_build_plan", entity_id=binding.plan_id,
                entity_version=0, mutation_kind="append", patch={"project_id": binding.project_id,
                    "plan_id": binding.plan_id, "image_revision_id": candidate.image_revision_id, "invocation_id": binding.invocation_id},
                query_keys=[["system-image-build-plans", binding.project_id], ["system-image-revisions", binding.project_id]],
            ), session=session)
        session.flush()
        from .build_lineage_repository import StructureBuildLineageRepository
        StructureBuildLineageRepository.attach(session, commit, candidate)
        commit.require_current()
