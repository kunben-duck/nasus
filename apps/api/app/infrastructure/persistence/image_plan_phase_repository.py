from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from ...application.agent.agent_models import AgentStep
from ...application.agent.image_plan_phases import ACTIVATE_PLAN_REVISION_TOOL, StoredImagePlanPhase, phase_steps
from ...application.platform.tool_handlers.query_input import query_payload
from ...application.platform.tool_models import EventPayload
from ...domain.agent.image_plan_phases import ImagePlanPhase, PHASE_REF, PHASE_PREPARED, phase_contract, verify_phase_chain
from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ...domain.system_image.build_authorization import ApprovedBuildBudget
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.build_plan_revisions import REVISION_PAUSE_REASONS
from ...domain.system_image.source_snapshots import snapshot_digest
from .build_plan_revision_repository import BuildPlanRevisionRepository
from .build_plan_revision_models import BuildPlanRevisionRecord
from .conversation_repository import ConversationRepository
from .db_models import AuditEventRecord, BaselineRecord, ToolInvocationRecord, UserIdentityRecord, VersionRecord
from .event_outbox_repository import EventOutboxRepository
from .image_plan_phase_models import ImagePlanPhaseRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .structure_build_models import StructureBuildArtifactRecord
from .unit_of_work import session_scope


class ImagePlanPhaseRepository:
    @staticmethod
    def _stored(row):
        payload = dict(row.payload)
        payload.update(budget=ApprovedBuildBudget(**payload["budget"]),
            checkpoint=AgentResumeCheckpoint.from_payload(payload["checkpoint"]), contracts=tuple(payload["contracts"]))
        phase = ImagePlanPhase(**payload)
        phase.require_valid()
        if (phase.phase_id, phase.project_id, phase.goal_id, phase.revision_id, phase.plan_id,
                phase.parent_phase_id, phase.phase_number, phase.invocation_id, phase.digest) != (
                row.phase_id, row.project_id, row.goal_id, row.revision_id, row.plan_id,
                row.parent_phase_id, row.phase_number, row.invocation_id, row.phase_hash):
            raise BuildPlanIntegrityError("Plan phase ledger failed its scope or digest check.")
        return StoredImagePlanPhase(phase, row.phase_hash)

    @classmethod
    def scope_in_session(cls, session, goal):
        records = [cls._stored(row) for row in session.scalars(select(ImagePlanPhaseRecord).where(
            ImagePlanPhaseRecord.goal_id == goal.id).order_by(ImagePlanPhaseRecord.phase_number).limit(81)).all()]
        start = verify_phase_chain(goal, [record.phase for record in records])
        return records, start

    def verify_goal(self, goal):
        with session_scope() as session:
            return self.scope_in_session(session, goal)

    def history(self, project_id, root_plan_id, goal_id):
        with session_scope() as session:
            row = BuildPlanRevisionRepository._goal(session, project_id, root_plan_id, goal_id)
            records, _ = self.scope_in_session(session, ConversationRepository._to_goal(row))
            if any(item.phase.root_plan_id != root_plan_id for item in records):
                raise BuildPlanIntegrityError("Plan phase root differs from its original goal.")
            return records

    def activate(self, request, revision, *, actor_id, invocation_id, created_at, require_current):
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, request.project_id)
            row = BuildPlanRevisionRepository._goal(session, request.project_id, request.root_plan_id, request.goal_id, lock=True)
            goal = ConversationRepository._to_goal(row)
            command = session.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.id == invocation_id).with_for_update())
            actor = session.get(UserIdentityRecord, actor_id)
            body = query_payload(command.input_payload) if command else {}
            confirmed_at, confirmed = body.pop("confirmed_at", None), body.pop("confirmed_by_user", None)
            if (command is None or command.tool_id != ACTIVATE_PLAN_REVISION_TOOL or command.status != "running"
                    or body != request.model_dump() or confirmed is not True or actor is None or actor.status != "active"
                    or command.input_payload.get("confirmed_actor_id") != actor_id or command.conversation_id != goal.conversation_id
                    or command.input_payload.get("agent_goal_id", goal.id) != goal.id):
                raise BuildPlanIntegrityError("Phase activation requires its exact independent canonical confirmation.")
            try:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(confirmed_at)).total_seconds()
                if not 0 <= elapsed <= 900:
                    raise ValueError("expired")
            except (TypeError, ValueError) as exc:
                raise BuildPlanIntegrityError("Plan phase confirmation expired.") from exc
            records, _ = self.scope_in_session(session, goal)
            existing = session.scalar(select(ImagePlanPhaseRecord).where(ImagePlanPhaseRecord.invocation_id == invocation_id))
            if existing is not None:
                saved = self._stored(existing)
                if (saved.phase.revision_id, saved.phase.revision_hash, saved.phase.checkpoint, saved.phase.budget,
                        saved.phase.parent_phase_id, saved.phase.parent_phase_hash) != (
                        request.revision_id, request.revision_hash, request.checkpoint(),
                        ApprovedBuildBudget(**request.budget.model_dump()), request.parent_phase_id, request.parent_phase_hash):
                    raise BuildPlanIntegrityError("Activation cannot change its original proposal.")
                require_current()
                return saved
            request.checkpoint().require_matches(goal.model_dump(mode="json"))
            if goal.status != "paused" or goal.pause_reason not in REVISION_PAUSE_REASONS:
                raise BuildPlanIntegrityError("Plan activation requires the original paused review checkpoint.")
            latest_revision = session.scalar(select(BuildPlanRevisionRecord).where(
                BuildPlanRevisionRecord.goal_id == goal.id).order_by(BuildPlanRevisionRecord.revision_number.desc()).limit(1))
            if latest_revision is None or (latest_revision.revision_id, latest_revision.revision_hash) != (request.revision_id, request.revision_hash):
                raise BuildPlanIntegrityError("Source-enrichment revision changed before activation.")
            parent = records[-1].phase if records else None
            if (request.parent_phase_id, request.parent_phase_hash) != (parent.phase_id if parent else None, parent.digest if parent else None):
                raise BuildPlanIntegrityError("Plan phase head changed; reread before activating.")
            if parent and revision.from_plan_id != parent.plan_id:
                raise BuildPlanIntegrityError("Activation must follow the active plan, without skipping a source revision.")
            targets = {step.tool_input_payload.get("target_baseline_id") for step in goal.steps
                if step.selected_tool_id == "system_image.build.structure"}
            if len(targets) != 1 or None in targets:
                raise BuildPlanIntegrityError("Original structural target is missing or ambiguous.")
            target, = targets
            baseline = session.scalar(select(BaselineRecord).where(BaselineRecord.id == target).with_for_update())
            if baseline is None or baseline.project_id != goal.project_id:
                raise BuildPlanIntegrityError("Original structural target is unavailable.")
            if baseline.source_version_id:
                version = session.scalar(select(VersionRecord).where(VersionRecord.id == baseline.source_version_id).with_for_update())
                if version is None or version.project_id != goal.project_id:
                    raise BuildPlanIntegrityError("Original structural target version is unavailable.")
            if parent and baseline.source_version_id != parent.target_version_id:
                raise BuildPlanIntegrityError("Original target version changed.")
            if parent is None:
                original_work = [step for step in goal.steps if step.selected_tool_id == "system_image.build.structure"
                    and step.tool_input_payload.get("plan_id") == request.root_plan_id]
                original_artifact = session.get(StructureBuildArtifactRecord, original_work[0].tool_invocation_id) if len(original_work) == 1 else None
                original_command = session.get(ToolInvocationRecord, original_artifact.invocation_id) if original_artifact else None
                if (original_artifact is None or original_artifact.project_id != goal.project_id
                        or original_artifact.plan_id != request.root_plan_id or original_artifact.target_baseline_id != target
                        or original_artifact.target_version_id != baseline.source_version_id
                        or original_artifact.plan_digest != original_work[0].tool_input_payload.get("plan_digest")
                        or original_command is None or original_command.tool_id != "system_image.build.structure"
                        or original_command.status != "completed" or original_command.conversation_id != goal.conversation_id):
                    raise BuildPlanIntegrityError("Original structural artifact target changed; prepare a separately scoped goal.")
            phase_id = str(uuid4())
            steps = phase_steps(goal, phase_id, request, revision, target)
            phase = ImagePlanPhase(phase_id=phase_id, project_id=goal.project_id, goal_id=goal.id, root_plan_id=request.root_plan_id,
                revision_id=revision.revision_id, revision_hash=request.revision_hash, plan_id=revision.plan_id,
                plan_digest=revision.plan_digest, source_manifest_id=revision.source_manifest_id,
                source_manifest_hash=revision.source_manifest_hash, target_baseline_id=target, target_version_id=baseline.source_version_id,
                parent_phase_id=request.parent_phase_id, parent_phase_hash=request.parent_phase_hash,
                phase_number=len(records) + 1, start_index=len(goal.steps),
                prefix_hash=snapshot_digest([step.model_dump(mode="json") for step in goal.steps]),
                contracts=tuple(phase_contract(step) for step in steps), budget=ApprovedBuildBudget(**request.budget.model_dump()),
                checkpoint=request.checkpoint(), invocation_id=invocation_id, created_at=created_at)
            phase.require_valid()
            marker = AgentStep(id=PHASE_REF + phase_id, title="Activate reviewed source-enrichment phase", status="completed",
                phase="deciding", tool_input_payload=phase.marker(), decision="continue")
            goal.steps.extend([marker, *steps])
            goal.target_refs = [ref for ref in goal.target_refs if not ref.startswith(PHASE_REF)] + [PHASE_REF + phase_id]
            goal.pause_reason = PHASE_PREPARED
            verify_phase_chain(goal, [*[item.phase for item in records], phase])
            row.steps, row.target_refs, row.pause_reason = [step.model_dump(mode="json") for step in goal.steps], goal.target_refs, goal.pause_reason
            saved = ImagePlanPhaseRecord(phase_id=phase_id, project_id=phase.project_id, goal_id=goal.id,
                revision_id=phase.revision_id, plan_id=phase.plan_id, parent_phase_id=phase.parent_phase_id,
                phase_number=phase.phase_number, invocation_id=invocation_id, payload=asdict(phase), phase_hash=phase.digest)
            session.add(saved)
            session.add(AuditEventRecord(id=str(uuid4()), occurred_at=created_at, actor=actor_id, actor_kind="user",
                action="agent.image_plan_phase.activated", entity_type="agent_image_plan_phase", entity_id=phase_id,
                status="paused", summary="Original-goal phase prepared; independent execution consent is still required.",
                conversation_id=goal.conversation_id, tool_invocation_id=invocation_id, agent_goal_id=goal.id,
                object_refs=[], evidence_refs=[], event_metadata={"project_id": goal.project_id}))
            EventOutboxRepository().append(EventPayload(event_id=str(uuid4()), event_type="agent.image_plan_phase.activated",
                occurred_at=created_at, correlation_id=goal.project_id, entity_type="agent_image_plan_phase", entity_id=phase_id,
                entity_version=0, mutation_kind="append", patch={"project_id": goal.project_id, "goal_id": goal.id},
                query_keys=[["system-image-build-plans", goal.project_id], ["conversation", goal.conversation_id]]), session=session)
            session.flush()
            require_current()
            return self._stored(saved)
