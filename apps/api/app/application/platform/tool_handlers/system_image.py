from __future__ import annotations

import asyncio

from ....domain.system_image.source_binding import REQUIRED_SOURCE_TYPES
from ...agent import AgentApplicationService, AgentReplyApplicationService
from ..tool_invocation_ports import ToolStatusEventPort
from ...system_image import SystemImageApplicationService
from ..tool_models import ToolInvocation, ToolResult


class SystemImageToolHandler:
    """Executes system-image ToolInvocations through application use cases."""

    def __init__(
        self,
        system_image_app: SystemImageApplicationService,
        tool_invocations: ToolStatusEventPort,
        agent_replies: AgentReplyApplicationService,
        agent_app: AgentApplicationService,
    ) -> None:
        self.system_image_app = system_image_app
        self.tool_invocations = tool_invocations
        self.agent_replies = agent_replies
        self.agent_app = agent_app

    async def register_sources(self, invocation: ToolInvocation) -> None:
        project_id = self._project_id(invocation)
        if not await self._require_project(invocation.id, project_id, "register system image sources"):
            return

        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            "Registering code, US document, and test asset source groups",
            [["project", project_id], ["system-image", project_id]],
        )
        source_specs = self.system_image_app.normalize_source_specs(
            invocation.input_payload.get("source_specs")
        )
        system_image = self.system_image_app.register_sources(
            project_id,
            source_specs=source_specs,
            registered_by_actor=invocation.initiator_actor,
            registered_from_invocation_id=invocation.id,
        )
        if not source_specs and self.system_image_app.source_binding_incomplete(project_id):
            missing = self.system_image_app.missing_source_types(project_id)
            followup_prompt = (
                "I prepared the system image source slots, but a real code binding is required before ingestion. "
                "Provide a code path or Git URL. Historical US documents and test assets are optional enrichment."
            )
            await self._append_assistant_message(
                invocation,
                (
                f"{followup_prompt}\n\n"
                    "Example: `code path /repo/app` or `Git URL https://example.com/team/repository.git`."
                ),
                {
                    "planner_kind": "source_binding_required",
                    "tool_invocation_id": invocation.id,
                    "tool_id": invocation.tool_id,
                    "missing_source_types": missing,
                },
            )
            await self.tool_invocations.emit_tool_status(
                invocation.id,
                "completed",
                "A code source binding is required before ingestion",
                [["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="completed",
                    summary="Source slots are ready, but a code source binding is required before ingestion can continue.",
                    object_refs=[f"project:{project_id}"] + [f"raw_asset:{source.id}" for source in system_image.sources],
                    requires_followup=True,
                    followup_reason="missing_source_binding",
                    followup_prompt=followup_prompt,
                    next_recommended_tools=["system_image.sources.register"],
                ),
            )
            return
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "completed",
            f"Registered {len(system_image.sources)} system image source groups",
            [["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=f"Registered {len(system_image.sources)} source groups for {system_image.project.name}.",
                object_refs=[f"project:{project_id}"] + [f"raw_asset:{source.id}" for source in system_image.sources],
                next_recommended_tools=["system_image.sources.ingest"],
            ),
        )

    async def ingest_sources(self, invocation: ToolInvocation) -> None:
        project_id = self._project_id(invocation)
        if not await self._require_project(invocation.id, project_id, "ingest system image sources"):
            return

        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            "Indexing registered system image sources",
            [["project", project_id], ["system-image", project_id]],
        )
        try:
            system_image = self.system_image_app.ingest_sources(project_id)
        except RuntimeError as exc:
            await self.tool_invocations.emit_tool_status(
                invocation.id,
                "failed",
                str(exc),
                [["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=str(exc),
                    object_refs=[f"project:{project_id}"],
                    requires_followup=True,
                    followup_reason="missing_source_binding",
                    followup_prompt=(
                        "Please bind a real code path or Git URL before ingestion. "
                        "Historical US documents and test assets can be added later."
                    ),
                    next_recommended_tools=["system_image.sources.register"],
                ),
            )
            return
        evidence_refs = [evidence for source in system_image.sources for evidence in source.evidence_refs]
        failed_sources = [source for source in system_image.sources if source.ingestion_status == "failed"]
        indexed_sources = [
            source
            for source in system_image.sources
            if source.ingestion_status == "indexed"
        ]
        unavailable_required_types = [
            source_type
            for source_type in REQUIRED_SOURCE_TYPES
            if not any(source.source_type == source_type for source in indexed_sources)
        ]
        if unavailable_required_types:
            failed_required_sources = [
                source
                for source in system_image.sources
                if source.source_type in unavailable_required_types
            ]
            failed_details = ", ".join(
                (
                    f"{source.source_type}:{source.source_uri}"
                    + (f" ({source.failure_reason})" if source.failure_reason else "")
                )
                for source in failed_required_sources
            )
            failed_summary = (
                "Required system image source types were not indexed: "
                + ", ".join(unavailable_required_types)
                + (f". Details: {failed_details}" if failed_details else ".")
            )
            await self.tool_invocations.emit_tool_status(
                invocation.id,
                "failed",
                failed_summary,
                [["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=failed_summary,
                    object_refs=[f"project:{project_id}"] + [f"raw_asset:{source.id}" for source in system_image.sources],
                    evidence_refs=evidence_refs,
                    requires_followup=True,
                    followup_reason="required_source_ingestion_failed",
                    followup_prompt="Review or replace the unavailable required source, then retry ingestion.",
                    next_recommended_tools=["system_image.sources.register"],
                ),
            )
            return
        optional_gap_summary = (
            " Optional source gaps: "
            + ", ".join(f"{source.source_type}:{source.source_uri}" for source in failed_sources)
            + "."
            if failed_sources
            else ""
        )
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "completed",
            f"Indexed {len(indexed_sources)} source groups.{optional_gap_summary}",
            [["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=(
                    f"Indexed {len(indexed_sources)} registered source group(s) for "
                    f"{system_image.project.name}.{optional_gap_summary}"
                ),
                object_refs=[f"project:{project_id}"] + [f"raw_asset:{source.id}" for source in system_image.sources],
                evidence_refs=evidence_refs,
                requires_followup=bool(failed_sources),
                followup_reason="optional_source_gap" if failed_sources else None,
                followup_prompt=(
                    "Review or replace the unavailable optional sources to improve traceability coverage."
                    if failed_sources
                    else None
                ),
                next_recommended_tools=["system_image.context.materialize"],
            ),
        )

    async def materialize_context(self, invocation: ToolInvocation) -> None:
        project_id = self._project_id(invocation)
        if not await self._require_project(invocation.id, project_id, "materialize system context"):
            return

        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            "Materializing system context objects, relationships, and quality metrics",
            [["project", project_id], ["system-image", project_id]],
        )
        try:
            system_image = await self.system_image_app.materialize_context(project_id)
        except RuntimeError as exc:
            await self.tool_invocations.emit_tool_status(
                invocation.id,
                "failed",
                str(exc),
                [["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=str(exc),
                    object_refs=[f"project:{project_id}"],
                ),
            )
            return

        swarm_ref: list[str] = []
        agent_goal_id = invocation.input_payload.get("agent_goal_id")
        swarm = await self.agent_app.run_system_image_materialization_swarm(
            agent_goal_id=agent_goal_id if isinstance(agent_goal_id, str) else None,
            conversation_id=invocation.conversation_id,
            project_id=project_id,
            invocation_id=invocation.id,
            sources=system_image.sources,
        )
        if swarm is not None:
            swarm_ref = [f"agent_swarm:{swarm.id}"]
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "completed",
            (
                f"Materialized {len(system_image.objects)} context objects, "
                f"{len(system_image.relationships)} relationships, and "
                f"{len(system_image.metric_snapshots)} metric snapshots"
            ),
            [["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=(
                    f"Materialized context for {system_image.project.name}: {len(system_image.objects)} objects, "
                    f"{len(system_image.relationships)} relationships, {len(system_image.metric_snapshots)} metrics."
                ),
                object_refs=[f"context_object:{item.id}" for item in system_image.objects] + swarm_ref,
                evidence_refs=[source.id for source in system_image.sources],
                next_recommended_tools=["system_image.baseline.initialize"],
            ),
        )

    async def initialize_baseline(self, invocation: ToolInvocation) -> None:
        project_id = self._project_id(invocation)
        if not await self._require_project(invocation.id, project_id, "initialize a system image"):
            return

        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "running",
            "Initializing Official System Image from code, US docs, and test assets",
            [["project", project_id], ["system-image", project_id], ["dashboard"]],
        )
        await asyncio.sleep(0.2)
        try:
            system_image = await self.system_image_app.initialize_baseline(project_id)
        except RuntimeError as exc:
            message = str(exc)
            missing_binding = "source bindings are required" in message.lower() or "missing source types" in message.lower()
            await self.tool_invocations.emit_tool_status(
                invocation.id,
                "failed",
                message,
                [["project", project_id], ["system-image", project_id], ["dashboard"], ["knowledge", project_id]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=message,
                    object_refs=[f"project:{project_id}"],
                    requires_followup=missing_binding,
                    followup_reason="missing_source_binding" if missing_binding else None,
                    followup_prompt=(
                        "Please bind a real code path or Git URL before initializing the Official System Image. "
                        "Historical US documents and test assets are optional enrichment sources."
                    )
                    if missing_binding
                    else None,
                    next_recommended_tools=["system_image.sources.register"] if missing_binding else [],
                ),
            )
            return
        await self._append_assistant_message(
            invocation,
            (
                f"The Official System Image for **{system_image.project.name}** is ready. "
                f"I indexed {len(system_image.sources)} source groups, materialized "
                f"{len(system_image.objects)} context objects, {len(system_image.relationships)} relationships, "
                f"and {len(system_image.metric_snapshots)} quality metric snapshots."
            ),
        )
        await self.tool_invocations.emit_tool_status(
            invocation.id,
            "completed",
            f"Initialized system image for {system_image.project.name}",
            [["project", project_id], ["system-image", project_id], ["dashboard"], ["knowledge", project_id]],
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=system_image.summary,
                object_refs=[f"project:{project_id}", f"baseline:{system_image.baselines[0].id}"],
                evidence_refs=[source.id for source in system_image.sources],
                next_recommended_tools=["query.system_image.status", "version.create"],
            ),
        )

    async def _append_assistant_message(
        self,
        invocation: ToolInvocation,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        if not invocation.conversation_id:
            return
        await self.agent_replies.append_assistant_message(
            conversation_id=invocation.conversation_id,
            content=content,
            metadata=metadata,
        )

    async def _require_project(self, invocation_id: str, project_id: str, action: str) -> bool:
        if self.system_image_app.has_project(project_id):
            return True
        await self.tool_invocations.emit_tool_status(
            invocation_id,
            "failed",
            f"project_id is required to {action}",
            [["projects"]],
            ToolResult(
                invocation_id=invocation_id,
                status="failed",
                summary=f"project_id is required to {action}",
            ),
        )
        return False

    @staticmethod
    def _project_id(invocation: ToolInvocation) -> str:
        return str(invocation.input_payload.get("project_id") or "")
