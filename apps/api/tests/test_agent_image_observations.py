from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal
from apps.api.app.application.agent.planner import LLMStructuredAgentPlanner
from apps.api.app.application.agent.replanning import AgentReplanRequest
from apps.api.app.application.agent.tool_context import compact_tool_catalog_json
from apps.api.app.application.agent.tool_catalog_encoding import planner_catalog_tool_ids
from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
from apps.api.app.application.platform.tool_evidence import ToolEvidenceObservationApplicationService
from apps.api.app.application.platform.tool_images import ToolImageObservationApplicationService
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.system_image.image_query_models import ImagePageInput, ImagePageReceipt, ImageDocumentInput, ImageDocumentReceipt
from apps.api.app.application.system_image.image_query_models import ImageReferenceInput, ImageReferenceReceipt
from apps.api.app.application.system_image.image_query_models import ImageDecisionInput, ImageDecisionReceipt
from apps.api.app.application.system_image.image_query_models import ImageLinkCandidatesInput, ImageLinkCandidatesReceipt, LinkCandidatePin
from apps.api.app.application.system_image.image_query_models import ImageSemanticDecisionInput, ImageSemanticDecisionReceipt
from apps.api.app.application.system_image.image_query_models import ImageSemanticApplicabilityInput, ImageSemanticApplicabilityReceipt
from apps.api.app.domain.agent.memory import AgentMemoryContext
from apps.api.app.domain.agent.runtime_models import ToolPlanStep
from apps.api.app.domain.system_image.image_revision import ImageObjectMember
from apps.api.tests.test_agent_evidence_observations import InvocationAccess, Invocations, conversation


@pytest.mark.parametrize("operation", ["read", "document", "references", "link_decisions", "link_candidates", "semantic_decisions", "semantic_applicability"])
def test_replanner_reauthorizes_image_receipt_and_never_implicitly_sends_knowledge_body(operation):
    request = ImagePageInput(project_id="project", image_revision_id="image", section="members")
    receipt = ImagePageReceipt(request=request, result_hash="sha256:" + "a" * 64, artifact_hash="sha256:" + "b" * 64,
        item_ids=["code"], total=1, next_offset=None, frozen_members=[ImageObjectMember(
            "code", "sha256:" + "c" * 64, "code_entity", "entity", "entity-revision", "source-revision", ("evidence",))])
    if operation == "document":
        request = ImageDocumentInput(project_id="project", image_revision_id="image", object_id="document")
        receipt = ImageDocumentReceipt(request=request, result_hash="sha256:" + "a" * 64, payload_hash="sha256:" + "b" * 64,
            document_revision_id="document-revision", source_revision_id="source-revision", evidence_ids=["evidence"],
            total_fields=1, next_offset=None)
    tool_id = "query.system_image.revisions." + operation
    if operation == "references":
        tool_id = "query.system_image.references.read"
        request = ImageReferenceInput(project_id="project", proposal_id="proposal")
        receipt = ImageReferenceReceipt(request=request, result_hash="sha256:" + "a" * 64, proposal_digest="sha256:" + "b" * 64,
            image_revision_id="image", assertion_ids=["assertion"], next_offset=None)
    if operation == "link_decisions":
        tool_id = "query.system_image.links.decisions"
        request = ImageDecisionInput(project_id="project", proposal_id="proposal", assertion_id="assertion")
        receipt = ImageDecisionReceipt(request=request, result_hash="sha256:" + "a" * 64, proposal_digest="sha256:" + "b" * 64,
            image_revision_id="image", head_decision_id="decision", decision_ids=["decision"], next_offset=None)
    if operation == "link_candidates":
        tool_id = "query.system_image.links.candidates"
        request = ImageLinkCandidatesInput(project_id="project", image_revision_id="image", target_object_id="ac", relation="asserts")
        target = LinkCandidatePin(object_id="ac", revision_id="ac-revision", source_revision_id="source-revision",
                                  kind="acceptance_criterion", content_hash="sha256:" + "b" * 64, evidence_ids=["evidence"])
        receipt = ImageLinkCandidatesReceipt(request=request, result_hash="sha256:" + "a" * 64,
            artifact_hash="sha256:" + "c" * 64, target=target, candidates=[], truncated=False)
    if operation == "semantic_decisions":
        tool_id = "query.system_image.links.semantic_decisions"
        request = ImageSemanticDecisionInput(project_id="project", evaluation_id="evaluation", subject_object_id="test")
        receipt = ImageSemanticDecisionReceipt(request=request, result_hash="sha256:" + "a" * 64,
            image_revision_id="image", image_artifact_hash="sha256:" + "b" * 64, evaluation_artifact_hash="sha256:" + "c" * 64,
            assertion_id="assertion", assertion_digest="sha256:" + "d" * 64, evidence_digest="sha256:" + "e" * 64,
            claim_id="claim", head_decision_id="decision", decision_ids=["decision"], total=1, next_offset=None)
    if operation == "semantic_applicability":
        tool_id = "query.system_image.links.decision_applicability"
        request = ImageSemanticApplicabilityInput(project_id="project", image_revision_id="image", expected_image_hash="sha256:" + "a" * 64,
            source_decision_id="decision", subject_object_id="test", target_object_id="ac")
        receipt = ImageSemanticApplicabilityReceipt(request=request, result_hash="sha256:" + "b" * 64,
            head_decision_id="decision", head_decision_digest="sha256:" + "c" * 64,
            source_image_revision_id="old", source_image_artifact_hash="sha256:" + "d" * 64,
            assertion_id="assertion", assertion_digest="sha256:" + "e" * 64,
            assessment_status="stale_requires_review", candidate_action="revalidate_before_review")
    invocation = ToolInvocation(id="tool", tool_id=tool_id, status="completed", summary="verified",
        input_payload={**request.model_dump(), "agent_step_id": "step"}, result=ToolResult(
            invocation_id="tool", status="completed", summary="verified", image_query=receipt))
    access = InvocationAccess()

    class Images:
        allowed = True
        calls = 0

        def expand(self, value):
            assert value == receipt
            self.calls += 1
            if not self.allowed:
                raise PermissionError("image source revoked")
            return {"content": "private-source-body"}

    images = Images()
    image_observations = ToolImageObservationApplicationService(Invocations(invocation), images, access)
    observations = ToolEvidenceObservationApplicationService(Invocations(invocation), None, access, image_observations)
    calls = []

    class LLM:
        async def generate_reply(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(mode="live", content='{"action":"keep","rationale":"Continue fixed revision investigation"}')

    async def memory(_):
        return AgentMemoryContext("system", "context", "history", 0, 0)

    planner = LLMStructuredAgentPlanner(fallback=None, llm=LLM(), tools=[],
        settings_provider=lambda: SimpleNamespace(runtime_mode="live"), custom_api_key_provider=lambda: "",
        memory_context_builder=memory, evidence_observations=observations)
    goal = AgentGoal(id="goal", conversation_id="conversation", project_id="project", planner_kind="llm_structured",
                    title="Inspect fixed image", summary="Inspect candidates", status="running", steps=[])
    replan = AgentReplanRequest(conversation(), goal, "Image query verified", latest_invocation_id="tool",
        remaining_steps=[ToolPlanStep(tool_id=tool_id, input_payload=request.model_dump())])
    assert asyncio.run(planner.replan(replan)).action == "keep"
    assert images.calls == 1
    payload = json.loads(calls[0]["user_message"])
    assert payload["evidence_query_receipt"] == receipt.model_dump(mode="json")
    if operation == "read":
        assert payload["evidence_query_receipt"]["frozen_members"][0]["evidence_ids"] == ["evidence"]
    elif operation == "document":
        assert payload["evidence_query_receipt"]["evidence_ids"] == ["evidence"]
    elif operation == "references":
        assert payload["evidence_query_receipt"]["assertion_ids"] == ["assertion"]
    elif operation == "link_candidates":
        assert payload["evidence_query_receipt"]["target"]["revision_id"] == "ac-revision"
        assert payload["evidence_query_receipt"]["semantic_status"] == "retrieved_not_asserted"
    elif operation == "semantic_applicability":
        assert payload["evidence_query_receipt"]["head_decision_id"] == "decision"
        assert payload["evidence_query_receipt"]["candidate_action"] == "revalidate_before_review"
        assert payload["evidence_query_receipt"]["approval_transferred"] is False
    else:
        assert payload["evidence_query_receipt"]["decision_ids"] == ["decision"]
    assert "private-source-body" not in calls[0]["user_message"]
    images.allowed = False
    with pytest.raises(PermissionError, match="source revoked"):
        asyncio.run(planner.replan(replan))
    assert len(calls) == 1
    with pytest.raises(Exception) as mismatch:
        image_observations.describe("tool", "other-project")
    assert mismatch.value.status_code == 403
    assert images.calls == 2
    invocation.status = "failed"
    assert observations.describe("tool", "project") is None
    assert images.calls == 2


def test_image_tools_are_discoverable_without_changing_existing_catalog_ids():
    session = conversation()
    session.title = "Inspect frozen system image revision evidence"
    tools = core_tool_definitions() + system_image_tool_definitions()
    catalog = json.loads(compact_tool_catalog_json(tools, session))
    ids = {item["tool_id"] for item in catalog["relevant_tools"]}
    assert {"query.system_image.revisions.list", "query.system_image.revisions.read", "query.system_image.revisions.evidence",
            "query.system_image.revisions.document"} <= ids
    assert planner_catalog_tool_ids(catalog) == [tool.tool_id for tool in tools]


def test_reference_tools_are_discoverable_without_enlarging_the_prompt_budget():
    session = conversation()
    session.title = "Inspect explicit requirement references in a frozen image revision"
    catalog = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), session))
    assert len(catalog["relevant_tools"]) == 12
    assert {"system_image.links.propose_references", "query.system_image.references.read"} <= {
        item["tool_id"] for item in catalog["relevant_tools"]}


@pytest.mark.parametrize("title", ["Review and reject an explicit reference", "审阅并拒绝引用关联"])
def test_reference_review_tools_are_discoverable_within_existing_budget(title):
    session = conversation()
    session.title = title
    catalog = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), session))
    assert len(catalog["relevant_tools"]) == 12
    assert {"system_image.links.review", "query.system_image.links.decisions"} <= {
        item["tool_id"] for item in catalog["relevant_tools"]}


@pytest.mark.parametrize("title", ["Freeze reviewed references into a child candidate", "冻结引用审阅到新的画像候选"])
def test_review_freeze_is_discoverable_but_still_requires_confirmation(title):
    session = conversation()
    session.title = title
    catalog = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), session))
    assert len(catalog["relevant_tools"]) == 12
    tools = {item["tool_id"]: item for item in catalog["relevant_tools"]}
    assert "query.system_image.revisions.read" in tools
    assert tools["system_image.revisions.freeze_links"]["confirmation_mode"] == "user_confirm"


@pytest.mark.parametrize("title", ["Find which code implements an acceptance criterion and which test asserts it", "调查验收条件的代码和测试语义关联"])
def test_link_recall_is_discoverable_without_increasing_planner_budget(title):
    session = conversation()
    session.title = title
    catalog = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), session))
    assert len(catalog["relevant_tools"]) == 12
    assert "query.system_image.links.candidates" in {item["tool_id"] for item in catalog["relevant_tools"]}
    assert "query.system_image.links.screened_candidates" in {item["tool_id"] for item in catalog["relevant_tools"]}


@pytest.mark.parametrize("title", ["Read semantic review history for an asserts claim", "读取语义关联的人工裁决历史"])
def test_semantic_history_is_discoverable_without_increasing_planner_budget(title):
    session = conversation()
    session.title = title
    catalog = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), session))
    assert len(catalog["relevant_tools"]) == 12
    tools = {item["tool_id"]: item for item in catalog["relevant_tools"]}
    assert tools["query.system_image.links.semantic_decisions"]["confirmation_mode"] == "none"


@pytest.mark.parametrize("title", ["Check cross-revision decision applicability before reingestion", "跨修订重新摄入之前检查人工否定的适用性"])
def test_semantic_applicability_is_discoverable_without_increasing_planner_budget(title):
    session = conversation()
    session.title = title
    catalog = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), session))
    assert len(catalog["relevant_tools"]) == 12
    tools = {item["tool_id"]: item for item in catalog["relevant_tools"]}
    assert tools["query.system_image.links.decision_applicability"]["confirmation_mode"] == "none"
