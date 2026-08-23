from __future__ import annotations

from dataclasses import dataclass, field

from apps.api.app.application.platform.tool_models import ToolInvocation
from apps.api.app.application.quality_loop.ports import (
    QualityLoopConversationScope,
)
from apps.api.app.application.quality_loop.quality_models import RunDetail
from apps.api.app.application.quality_loop.scope_queries import (
    QualityLoopScopeQueryApplicationService,
)


@dataclass
class InMemoryQualityLoopScopeWorkspace:
    conversations: dict[str, QualityLoopConversationScope] = field(
        default_factory=dict
    )
    us_owners: dict[str, str] = field(default_factory=dict)
    project_us: dict[str, list[str]] = field(default_factory=dict)
    run_owners: dict[str, str] = field(default_factory=dict)
    run_details: dict[str, list[RunDetail]] = field(default_factory=dict)
    evidence_us: dict[tuple[str, str], str] = field(default_factory=dict)

    def conversation_scope(
        self,
        conversation_id: str | None,
    ) -> QualityLoopConversationScope | None:
        return self.conversations.get(conversation_id or "")

    def project_id_for_us(self, us_id: str) -> str | None:
        return self.us_owners.get(us_id)

    def first_us_id(self, project_id: str) -> str | None:
        items = self.project_us.get(project_id, [])
        return items[0] if items else None

    def project_id_for_run(self, run_id: str) -> str | None:
        return self.run_owners.get(run_id)

    def list_run_details(self, project_id: str) -> list[RunDetail]:
        return list(self.run_details.get(project_id, []))

    def us_id_for_run_evidence(
        self,
        project_id: str,
        run_id: str,
    ) -> str | None:
        return self.evidence_us.get((project_id, run_id))


def invocation(
    *,
    conversation_id: str | None = None,
    input_payload: dict[str, str] | None = None,
) -> ToolInvocation:
    return ToolInvocation(
        id="inv_scope",
        conversation_id=conversation_id,
        tool_id="quality.failure.analyze",
        status="pending",
        summary="Resolve governed quality-loop scope",
        input_payload=input_payload or {},
    )


def failed_run(run_id: str) -> RunDetail:
    return RunDetail(
        id=run_id,
        status="failed",
        channel="web_runner",
        title="Checkout regression",
        summary="Checkout assertion failed.",
        started_at="2026-07-30T00:00:00+00:00",
        failure_summary="Assertion failed.",
        healing_status="not_started",
    )


def test_scope_resolves_conversation_project_and_first_us() -> None:
    workspace = InMemoryQualityLoopScopeWorkspace(
        conversations={
            "conv_project": QualityLoopConversationScope(
                project_id=None,
                us_id=None,
                space_type="project",
                space_id="proj_a",
            ),
            "conv_workspace": QualityLoopConversationScope(
                project_id="proj_a",
                us_id=None,
                space_type="workspace",
                space_id="US-A2",
            ),
        },
        us_owners={"US-A1": "proj_a", "US-A2": "proj_a"},
        project_us={"proj_a": ["US-A1", "US-A2"]},
    )
    service = QualityLoopScopeQueryApplicationService(workspace)

    assert service.resolve_scope(
        invocation(conversation_id="conv_project")
    ) == ("proj_a", "US-A1")
    assert service.resolve_scope(
        invocation(conversation_id="conv_workspace")
    ) == ("proj_a", "US-A2")


def test_scope_rejects_unknown_or_cross_project_us() -> None:
    workspace = InMemoryQualityLoopScopeWorkspace(
        us_owners={"US-A1": "proj_a", "US-B1": "proj_b"},
        project_us={"proj_a": ["US-A1"], "proj_b": ["US-B1"]},
    )
    service = QualityLoopScopeQueryApplicationService(workspace)

    assert service.resolve_scope(
        invocation(input_payload={"project_id": "proj_a", "us_id": "US-B1"})
    ) is None
    assert service.resolve_scope(
        invocation(input_payload={"project_id": "proj_a", "us_id": "US-X"})
    ) is None


def test_failure_scope_uses_run_ownership_and_evidence_us() -> None:
    run = failed_run("run_a")
    workspace = InMemoryQualityLoopScopeWorkspace(
        us_owners={"US-A1": "proj_a"},
        project_us={"proj_a": ["US-A1"]},
        run_owners={"run_a": "proj_a"},
        run_details={"proj_a": [run]},
        evidence_us={("proj_a", "run_a"): "US-A1"},
    )
    service = QualityLoopScopeQueryApplicationService(workspace)

    assert service.resolve_failure_scope(
        invocation(input_payload={"run_id": "run_a"})
    ) == ("proj_a", "US-A1", run)


def test_failure_scope_rejects_cross_project_run_and_us() -> None:
    workspace = InMemoryQualityLoopScopeWorkspace(
        us_owners={"US-A1": "proj_a", "US-B1": "proj_b"},
        project_us={"proj_a": ["US-A1"], "proj_b": ["US-B1"]},
        run_owners={"run_b": "proj_b"},
        run_details={"proj_b": [failed_run("run_b")]},
    )
    service = QualityLoopScopeQueryApplicationService(workspace)

    assert service.resolve_failure_scope(
        invocation(
            input_payload={
                "project_id": "proj_a",
                "run_id": "run_b",
            }
        )
    ) is None
    assert service.resolve_failure_scope(
        invocation(
            input_payload={
                "project_id": "proj_b",
                "run_id": "run_b",
                "us_id": "US-A1",
            }
        )
    ) is None


def test_query_keys_keep_conversation_and_quality_projections() -> None:
    service = QualityLoopScopeQueryApplicationService(
        InMemoryQualityLoopScopeWorkspace()
    )

    assert service.query_keys_for(
        invocation(conversation_id="conv_a"),
        "proj_a",
        "US-A1",
    ) == [
        ["conversation", "conv_a"],
        ["project", "proj_a"],
        ["workspace", "proj_a", "US-A1"],
        ["runs", "proj_a"],
        ["governance", "proj_a"],
    ]
