"""Opt-in real source + live model + canonical M2 commands; never a full-loop claim."""
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone

import pytest
import yaml

from apps.api.app.main import app
from apps.api.app.application.platform.model_settings import StudioSettings
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_delivery_dialogue_api import test_chat_project_to_reviewed_image_and_explicit_iteration as build_m1, intake
from apps.api.tests.test_natural_build_entries_api import send
from apps.api.tests.test_requirement_reviews_api import command, review_url

SPEC = "25588846c314b15a5e427ffe816e6b4af7be68c7"


def contract_document():
    root = os.environ["M2_REALWORLD_SPEC"]
    read = lambda path: subprocess.check_output(["git", "-C", root, "show", SPEC + ":" + path]).decode()
    api = yaml.safe_load(read("specs/api/openapi.yml"))
    paths = {key: {"put": value["put"]} for key, value in api["paths"].items() if key.endswith("articles/{slug}")}
    assert paths and any("put" in value for value in paths.values())
    # Archive exact excerpts and their upstream commit; these are independent of
    # the application under test and are not upgraded to human-approved oracles.
    return ("# US-RW-001 RealWorld article update API contract\nDescription: Pinned official specification, not a confirmed iteration requirement.\n"
        + "Source: https://github.com/realworld-apps/realworld at " + SPEC + "\n"
        + "## Article endpoint specification\n```json\n" + json.dumps(paths, ensure_ascii=False) + "\n```\n"
        + "## Historical authorization examples\n```\n" + read("specs/api/hurl/errors_authorization.hurl") + "\n```\n").encode()


@pytest.mark.skipif(not os.getenv("M2_LIVE_SETTINGS"), reason="Run verify:realworld-m2 to opt into real provider calls")
def test_realworld_live_review_clarification_independent_confirmation(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    build_m1(v, tmp_path, monkeypatch, "langgraph_postgres", requirement_document=contract_document())
    conversation_id = v["conversation"].json()["id"]
    current = v["client"].get(f"/v1/conversations/{conversation_id}", headers=v["headers"]).json()
    v["version"] = intake(current)["version_id"]
    delivery_url = f"/v1/projects/{v['project_id']}/versions/{v['version']}/delivery"
    initial = v["client"].get(delivery_url, headers=v["headers"]).json()
    model = app.state.container.requirement_reviews.model
    settings = StudioSettings.model_validate_json(os.environ["M2_LIVE_SETTINGS"])
    assert settings.runtime_mode == "live"
    monkeypatch.setattr(model, "settings", lambda: settings)
    monkeypatch.setattr(model, "secret", lambda route: os.environ["M2_LIVE_KEY"])
    report = Path(os.environ["M2_ACCEPTANCE_REPORT"])
    original = model.llm.generate_reply
    replies = []
    provider = model.llm._call_provider
    async def capture_provider(**kwargs):
        try:
            return await provider(**kwargs)
        except Exception as exc:
            report.with_name("provider-failure.json").write_text(json.dumps({"error_type": type(exc).__name__,
                "status_code": getattr(getattr(exc, "response", None), "status_code", None)}))
            raise
    monkeypatch.setattr(model.llm, "_call_provider", capture_provider)
    async def capture_reply(**kwargs):
        result = await original(**kwargs)
        if kwargs.get("call_context") and kwargs["call_context"].purpose == "quality.requirement.evaluate":
            replies.append({"mode": result.mode, "reason": result.reason, "content": result.content,
                "llm_call_id": result.llm_call_id, "input_tokens": result.input_tokens, "output_tokens": result.output_tokens})
            report.with_name("provider-replies.json").write_text(json.dumps(replies, ensure_ascii=False, indent=2))
        return result
    monkeypatch.setattr(model.llm, "generate_reply", capture_reply)
    # The model adapter and gateway are real. Only the isolated test's configuration
    # provider is pinned to the explicitly selected development model snapshot.
    created = send(v, "需求：US-001 Article editing and permissions：支持修改文章", timeout_seconds=240)
    first = created["messages"][-1]["metadata"]["requirement_intake"]
    reviewed = send(v, "确认评审需求", timeout_seconds=240)
    review = v["client"].get(review_url(v, first), headers=v["headers"]).json()
    report.write_text(json.dumps({"status": "first_review", "review": review}, ensure_ascii=False, indent=2))
    assert review["status"] == "clarification_required", review
    assert review["evaluation"]["payload"]["model"]["llm_call_id"]
    first_review = review
    refs = first_review["events"][0]["payload"]["input"]["evidence"]
    assert any(item["kind"] == "source_document" and '"put"' in item["text"] for item in refs), "Fixed update specification was not retrieved"
    assert any("update (apps/articles/api.py)" in item.get("title", "") for item in refs), "Update handler evidence was not retrieved"
    # Predeclared acceptance operator response, not an answer inferred from target code.
    answer = ("本轮仅 HTTP API 文章编辑与权限。只允许作者修改自己的文章；有效字段 title、description、body 均可单独或组合修改，"
        "未提供字段保留原值；成功 200 并回读验证。标题改为新唯一值时 slug 按小写连字符更新并可回读；未改标题时 slug 不变。"
        "未登录拒绝 401，其他用户拒绝 403，两者均须回读确认原文及作者不变。已登录作者访问不存在的 slug 返回 404。"
        "注册、登录、建文章仅作准备，不纳入新需求。tagList、重复标题、空值校验和并发编辑不在本轮范围，另立需求，不阻塞本需求的这六条路径。"
        "按固定 OpenAPI，方法为 PUT /api/articles/{slug}，JSON 请求体为 {article:{title?,description?,body?}}，字段名称就是 title/description/body。"
        "200 响应为 {article:{slug,title,description,body,tagList,createdAt,updatedAt,favorited,favoritesCount,author:{username,bio,image,following}}}，"
        "新 slug 通过响应读取并 GET /api/articles/{new_slug} 验证；旧 slug 返回 404。未提供字段及作者保持不变；本轮不额外断言时间精度。"
        "管理员若非作者也属于其他用户。无效凭据视为未认证，401；测试准备使用有效且未过期的凭据。"
        "本轮拒绝响应只断言状态及数据不变，不限定 errors 的具体文字。显式 null 和空串不在本轮，不为它们生成断言。"
        "这些是我明确确认的需求意图；如发现与固定规格有冲突必须指出，不能以实现行为改变预期。")
    send(v, "回答：" + answer, timeout_seconds=240)
    refreshed = v["client"].get(f"/v1/conversations/{conversation_id}", headers=v["headers"])
    assert refreshed.status_code == 200
    reviewed = send(v, "确认评审需求", timeout_seconds=240)
    latest = reviewed["messages"][-1]["metadata"]["requirement_intake"]
    response = v["client"].get(review_url(v, latest), headers=v["headers"])
    assert response.status_code == 200
    review = response.json()
    clarification_rounds = [review]
    if review["status"] == "clarification_required":
        # A second explicit operator response narrows fixture inputs, never changes
        # denial expectations to match the implementation or overrides a blocker.
        followup = ("补充验收边界：本迭代正式采用固定 OpenAPI 中的 PUT 文章更新契约及上一轮我给出的权限规则。"
            "标题更新的输入固定为新的唯一 ASCII 标题 New Test Title，预期 slug 精确为 new-test-title；旧 slug 为 404，新 slug 回读一致。"
            "其他正常样本也只使用非空、有效且唯一的 ASCII 输入。重复标题、标点和非 ASCII slug、未知字段、null、空串、并发编辑不属于本 US 的六条路径，另立需求。"
            "不存在文章路径以有效作者凭据访问一个确实不存在的 slug，预期 404；非作者访问不存在文章不在此用例中。"
            "这些边界不排除任何本轮权限断言：未登录必须 401，已登录非作者（含管理员）必须 403，拒绝后内容和作者均不变。"
            "若上述内容仍与固定更新契约矛盾，继续列出具体矛盾，不要自行批准。")
        send(v, "回答：" + followup, timeout_seconds=240)
        reviewed = send(v, "确认评审需求", timeout_seconds=240)
        latest = reviewed["messages"][-1]["metadata"]["requirement_intake"]
        response = v["client"].get(review_url(v, latest), headers=v["headers"])
        assert response.status_code == 200
        review = response.json()
        clarification_rounds.append(review)
    evidence = {"schema": "nasus.realworld-m2-acceptance.v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": "87dd078c883a046f5ff20269df2fb004d8b5f83f", "spec_commit": SPEC,
        "project_id": v["project_id"], "version_id": v["version"], "conversation_id": conversation_id,
        "first_review": first_review, "latest_review": review, "clarification_rounds": clarification_rounds, "operator_id": v["owner"]["id"],
        "independent_reviewer_id": v["member"]["id"], "live_model_verified": True, "full_loop_verified": False,
        "status": "awaiting_independent_confirmation", "scope": "M2 only; no generated or executed tests, defects or release gate."}
    report = Path(os.environ["M2_ACCEPTANCE_REPORT"])
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    assert review["status"] == "awaiting_confirmation", review
    assert len(review["approval_requests"]) >= 6
    for criterion in review["approval_requests"]:
        approved = command(v, "quality.acceptance_specification.review", {**criterion["input"],
            "reason": "Independent acceptance operator reviewed against fixed specification and predeclared US-001 response"}, headers=v["member_headers"])
        assert approved["status"] == "completed", approved
    result = command(v, "quality.requirement.confirm", {key: latest[key] for key in ("project_id", "version_id", "revision_id")} | {
        "evaluation_id": review["evaluation"]["event_id"], "review_digest": review["evaluation"]["content_hash"],
        "reason": "Independent M2 acceptance confirmation; not approval to generate, execute or release"}, headers=v["member_headers"])
    assert result["status"] == "completed", result
    delivery = v["client"].get(delivery_url, headers=v["headers"]).json()
    assert delivery["stage"] == "requirements_confirmed"
    assert delivery["baseline"] == initial["baseline"]
    assert delivery["iteration_image"]["image_revision_id"] != initial["iteration_image"]["image_revision_id"]
    assert delivery["code_revisions"] == initial["code_revisions"]
    final = v["client"].get(review_url(v, latest), headers=v["headers"]).json()
    assert final["status"] == "confirmed"
    evidence.update(status="passed", final_review=final, iteration=delivery, confirmation_invocation_id=result["id"])
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
