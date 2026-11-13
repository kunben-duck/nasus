"""M2 contract tests use an explicitly substituted review model, not live-model evidence."""
from uuid import uuid4

import pytest

from apps.api.app.main import app
from apps.api.app.application.quality_loop.requirement_review_models import RequirementAssessment
from apps.api.tests.test_requirement_revisions_api import iteration, publication, documents, evidence_api, save, read


def review_url(v, revision):
    return f"/v1/projects/{v['project_id']}/versions/{v['version']}/requirements/{revision['revision_id']}/review"


def command(v, tool, payload, *, headers=None, key=None):
    headers = headers or v["headers"]
    pending = v["client"].post("/v1/tool-invocations", headers=headers, json={
        "tool_id": tool, "input": payload, "idempotency_key": key or uuid4().hex})
    assert pending.status_code == 200, pending.text
    if pending.json()["status"] == "waiting_confirmation":
        result = v["client"].post(f"/v1/tool-invocations/{pending.json()['id']}/confirm", headers=headers)
        assert result.status_code == 200, result.text
        return result.json()
    return pending.json()


def assessment(payload, *, blocked=False):
    ref = payload["evidence"][0]["ref"]
    return RequirementAssessment.model_validate({"summary": "Contract fixture only, not semantic acceptance.",
        "checks": [{"dimension": name, "assessment": "Reviewed fixture", "refs": [ref]} for name in
            ("roles", "preconditions", "inputs_outputs", "errors", "verifiability", "conflicts")],
        "questions": [{"question": "Who may edit?", "blocking": True, "rationale": "Ownership unspecified", "refs": [ref]}] if blocked else [],
        "suggestions": [], "criteria": [{"title": "Only author may edit", "refs": [ref], "oracle": {
            "preconditions": "Article belongs to user A", "action": "User B updates the article",
            "observation": "Read response and original article", "expected_result": "403; stored article unchanged"}}]})


@pytest.fixture
def review_case(iteration, monkeypatch):
    v = iteration
    service = app.state.container.requirement_reviews
    calls = []
    monkeypatch.setattr(service.model, "prepare", lambda: ({"digest": "sha256:" + "a" * 64,
        "provider": "explicit_test_fixture", "model": "fixture", "prompt_version": "test"}, None, None))
    async def evaluate(payload, prepared):
        calls.append(payload)
        return assessment(payload, blocked=not any(e["kind"] == "user_answer" for e in payload["evidence"])), prepared[0]
    monkeypatch.setattr(service.model, "evaluate", evaluate)
    assert save(v)["status"] == "completed"
    v.update(revision=read(v).json()["items"][0], calls=calls)
    return v


def evaluate(v, revision):
    preview = v["client"].get(review_url(v, revision), headers=v["headers"], params={"preview": True})
    assert preview.status_code == 200, preview.text
    return command(v, "quality.requirement.evaluate", preview.json()["request"])


def test_review_clarify_project_and_independent_confirm(review_case):
    v = review_case
    first = v["revision"]
    result = evaluate(v, first)
    assert result["status"] == "completed", result
    view = v["client"].get(review_url(v, first), headers=v["headers"]).json()
    assert view["status"] == "clarification_required" and not view["can_confirm"]
    assert view["evaluation"]["payload"]["projection"] is None
    receipt = command(v, "query.quality.requirement_review", {
        "project_id": v["project_id"], "version_id": v["version"], "revision_id": first["revision_id"]})
    assert receipt["status"] == "completed"
    assert receipt["result"]["requirement_review"]["status"] == "clarification_required"
    assert receipt["result"]["requirement_review"]["assessment"]["questions"][0]["question"] == "Who may edit?"
    revised = {**v["request"], "us_id": first["us_id"], "expected_revision_id": first["revision_id"],
        "clarification_answers": [{"question": "Who may edit?", "answer": "Only the author. Others get 403 and the article is unchanged."}]}
    assert save(v, revised)["status"] == "completed"
    current = read(v).json()["items"][0]
    assert evaluate(v, current)["status"] == "completed"
    assert v["client"].get(review_url(v, first), headers=v["headers"]).json()["status"] == "superseded"
    view = v["client"].get(review_url(v, current), headers=v["headers"]).json()
    assert view["status"] == "awaiting_confirmation" and not view["can_confirm"]
    assert len(view["approval_requests"]) == 1
    payload = {"project_id": v["project_id"], "version_id": v["version"], "revision_id": current["revision_id"],
        "evaluation_id": view["evaluation"]["event_id"], "review_digest": view["evaluation"]["content_hash"], "reason": "Human reviewed expected behavior"}
    assert command(v, "quality.requirement.confirm", payload)["status"] == "failed"
    role = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}", headers=v["headers"], json={"role": "project_admin"})
    assert role.status_code == 200
    assert command(v, "quality.requirement.confirm", payload, headers=v["member_headers"])["status"] == "failed"
    for item in view["approval_requests"]:
        assert command(v, "quality.acceptance_specification.review", item["input"], headers=v["member_headers"])["status"] == "completed"
    key = uuid4().hex
    confirmed = command(v, "quality.requirement.confirm", payload, headers=v["member_headers"], key=key)
    assert confirmed["status"] == "completed", confirmed
    assert command(v, "quality.requirement.confirm", payload, headers=v["member_headers"], key=key)["id"] == confirmed["id"]
    final = v["client"].get(review_url(v, current), headers=v["headers"]).json()
    assert final["status"] == "confirmed" and not final["generation_authorized"]
    delivery = v["client"].get(f"/v1/projects/{v['project_id']}/versions/{v['version']}/delivery", headers=v["headers"]).json()
    assert delivery["stage"] == "requirements_confirmed"
    assert delivery["baseline"]["image_revision_id"] == first["image_revision_id"]
    assert delivery["iteration_image"]["image_revision_id"] == final["evaluation"]["payload"]["projection"]["image_revision_id"]
    assert delivery["iteration_image"]["publication_id"] is None
    assert delivery["blockers"] == ["formal_test_design_required"]
    assert len(v["calls"]) == 2


def test_changed_review_inputs_never_call_model(review_case):
    v = review_case
    preview = v["client"].get(review_url(v, v["revision"]), headers=v["headers"], params={"preview": True}).json()
    for key in ("input_digest", "model_digest"):
        result = command(v, "quality.requirement.evaluate", {**preview["request"], key: "sha256:" + "b" * 64})
        assert result["status"] == "failed"
    assert not v["calls"]


def test_projection_and_evaluation_roll_back_together(review_case, monkeypatch):
    from sqlalchemy import func, select
    from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
    from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord
    from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
    from apps.api.app.infrastructure.persistence.requirement_review_models import RequirementReviewEventRecord
    from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
    v = review_case
    def counts():
        with session_scope() as session:
            return tuple(session.scalar(select(func.count()).select_from(model).where(model.project_id == v["project_id"]))
                for model in (SourceBindingRecord, ImageRevisionRecord))
    before = counts()
    async def unblocked(payload, prepared):
        return assessment(payload), prepared[0]
    monkeypatch.setattr(app.state.container.requirement_reviews.model, "evaluate", unblocked)
    original = EventOutboxRepository.append
    def broken(self, event, **kwargs):
        session = kwargs.get("session")
        if event.event_type == "requirement.review.updated" and session is not None and any(
                isinstance(row, RequirementReviewEventRecord) and row.kind == "evaluated" for row in session.new):
            raise RuntimeError("injected evaluation outbox failure")
        return original(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", broken)
    assert evaluate(v, v["revision"])["status"] == "failed"
    assert counts() == before
    view = v["client"].get(review_url(v, v["revision"]), headers=v["headers"]).json()
    assert view["status"] == "review_failed"
    assert view["evaluation"] is None and view["confirmation"] is None


def test_late_model_result_cannot_replace_newer_review(review_case, monkeypatch):
    v = review_case
    calls = []
    async def racing(payload, prepared):
        calls.append(payload)
        if len(calls) == 1:
            newer = evaluate(v, v["revision"])
            assert newer["status"] == "completed", newer
            return assessment(payload), prepared[0]
        return assessment(payload, blocked=True), prepared[0]
    monkeypatch.setattr(app.state.container.requirement_reviews.model, "evaluate", racing)
    older = evaluate(v, v["revision"])
    assert older["status"] == "failed"
    view = v["client"].get(review_url(v, v["revision"]), headers=v["headers"]).json()
    assert view["status"] == "clarification_required"
    assert view["evaluation"]["invocation_id"] != older["id"]
    assert view["evaluation"]["payload"]["projection"] is None
    assert len([event for event in view["events"] if event["kind"] == "evaluated"]) == 1


@pytest.mark.parametrize("failure", ["timeout", "invalid_refs", "revised_during_call", "acl_changed"])
def test_failed_or_stale_review_does_not_create_authority(review_case, monkeypatch, failure):
    v = review_case
    assert evaluate(v, v["revision"])["status"] == "completed"
    async def broken(payload, prepared):
        if failure == "timeout":
            raise TimeoutError("private provider detail must not be published")
        if failure == "revised_during_call":
            assert save(v, {**v["request"], "us_id": v["revision"]["us_id"],
                "expected_revision_id": v["revision"]["revision_id"], "text": "A new requirement, not the reserved input"})["status"] == "completed"
            return assessment(payload), prepared[0]
        if failure == "acl_changed":
            from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
            from apps.api.app.domain.system_image.source_access import SourceAccessRule
            access = SourceAccessRepository()
            scope = access.load_snapshot(v["project_id"])
            access.set_policy(v["project_id"], scope.bindings[0].binding_id, SourceAccessRule("restricted"),
                expected_epoch=scope.acl_epoch, changed_by=v["owner"]["id"], invocation_id="test-revoke-during-review")
            return assessment(payload), prepared[0]
        result = assessment(payload).model_dump()
        result["checks"][0]["refs"] = ["unknown:approval"]
        return RequirementAssessment.model_validate(result), prepared[0]
    monkeypatch.setattr(app.state.container.requirement_reviews.model, "evaluate", broken)
    assert evaluate(v, v["revision"])["status"] == "failed"
    view = v["client"].get(review_url(v, v["revision"]), headers=v["headers"]).json()
    assert view["status"] == ("superseded" if failure == "revised_during_call" else "review_failed")
    assert not view["can_confirm"] and not view["approval_requests"]
    assert not view["confirmation"] and not view["generation_authorized"]
    assert "private provider" not in str(view)


def test_chat_clarification_refresh_and_unrelated_question(review_case, monkeypatch):
    from apps.api.tests.test_agent_investigation_continuation import replace_graph
    from apps.api.tests.test_natural_build_entries_api import send
    v = review_case
    replace_graph(monkeypatch, "langgraph_postgres")
    v["conversation"] = v["client"].post("/v1/conversations", headers=v["headers"], json={
        "space_type": "version", "space_id": v["version"], "title": "M2 clarification"})
    assert v["conversation"].status_code == 200, v["conversation"].text
    pending = send(v, "需求：支持修改文章")
    state = pending["messages"][-1]["metadata"]["requirement_intake"]
    assert "确认评审需求" in pending["messages"][-1]["blocks"][0]["text"]
    assert not v["calls"]
    blocked = send(v, "确认评审需求")
    assert "Who may edit?" in blocked["messages"][-1]["blocks"][0]["text"]
    question = send(v, "当前项目名称是什么")
    assert question["messages"][-1]["metadata"].get("planner_kind") != "guided_requirement"
    refreshed = v["client"].get(f"/v1/conversations/{question['id']}", headers=v["headers"])
    assert refreshed.status_code == 200
    replace_graph(monkeypatch, "langgraph_postgres")
    answered = send(v, "回答：Only the author may edit. Others receive 403 and the article remains unchanged.")
    new_state = answered["messages"][-1]["metadata"]["requirement_intake"]
    assert new_state["revision_id"] != state["revision_id"]
    assert "确认评审需求" in answered["messages"][-1]["blocks"][0]["text"]
    reviewed = send(v, "确认评审需求")
    assert "独立审核人" in reviewed["messages"][-1]["blocks"][0]["text"]
    assert len(v["calls"]) == 2
    assert any(e["kind"] == "user_answer" for e in v["calls"][-1]["evidence"])
