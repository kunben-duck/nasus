from __future__ import annotations

from .models import ToolDefinition


def system_image_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            tool_id="system_image.sources.register",
            label="Register System Image Sources",
            tool_kind="project",
            scope="central",
            risk_level="low",
            confirmation_mode="none",
            description=(
                "Register the first-class source groups used to build a project system image. "
                "Input may include source_specs: [{source_type: code|us_doc|test_asset, source_uri: file path or external URI}]."
            ),
            required_context=["project_id"],
            produced_objects=["RawAssetRecord"],
            input_schema_ref="schema://system-image/sources-register-input",
            output_schema_ref="schema://system-image/sources-register-output",
        ),
        ToolDefinition(
            tool_id="system_image.sources.ingest",
            label="Ingest System Image Sources",
            tool_kind="sync",
            scope="central",
            risk_level="medium",
            confirmation_mode="none",
            description="Index code, historical US documents, and historical tests into raw system image assets.",
            required_context=["project_id"],
            produced_objects=["RawAssetRecord", "ExecutionEvidence"],
            input_schema_ref="schema://system-image/sources-ingest-input",
            output_schema_ref="schema://system-image/sources-ingest-output",
        ),
        ToolDefinition(
            tool_id="system_image.context.materialize",
            label="Materialize System Context",
            tool_kind="analysis",
            scope="central",
            risk_level="medium",
            confirmation_mode="none",
            description="Materialize context objects, relationships, and quality metric snapshots from indexed sources.",
            required_context=["project_id"],
            produced_objects=["ContextObject", "ContextRelationship", "QualityMetricSnapshot"],
            input_schema_ref="schema://system-image/context-materialize-input",
            output_schema_ref="schema://system-image/context-materialize-output",
        ),
        ToolDefinition(
            tool_id="system_image.baseline.initialize",
            label="Initialize Official System Image",
            tool_kind="governance",
            scope="central",
            risk_level="high",
            confirmation_mode="user_confirm",
            description="Promote materialized context into the first Official System Image baseline.",
            required_context=["project_id"],
            produced_objects=["Baseline", "AuditEvent"],
            input_schema_ref="schema://system-image/baseline-initialize-input",
            output_schema_ref="schema://system-image/baseline-initialize-output",
        ),
    ]
