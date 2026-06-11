from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import delete, select

from .database import SessionLocal
from .db_models import (
    ApprovalRecord,
    AgentGoalRecord,
    AssetLaneRecord,
    BaselineRecord as BaselineRow,
    ConversationMessageRecord,
    ConversationRecord,
    ConversationSummaryCheckpointRecord,
    ContextObjectOverlayRecord,
    ContextRelationshipRecord,
    KnowledgeObjectRecord,
    ProjectRecord,
    QualityMetricSnapshotRecord,
    RawAssetRecord as RawAssetRow,
    ReleaseReadinessRecord,
    RunRecord,
    SessionKnowledgeBindingRecord,
    SettingsRecord,
    ToolInvocationRecord,
    USWorkItemRecord,
    VersionRecord,
)
from .models import (
    AgentGoal,
    AgentStep,
    ApprovalDetail,
    ApprovalSummary,
    AssetLane,
    BaselineRecord,
    ConversationMessage,
    ConversationSession,
    ConversationSummaryCheckpoint,
    ContextObjectOverlay,
    ContextRelationship,
    CustomModelConfig,
    KnowledgeObject,
    MessageBlock,
    ProjectCard,
    QualityMetricSnapshot,
    RawAssetRecord,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    SessionKnowledgeBinding,
    StudioSettings,
    ToolInvocation,
    ToolResult,
    USItem,
    VersionSummary,
)


@contextmanager
def session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class SettingsRepository:
    def load(self) -> tuple[dict[str, Any], str]:
        with session_scope() as session:
            record = session.get(SettingsRecord, 1)
            if record is None:
                return self._defaults(), ""

            custom = record.custom_model or {}
            encrypted_secret = record.custom_api_key_encrypted or ""
            loaded = {
                "language": record.language,
                "theme": record.theme,
                "notification_mode": record.notification_mode,
                "model_preset": record.model_preset,
                "custom_model": {
                    "provider_kind": custom.get("provider_kind", "openai_compatible"),
                    "base_url": custom.get("base_url"),
                    "model_name": custom.get("model_name", ""),
                    "has_api_key": bool(encrypted_secret),
                    "api_key_masked": custom.get("api_key_masked"),
                },
            }
            return loaded, encrypted_secret

    def save(self, settings: StudioSettings, encrypted_custom_api_key: str) -> None:
        with session_scope() as session:
            record = session.get(SettingsRecord, 1)
            if record is None:
                record = SettingsRecord(settings_id=1)
                session.add(record)

            record.language = settings.language
            record.theme = settings.theme
            record.notification_mode = settings.notification_mode
            record.model_preset = settings.model_preset
            record.custom_model = {
                "provider_kind": settings.custom_model.provider_kind,
                "base_url": settings.custom_model.base_url,
                "model_name": settings.custom_model.model_name,
                "api_key_masked": settings.custom_model.api_key_masked,
            }
            record.custom_api_key_encrypted = encrypted_custom_api_key or None

    @staticmethod
    def _defaults() -> dict[str, Any]:
        return {
            "language": "zh",
            "theme": "dark",
            "notification_mode": "important",
            "model_preset": "system_default",
            "custom_model": CustomModelConfig().model_dump(),
        }


class ConversationRepository:
    def load_all(self) -> list[ConversationSession]:
        with session_scope() as session:
            conversations = session.scalars(select(ConversationRecord)).all()
            message_rows = session.scalars(select(ConversationMessageRecord)).all()
            goal_rows = session.scalars(select(AgentGoalRecord)).all()

        messages_by_conversation: dict[str, list[ConversationMessage]] = {}
        for row in message_rows:
            messages_by_conversation.setdefault(row.conversation_id, []).append(self._to_message(row))
        for items in messages_by_conversation.values():
            items.sort(key=lambda item: item.created_at)

        goals_by_conversation: dict[str, list[AgentGoal]] = {}
        for row in goal_rows:
            goals_by_conversation.setdefault(row.conversation_id, []).append(self._to_goal(row))

        return [
            self._to_conversation(
                row,
                messages_by_conversation.get(row.id, []),
                goals_by_conversation.get(row.id, []),
            )
            for row in conversations
        ]

    def upsert_conversation(self, conversation: ConversationSession) -> None:
        with session_scope() as session:
            record = session.get(ConversationRecord, conversation.id)
            if record is None:
                record = ConversationRecord(id=conversation.id)
                session.add(record)

            record.session_id = conversation.session_id
            record.title = conversation.title
            record.space_type = conversation.space_type
            record.space_id = conversation.space_id
            record.project_id = conversation.project_id
            record.version_id = conversation.version_id
            record.us_id = conversation.us_id
            record.task_id = conversation.task_id
            record.initiator_id = conversation.initiator_id
            record.status = conversation.status
            record.last_message_at = conversation.last_message_at
            record.latest_summary_checkpoint_id = conversation.latest_summary_checkpoint_id
            record.merged_into_conversation_id = conversation.merged_into_conversation_id
            record.archived_at = conversation.archived_at
            record.related_conversation_ids = conversation.related_conversation_ids

    def append_message(self, conversation_id: str, message: ConversationMessage) -> None:
        with session_scope() as session:
            record = ConversationMessageRecord(
                id=message.id,
                conversation_id=conversation_id,
                role=message.role,
                status=message.status,
                content_type=message.content_type,
                created_at=message.created_at,
                blocks=[block.model_dump() for block in message.blocks],
                tool_refs=message.tool_refs,
                object_refs=message.object_refs,
                message_metadata=message.metadata,
                stream_id=message.stream_id,
                sequence_max=message.sequence_max,
            )
            session.add(record)

            conversation = session.get(ConversationRecord, conversation_id)
            if conversation is not None:
                conversation.last_message_at = message.created_at
                if conversation.status in {"draft", "idle"}:
                    conversation.status = "active"

    def replace_goals(self, conversation_id: str, goals: list[AgentGoal]) -> None:
        with session_scope() as session:
            session.execute(delete(AgentGoalRecord).where(AgentGoalRecord.conversation_id == conversation_id))
            for goal in goals:
                session.add(
                    AgentGoalRecord(
                        id=goal.id,
                        conversation_id=goal.conversation_id,
                        project_id=goal.project_id,
                        us_id=goal.us_id,
                        title=goal.title,
                        status=goal.status,
                        summary=goal.summary,
                        steps=[step.model_dump() for step in goal.steps],
                        autonomy_level=goal.autonomy_level,
                        max_steps=goal.max_steps,
                        steps_completed=goal.steps_completed,
                        pause_reason=goal.pause_reason,
                        workflow_id=goal.workflow_id,
                    )
                )

    def upsert_goal(self, goal: AgentGoal) -> None:
        with session_scope() as session:
            record = session.get(AgentGoalRecord, goal.id)
            if record is None:
                record = AgentGoalRecord(id=goal.id, conversation_id=goal.conversation_id)
                session.add(record)

            record.conversation_id = goal.conversation_id
            record.project_id = goal.project_id
            record.us_id = goal.us_id
            record.title = goal.title
            record.status = goal.status
            record.summary = goal.summary
            record.steps = [step.model_dump() for step in goal.steps]
            record.autonomy_level = goal.autonomy_level
            record.max_steps = goal.max_steps
            record.steps_completed = goal.steps_completed
            record.pause_reason = goal.pause_reason
            record.workflow_id = goal.workflow_id

    def load_tool_invocations(self) -> list[ToolInvocation]:
        with session_scope() as session:
            rows = session.scalars(select(ToolInvocationRecord)).all()
        return [self._to_tool_invocation(row) for row in rows]

    def load_summary_checkpoints(self) -> list[ConversationSummaryCheckpoint]:
        with session_scope() as session:
            rows = session.scalars(
                select(ConversationSummaryCheckpointRecord).order_by(ConversationSummaryCheckpointRecord.created_at)
            ).all()
        return [self._to_summary_checkpoint(row) for row in rows]

    def upsert_summary_checkpoint(self, checkpoint: ConversationSummaryCheckpoint) -> None:
        with session_scope() as session:
            record = session.get(ConversationSummaryCheckpointRecord, checkpoint.id)
            if record is None:
                record = ConversationSummaryCheckpointRecord(id=checkpoint.id)
                session.add(record)

            record.conversation_id = checkpoint.conversation_id
            record.message_range_start = checkpoint.message_range_start
            record.message_range_end = checkpoint.message_range_end
            record.summary_text = checkpoint.summary_text
            record.summary_object_refs = checkpoint.summary_object_refs
            record.summary_token_count = checkpoint.summary_token_count
            record.created_by = checkpoint.created_by
            record.created_at = checkpoint.created_at

    def load_session_knowledge_bindings(self) -> list[SessionKnowledgeBinding]:
        with session_scope() as session:
            rows = session.scalars(
                select(SessionKnowledgeBindingRecord).order_by(SessionKnowledgeBindingRecord.created_at)
            ).all()
        return [self._to_session_knowledge_binding(row) for row in rows]

    def upsert_session_knowledge_binding(self, binding: SessionKnowledgeBinding) -> None:
        with session_scope() as session:
            record = session.get(SessionKnowledgeBindingRecord, binding.id)
            if record is None:
                record = SessionKnowledgeBindingRecord(id=binding.id)
                session.add(record)

            record.conversation_id = binding.conversation_id
            record.candidate_object_ref = binding.candidate_object_ref
            record.scope = binding.scope
            record.created_at = binding.created_at

    def upsert_tool_invocation(self, invocation: ToolInvocation) -> None:
        with session_scope() as session:
            record = session.get(ToolInvocationRecord, invocation.id)
            if record is None:
                record = ToolInvocationRecord(id=invocation.id)
                session.add(record)

            record.conversation_id = invocation.conversation_id
            record.tool_id = invocation.tool_id
            record.status = invocation.status
            record.summary = invocation.summary
            record.initiator_surface = invocation.initiator_surface
            record.initiator_actor = invocation.initiator_actor
            record.target_scope = invocation.target_scope
            record.input_payload = invocation.input_payload
            record.result_payload = invocation.result.model_dump() if invocation.result else None

    def _to_conversation(
        self,
        row: ConversationRecord,
        messages: list[ConversationMessage],
        goals: list[AgentGoal],
    ) -> ConversationSession:
        return ConversationSession(
            id=row.id,
            session_id=row.session_id,
            title=row.title,
            space_type=row.space_type,
            space_id=row.space_id,
            project_id=row.project_id,
            version_id=row.version_id,
            us_id=row.us_id,
            task_id=row.task_id,
            initiator_id=row.initiator_id,
            status=row.status,
            last_message_at=row.last_message_at,
            latest_summary_checkpoint_id=row.latest_summary_checkpoint_id,
            merged_into_conversation_id=row.merged_into_conversation_id,
            archived_at=row.archived_at,
            messages=messages,
            agent_goals=goals,
            related_conversation_ids=row.related_conversation_ids or [],
        )

    @staticmethod
    def _to_message(row: ConversationMessageRecord) -> ConversationMessage:
        return ConversationMessage(
            id=row.id,
            role=row.role,
            status=row.status,
            content_type=row.content_type,
            created_at=row.created_at,
            blocks=[MessageBlock(**block) for block in (row.blocks or [])],
            tool_refs=row.tool_refs or [],
            object_refs=row.object_refs or [],
            metadata=row.message_metadata or {},
            stream_id=row.stream_id,
            sequence_max=row.sequence_max,
        )

    @staticmethod
    def _to_goal(row: AgentGoalRecord) -> AgentGoal:
        return AgentGoal(
            id=row.id,
            conversation_id=row.conversation_id,
            project_id=row.project_id,
            us_id=row.us_id,
            title=row.title,
            status=row.status,
            summary=row.summary,
            steps=[AgentStep(**step) for step in (row.steps or [])],
            autonomy_level=row.autonomy_level,
            max_steps=row.max_steps,
            steps_completed=row.steps_completed,
            pause_reason=row.pause_reason,
            workflow_id=row.workflow_id,
        )

    @staticmethod
    def _to_tool_invocation(row: ToolInvocationRecord) -> ToolInvocation:
        result = ToolResult(**row.result_payload) if row.result_payload else None
        return ToolInvocation(
            id=row.id,
            conversation_id=row.conversation_id,
            tool_id=row.tool_id,
            status=row.status,  # type: ignore[arg-type]
            summary=row.summary,
            initiator_surface=row.initiator_surface,  # type: ignore[arg-type]
            initiator_actor=row.initiator_actor,  # type: ignore[arg-type]
            target_scope=row.target_scope,  # type: ignore[arg-type]
            input_payload=row.input_payload or {},
            result=result,
        )

    @staticmethod
    def _to_summary_checkpoint(row: ConversationSummaryCheckpointRecord) -> ConversationSummaryCheckpoint:
        return ConversationSummaryCheckpoint(
            id=row.id,
            conversation_id=row.conversation_id,
            message_range_start=row.message_range_start,
            message_range_end=row.message_range_end,
            summary_text=row.summary_text,
            summary_object_refs=row.summary_object_refs or [],
            summary_token_count=row.summary_token_count,
            created_by=row.created_by,  # type: ignore[arg-type]
            created_at=row.created_at,
        )

    @staticmethod
    def _to_session_knowledge_binding(row: SessionKnowledgeBindingRecord) -> SessionKnowledgeBinding:
        return SessionKnowledgeBinding(
            id=row.id,
            conversation_id=row.conversation_id,
            candidate_object_ref=row.candidate_object_ref,
            scope=row.scope,  # type: ignore[arg-type]
            created_at=row.created_at,
        )


class ProjectRepository:
    def load_projects(self) -> list[ProjectCard]:
        with session_scope() as session:
            rows = session.scalars(select(ProjectRecord)).all()
        return [self._to_project(row) for row in rows]

    def load_versions(self) -> dict[str, list[VersionSummary]]:
        with session_scope() as session:
            rows = session.scalars(select(VersionRecord).order_by(VersionRecord.project_id, VersionRecord.sort_order)).all()
        grouped: dict[str, list[VersionSummary]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_version(row))
        return grouped

    def load_us_items(self) -> dict[str, list[USItem]]:
        with session_scope() as session:
            rows = session.scalars(select(USWorkItemRecord).order_by(USWorkItemRecord.project_id, USWorkItemRecord.id)).all()
        grouped: dict[str, list[USItem]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_us_item(row))
        return grouped

    def load_asset_lanes(self) -> dict[str, list[AssetLane]]:
        with session_scope() as session:
            rows = session.scalars(select(AssetLaneRecord).order_by(AssetLaneRecord.us_id, AssetLaneRecord.sort_order)).all()
        grouped: dict[str, list[AssetLane]] = {}
        for row in rows:
            grouped.setdefault(row.us_id, []).append(self._to_asset_lane(row))
        return grouped

    def load_runs(self) -> tuple[dict[str, list[RunSummary]], dict[str, RunDetail]]:
        with session_scope() as session:
            rows = session.scalars(select(RunRecord).order_by(RunRecord.project_id, RunRecord.sort_order)).all()
        grouped: dict[str, list[RunSummary]] = {}
        details: dict[str, RunDetail] = {}
        for row in rows:
            summary = self._to_run_summary(row)
            grouped.setdefault(row.project_id, []).append(summary)
            details[row.id] = self._to_run_detail(row)
        return grouped, details

    def load_approvals(self) -> tuple[dict[str, list[ApprovalSummary]], dict[str, ApprovalDetail]]:
        with session_scope() as session:
            rows = session.scalars(select(ApprovalRecord).order_by(ApprovalRecord.project_id, ApprovalRecord.sort_order)).all()
        grouped: dict[str, list[ApprovalSummary]] = {}
        details: dict[str, ApprovalDetail] = {}
        for row in rows:
            summary = self._to_approval_summary(row)
            grouped.setdefault(row.project_id, []).append(summary)
            details[row.id] = self._to_approval_detail(row)
        return grouped, details

    def load_knowledge_objects(self) -> dict[str, list[KnowledgeObject]]:
        with session_scope() as session:
            rows = session.scalars(
                select(KnowledgeObjectRecord).order_by(KnowledgeObjectRecord.project_id, KnowledgeObjectRecord.sort_order)
            ).all()
        grouped: dict[str, list[KnowledgeObject]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_knowledge_object(row))
        return grouped

    def load_raw_assets(self) -> dict[str, list[RawAssetRecord]]:
        with session_scope() as session:
            rows = session.scalars(
                select(RawAssetRow).order_by(RawAssetRow.project_id, RawAssetRow.sort_order)
            ).all()
        grouped: dict[str, list[RawAssetRecord]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_raw_asset(row))
        return grouped

    def load_baselines(self) -> dict[str, list[BaselineRecord]]:
        with session_scope() as session:
            rows = session.scalars(
                select(BaselineRow).order_by(BaselineRow.project_id, BaselineRow.sort_order)
            ).all()
        grouped: dict[str, list[BaselineRecord]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_baseline(row))
        return grouped

    def load_context_relationships(self) -> dict[str, list[ContextRelationship]]:
        with session_scope() as session:
            rows = session.scalars(
                select(ContextRelationshipRecord).order_by(
                    ContextRelationshipRecord.project_id,
                    ContextRelationshipRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[ContextRelationship]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_context_relationship(row))
        return grouped

    def load_context_object_overlays(self) -> dict[str, list[ContextObjectOverlay]]:
        with session_scope() as session:
            rows = session.scalars(
                select(ContextObjectOverlayRecord).order_by(
                    ContextObjectOverlayRecord.project_id,
                    ContextObjectOverlayRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[ContextObjectOverlay]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_context_object_overlay(row))
        return grouped

    def load_quality_metric_snapshots(self) -> dict[str, list[QualityMetricSnapshot]]:
        with session_scope() as session:
            rows = session.scalars(
                select(QualityMetricSnapshotRecord).order_by(
                    QualityMetricSnapshotRecord.project_id,
                    QualityMetricSnapshotRecord.sort_order,
                )
            ).all()
        grouped: dict[str, list[QualityMetricSnapshot]] = {}
        for row in rows:
            grouped.setdefault(row.project_id, []).append(self._to_quality_metric_snapshot(row))
        return grouped

    def load_release_readiness(self) -> dict[str, ReleaseReadiness]:
        with session_scope() as session:
            rows = session.scalars(select(ReleaseReadinessRecord)).all()
        return {row.version_id: self._to_release_readiness(row) for row in rows}

    def upsert_project(self, project: ProjectCard) -> None:
        with session_scope() as session:
            row = session.get(ProjectRecord, project.id)
            if row is None:
                row = ProjectRecord(id=project.id)
                session.add(row)
            row.name = project.name
            row.code = project.code
            row.summary = project.summary
            row.status = project.status
            row.risk = project.risk
            row.progress = project.progress
            row.active_version = project.active_version
            row.blocked_items = project.blocked_items
            row.pending_approvals = project.pending_approvals
            row.system_image_status = project.system_image_status

    def upsert_version(self, project_id: str, version: VersionSummary, sort_order: int = 0) -> None:
        with session_scope() as session:
            row = session.get(VersionRecord, version.id)
            if row is None:
                row = VersionRecord(id=version.id, project_id=project_id)
                session.add(row)
            row.project_id = project_id
            row.name = version.name
            row.status = version.status
            row.branch_name = version.branch_name
            row.us_total = version.us_total
            row.us_closed = version.us_closed
            row.pending_runs = version.pending_runs
            row.pending_approvals = version.pending_approvals
            row.sort_order = sort_order

    def replace_versions(self, project_id: str, versions: list[VersionSummary]) -> None:
        with session_scope() as session:
            session.execute(delete(VersionRecord).where(VersionRecord.project_id == project_id))
            for sort_order, version in enumerate(versions):
                session.add(
                    VersionRecord(
                        id=version.id,
                        project_id=project_id,
                        name=version.name,
                        status=version.status,
                        branch_name=version.branch_name,
                        us_total=version.us_total,
                        us_closed=version.us_closed,
                        pending_runs=version.pending_runs,
                        pending_approvals=version.pending_approvals,
                        sort_order=sort_order,
                    )
                )

    def replace_us_items(self, project_id: str, version_id: str | None, items: list[USItem]) -> None:
        with session_scope() as session:
            session.execute(delete(USWorkItemRecord).where(USWorkItemRecord.project_id == project_id))
            for item in items:
                session.add(
                    USWorkItemRecord(
                        id=item.id,
                        project_id=project_id,
                        version_id=version_id,
                        title=item.title,
                        owner=item.owner,
                        status=item.status,
                        risk=item.risk,
                        progress=item.progress,
                        next_action=item.next_action,
                    )
                )

    def upsert_us_item(self, project_id: str, version_id: str | None, item: USItem) -> None:
        with session_scope() as session:
            row = session.get(USWorkItemRecord, item.id)
            if row is None:
                row = USWorkItemRecord(id=item.id, project_id=project_id, version_id=version_id)
                session.add(row)
            row.project_id = project_id
            row.version_id = version_id
            row.title = item.title
            row.owner = item.owner
            row.status = item.status
            row.risk = item.risk
            row.progress = item.progress
            row.next_action = item.next_action

    def replace_asset_lanes(self, project_id: str, us_id: str, lanes: list[AssetLane]) -> None:
        with session_scope() as session:
            session.execute(delete(AssetLaneRecord).where(AssetLaneRecord.us_id == us_id))
            for sort_order, lane in enumerate(lanes):
                session.add(
                    AssetLaneRecord(
                        id=lane.id,
                        project_id=project_id,
                        us_id=us_id,
                        label=lane.label,
                        status=lane.status,
                        summary=lane.summary,
                        updated_at=lane.updated_at,
                        sort_order=sort_order,
                    )
                )

    def replace_runs(self, project_id: str, runs: list[RunDetail]) -> None:
        with session_scope() as session:
            session.execute(delete(RunRecord).where(RunRecord.project_id == project_id))
            for sort_order, run in enumerate(runs):
                session.add(
                    RunRecord(
                        id=run.id,
                        project_id=project_id,
                        status=run.status,
                        channel=run.channel,
                        title=run.title,
                        summary=run.summary,
                        started_at=run.started_at,
                        timeline=run.timeline,
                        evidence=run.evidence,
                        failure_summary=run.failure_summary,
                        healing_status=run.healing_status,
                        sort_order=sort_order,
                    )
                )

    def replace_approvals(self, project_id: str, approvals: list[ApprovalDetail]) -> None:
        with session_scope() as session:
            session.execute(delete(ApprovalRecord).where(ApprovalRecord.project_id == project_id))
            for sort_order, approval in enumerate(approvals):
                session.add(
                    ApprovalRecord(
                        id=approval.id,
                        project_id=project_id,
                        title=approval.title,
                        status=approval.status,
                        summary=approval.summary,
                        policy_reason=approval.policy_reason,
                        conflict_fields=approval.conflict_fields,
                        recommended_resolution=approval.recommended_resolution,
                        evidence=approval.evidence,
                        sort_order=sort_order,
                    )
                )

    def replace_knowledge_objects(self, project_id: str, objects: list[KnowledgeObject]) -> None:
        with session_scope() as session:
            session.execute(delete(KnowledgeObjectRecord).where(KnowledgeObjectRecord.project_id == project_id))
            for sort_order, item in enumerate(objects):
                session.add(
                    KnowledgeObjectRecord(
                        id=item.id,
                        project_id=project_id,
                        name=item.name,
                        type=item.type,
                        branch=item.branch,
                        confidence=item.confidence,
                        relations=item.relations,
                        evidence=item.evidence,
                        freshness=item.freshness,
                        sort_order=sort_order,
                    )
                )

    def replace_system_image(
        self,
        project_id: str,
        *,
        sources: list[RawAssetRecord],
        baselines: list[BaselineRecord],
        relationships: list[ContextRelationship],
        overlays: list[ContextObjectOverlay],
        metric_snapshots: list[QualityMetricSnapshot],
    ) -> None:
        with session_scope() as session:
            session.execute(delete(RawAssetRow).where(RawAssetRow.project_id == project_id))
            session.execute(delete(BaselineRow).where(BaselineRow.project_id == project_id))
            session.execute(delete(ContextRelationshipRecord).where(ContextRelationshipRecord.project_id == project_id))
            session.execute(delete(ContextObjectOverlayRecord).where(ContextObjectOverlayRecord.project_id == project_id))
            session.execute(delete(QualityMetricSnapshotRecord).where(QualityMetricSnapshotRecord.project_id == project_id))

            for sort_order, source in enumerate(sources):
                session.add(
                    RawAssetRow(
                        id=source.id,
                        project_id=source.project_id,
                        version_id=source.version_id,
                        source_type=source.source_type,
                        source_uri=source.source_uri,
                        ingestion_status=source.ingestion_status,
                        content_hash=source.content_hash,
                        content_ref=source.content_ref,
                        evidence_refs=source.evidence_refs,
                        last_ingested_at=source.last_ingested_at,
                        sort_order=sort_order,
                    )
                )

            for sort_order, baseline in enumerate(baselines):
                session.add(
                    BaselineRow(
                        id=baseline.id,
                        project_id=baseline.project_id,
                        kind=baseline.kind,
                        status=baseline.status,
                        source_version_id=baseline.source_version_id,
                        parent_baseline_id=baseline.parent_baseline_id,
                        fork_strategy=baseline.fork_strategy,
                        object_count=baseline.object_count,
                        relationship_count=baseline.relationship_count,
                        metric_snapshot_count=baseline.metric_snapshot_count,
                        updated_at=baseline.updated_at,
                        sort_order=sort_order,
                    )
                )

            for sort_order, relationship in enumerate(relationships):
                session.add(
                    ContextRelationshipRecord(
                        id=relationship.id,
                        project_id=relationship.project_id,
                        baseline_id=relationship.baseline_id,
                        from_object_id=relationship.from_object_id,
                        relationship_type=relationship.relationship_type,
                        to_object_id=relationship.to_object_id,
                        confidence=relationship.confidence,
                        source_refs=relationship.source_refs,
                        sort_order=sort_order,
                    )
                )

            for sort_order, overlay in enumerate(overlays):
                session.add(
                    ContextObjectOverlayRecord(
                        id=overlay.id,
                        project_id=overlay.project_id,
                        baseline_id=overlay.baseline_id,
                        object_id=overlay.object_id,
                        field_path=overlay.field_path,
                        operation=overlay.operation,
                        value_ref=overlay.value_ref,
                        source_refs=overlay.source_refs,
                        status=overlay.status,
                        sort_order=sort_order,
                    )
                )

            for sort_order, metric in enumerate(metric_snapshots):
                session.add(
                    QualityMetricSnapshotRecord(
                        id=metric.id,
                        project_id=metric.project_id,
                        baseline_id=metric.baseline_id,
                        version_id=metric.version_id,
                        us_id=metric.us_id,
                        task_id=metric.task_id,
                        metric_group=metric.metric_group,
                        metrics=metric.metrics,
                        evidence_refs=metric.evidence_refs,
                        captured_at=metric.captured_at,
                        sort_order=sort_order,
                    )
                )

    def upsert_release_readiness(self, project_id: str, readiness: ReleaseReadiness) -> None:
        with session_scope() as session:
            row = session.get(ReleaseReadinessRecord, readiness.version_id)
            if row is None:
                row = ReleaseReadinessRecord(version_id=readiness.version_id, project_id=project_id)
                session.add(row)
            row.project_id = project_id
            row.status = readiness.status
            row.score = readiness.score
            row.blockers = readiness.blockers
            row.approvals_open = readiness.approvals_open
            row.pending_merge = readiness.pending_merge
            row.execution_health = readiness.execution_health
            row.summary = readiness.summary
            row.blocker_items = readiness.blocker_items

    @staticmethod
    def _to_project(row: ProjectRecord) -> ProjectCard:
        return ProjectCard(
            id=row.id,
            name=row.name,
            code=row.code,
            summary=row.summary,
            status=row.status,
            risk=row.risk,
            progress=row.progress,
            active_version=row.active_version,
            blocked_items=row.blocked_items,
            pending_approvals=row.pending_approvals,
            system_image_status=row.system_image_status,
        )

    @staticmethod
    def _to_version(row: VersionRecord) -> VersionSummary:
        return VersionSummary(
            id=row.id,
            name=row.name,
            status=row.status,
            branch_name=row.branch_name,
            us_total=row.us_total,
            us_closed=row.us_closed,
            pending_runs=row.pending_runs,
            pending_approvals=row.pending_approvals,
        )

    @staticmethod
    def _to_us_item(row: USWorkItemRecord) -> USItem:
        return USItem(
            id=row.id,
            title=row.title,
            owner=row.owner,
            status=row.status,
            risk=row.risk,
            progress=row.progress,
            next_action=row.next_action,
        )

    @staticmethod
    def _to_asset_lane(row: AssetLaneRecord) -> AssetLane:
        return AssetLane(
            id=row.id,
            label=row.label,
            status=row.status,
            summary=row.summary,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_run_summary(row: RunRecord) -> RunSummary:
        return RunSummary(
            id=row.id,
            status=row.status,
            channel=row.channel,  # type: ignore[arg-type]
            title=row.title,
            summary=row.summary,
            started_at=row.started_at,
        )

    @staticmethod
    def _to_run_detail(row: RunRecord) -> RunDetail:
        return RunDetail(
            id=row.id,
            status=row.status,
            channel=row.channel,  # type: ignore[arg-type]
            title=row.title,
            summary=row.summary,
            started_at=row.started_at,
            timeline=row.timeline or [],
            evidence=row.evidence or [],
            failure_summary=row.failure_summary,
            healing_status=row.healing_status,
        )

    @staticmethod
    def _to_approval_summary(row: ApprovalRecord) -> ApprovalSummary:
        return ApprovalSummary(
            id=row.id,
            title=row.title,
            status=row.status,
            summary=row.summary,
        )

    @staticmethod
    def _to_approval_detail(row: ApprovalRecord) -> ApprovalDetail:
        return ApprovalDetail(
            id=row.id,
            title=row.title,
            status=row.status,
            summary=row.summary,
            policy_reason=row.policy_reason,
            conflict_fields=row.conflict_fields or [],
            recommended_resolution=row.recommended_resolution,
            evidence=row.evidence or [],
        )

    @staticmethod
    def _to_knowledge_object(row: KnowledgeObjectRecord) -> KnowledgeObject:
        return KnowledgeObject(
            id=row.id,
            name=row.name,
            type=row.type,
            branch=row.branch,
            confidence=row.confidence,
            relations=row.relations or [],
            evidence=row.evidence or [],
            freshness=row.freshness,
        )

    @staticmethod
    def _to_raw_asset(row: RawAssetRow) -> RawAssetRecord:
        return RawAssetRecord(
            id=row.id,
            project_id=row.project_id,
            version_id=row.version_id,
            source_type=row.source_type,  # type: ignore[arg-type]
            source_uri=row.source_uri,
            ingestion_status=row.ingestion_status,  # type: ignore[arg-type]
            content_hash=row.content_hash,
            content_ref=row.content_ref,
            evidence_refs=row.evidence_refs or [],
            last_ingested_at=row.last_ingested_at,
        )

    @staticmethod
    def _to_baseline(row: BaselineRow) -> BaselineRecord:
        return BaselineRecord(
            id=row.id,
            project_id=row.project_id,
            kind=row.kind,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            source_version_id=row.source_version_id,
            parent_baseline_id=row.parent_baseline_id,
            fork_strategy=row.fork_strategy,  # type: ignore[arg-type]
            object_count=row.object_count,
            relationship_count=row.relationship_count,
            metric_snapshot_count=row.metric_snapshot_count,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_context_relationship(row: ContextRelationshipRecord) -> ContextRelationship:
        return ContextRelationship(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            from_object_id=row.from_object_id,
            relationship_type=row.relationship_type,  # type: ignore[arg-type]
            to_object_id=row.to_object_id,
            confidence=row.confidence,
            source_refs=row.source_refs or [],
        )

    @staticmethod
    def _to_context_object_overlay(row: ContextObjectOverlayRecord) -> ContextObjectOverlay:
        return ContextObjectOverlay(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            object_id=row.object_id,
            field_path=row.field_path,
            operation=row.operation,  # type: ignore[arg-type]
            value_ref=row.value_ref,
            source_refs=row.source_refs or [],
            status=row.status,  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_quality_metric_snapshot(row: QualityMetricSnapshotRecord) -> QualityMetricSnapshot:
        return QualityMetricSnapshot(
            id=row.id,
            project_id=row.project_id,
            baseline_id=row.baseline_id,
            version_id=row.version_id,
            us_id=row.us_id,
            task_id=row.task_id,
            metric_group=row.metric_group,  # type: ignore[arg-type]
            metrics=row.metrics or {},
            evidence_refs=row.evidence_refs or [],
            captured_at=row.captured_at,
        )

    @staticmethod
    def _to_release_readiness(row: ReleaseReadinessRecord) -> ReleaseReadiness:
        return ReleaseReadiness(
            version_id=row.version_id,
            status=row.status,
            score=row.score,
            blockers=row.blockers,
            approvals_open=row.approvals_open,
            pending_merge=row.pending_merge,
            execution_health=row.execution_health,
            summary=row.summary,
            blocker_items=row.blocker_items or [],
        )
