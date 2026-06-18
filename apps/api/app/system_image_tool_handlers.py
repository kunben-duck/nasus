from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .models import ToolInvocation, ToolResult

if TYPE_CHECKING:
    from .store import ApplicationStore


class SystemImageToolHandler:
    """Executes system-image ToolInvocations through the system image domain service."""

    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store

    async def register_sources(self, invocation: ToolInvocation) -> None:
        project_id = self._project_id(invocation)
        if not await self._require_project(invocation.id, project_id, "register system image sources"):
            return

        await self.store._emit_tool_status(
            invocation.id,
            "running",
            "Registering code, US document, and test asset source groups",
            [["project", project_id], ["system-image", project_id]],
        )
        source_specs = self.store.system_image_service.source_ingestion.normalize_specs(
            invocation.input_payload.get("source_specs")
        )
        system_image = self.store.system_image_service.register_sources(project_id, source_specs=source_specs)
        if not source_specs and self.store.system_image_service.source_binding_incomplete(project_id):
            missing = self.store.system_image_service.missing_source_types(project_id)
            followup_prompt = (
                "I prepared the system image source slots, but I need real source bindings before ingestion. "
                "Please provide code path or Git URL, historical US documents path, and historical test assets path."
            )
            if invocation.conversation_id:
                await self.store.append_message(
                    invocation.conversation_id,
                    "assistant",
                    (
                        f"{followup_prompt}\n\n"
                        "Example: `code path /repo/app, US docs path /docs/us, tests path /repo/tests`."
                    ),
                    metadata={
                        "planner_kind": "source_binding_required",
                        "tool_invocation_id": invocation.id,
                        "tool_id": invocation.tool_id,
                        "missing_source_types": missing,
                    },
                )
            await self.store._emit_tool_status(
                invocation.id,
                "completed",
                "System image source bindings are required before ingestion",
                [["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="completed",
                    summary="Source slots are ready, but source bindings are required before ingestion can continue.",
                    object_refs=[f"project:{project_id}"] + [f"raw_asset:{source.id}" for source in system_image.sources],
                    requires_followup=True,
                    followup_reason="missing_source_binding",
                    followup_prompt=followup_prompt,
                    next_recommended_tools=["system_image.sources.register"],
                ),
            )
            return
        await self.store._emit_tool_status(
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

        await self.store._emit_tool_status(
            invocation.id,
            "running",
            "Indexing registered system image sources",
            [["project", project_id], ["system-image", project_id]],
        )
        system_image = self.store.system_image_service.ingest_sources(project_id)
        evidence_refs = [evidence for source in system_image.sources for evidence in source.evidence_refs]
        failed_sources = [source for source in system_image.sources if source.ingestion_status == "failed"]
        if failed_sources:
            failed_summary = (
                "Failed to ingest system image sources: "
                + ", ".join(f"{source.source_type}:{source.source_uri}" for source in failed_sources)
            )
            await self.store._emit_tool_status(
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
                ),
            )
            return
        await self.store._emit_tool_status(
            invocation.id,
            "completed",
            f"Indexed {len(system_image.sources)} source groups",
            [["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
            ToolResult(
                invocation_id=invocation.id,
                status="completed",
                summary=f"Indexed code, historical US documents, and historical test assets for {system_image.project.name}.",
                object_refs=[f"project:{project_id}"] + [f"raw_asset:{source.id}" for source in system_image.sources],
                evidence_refs=evidence_refs,
                next_recommended_tools=["system_image.context.materialize"],
            ),
        )

    async def materialize_context(self, invocation: ToolInvocation) -> None:
        project_id = self._project_id(invocation)
        if not await self._require_project(invocation.id, project_id, "materialize system context"):
            return

        await self.store._emit_tool_status(
            invocation.id,
            "running",
            "Materializing system context objects, relationships, and quality metrics",
            [["project", project_id], ["system-image", project_id]],
        )
        try:
            system_image = self.store.system_image_service.materialize_context(project_id)
        except RuntimeError as exc:
            await self.store._emit_tool_status(
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
        if isinstance(agent_goal_id, str) and agent_goal_id in self.store.agent_goals and invocation.conversation_id:
            swarm = await self.store.agent_swarm_coordinator.run_system_image_materialization_swarm(
                parent_goal_id=agent_goal_id,
                conversation_id=invocation.conversation_id,
                project_id=project_id,
                invocation_id=invocation.id,
                sources=system_image.sources,
            )
            swarm_ref = [f"agent_swarm:{swarm.id}"]
        await self.store._emit_tool_status(
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

        await self.store._emit_tool_status(
            invocation.id,
            "running",
            "Initializing Official System Image from code, US docs, and test assets",
            [["project", project_id], ["system-image", project_id], ["dashboard"]],
        )
        await asyncio.sleep(0.2)
        try:
            system_image = self.store.system_image_service.initialize_baseline(project_id)
        except RuntimeError as exc:
            await self.store._emit_tool_status(
                invocation.id,
                "failed",
                str(exc),
                [["project", project_id], ["system-image", project_id], ["dashboard"], ["knowledge", project_id]],
                ToolResult(
                    invocation_id=invocation.id,
                    status="failed",
                    summary=str(exc),
                    object_refs=[f"project:{project_id}"],
                ),
            )
            return
        if invocation.conversation_id:
            await self.store.append_message(
                invocation.conversation_id,
                "assistant",
                (
                    f"The Official System Image for **{system_image.project.name}** is ready. "
                    f"I indexed {len(system_image.sources)} source groups, materialized "
                    f"{len(system_image.objects)} context objects, {len(system_image.relationships)} relationships, "
                    f"and {len(system_image.metric_snapshots)} quality metric snapshots."
                ),
            )
        await self.store._emit_tool_status(
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

    async def _require_project(self, invocation_id: str, project_id: str, action: str) -> bool:
        if project_id and project_id in self.store.projects:
            return True
        await self.store._emit_tool_status(
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
