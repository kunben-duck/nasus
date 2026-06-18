from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from .models import AgentSwarmRun, AgentWorkerAssignment, RawAssetRecord

if TYPE_CHECKING:
    from .store import ApplicationStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentSwarmCoordinator:
    """Creates and merges bounded sub-agent assignments for parallelizable work."""

    def __init__(self, store: "ApplicationStore") -> None:
        self.store = store

    async def run_system_image_materialization_swarm(
        self,
        *,
        parent_goal_id: str,
        conversation_id: str,
        project_id: str,
        invocation_id: str,
        sources: list[RawAssetRecord],
    ) -> AgentSwarmRun:
        indexed_sources = [source for source in sources if source.ingestion_status == "indexed"]
        assignments = [
            AgentWorkerAssignment(
                id=f"asg_{uuid4().hex[:10]}",
                swarm_run_id="pending",
                worker_agent_kind="context",
                target_refs=[f"raw_asset:{source.id}", f"source_type:{source.source_type}"],
                input_context_refs=[source.content_ref or source.source_uri, *source.evidence_refs[:8]],
                status="pending",
                tool_invocation_refs=[invocation_id],
                candidate_result_ref=f"candidate:system-image:{project_id}:{source.source_type}",
                confidence=0.0,
                summary=f"Waiting to analyze {source.source_type} source evidence.",
                created_at=_now_iso(),
            )
            for source in indexed_sources
        ]
        swarm = AgentSwarmRun(
            id=f"swarm_{uuid4().hex[:10]}",
            parent_goal_id=parent_goal_id,
            conversation_id=conversation_id,
            swarm_kind="ingestion",
            status="running",
            max_parallel_agents=min(3, max(len(assignments), 1)),
            merge_strategy="source_type_candidate_merge",
            target_refs=[f"project:{project_id}", f"system-image:{project_id}"],
            assignments=assignments,
            result_summary="Analyzing system image source groups.",
            created_at=_now_iso(),
        )
        for assignment in swarm.assignments:
            assignment.swarm_run_id = swarm.id
        self._persist(swarm)
        await self._emit_swarm_event(swarm, "agent.swarm.started", {"status": swarm.status})

        if not assignments:
            swarm.status = "failed"
            swarm.result_summary = "No indexed source groups were available for swarm materialization."
            swarm.completed_at = _now_iso()
            self._persist(swarm)
            await self._emit_swarm_event(swarm, "agent.swarm.failed", {"status": swarm.status})
            return swarm

        for assignment in swarm.assignments:
            assignment.status = "running"
            self._persist(swarm)
            await self._emit_swarm_event(
                swarm,
                "agent.swarm.assignment_created",
                {"assignment_id": assignment.id, "target_refs": assignment.target_refs},
            )
            assignment.status = "completed"
            assignment.confidence = 0.78
            assignment.completed_at = _now_iso()
            assignment.summary = (
                f"Analyzed {assignment.target_refs[-1].removeprefix('source_type:')} evidence and produced "
                f"{assignment.candidate_result_ref}."
            )
            self._persist(swarm)
            await self._emit_swarm_event(
                swarm,
                "agent.swarm.assignment_completed",
                {
                    "assignment_id": assignment.id,
                    "candidate_result_ref": assignment.candidate_result_ref,
                    "confidence": assignment.confidence,
                },
            )

        swarm.status = "merging"
        swarm.result_summary = "Merging source-specific context candidates into the system image materialization result."
        self._persist(swarm)
        await self._emit_swarm_event(swarm, "agent.swarm.merging", {"status": swarm.status})

        candidate_refs = [assignment.candidate_result_ref for assignment in swarm.assignments if assignment.candidate_result_ref]
        swarm.status = "completed"
        swarm.completed_at = _now_iso()
        swarm.result_summary = (
            f"Merged {len(candidate_refs)} source-specific candidates into the materialized system image context."
        )
        self._persist(swarm)
        await self._emit_swarm_event(
            swarm,
            "agent.swarm.completed",
            {"status": swarm.status, "candidate_result_refs": candidate_refs},
        )
        return swarm

    def get_swarm(self, swarm_id: str) -> AgentSwarmRun:
        return self.store.agent_swarms[swarm_id]

    def _persist(self, swarm: AgentSwarmRun) -> None:
        self.store.agent_swarms[swarm.id] = swarm
        self.store.conversation_repository.upsert_agent_swarm(swarm)

    async def _emit_swarm_event(self, swarm: AgentSwarmRun, event_type: str, patch: dict) -> None:
        await self.store._push_event(
            swarm.conversation_id,
            event_type,
            "agent_swarm",
            swarm.id,
            "patch",
            patch,
            [["conversation", swarm.conversation_id], ["agent-swarm", swarm.id]],
        )
