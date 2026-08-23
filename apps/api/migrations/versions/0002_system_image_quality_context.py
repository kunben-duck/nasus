"""add system image quality context objects

Revision ID: 0002_system_quality
Revises: 0001_initial_agent_first_schema
Create Date: 2026-06-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_system_quality"
down_revision = "0001_initial_agent_first_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_assets", sa.Column("source_label", sa.String(), nullable=True))
    op.add_column("raw_assets", sa.Column("registered_at", sa.String(), nullable=True))
    op.add_column(
        "raw_assets",
        sa.Column("registered_by_actor", sa.String(), nullable=False, server_default="system"),
    )
    op.add_column("raw_assets", sa.Column("registered_from_invocation_id", sa.String(), nullable=True))
    op.add_column("raw_assets", sa.Column("credential_ref", sa.String(), nullable=True))
    op.add_column(
        "raw_assets",
        sa.Column("permission_status", sa.String(), nullable=False, server_default="not_checked"),
    )
    op.add_column("raw_assets", sa.Column("permission_checked_at", sa.String(), nullable=True))
    op.add_column("raw_assets", sa.Column("ingest_started_at", sa.String(), nullable=True))
    op.add_column("raw_assets", sa.Column("failure_reason", sa.String(), nullable=True))
    op.add_column("raw_assets", sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("raw_assets", sa.Column("byte_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_raw_assets_registered_at", "raw_assets", ["registered_at"])
    op.create_index("ix_raw_assets_registered_by_actor", "raw_assets", ["registered_by_actor"])
    op.create_index(
        "ix_raw_assets_registered_from_invocation_id",
        "raw_assets",
        ["registered_from_invocation_id"],
    )
    op.create_index("ix_raw_assets_permission_status", "raw_assets", ["permission_status"])
    op.create_index("ix_raw_assets_permission_checked_at", "raw_assets", ["permission_checked_at"])
    op.create_index("ix_raw_assets_ingest_started_at", "raw_assets", ["ingest_started_at"])

    op.create_table(
        "embedding_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("baseline_id", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("object_ref", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("embedding_model", sa.String(), nullable=False),
        sa.Column("embedding_version", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("vector_ref", sa.String(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("fallback_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_embedding_records_project_id", "embedding_records", ["project_id"])
    op.create_index("ix_embedding_records_baseline_id", "embedding_records", ["baseline_id"])
    op.create_index("ix_embedding_records_source_ref", "embedding_records", ["source_ref"])
    op.create_index("ix_embedding_records_object_ref", "embedding_records", ["object_ref"])
    op.create_index("ix_embedding_records_content_hash", "embedding_records", ["content_hash"])
    op.create_index("ix_embedding_records_provider", "embedding_records", ["provider"])
    op.create_index("ix_embedding_records_status", "embedding_records", ["status"])
    op.create_index("ix_embedding_records_created_at", "embedding_records", ["created_at"])

    op.create_table(
        "retrieval_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("baseline_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("us_id", sa.String(), nullable=True),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("result_refs", sa.JSON(), nullable=False),
        sa.Column("embedding_record_ids", sa.JSON(), nullable=False),
        sa.Column("rerank_record_id", sa.String(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_retrieval_runs_project_id", "retrieval_runs", ["project_id"])
    op.create_index("ix_retrieval_runs_baseline_id", "retrieval_runs", ["baseline_id"])
    op.create_index("ix_retrieval_runs_version_id", "retrieval_runs", ["version_id"])
    op.create_index("ix_retrieval_runs_us_id", "retrieval_runs", ["us_id"])
    op.create_index("ix_retrieval_runs_strategy", "retrieval_runs", ["strategy"])
    op.create_index("ix_retrieval_runs_rerank_record_id", "retrieval_runs", ["rerank_record_id"])
    op.create_index("ix_retrieval_runs_created_at", "retrieval_runs", ["created_at"])

    op.create_table(
        "rerank_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("retrieval_run_id", sa.String(), nullable=False),
        sa.Column("rerank_model", sa.String(), nullable=False),
        sa.Column("rerank_version", sa.String(), nullable=False),
        sa.Column("input_count", sa.Integer(), nullable=False),
        sa.Column("output_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("fallback_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_rerank_records_project_id", "rerank_records", ["project_id"])
    op.create_index("ix_rerank_records_retrieval_run_id", "rerank_records", ["retrieval_run_id"])
    op.create_index("ix_rerank_records_status", "rerank_records", ["status"])
    op.create_index("ix_rerank_records_created_at", "rerank_records", ["created_at"])

    op.create_table(
        "task_contexts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("baseline_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("us_id", sa.String(), nullable=True),
        sa.Column("retrieval_run_id", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("readiness", sa.String(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("object_refs", sa.JSON(), nullable=False),
        sa.Column("relationship_refs", sa.JSON(), nullable=False),
        sa.Column("metric_refs", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("missing_context", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("freshness_at", sa.String(), nullable=False),
        sa.Column("context_hash", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_task_contexts_project_id", "task_contexts", ["project_id"])
    op.create_index("ix_task_contexts_baseline_id", "task_contexts", ["baseline_id"])
    op.create_index("ix_task_contexts_version_id", "task_contexts", ["version_id"])
    op.create_index("ix_task_contexts_us_id", "task_contexts", ["us_id"])
    op.create_index("ix_task_contexts_retrieval_run_id", "task_contexts", ["retrieval_run_id"])
    op.create_index("ix_task_contexts_readiness", "task_contexts", ["readiness"])
    op.create_index("ix_task_contexts_freshness_at", "task_contexts", ["freshness_at"])
    op.create_index("ix_task_contexts_context_hash", "task_contexts", ["context_hash"])

    op.create_table(
        "quality_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("baseline_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("us_id", sa.String(), nullable=True),
        sa.Column("task_context_id", sa.String(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("coverage_score", sa.Integer(), nullable=False),
        sa.Column("release_score", sa.Integer(), nullable=False),
        sa.Column("automation_feasibility", sa.Integer(), nullable=False),
        sa.Column("risk_drivers", sa.JSON(), nullable=False),
        sa.Column("regression_scope_refs", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("freshness_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_quality_profiles_project_id", "quality_profiles", ["project_id"])
    op.create_index("ix_quality_profiles_baseline_id", "quality_profiles", ["baseline_id"])
    op.create_index("ix_quality_profiles_version_id", "quality_profiles", ["version_id"])
    op.create_index("ix_quality_profiles_us_id", "quality_profiles", ["us_id"])
    op.create_index("ix_quality_profiles_task_context_id", "quality_profiles", ["task_context_id"])
    op.create_index("ix_quality_profiles_freshness_at", "quality_profiles", ["freshness_at"])

    op.create_table(
        "quality_asset_packs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("us_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("parts", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_quality_asset_packs_project_id", "quality_asset_packs", ["project_id"])
    op.create_index("ix_quality_asset_packs_version_id", "quality_asset_packs", ["version_id"])
    op.create_index("ix_quality_asset_packs_us_id", "quality_asset_packs", ["us_id"])
    op.create_index("ix_quality_asset_packs_status", "quality_asset_packs", ["status"])
    op.create_index("ix_quality_asset_packs_updated_at", "quality_asset_packs", ["updated_at"])

    op.create_table(
        "execution_evidence",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("us_id", sa.String(), nullable=True),
        sa.Column("case_ref", sa.String(), nullable=True),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("storage_ref", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("producer", sa.String(), nullable=False),
        sa.Column("captured_at", sa.String(), nullable=False),
        sa.Column("redaction_status", sa.String(), nullable=False),
        sa.Column("retention_policy", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_execution_evidence_project_id", "execution_evidence", ["project_id"])
    op.create_index("ix_execution_evidence_run_id", "execution_evidence", ["run_id"])
    op.create_index("ix_execution_evidence_us_id", "execution_evidence", ["us_id"])
    op.create_index("ix_execution_evidence_evidence_type", "execution_evidence", ["evidence_type"])
    op.create_index("ix_execution_evidence_content_hash", "execution_evidence", ["content_hash"])
    op.create_index("ix_execution_evidence_producer", "execution_evidence", ["producer"])
    op.create_index("ix_execution_evidence_captured_at", "execution_evidence", ["captured_at"])
    op.create_index("ix_execution_evidence_redaction_status", "execution_evidence", ["redaction_status"])

    op.create_table(
        "failure_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("us_id", sa.String(), nullable=True),
        sa.Column("failure_kind", sa.String(), nullable=False),
        sa.Column("failure_fingerprint", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("root_cause", sa.String(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("healing_attempt_count", sa.Integer(), nullable=False),
        sa.Column("fallback_to_human", sa.Boolean(), nullable=False),
        sa.Column("cooldown_until", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_failure_reports_project_id", "failure_reports", ["project_id"])
    op.create_index("ix_failure_reports_run_id", "failure_reports", ["run_id"])
    op.create_index("ix_failure_reports_us_id", "failure_reports", ["us_id"])
    op.create_index("ix_failure_reports_failure_kind", "failure_reports", ["failure_kind"])
    op.create_index("ix_failure_reports_failure_fingerprint", "failure_reports", ["failure_fingerprint"])
    op.create_index("ix_failure_reports_status", "failure_reports", ["status"])
    op.create_index("ix_failure_reports_fallback_to_human", "failure_reports", ["fallback_to_human"])
    op.create_index("ix_failure_reports_cooldown_until", "failure_reports", ["cooldown_until"])
    op.create_index("ix_failure_reports_created_at", "failure_reports", ["created_at"])

    op.create_table(
        "release_decisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("us_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("approval_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_release_decisions_project_id", "release_decisions", ["project_id"])
    op.create_index("ix_release_decisions_version_id", "release_decisions", ["version_id"])
    op.create_index("ix_release_decisions_us_id", "release_decisions", ["us_id"])
    op.create_index("ix_release_decisions_status", "release_decisions", ["status"])
    op.create_index("ix_release_decisions_approval_ref", "release_decisions", ["approval_ref"])
    op.create_index("ix_release_decisions_created_at", "release_decisions", ["created_at"])


def downgrade() -> None:
    for table in [
        "release_decisions",
        "failure_reports",
        "execution_evidence",
        "quality_asset_packs",
        "quality_profiles",
        "task_contexts",
        "rerank_records",
        "retrieval_runs",
        "embedding_records",
    ]:
        op.drop_table(table)
    for index in [
        "ix_raw_assets_ingest_started_at",
        "ix_raw_assets_permission_checked_at",
        "ix_raw_assets_permission_status",
        "ix_raw_assets_registered_from_invocation_id",
        "ix_raw_assets_registered_by_actor",
        "ix_raw_assets_registered_at",
    ]:
        op.drop_index(index, table_name="raw_assets")
    for column in [
        "byte_count",
        "file_count",
        "failure_reason",
        "ingest_started_at",
        "permission_checked_at",
        "permission_status",
        "credential_ref",
        "registered_from_invocation_id",
        "registered_by_actor",
        "registered_at",
        "source_label",
    ]:
        op.drop_column("raw_assets", column)
