"""M1 through real conversation Turns, canonical commands and PostgreSQL facts."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_build_dialogue_api import start, draft
from apps.api.tests.test_natural_build_entries_api import send as send_turn
from apps.api.tests.test_agent_investigation_continuation import replace_graph
from apps.api.tests.test_git_source_connector import _create_repository
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_image_publications_api import publication, review, review_request, publish_request, history, inspect
from apps.api.tests.test_semantic_evaluations_api import invoke, completed
from apps.api.app.application.agent.delivery_dialogue_inputs import DELIVERY_STATE_KEY
from apps.api.app.store import get_runtime_assembly
from apps.api.app.infrastructure.system_image.git_source_connector import GitSourceConnector


def intake(conversation):
    return next(message["metadata"][DELIVERY_STATE_KEY] for message in reversed(conversation["messages"])
        if DELIVERY_STATE_KEY in message["metadata"])


def send(v, message):
    return send_turn(v, message, timeout_seconds=180 if os.getenv("M1_REALWORLD_REPOSITORY") else 20)


def realworld_code_evidence(v, image):
    root = f"{v['image_url']}/revisions/{image['image_revision_id']}"

    def all_items(section):
        items, offset = [], 0
        while offset is not None:
            response = v["client"].get(root, headers=v["headers"],
                params={"section": section, "offset": offset, "limit": 10})
            assert response.status_code == 200, response.text
            page = response.json()
            items.extend(page["items"])
            offset = page["next_offset"]
        return items

    objects = all_items("objects")
    members = {item["object_id"]: item for item in all_items("members")}
    checks = (
        ("update", "apps/articles/api.py", ("request.user != article.author", "raise AuthorizationError", "exclude_unset=True")),
        ("Article", "apps/articles/models.py", ("class Article(", "author = models.ForeignKey", "slug = models.SlugField")),
    )
    evidence = []
    for symbol, path, expected in checks:
        found = [obj for obj in objects if obj["name"].startswith(symbol + " (") and path in obj["name"]]
        assert len(found) == 1, (symbol, path, [obj["name"] for obj in objects])
        obj = found[0]
        member = members[obj["id"]]
        assert member["source_revision_id"] == obj["code_reference"]["source_revision_id"]
        assert member["evidence_ids"], obj
        text, references = "", []
        for evidence_id in member["evidence_ids"]:
            response = v["client"].get(f"{root}/objects/{obj['id']}/evidence/{evidence_id}",
                headers=v["headers"], params={"max_lines": 200})
            assert response.status_code == 200, response.text
            page = response.json()
            assert page["integrity"] == "verified"
            assert page["evidence"]["source_revision_id"] == member["source_revision_id"]
            text += page["content"]
            references.append({"evidence_id": evidence_id, "excerpt_hash": page["excerpt_hash"],
                "start_line": page["start_line"], "end_line": page["end_line"]})
        assert all(fragment in text for fragment in expected), (symbol, text)
        evidence.append({"object_id": obj["id"], "name": obj["name"],
            "source_revision_id": member["source_revision_id"], "references": references})
    return evidence


def independent_publication(v):
    member = v["client"].put(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}",
        headers=v["headers"], json={"role": "project_admin"})
    assert member.status_code == 200, member.text
    conversation = v["client"].post("/v1/conversations", headers=v["member_headers"], json={
        "space_type": "project", "space_id": v["project_id"], "title": "Independent M1 review"})
    assert conversation.status_code == 200, conversation.text
    reviewer = {**v, "headers": v["member_headers"], "conversation": conversation}
    approval, _ = review(reviewer, review_request(reviewer))
    assert inspect(v)["review"]["actor_id"] == v["member"]["id"] != v["owner"]["id"]
    completed(invoke(v, "baseline.promote", publish_request(v, approval), key=uuid4().hex))
    head = history(v)["head"]
    preview = v["client"].get(v["publication_url"] + "/preview", headers=v["headers"], params={
        "image_revision_id": v["target"]["image_revision_id"],
        "image_artifact_hash": v["target"]["image_artifact_hash"],
        "target_baseline_id": v["target"]["target_baseline_id"], "expected_head_id": head["publication_id"],
    })
    assert preview.status_code == 200, preview.text
    assert head["actor_id"] == v["owner"]["id"]
    return head


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_chat_project_to_reviewed_image_and_explicit_iteration(evidence_api, tmp_path, monkeypatch, graph_kind, requirement_document=None):
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    repository = tmp_path / "source.git"
    commit = _create_repository(repository)
    realworld = os.getenv("M1_REALWORLD_REPOSITORY")
    if realworld:
        repository = Path(realworld).resolve(strict=True)
        commit = "87dd078c883a046f5ff20269df2fb004d8b5f83f"
    for connector in get_runtime_assembly().source_ingestion.connectors:
        if isinstance(connector, GitSourceConnector):
            monkeypatch.setattr(connector, "allowed_schemes", {"file"})
    start(v)
    send(v, "帮我构建一个系统画像")
    created = send(v, "项目叫 M1 对话闭环")
    v["project_id"] = created["project_id"]
    assert v["project_id"] and draft(created)["stage"] == "sources"
    source = send(v, f"代码仓库 {repository.as_uri()} 提交 {commit}")
    assert draft(source)["code_ref"] == commit
    assert draft(source)["code"] == repository.as_uri(), draft(source)
    if requirement_document is not None:
        uploaded = v["client"].post(f"/v1/projects/{v['project_id']}/source-files", headers=v["headers"],
            data={"source_type": "us_doc"}, files=[("files", ("realworld-contract.md", requirement_document, "text/plain"))])
        assert uploaded.status_code == 200, uploaded.text
        attached = send(v, "需求文档地址 " + uploaded.json()["source_uri"])
        assert draft(attached)["requirements"] == uploaded.json()["source_uri"]
    send(v, "跳过可选资料")
    prepared = send(v, "确认接入并构建")
    assert prepared["agent_goals"], prepared["messages"][-1]
    assert prepared["agent_goals"][0]["pause_reason"] == "waiting_confirmation"
    built = send(v, "确认")
    assert built["agent_goals"][0]["pause_reason"] == "structural_candidate_review", built
    v["image_url"] = f"/v1/projects/{v['project_id']}/system-image"
    image = candidate(v)
    v["publication_url"] = v["image_url"] + "/publications"
    v["target"] = {"project_id": v["project_id"], "image_revision_id": image["image_revision_id"],
        "image_artifact_hash": image["artifact_hash"], "target_baseline_id": image["baseline_id"],
        "expected_head_id": None, "policy_revision": "nasus.image-publication.v1"}
    waiting = send(v, "创建迭代 Sprint 1")
    assert intake(waiting)["stage"] == "selection" and history(v)["head"] is None
    assert not any(item["tool_id"] == "version.create" for item in waiting["tool_invocations"])
    handoff = send(v, "发布系统画像")
    assert handoff["messages"][-1]["metadata"]["delivery_next_action"]["action"] == "review_publication"
    assert history(v)["head"] is None
    head = independent_publication(v)
    selected = send(v, f"使用画像发布 {head['publication_id']}")
    assert intake(selected)["stage"] == "confirmation"
    assert intake(selected)["name"] == "Sprint 1"
    # The actual current project question stays a question, even during the pending proposal.
    question = send(v, "当前项目名称是什么")
    assert question["messages"][-1]["metadata"].get("planner_kind") != "guided_delivery"
    assert intake(question) == intake(selected)
    chat_id = created["id"]
    refreshed = v["client"].get(f"/v1/conversations/{chat_id}", headers=v["headers"])
    assert refreshed.status_code == 200 and intake(refreshed.json()) == intake(selected)
    replace_graph(monkeypatch, graph_kind)
    done = send(v, "确认创建迭代")
    state = intake(done)
    assert state["stage"] == "created"
    response = v["client"].get(f"/v1/projects/{v['project_id']}/versions/{state['version_id']}/delivery", headers=v["headers"])
    assert response.status_code == 200, response.text
    actual = response.json()
    assert actual["baseline"]["publication_id"] == head["publication_id"]
    assert actual["baseline"]["image_revision_id"] == image["image_revision_id"]
    assert actual["iteration_image"] == actual["baseline"]
    assert actual["code_revisions"][0]["commit_sha"] == commit
    assert actual["stage"] == "image_pinned" and actual["baseline"]["release_authorized"] is False
    assert done["messages"][-1]["metadata"]["version_delivery"] == actual
    code_evidence = realworld_code_evidence(v, image) if realworld else []
    again = send(v, "确认创建迭代")
    assert intake(again) == state
    assert sum(item["tool_id"] == "version.create" for item in again["tool_invocations"]) == 1
    assert sum(item["tool_id"] == "project.create" for item in again["tool_invocations"]) == 1
    status = send(v, "迭代进度")
    assert status["messages"][-1]["metadata"]["version_delivery"] == actual
    assert v["client"].get(f"/v1/conversations/{chat_id}", headers=v["member_headers"]).status_code == 403
    report_path = os.getenv("M1_ACCEPTANCE_REPORT")
    if realworld and report_path:
        report = Path(report_path)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({
            "schema": "nasus.realworld-m1-acceptance.v1", "stage": "M1",
            "recorded_at": datetime.now(timezone.utc).isoformat(), "graph_runtime": graph_kind,
            "source_commit": commit, "project_id": v["project_id"], "conversation_id": chat_id,
            "publication": head, "independent_reviewer_id": v["member"]["id"],
            "iteration": actual, "refresh_verified": True, "duplicate_confirmation_verified": True,
            "verified_code_evidence": code_evidence,
            "tool_invocations": [{"id": item["id"], "tool_id": item["tool_id"], "status": item["status"]}
                for item in status["tool_invocations"]],
            "business_loop_verified": False, "live_model_verified": False,
            "scope": "Source capture, structural candidate, independent publication and pinned iteration only; not M2-M5.",
        }, ensure_ascii=False, indent=2), encoding="utf-8")


def test_changed_publication_does_not_silently_rebind_a_chat_proposal(publication):
    v = publication
    first = independent_publication(v)
    proposal = send(v, f"创建迭代 Sprint 1，使用画像发布 {first['publication_id']}")
    assert intake(proposal)["stage"] == "confirmation"
    target = {**v["target"], "expected_head_id": first["publication_id"]}
    approval, _ = review(v, review_request(v, target=target))
    completed(invoke(v, "baseline.promote", publish_request(v, approval, target), key=uuid4().hex))
    second = history(v)["head"]
    before = v["client"].get(f"/v1/projects/{v['project_id']}/versions", headers=v["headers"]).json()
    stale = send(v, "确认创建迭代")
    assert "尚未确认迭代创建成功" in stale["messages"][-1]["blocks"][0]["text"]
    assert v["client"].get(f"/v1/projects/{v['project_id']}/versions", headers=v["headers"]).json() == before
    fresh = send(v, f"使用画像发布 {second['publication_id']}")
    assert intake(fresh)["proposal_id"] != intake(proposal)["proposal_id"]
    done = send(v, "确认创建迭代")
    assert intake(done)["stage"] == "created"
    assert done["messages"][-1]["metadata"]["version_delivery"]["baseline"]["publication_id"] == second["publication_id"]


def test_cancelled_proposal_cannot_create_from_a_later_confirmation(publication):
    v = publication
    head = independent_publication(v)
    send(v, f"创建迭代 Cancelled，使用画像发布 {head['publication_id']}")
    cancelled = send(v, "取消创建迭代")
    assert intake(cancelled)["stage"] == "selection"
    repeated = send(v, "确认创建迭代")
    assert "还没有可确认" in repeated["messages"][-1]["blocks"][0]["text"]
    assert not any(item["tool_id"] == "version.create" for item in repeated["tool_invocations"])
