from __future__ import annotations

import asyncio

from apps.api.app.application.agent.agent_models import AgentSwarmRun
from apps.api.app.application.agent.swarm import (
    AgentSwarmCoordinator,
    AgentWorkerAnalysis,
)
from apps.api.app.application.system_image.system_image_models import RawAssetRecord


class InMemoryAgentSwarmState:
    def __init__(self) -> None:
        self.swarms: dict[str, AgentSwarmRun] = {}
        self.events: list[tuple[str, str, dict]] = []

    def get_swarm(self, swarm_id: str) -> AgentSwarmRun:
        return self.swarms[swarm_id]

    def persist_swarm(self, swarm: AgentSwarmRun) -> None:
        self.swarms[swarm.id] = swarm

    async def publish_swarm_event(
        self,
        swarm: AgentSwarmRun,
        event_type: str,
        patch: dict,
    ) -> None:
        self.events.append((swarm.id, event_type, dict(patch)))


class ConcurrencyProbeWorker:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def analyze_system_image_source(self, *, project_id, source, assignment):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        return AgentWorkerAnalysis(
            candidate_result_ref=f"candidate:{project_id}:{source.id}",
            confidence=0.9,
            summary=f"Analyzed {source.id}.",
        )


class SelectiveFailureWorker:
    async def analyze_system_image_source(self, *, project_id, source, assignment):
        await asyncio.sleep(0)
        if source.source_type == "us_doc":
            raise RuntimeError("US source parser failed.")
        return AgentWorkerAnalysis(
            candidate_result_ref=f"candidate:{project_id}:{source.id}",
            confidence=0.88,
            summary=f"Analyzed {source.id}.",
        )


class SlowWorker:
    async def analyze_system_image_source(self, *, project_id, source, assignment):
        await asyncio.sleep(2)
        raise AssertionError("The coordinator should time out before completion.")


def _source(source_type: str) -> RawAssetRecord:
    return RawAssetRecord(
        id=f"raw_{source_type}",
        project_id="project_checkout",
        source_type=source_type,
        source_uri=f"/sources/{source_type}",
        ingestion_status="indexed",
        content_hash=f"hash-{source_type}",
        content_ref=f"s3://sources/{source_type}",
        evidence_refs=[f"evidence:{source_type}"],
        file_count=2,
        byte_count=256,
    )


def _run(
    coordinator: AgentSwarmCoordinator,
    sources: list[RawAssetRecord],
) -> AgentSwarmRun:
    return asyncio.run(
        coordinator.run_system_image_materialization_swarm(
            parent_goal_id="goal_system_image",
            conversation_id="conversation_checkout",
            project_id="project_checkout",
            invocation_id="invocation_materialize",
            sources=sources,
        )
    )


def test_swarm_uses_bounded_concurrency_and_persists_runtime_controls() -> None:
    state = InMemoryAgentSwarmState()
    worker = ConcurrencyProbeWorker()
    coordinator = AgentSwarmCoordinator(
        state,
        worker,
        max_parallel_agents=2,
        assignment_timeout_seconds=15,
    )

    swarm = _run(
        coordinator,
        [_source("code"), _source("us_doc"), _source("test_asset")],
    )

    assert worker.max_active == 2
    assert swarm.status == "completed"
    assert swarm.max_parallel_agents == 2
    assert swarm.budget_ref == "agent_goal:goal_system_image:budget"
    assert {item.timeout_seconds for item in swarm.assignments} == {15}
    assert coordinator.get_swarm(swarm.id) is swarm
    assert state.events[-1][1] == "agent.swarm.completed"


def test_swarm_preserves_successful_candidates_when_one_worker_fails() -> None:
    state = InMemoryAgentSwarmState()
    coordinator = AgentSwarmCoordinator(state, SelectiveFailureWorker())

    swarm = _run(coordinator, [_source("code"), _source("us_doc")])

    assert swarm.status == "partially_failed"
    assert {item.status for item in swarm.assignments} == {
        "completed",
        "failed",
    }
    assert "1 worker assignment(s) failed" in swarm.result_summary
    assert state.events[-1][1] == "agent.swarm.partially_failed"
    assert len(state.events[-1][2]["candidate_result_refs"]) == 1


def test_swarm_fails_assignment_after_configured_timeout() -> None:
    state = InMemoryAgentSwarmState()
    coordinator = AgentSwarmCoordinator(
        state,
        SlowWorker(),
        assignment_timeout_seconds=1,
    )

    swarm = _run(coordinator, [_source("code")])

    assert swarm.status == "failed"
    assert swarm.assignments[0].status == "failed"
    assert "exceeded 1 seconds" in swarm.assignments[0].summary
    assert state.events[-1][1] == "agent.swarm.failed"
