from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal, ConversationSession
from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
from apps.api.app.application.agent.planner import LLMStructuredAgentPlanner
from apps.api.app.application.agent.replanning import AgentReplanDecision, AgentReplanRequest
from apps.api.app.application.agent.tool_context import compact_tool_catalog_json
from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
from apps.api.app.application.platform.tool_evidence import ToolEvidenceObservationApplicationService
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.system_image.evidence_tool_models import EvidenceListInput, EvidenceReadInput
from apps.api.app.application.system_image.evidence_tools import EvidenceToolApplicationService
from apps.api.app.application.system_image.memory_context import SystemImageContextFacts, SystemImageMemoryContextApplicationService
from apps.api.app.domain.agent.memory import AgentMemoryContext
from apps.api.app.domain.agent.runtime_models import AgentGoalProposal, ToolPlanStep
from apps.api.app.domain.agent.state_machine import AgentGoalStateMachine
from apps.api.tests.test_agent_graph_application import InMemoryAgentGraphState, StaticPlanCompiler
from apps.api.tests.test_agent_memory_application import EmptyProjectContextReader
from apps.api.tests.test_source_evidence import service


def conversation():
    return ConversationSession(id="conversation", session_id="session", title="Inspect code evidence",
                               space_type="project", space_id="project", project_id="project")


class InvocationAccess:
    allowed = True

    def require_invocation_project_scope(self, invocation):
        if not self.allowed:
            raise PermissionError("revoked")


class Invocations:
    def __init__(self, invocation):
        self.invocation = invocation

    def get_tool_invocation(self, invocation_id):
        assert invocation_id == self.invocation.id
        return self.invocation


@pytest.mark.parametrize("operation", ["list", "read"])
def test_replanner_uses_authorized_receipts_not_source_body(operation):
    queries, reader, _ = service()
    tools = EvidenceToolApplicationService(queries)
    if operation == "list":
        request = EvidenceListInput(project_id="project", source_revision_id="revision", object_id="object")
        receipt = tools.list(request)
    else:
        request = EvidenceReadInput(project_id="project", source_revision_id="revision", evidence_id="evidence")
        receipt = tools.read(request)
    invocation = ToolInvocation(id="tool", tool_id=f"query.system_image.evidence.{operation}", status="completed",
                                summary="verified", input_payload=request.model_dump(), result=ToolResult(
                                    invocation_id="tool", status="completed", summary="verified", evidence_query=receipt,
                                ))
    access = InvocationAccess()
    observations = ToolEvidenceObservationApplicationService(Invocations(invocation), tools, access)
    calls = []

    class LLM:
        async def generate_reply(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(mode="live", content='{"action":"keep","rationale":"Inspect next pinned evidence"}')

    async def memory(session):
        return AgentMemoryContext("system", "context", "history", 0, 0)

    planner = LLMStructuredAgentPlanner(
        fallback=None, llm=LLM(), tools=[], settings_provider=lambda: SimpleNamespace(runtime_mode="live"),
        custom_api_key_provider=lambda: "", memory_context_builder=memory, evidence_observations=observations,
    )
    goal = AgentGoal(id="goal", conversation_id="conversation", project_id="project", planner_kind="llm_structured",
                     title="Inspect code", summary="Inspect pinned evidence", status="running", steps=[])
    replan = AgentReplanRequest(conversation(), goal, "Evidence verified", latest_invocation_id="tool",
                               remaining_steps=[ToolPlanStep(tool_id="query.system_image.status", input_payload={"project_id": "project"})])
    reads_before = reader.calls
    assert asyncio.run(planner.replan(replan)).action == "keep"
    data = json.loads(calls[-1]["user_message"])
    assert data["evidence_query_receipt"] == receipt.model_dump(mode="json")
    assert "untrusted" in data["evidence_handling"]
    assert "return 'ok'" not in calls[-1]["user_message"]
    assert reader.calls == reads_before
    class SourceAccess:
        def require_binding_access(self, project_id, binding_id):
            raise PermissionError("source revoked")

        def require_revision_access(self, project_id, revision_id):
            raise PermissionError("source revoked")
    original_source_authorization = queries.source_authorization
    queries.source_authorization = SourceAccess()
    with pytest.raises(PermissionError, match="source revoked"):
        asyncio.run(planner.replan(replan))
    assert len(calls) == 1 and reader.calls == reads_before
    queries.source_authorization = original_source_authorization
    access.allowed = False
    with pytest.raises(PermissionError):
        asyncio.run(planner.replan(replan))
    assert len(calls) == 1


def test_graph_passes_the_observed_invocation_id_to_replanner():
    session = conversation()
    state = InMemoryAgentGraphState(session)
    requests = []

    class Replanner:
        async def replan(self, request):
            requests.append(request)
            return AgentReplanDecision.keep("Continue validated inspection")

    graph = LocalAgentGraphRuntime(state, AgentGoalStateMachine(), StaticPlanCompiler(), Replanner())
    proposal = AgentGoalProposal(goal_template="status_query", title="Inspect evidence", summary="Inspect sources", goal_description="Inspect pinned sources",
                                 planned_tools=[ToolPlanStep(tool_id=tool, input_payload={"project_id": "project"})
                                                for tool in ("query.system_image.evidence.list", "query.system_image.status")])
    goal = AgentGoal(id="goal", conversation_id=session.id, project_id="project", title=proposal.title,
                     status="pending", summary=proposal.summary, steps=graph.steps_for_proposal(proposal))
    state.goals[goal.id] = goal
    asyncio.run(graph.start(goal.id, proposal))
    assert goal.status == "completed"
    assert requests[0].latest_invocation_id == "invocation_1"


def test_agent_context_advertises_evidence_tools_and_real_revision_pins_only():
    catalog = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation()))
    assert {"query.system_image.evidence.list", "query.system_image.evidence.read"} <= {
        item["tool_id"] for item in catalog["relevant_tools"]
    }
    attrs = dict(name="Orders", type="code", branch="main", confidence=1, freshness="fresh")
    class PinnedContextReader(EmptyProjectContextReader):
        def read(self, project_id):
            return SystemImageContextFacts(scope=self.scope(project_id), objects=(
                SimpleNamespace(id="code", **attrs, code_reference=SimpleNamespace(source_revision_id="revision", entity_revision_id="entity-revision")),
                SimpleNamespace(id="legacy", **attrs),
            ))

    sections = SystemImageMemoryContextApplicationService(PinnedContextReader()).context_sections("project")
    pins = [json.loads(item.split("=", 1)[1]) for item in sections if item.startswith("code_evidence_query=")]
    assert pins == [{"project_id": "project", "object_id": "code", "source_revision_id": "revision", "entity_revision_id": "entity-revision"}]
