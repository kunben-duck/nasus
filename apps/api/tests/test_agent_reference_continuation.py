"""Reference proposals remain candidates on the original, independently reviewed goal."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.agent_models import AgentGoal, AgentStep
from apps.api.app.application.agent.image_investigation_plans import AgentInvestigationPlanApplicationService
from apps.api.app.application.system_image.investigations import InvestigationInput
from apps.api.app.application.system_image.reference_links import ReferenceProposalPage
from apps.api.app.domain.agent.image_plan_policy import validate_image_plan
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.app.domain.agent.runtime_models import ToolPlanStep
from apps.api.app.domain.system_image.image_revision import ImageRevisionPageTooLarge
from apps.api.app.domain.system_image.investigation import InvestigationTask


HASH = "sha256:" + "a" * 64


@pytest.fixture
def reference_goal():
    request = InvestigationInput(project_id="project", plan_id="plan", plan_digest=HASH, goal_id="goal",
        image_revision_id="image", image_artifact_hash=HASH)
    body = {"project_id": "project", "image_revision_id": "image"}
    task = InvestigationTask("explicit-reference", "Which tests reference requirements?", "Inspect fixed field evidence",
        "explicit_reference_candidates_unreviewed", "system_image.links.propose_references", body, ("not coverage",))
    review = SimpleNamespace(state="investigation_ready", policy_version="nasus.image-investigation-revision.v2",
        work_items=(task,))
    revision = SimpleNamespace(request=request, review=review, revision_hash=HASH)
    investigation = SimpleNamespace(id="investigate", status="completed", tool_id="system_image.build.investigate",
        conversation_id="conversation", input_payload={**request.model_dump(mode="json", exclude_none=True), "agent_goal_id": "goal"},
        result=SimpleNamespace(status="completed", object_refs=["image_investigation:review"],
            investigation=SimpleNamespace(project_id="project", revision_id="review", revision_hash=HASH)))
    command = SimpleNamespace(id="reference", status="completed", tool_id="system_image.links.propose_references",
        conversation_id="conversation", input_payload={**body, "agent_goal_id": "goal"},
        result=SimpleNamespace(status="completed", object_refs=["image_reference_proposal:proposal"],
            followup_reason="reference_candidate_review"))
    goal = AgentGoal(id="goal", project_id="project", conversation_id="conversation", title="Build fixed image",
        summary="Inspect references", goal_template="system_image_build", status="paused",
        pause_reason="reference_candidate_review", target_refs=["build_plan:plan"], max_steps=1000,
        steps=[AgentStep(id="investigate-step", title="Investigate", phase="acting", status="completed",
            selected_tool_id=investigation.tool_id, tool_invocation_id=investigation.id,
            tool_input_payload=request.model_dump(mode="json", exclude_none=True)),
            AgentStep(id="reference-step", title="Propose references", phase="acting", status="blocked",
                selected_tool_id=command.tool_id, tool_invocation_id=command.id, tool_input_payload=body)])
    page = ReferenceProposalPage("proposal", HASH, "image", HASH, "nasus.explicit-requirement-reference.v1",
        "proposed", "not_in_image_membership", "2026-10-08T00:00:00Z", 2, 51, 2, "assertions", ({"fixture_index": 0},), 1)
    reads = []

    def read(project, proposal, **kwargs):
        reads.append((project, proposal, kwargs))
        return reference_page(page, **kwargs)

    commands = {investigation.id: investigation, command.id: command}
    service = AgentInvestigationPlanApplicationService(SimpleNamespace(get_tool_invocation=commands.__getitem__),
        SimpleNamespace(read=lambda project, ident: revision), None, references=SimpleNamespace(read=read))
    return SimpleNamespace(goal=goal, service=service, revision=revision, task=task, command=command,
        investigation=investigation, reads=reads, page=page)


def reference_page(page, *, section, offset, limit):
    count = page.assertion_count if section == "assertions" else page.gap_count
    end = min(offset + limit, count)
    return replace(page, section=section, items=tuple({"fixture_index": index} for index in range(offset, end)),
        next_offset=end if end < count else None)


def test_v2_followup_adds_only_the_reviewed_fixed_reference_capability(reference_goal):
    v = reference_goal
    v.goal.steps = v.goal.steps[:1]
    steps = v.service.followup(v.goal)
    assert len(steps) == 1 and steps[0].tool_id == v.task.tool_id and steps[0].input_payload == v.task.input_payload
    assert not v.reads


@pytest.mark.parametrize("change", ["old_policy", "model", "attempts", "image", "tool", "conversation"])
def test_followup_rejects_unreviewed_or_replaced_reference_capabilities(reference_goal, change):
    v = reference_goal
    v.goal.steps = v.goal.steps[:1]
    if change == "old_policy":
        v.revision.review.policy_version = "nasus.image-investigation-revision.v1"
    elif change in {"model", "attempts", "image", "tool"}:
        patch = {"model": {"max_model_calls": 1}, "attempts": {"max_attempts": 2},
            "image": {"input_payload": {**v.task.input_payload, "image_revision_id": "foreign"}},
            "tool": {"tool_id": "system_image.links.review"}}[change]
        v.revision.review.work_items = (replace(v.task, **patch),)
    else:
        v.investigation.conversation_id = "foreign"
    with pytest.raises(AgentPlanPolicyViolation):
        v.service.followup(v.goal)
    assert not v.reads


def test_reference_review_compiles_every_candidate_and_gap_page_without_accepting_any(reference_goal):
    v = reference_goal
    original = v.goal.model_dump(mode="json")
    steps = v.service.after_reference(v.goal)
    assert [(step.input_payload["section"], step.input_payload["offset"], step.input_payload["limit"])
        for step in steps] == [("assertions", 0, 50), ("assertions", 50, 50), ("gaps", 0, 50)]
    assert all(step.tool_id == "query.system_image.references.read"
        and step.input_payload["proposal_id"] == "proposal" for step in steps)
    assert v.reads == [("project", "proposal", {"section": "assertions", "offset": 0, "limit": 1}),
        ("project", "proposal", {"section": "assertions", "offset": 0, "limit": 50}),
        ("project", "proposal", {"section": "assertions", "offset": 50, "limit": 50}),
        ("project", "proposal", {"section": "gaps", "offset": 0, "limit": 50})]
    assert v.goal.model_dump(mode="json") == original


@pytest.mark.parametrize("change", ["goal", "conversation", "image", "step", "refs", "hash", "policy", "status", "count", "budget"])
def test_reference_review_cannot_change_original_goal_image_or_candidate_semantics(reference_goal, change, monkeypatch):
    v = reference_goal
    if change in {"goal", "conversation", "image", "refs"}:
        if change == "goal":
            v.command.input_payload["agent_goal_id"] = "foreign"
        elif change == "conversation":
            v.command.conversation_id = "foreign"
        elif change == "image":
            v.command.input_payload["image_revision_id"] = "foreign"
        else:
            v.command.result.object_refs = ["image_reference_proposal:proposal", "image_reference_proposal:foreign"]
    elif change == "step":
        v.goal.steps[-1].tool_input_payload = {"project_id": "project", "image_revision_id": "foreign"}
    elif change == "policy":
        v.revision.review.policy_version = "nasus.image-investigation-revision.v1"
    elif change == "budget":
        v.goal.max_steps = 4
    else:
        patch = {"hash": {"image_artifact_hash": "sha256:" + "b" * 64},
            "status": {"status": "accepted"}, "count": {"gap_count": True}}[change]
        monkeypatch.setattr(v.service.references, "read", lambda *args, **kwargs: replace(v.page, **patch))
    original = v.goal.model_dump(mode="json")
    with pytest.raises(AgentPlanPolicyViolation):
        v.service.after_reference(v.goal)
    assert v.goal.model_dump(mode="json") == original


def test_empty_reference_report_still_accounts_for_both_sections(reference_goal, monkeypatch):
    v = reference_goal
    monkeypatch.setattr(v.service.references, "read", lambda *args, **kwargs:
        reference_page(replace(v.page, assertion_count=0, gap_count=0), **kwargs))
    assert [step.input_payload["section"] for step in v.service.after_reference(v.goal)] == ["assertions", "gaps"]


def test_reference_pages_reduce_item_limit_without_losing_candidates_or_gaps(reference_goal, monkeypatch):
    v, calls = reference_goal, []
    page = replace(v.page, assertion_count=5, gap_count=1)

    def bounded(*args, **kwargs):
        calls.append(kwargs)
        if kwargs["section"] == "assertions" and kwargs["limit"] > 2:
            raise ImageRevisionPageTooLarge("request fewer reference assertions")
        return reference_page(page, **kwargs)

    monkeypatch.setattr(v.service.references, "read", bounded)
    original = v.goal.model_dump(mode="json")
    steps = v.service.after_reference(v.goal)
    assert [(step.input_payload["section"], step.input_payload["offset"], step.input_payload["limit"])
        for step in steps] == [("assertions", 0, 2), ("assertions", 2, 2), ("assertions", 4, 2), ("gaps", 0, 50)]
    assert {index for step in steps if step.input_payload["section"] == "assertions"
        for index in range(step.input_payload["offset"], min(5, step.input_payload["offset"] + step.input_payload["limit"]))} == set(range(5))
    assert v.goal.model_dump(mode="json") == original
    assert [call["limit"] for call in calls if call["offset"] == 0 and call["section"] == "assertions"] == [1, 50, 25, 13, 7, 4, 2]


@pytest.mark.parametrize("change", ["digest", "section", "count", "items", "cursor", "publication"])
def test_reference_plan_rejects_inconsistent_or_partial_page_before_advancing_goal(reference_goal, monkeypatch, change):
    v = reference_goal
    read = v.service.references.read

    def corrupted(*args, **kwargs):
        page = read(*args, **kwargs)
        if kwargs["limit"] == 1:
            return page
        patch = {"digest": {"digest": "sha256:" + "b" * 64}, "section": {"section": "gaps"},
            "count": {"assertion_count": 50}, "items": {"items": page.items[:-1]},
            "cursor": {"next_offset": 0}, "publication": {"publication": "accepted"}}[change]
        return replace(page, **patch)

    monkeypatch.setattr(v.service.references, "read", corrupted)
    original = v.goal.model_dump(mode="json")
    with pytest.raises(AgentPlanPolicyViolation, match="Reference pagination"):
        v.service.after_reference(v.goal)
    assert v.goal.model_dump(mode="json") == original


def test_smaller_reference_pages_cannot_exceed_original_step_ceiling(reference_goal, monkeypatch):
    v = reference_goal
    page = replace(v.page, assertion_count=5, gap_count=1)
    v.goal.max_steps = 9

    def bounded(*args, **kwargs):
        if kwargs["section"] == "assertions" and kwargs["limit"] > 2:
            raise ImageRevisionPageTooLarge("request fewer reference assertions")
        return reference_page(page, **kwargs)

    monkeypatch.setattr(v.service.references, "read", bounded)
    original = v.goal.model_dump(mode="json")
    with pytest.raises(AgentPlanPolicyViolation) as failure:
        v.service.after_reference(v.goal)
    assert failure.value.code == "reference_review_budget_insufficient"
    assert v.goal.model_dump(mode="json") == original


def test_one_reference_over_byte_limit_fails_without_omitting_it(reference_goal, monkeypatch):
    v = reference_goal

    def oversized(*args, **kwargs):
        raise ImageRevisionPageTooLarge("single reference cannot fit the response budget")

    monkeypatch.setattr(v.service.references, "read", oversized)
    original = v.goal.model_dump(mode="json")
    with pytest.raises(ImageRevisionPageTooLarge):
        v.service.after_reference(v.goal)
    assert v.goal.model_dump(mode="json") == original


def test_structural_consent_cannot_skip_independent_investigation_to_get_reference_work():
    body = {"project_id": "project", "image_revision_id": "image"}
    structure = [ToolPlanStep("system_image.build.authorize", {"project_id": "project"}),
        ToolPlanStep("system_image.build.structure", {"project_id": "project"})]
    references = ToolPlanStep("system_image.links.propose_references", body)
    with pytest.raises(AgentPlanPolicyViolation):
        validate_image_plan([*structure, references])
    investigate = ToolPlanStep("system_image.build.investigate", body)
    validate_image_plan([*structure, investigate, references])
    with pytest.raises(AgentPlanPolicyViolation):
        validate_image_plan([*structure, references, investigate])
