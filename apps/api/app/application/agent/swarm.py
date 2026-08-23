from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from .agent_models import AgentSwarmRun, AgentWorkerAssignment
from .ports import AgentSwarmStatePort
from ..system_image.system_image_models import RawAssetRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AgentWorkerAnalysis:
    candidate_result_ref: str
    confidence: float
    summary: str


class AgentWorkerExecutionPort(Protocol):
    async def analyze_system_image_source(
        self,
        *,
        project_id: str,
        source: RawAssetRecord,
        assignment: AgentWorkerAssignment,
    ) -> AgentWorkerAnalysis:
        ...


class IndexedSourceAgentWorker:
    """Deterministic worker over real indexed-source evidence.

    The worker does not invent a successful candidate. Confidence is derived
    from ingestion facts and available evidence, while the parent
    ToolInvocation remains the governed command boundary.
    """

    async def analyze_system_image_source(
        self,
        *,
        project_id: str,
        source: RawAssetRecord,
        assignment: AgentWorkerAssignment,
    ) -> AgentWorkerAnalysis:
        await asyncio.sleep(0)
        if source.ingestion_status != "indexed":
            raise RuntimeError(f"Source {source.id} is not indexed.")
        if not source.content_ref and not source.evidence_refs:
            raise RuntimeError(f"Source {source.id} has no readable evidence reference.")

        evidence_score = min(0.18, len(source.evidence_refs) * 0.02)
        file_score = min(0.16, source.file_count * 0.01)
        byte_score = min(0.12, source.byte_count / 5_000_000)
        hash_score = 0.08 if source.content_hash else 0.0
        confidence = round(min(0.98, 0.52 + evidence_score + file_score + byte_score + hash_score), 3)
        candidate_suffix = (source.content_hash or source.id).replace(":", "-")[:16]
        return AgentWorkerAnalysis(
            candidate_result_ref=(
                f"candidate:system-image:{project_id}:{source.source_type}:{candidate_suffix}"
            ),
            confidence=confidence,
            summary=(
                f"Analyzed indexed {source.source_type} source {source.id}: "
                f"{source.file_count} files, {source.byte_count} bytes, "
                f"{len(source.evidence_refs)} evidence references."
            ),
        )


class AgentSwarmCoordinator:
    """Runs bounded worker assignments concurrently and merges their facts."""

    def __init__(
        self,
        state: AgentSwarmStatePort,
        worker: AgentWorkerExecutionPort | None = None,
        *,
        max_parallel_agents: int = 3,
        assignment_timeout_seconds: int = 120,
    ) -> None:
        if max_parallel_agents < 1:
            raise ValueError("max_parallel_agents must be at least 1.")
        if not 1 <= assignment_timeout_seconds <= 3600:
            raise ValueError(
                "assignment_timeout_seconds must be between 1 and 3600."
            )
        self._state = state
        self.worker = worker or IndexedSourceAgentWorker()
        self.max_parallel_agents = max_parallel_agents
        self.assignment_timeout_seconds = assignment_timeout_seconds

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
                timeout_seconds=self.assignment_timeout_seconds,
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
            max_parallel_agents=min(
                self.max_parallel_agents,
                max(len(assignments), 1),
            ),
            budget_ref=f"agent_goal:{parent_goal_id}:budget",
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

        semaphore = asyncio.Semaphore(swarm.max_parallel_agents)
        projection_lock = asyncio.Lock()
        await asyncio.gather(
            *[
                self._run_assignment(
                    swarm=swarm,
                    assignment=assignment,
                    source=source,
                    project_id=project_id,
                    semaphore=semaphore,
                    projection_lock=projection_lock,
                )
                for assignment, source in zip(swarm.assignments, indexed_sources)
            ]
        )

        successful = [
            assignment
            for assignment in swarm.assignments
            if assignment.status == "completed" and assignment.candidate_result_ref
        ]
        failed = [assignment for assignment in swarm.assignments if assignment.status == "failed"]
        if not successful:
            swarm.status = "failed"
            swarm.completed_at = _now_iso()
            swarm.result_summary = (
                f"All {len(failed)} system image worker assignments failed; no candidate was merged."
            )
            self._persist(swarm)
            await self._emit_swarm_event(
                swarm,
                "agent.swarm.failed",
                {"status": swarm.status, "failed_assignment_ids": [item.id for item in failed]},
            )
            return swarm

        swarm.status = "merging"
        swarm.result_summary = "Merging source-specific context candidates into the system image materialization result."
        self._persist(swarm)
        await self._emit_swarm_event(swarm, "agent.swarm.merging", {"status": swarm.status})

        candidate_refs = [assignment.candidate_result_ref for assignment in successful]
        swarm.status = "partially_failed" if failed else "completed"
        swarm.completed_at = _now_iso()
        swarm.result_summary = (
            f"Merged {len(candidate_refs)} source-specific candidates into the materialized system image context"
            + (f"; {len(failed)} worker assignment(s) failed." if failed else ".")
        )
        self._persist(swarm)
        terminal_event_type = (
            "agent.swarm.partially_failed"
            if failed
            else "agent.swarm.completed"
        )
        await self._emit_swarm_event(
            swarm,
            terminal_event_type,
            {
                "status": swarm.status,
                "candidate_result_refs": candidate_refs,
                "failed_assignment_ids": [item.id for item in failed],
            },
        )
        return swarm

    async def _run_assignment(
        self,
        *,
        swarm: AgentSwarmRun,
        assignment: AgentWorkerAssignment,
        source: RawAssetRecord,
        project_id: str,
        semaphore: asyncio.Semaphore,
        projection_lock: asyncio.Lock,
    ) -> None:
        async with semaphore:
            async with projection_lock:
                assignment.status = "running"
                assignment.summary = f"Analyzing {source.source_type} source evidence."
                self._persist(swarm)
            await self._emit_swarm_event(
                swarm,
                "agent.swarm.assignment_created",
                {"assignment_id": assignment.id, "target_refs": assignment.target_refs},
            )
            try:
                result = await asyncio.wait_for(
                    self.worker.analyze_system_image_source(
                        project_id=project_id,
                        source=source,
                        assignment=assignment,
                    ),
                    timeout=assignment.timeout_seconds,
                )
            except asyncio.TimeoutError:
                async with projection_lock:
                    assignment.status = "failed"
                    assignment.summary = (
                        "TimeoutError: worker exceeded "
                        f"{assignment.timeout_seconds} seconds."
                    )
                    assignment.completed_at = _now_iso()
                    self._persist(swarm)
                await self._emit_swarm_event(
                    swarm,
                    "agent.swarm.assignment_failed",
                    {
                        "assignment_id": assignment.id,
                        "summary": assignment.summary,
                    },
                )
                return
            except Exception as exc:  # worker errors are isolated to their assignment
                async with projection_lock:
                    assignment.status = "failed"
                    assignment.summary = f"{type(exc).__name__}: {exc}"
                    assignment.completed_at = _now_iso()
                    self._persist(swarm)
                await self._emit_swarm_event(
                    swarm,
                    "agent.swarm.assignment_failed",
                    {"assignment_id": assignment.id, "summary": assignment.summary},
                )
                return

            async with projection_lock:
                assignment.status = "completed"
                assignment.candidate_result_ref = result.candidate_result_ref
                assignment.confidence = result.confidence
                assignment.summary = result.summary
                assignment.completed_at = _now_iso()
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

    def get_swarm(self, swarm_id: str) -> AgentSwarmRun:
        return self._state.get_swarm(swarm_id)

    def list_swarms(
        self,
        *,
        conversation_id: str | None = None,
        parent_goal_id: str | None = None,
    ) -> tuple[AgentSwarmRun, ...]:
        return self._state.list_swarms(
            conversation_id=conversation_id,
            parent_goal_id=parent_goal_id,
        )

    def _persist(self, swarm: AgentSwarmRun) -> None:
        self._state.persist_swarm(swarm)

    async def _emit_swarm_event(self, swarm: AgentSwarmRun, event_type: str, patch: dict) -> None:
        event_patch = {
            **patch,
            "transition_event_type": event_type,
            "agent_swarm": swarm.model_dump(),
        }
        await self._state.publish_swarm_event(swarm, "agent.swarm.updated", event_patch)
        # Keep the more specific transition event for existing integrations while
        # `agent.swarm.updated` remains the canonical reducer contract.
        await self._state.publish_swarm_event(swarm, event_type, event_patch)


__all__ = [
    "AgentSwarmCoordinator",
    "AgentWorkerAnalysis",
    "AgentWorkerExecutionPort",
    "IndexedSourceAgentWorker",
]
