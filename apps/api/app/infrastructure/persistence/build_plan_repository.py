from __future__ import annotations

from dataclasses import asdict
import json
from uuid import uuid4

from sqlalchemy import exists, select

from ...application.platform.tool_models import EventPayload
from ...application.system_image.build_plans import BuildPlanInput, StoredBuildPlan, StructureArtifactSummary, BuildAuthorizationSummary
from ...application.platform.tool_handlers.query_input import query_payload
from ...domain.system_image.build_authorization import authorization_from_dict
from ...domain.system_image.build_plan import BuildPlanIntegrityError, TargetedBuildIntent, MAX_PLAN_BYTES, decode_build_plan
from .build_target_projection_v1 import require_build_target_scope, require_current_build_target
from .build_plan_models import BuildPlanInvocationRecord, BuildPlanRecord
from .db_models import AgentGoalRecord, ConversationRecord, ToolInvocationRecord
from .event_outbox_repository import EventOutboxRepository
from .source_snapshot_models import SourceManifestMemberRecord, SourceManifestRecord
from .source_snapshot_repository import SourceSnapshotRepository
from .unit_of_work import session_scope
from .structure_build_models import StructureBuildArtifactRecord
from .image_revision_models import ImageRevisionRecord
from .build_authorization_models import BuildAuthorizationRecord, BuildWorkReservationRecord


class BuildPlanRepository:
    def verify_target_scope(self, target):
        with session_scope() as session:
            # This read also runs inside another connection's final commit check.
            require_build_target_scope(session, target, lock=False)

    @staticmethod
    def _stored(session, row):
        if len(json.dumps(row.payload, ensure_ascii=False).encode()) > MAX_PLAN_BYTES:
            raise BuildPlanIntegrityError("Build plan exceeds the artifact limit.")
        proposal = decode_build_plan(row.payload)
        intent = proposal.intent
        if (row.project_id != intent.project_id or row.manifest_id != intent.source_manifest_id
                or row.plan_digest != proposal.digest or row.state != proposal.state):
            raise BuildPlanIntegrityError("Build plan record digest mismatch.")
        manifest_row = session.get(SourceManifestRecord, row.manifest_id)
        if manifest_row is None:
            raise BuildPlanIntegrityError("Build plan manifest is missing.")
        manifest = SourceSnapshotRepository._manifest(session, manifest_row)
        if (manifest.project_id != row.project_id or manifest.content_hash != intent.source_manifest_hash
                or manifest.members != intent.sources):
            raise BuildPlanIntegrityError("Build plan input membership mismatch.")
        receipts = session.scalars(select(StructureBuildArtifactRecord).where(
            StructureBuildArtifactRecord.project_id == row.project_id, StructureBuildArtifactRecord.plan_id == row.plan_id
        ).order_by(StructureBuildArtifactRecord.confirmed_at.desc(), StructureBuildArtifactRecord.invocation_id).limit(20)).all()
        artifacts = []
        for receipt in receipts:
            image = session.get(ImageRevisionRecord, receipt.image_revision_id)
            if (receipt.plan_digest != row.plan_digest or image is None or image.project_id != row.project_id
                    or image.manifest_id != row.manifest_id or image.baseline_id != receipt.target_baseline_id):
                raise BuildPlanIntegrityError("Structural artifact does not match its plan inputs and target.")
            artifacts.append(StructureArtifactSummary(receipt.invocation_id, receipt.image_revision_id,
                receipt.target_baseline_id, receipt.confirmed_at))
        authorizations = []
        grants = session.scalars(select(BuildAuthorizationRecord).where(BuildAuthorizationRecord.project_id == row.project_id,
            BuildAuthorizationRecord.plan_id == row.plan_id).order_by(BuildAuthorizationRecord.authorization_id).limit(20)).all()
        for saved in grants:
            grant = authorization_from_dict(saved.payload)
            if (grant.digest != saved.content_hash or grant.authorization_id != saved.authorization_id
                    or grant.goal_id != saved.goal_id or grant.authorization_invocation_id != saved.authorization_invocation_id
                    or grant.project_id != row.project_id or grant.plan_id != row.plan_id or grant.plan_digest != row.plan_digest
                    or grant.source_manifest_id != row.manifest_id or grant.source_manifest_hash != manifest.content_hash):
                raise BuildPlanIntegrityError("Execution consent differs from the saved investigation plan.")
            reservations = session.scalars(select(BuildWorkReservationRecord.work_item_id).where(
                BuildWorkReservationRecord.authorization_id == grant.authorization_id).order_by(BuildWorkReservationRecord.work_item_id)).all()
            authorizations.append(BuildAuthorizationSummary(grant.authorization_id, grant.goal_id, grant.target_baseline_id,
                grant.target_version_id, grant.confirmed_at, grant.budget, grant.work_item_ids, tuple(reservations),
                tuple(item.work_item_id for item in proposal.work_items if item.work_item_id not in grant.work_item_ids)))
        return StoredBuildPlan(row.plan_id, row.project_id, row.plan_digest, row.created_at, proposal, tuple(artifacts), tuple(authorizations))

    @staticmethod
    def _invocation(session, invocation_id, project_id, proposal=None):
        invocation = session.get(ToolInvocationRecord, invocation_id)
        if (invocation is None or invocation.tool_id != "system_image.build.plan"
                or invocation.status != "running" or invocation.input_payload.get("project_id") != project_id):
            raise BuildPlanIntegrityError("Build plan requires a running canonical invocation.")
        if proposal is not None and isinstance(proposal.intent, TargetedBuildIntent):
            request = BuildPlanInput.model_validate(query_payload(invocation.input_payload))
            intent = proposal.intent
            if (request.source_manifest_id != intent.source_manifest_id or request.objective.strip() != intent.objective
                    or request.mode != intent.mode or request.purpose != intent.purpose
                    or request.budget.model_dump() != asdict(intent.budget)
                    or request.target is None or request.target.model_dump() != asdict(intent.target)):
                raise BuildPlanIntegrityError("Build intent differs from the canonical command.")
        if invocation.conversation_id:
            conversation = session.get(ConversationRecord, invocation.conversation_id)
            if conversation is None or conversation.project_id != project_id:
                raise BuildPlanIntegrityError("Build plan conversation scope mismatch.")
        goal_id = invocation.input_payload.get("agent_goal_id")
        if goal_id:
            goal = session.get(AgentGoalRecord, goal_id)
            if goal is None or goal.project_id != project_id or goal.conversation_id != invocation.conversation_id:
                raise BuildPlanIntegrityError("Build plan goal scope mismatch.")

    def record(self, proposal, *, actor_id, invocation_id, created_at, require_current_scope):
        payload = json.loads(json.dumps(asdict(proposal), ensure_ascii=False))
        if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_PLAN_BYTES:
            raise ValueError("Build plan exceeds the artifact limit.")
        with session_scope() as session:
            SourceSnapshotRepository._lock(session, proposal.intent.project_id)
            self._invocation(session, invocation_id, proposal.intent.project_id, proposal)
            require_current_build_target(session, proposal)
            existing_link = session.get(BuildPlanInvocationRecord, invocation_id)
            row = session.scalar(select(BuildPlanRecord).where(
                BuildPlanRecord.project_id == proposal.intent.project_id, BuildPlanRecord.plan_digest == proposal.digest))
            if existing_link and (row is None or existing_link.plan_id != row.plan_id
                                  or existing_link.project_id != proposal.intent.project_id):
                raise BuildPlanIntegrityError("Invocation is already bound to another build plan.")
            created = row is None
            if created:
                row = BuildPlanRecord(plan_id=str(uuid4()), project_id=proposal.intent.project_id,
                    manifest_id=proposal.intent.source_manifest_id, plan_digest=proposal.digest, payload=payload,
                    created_at=created_at, created_by=actor_id, state=proposal.state)
            # Historical manifests are valid planning inputs. Execution must
            # separately validate its approved scope and expected image head.
            stored = self._stored(session, row)
            if stored.proposal != proposal:
                raise BuildPlanIntegrityError("Build plan digest collision.")
            if created:
                session.add(row)
                session.flush()
            if existing_link is None:
                session.add(BuildPlanInvocationRecord(invocation_id=invocation_id, project_id=row.project_id, plan_id=row.plan_id))
                EventOutboxRepository().append(EventPayload(
                    event_id=str(uuid4()), event_type="system_image.build.plan.proposed", occurred_at=created_at,
                    correlation_id=row.project_id, entity_type="image_build_plan", entity_id=row.plan_id,
                    entity_version=0, mutation_kind="append", patch={"project_id": row.project_id, "plan_id": row.plan_id},
                    query_keys=[["system-image-build-plans", row.project_id]],
                ), session=session)
            session.flush()
            require_current_scope()
            return stored

    def get(self, project_id, plan_id):
        with session_scope() as session:
            row = session.get(BuildPlanRecord, plan_id)
            if row is None or row.project_id != project_id:
                raise KeyError("build plan not found")
            return self._stored(session, row)

    def list(self, project_id, *, binding_ids, after_id, limit):
        if type(limit) is not int or not 1 <= limit <= 51:
            raise ValueError("Invalid build plan page size.")
        model, member = BuildPlanRecord, SourceManifestMemberRecord
        denied = exists(select(1).where(member.project_id == model.project_id,
            member.manifest_id == model.manifest_id, member.binding_id.not_in(binding_ids)))
        with session_scope() as session:
            rows = session.scalars(select(model).where(model.project_id == project_id, ~denied,
                model.plan_id > after_id).order_by(model.plan_id).limit(limit)).all()
            return [self._stored(session, row) for row in rows]
