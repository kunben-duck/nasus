"""initial agent-first schema

Revision ID: 0001_initial_agent_first_schema
Revises:
Create Date: 2026-06-12 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_agent_first_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_settings",
        sa.Column("settings_id", sa.Integer(), primary_key=True),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("theme", sa.String(), nullable=False),
        sa.Column("notification_mode", sa.String(), nullable=False),
        sa.Column("model_preset", sa.String(), nullable=False),
        sa.Column("custom_model", sa.JSON(), nullable=False),
        sa.Column("custom_api_key_encrypted", sa.Text(), nullable=True),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("risk", sa.String(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("active_version", sa.String(), nullable=False),
        sa.Column("blocked_items", sa.Integer(), nullable=False),
        sa.Column("pending_approvals", sa.Integer(), nullable=False),
        sa.Column("system_image_status", sa.String(), nullable=False),
    )
    op.create_index("ix_projects_name", "projects", ["name"])
    op.create_index("ix_projects_status", "projects", ["status"])

    op.create_table(
        "versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("branch_name", sa.String(), nullable=False),
        sa.Column("us_total", sa.Integer(), nullable=False),
        sa.Column("us_closed", sa.Integer(), nullable=False),
        sa.Column("pending_runs", sa.Integer(), nullable=False),
        sa.Column("pending_approvals", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_versions_project_id", "versions", ["project_id"])
    op.create_index("ix_versions_status", "versions", ["status"])

    op.create_table(
        "us_work_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("risk", sa.String(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("next_action", sa.String(), nullable=False),
    )
    op.create_index("ix_us_work_items_project_id", "us_work_items", ["project_id"])
    op.create_index("ix_us_work_items_version_id", "us_work_items", ["version_id"])
    op.create_index("ix_us_work_items_status", "us_work_items", ["status"])

    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("space_type", sa.String(), nullable=False),
        sa.Column("space_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("us_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("initiator_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_message_at", sa.String(), nullable=True),
        sa.Column("latest_summary_checkpoint_id", sa.String(), nullable=True),
        sa.Column("merged_into_conversation_id", sa.String(), nullable=True),
        sa.Column("archived_at", sa.String(), nullable=True),
        sa.Column("related_conversation_ids", sa.JSON(), nullable=False),
    )
    op.create_index("ix_conversation_sessions_session_id", "conversation_sessions", ["session_id"])
    op.create_index("ix_conversation_sessions_space_type", "conversation_sessions", ["space_type"])
    op.create_index("ix_conversation_sessions_space_id", "conversation_sessions", ["space_id"])
    op.create_index("ix_conversation_sessions_project_id", "conversation_sessions", ["project_id"])
    op.create_index("ix_conversation_sessions_version_id", "conversation_sessions", ["version_id"])
    op.create_index("ix_conversation_sessions_us_id", "conversation_sessions", ["us_id"])
    op.create_index("ix_conversation_sessions_status", "conversation_sessions", ["status"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("blocks", sa.JSON(), nullable=False),
        sa.Column("tool_refs", sa.JSON(), nullable=False),
        sa.Column("object_refs", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("stream_id", sa.String(), nullable=True),
        sa.Column("sequence_max", sa.Integer(), nullable=True),
    )
    op.create_index("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"])
    op.create_index("ix_conversation_messages_created_at", "conversation_messages", ["created_at"])

    op.create_table(
        "conversation_summary_checkpoints",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("message_range_start", sa.String(), nullable=True),
        sa.Column("message_range_end", sa.String(), nullable=True),
        sa.Column("summary_text", sa.String(), nullable=False),
        sa.Column("summary_object_refs", sa.JSON(), nullable=False),
        sa.Column("summary_token_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_conversation_summary_checkpoints_conversation_id", "conversation_summary_checkpoints", ["conversation_id"])

    op.create_table(
        "session_knowledge_bindings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("candidate_object_ref", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_session_knowledge_bindings_conversation_id", "session_knowledge_bindings", ["conversation_id"])

    op.create_table(
        "agent_goals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("us_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("autonomy_level", sa.String(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("steps_completed", sa.Integer(), nullable=False),
        sa.Column("pause_reason", sa.String(), nullable=True),
        sa.Column("workflow_id", sa.String(), nullable=True),
    )
    op.create_index("ix_agent_goals_conversation_id", "agent_goals", ["conversation_id"])
    op.create_index("ix_agent_goals_project_id", "agent_goals", ["project_id"])
    op.create_index("ix_agent_goals_status", "agent_goals", ["status"])

    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("tool_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("initiator_surface", sa.String(), nullable=False),
        sa.Column("initiator_actor", sa.String(), nullable=False),
        sa.Column("target_scope", sa.String(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=True),
    )
    op.create_index("ix_tool_invocations_conversation_id", "tool_invocations", ["conversation_id"])
    op.create_index("ix_tool_invocations_tool_id", "tool_invocations", ["tool_id"])
    op.create_index("ix_tool_invocations_status", "tool_invocations", ["status"])

    op.create_table(
        "asset_lanes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("us_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_asset_lanes_project_id", "asset_lanes", ["project_id"])
    op.create_index("ix_asset_lanes_us_id", "asset_lanes", ["us_id"])
    op.create_index("ix_asset_lanes_status", "asset_lanes", ["status"])

    op.create_table(
        "runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("timeline", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("failure_summary", sa.String(), nullable=False),
        sa.Column("healing_status", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_runs_project_id", "runs", ["project_id"])
    op.create_index("ix_runs_status", "runs", ["status"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("policy_reason", sa.String(), nullable=False),
        sa.Column("conflict_fields", sa.JSON(), nullable=False),
        sa.Column("recommended_resolution", sa.String(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_approvals_project_id", "approvals", ["project_id"])
    op.create_index("ix_approvals_status", "approvals", ["status"])

    op.create_table(
        "knowledge_objects",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("relations", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("freshness", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_knowledge_objects_project_id", "knowledge_objects", ["project_id"])

    op.create_table(
        "raw_assets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_uri", sa.String(), nullable=False),
        sa.Column("ingestion_status", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("content_ref", sa.String(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("last_ingested_at", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_raw_assets_project_id", "raw_assets", ["project_id"])
    op.create_index("ix_raw_assets_version_id", "raw_assets", ["version_id"])
    op.create_index("ix_raw_assets_source_type", "raw_assets", ["source_type"])
    op.create_index("ix_raw_assets_ingestion_status", "raw_assets", ["ingestion_status"])

    op.create_table(
        "baselines",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_version_id", sa.String(), nullable=True),
        sa.Column("parent_baseline_id", sa.String(), nullable=True),
        sa.Column("fork_strategy", sa.String(), nullable=False),
        sa.Column("object_count", sa.Integer(), nullable=False),
        sa.Column("relationship_count", sa.Integer(), nullable=False),
        sa.Column("metric_snapshot_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_baselines_project_id", "baselines", ["project_id"])
    op.create_index("ix_baselines_kind", "baselines", ["kind"])
    op.create_index("ix_baselines_status", "baselines", ["status"])

    op.create_table(
        "context_relationships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("baseline_id", sa.String(), nullable=False),
        sa.Column("from_object_id", sa.String(), nullable=False),
        sa.Column("relationship_type", sa.String(), nullable=False),
        sa.Column("to_object_id", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_context_relationships_project_id", "context_relationships", ["project_id"])
    op.create_index("ix_context_relationships_baseline_id", "context_relationships", ["baseline_id"])
    op.create_index("ix_context_relationships_from_object_id", "context_relationships", ["from_object_id"])
    op.create_index("ix_context_relationships_to_object_id", "context_relationships", ["to_object_id"])
    op.create_index("ix_context_relationships_relationship_type", "context_relationships", ["relationship_type"])

    op.create_table(
        "context_object_overlays",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("baseline_id", sa.String(), nullable=False),
        sa.Column("object_id", sa.String(), nullable=False),
        sa.Column("field_path", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("value_ref", sa.String(), nullable=True),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_context_object_overlays_project_id", "context_object_overlays", ["project_id"])
    op.create_index("ix_context_object_overlays_baseline_id", "context_object_overlays", ["baseline_id"])
    op.create_index("ix_context_object_overlays_object_id", "context_object_overlays", ["object_id"])
    op.create_index("ix_context_object_overlays_status", "context_object_overlays", ["status"])

    op.create_table(
        "quality_metric_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("baseline_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("us_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("metric_group", sa.String(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_quality_metric_snapshots_project_id", "quality_metric_snapshots", ["project_id"])
    op.create_index("ix_quality_metric_snapshots_baseline_id", "quality_metric_snapshots", ["baseline_id"])
    op.create_index("ix_quality_metric_snapshots_version_id", "quality_metric_snapshots", ["version_id"])
    op.create_index("ix_quality_metric_snapshots_us_id", "quality_metric_snapshots", ["us_id"])
    op.create_index("ix_quality_metric_snapshots_metric_group", "quality_metric_snapshots", ["metric_group"])

    op.create_table(
        "release_readiness",
        sa.Column("version_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("blockers", sa.Integer(), nullable=False),
        sa.Column("approvals_open", sa.Integer(), nullable=False),
        sa.Column("pending_merge", sa.Integer(), nullable=False),
        sa.Column("execution_health", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("blocker_items", sa.JSON(), nullable=False),
    )
    op.create_index("ix_release_readiness_project_id", "release_readiness", ["project_id"])


def downgrade() -> None:
    for table in [
        "release_readiness",
        "quality_metric_snapshots",
        "context_object_overlays",
        "context_relationships",
        "baselines",
        "raw_assets",
        "knowledge_objects",
        "approvals",
        "runs",
        "asset_lanes",
        "tool_invocations",
        "agent_goals",
        "session_knowledge_bindings",
        "conversation_summary_checkpoints",
        "conversation_messages",
        "conversation_sessions",
        "us_work_items",
        "versions",
        "projects",
        "studio_settings",
    ]:
        op.drop_table(table)
