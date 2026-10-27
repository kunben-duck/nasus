from __future__ import annotations

import json
import re
from typing import Iterable

from .agent_models import ConversationSession
from .tool_catalog_encoding import planner_registry_fields
from ..platform.tool_models import ToolDefinition


_SPACE_TOOL_PREFIXES: dict[str, tuple[str, ...]] = {
    "build": ("project.", "system_image.", "query."),
    "dashboard": ("project.", "version.", "run.", "release.", "query.", "progress.", "risk."),
    "project": ("project.", "system_image.", "system-image.", "query.system_image.", "version.", "quality.", "release."),
    "version": ("version.", "us.", "quality.", "automation.", "run.", "release."),
    "workspace": ("us.", "quality.", "automation.", "run.", "failure.", "healing.", "release."),
    "knowledge": ("system_image.", "system-image.", "query.knowledge", "query.system_image"),
    "runs": ("run.", "failure.", "healing.", "query."),
    "governance": ("approval.", "release.", "resolution.", "conflicts.", "query.governance"),
    "documentation": ("query.",),
}

_INTENT_TOOL_PREFIXES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("project", "workspace", "项目"), ("project.",)),
    (("system image", "system_image", "code", "knowledge", "evidence", "画像", "代码", "知识", "证据"), ("system_image.", "system-image.", "query.system_image.")),
    (("version", "branch", "版本", "分支"), ("version.",)),
    (("test", "scenario", "case", "quality", "测试", "场景", "用例", "质量"), ("us.", "quality.", "automation.")),
    (("run", "execute", "execution", "运行", "执行"), ("run.",)),
    (("failure", "heal", "fix", "失败", "修复", "自愈"), ("failure.", "healing.")),
    (("release", "approval", "launch", "发布", "放行", "审批", "上线"), ("release.", "approval.", "resolution.")),
    (("status", "progress", "risk", "状态", "进展", "风险"), ("query.", "progress.", "risk.")),
)


def compact_tool_catalog_json(
    tools: Iterable[ToolDefinition],
    conversation: ConversationSession,
    *,
    relevant_limit: int = 12,
    max_bytes: int = 6_999,
) -> str:
    """Serialize a bounded planner view without weakening the canonical registry."""

    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("invalid tool catalog byte budget")
    catalog = tuple(tools)
    intent_text = _intent_text(conversation)
    intent_tokens = _tokens(intent_text)
    context_retrieval = (
        ("ac" in intent_tokens or any(phrase in intent_text for phrase in
            ("context", "上下文", "验收条件")))
        and any(phrase in intent_text for phrase in ("retriev", "queries", "query", "检索", "查询"))
    )
    space_prefixes = set(_SPACE_TOOL_PREFIXES.get(conversation.space_type, ()))
    intent_prefixes: set[str] = set()
    for phrases, prefixes in _INTENT_TOOL_PREFIXES:
        if any(phrase in intent_text for phrase in phrases):
            intent_prefixes.update(prefixes)

    available_context = {"space_type", "space_id"}
    if conversation.project_id:
        available_context.add("project_id")
    if conversation.version_id:
        available_context.add("version_id")
    if conversation.us_id:
        available_context.add("us_id")
    if conversation.task_id:
        available_context.add("task_id")

    scored: list[tuple[int, int, ToolDefinition]] = []
    for index, tool in enumerate(catalog):
        searchable = " ".join(
            (tool.tool_id.replace(".", " "), tool.label, tool.description)
        ).lower()
        score = 0
        if any(tool.tool_id.startswith(prefix) for prefix in space_prefixes):
            score += 30
        if any(tool.tool_id.startswith(prefix) for prefix in intent_prefixes):
            score += 55
        if tool.tool_id in {"quality.run_plan.execute_http", "quality.run_plan.cancel_http",
                "query.quality.run_plan_case_execution"}:
            case_execution = any(phrase in intent_text for phrase in (
                "runplan http", "runplan execution", "execute runplan", "execute the runplan",
                "business case execution", "business case history", "业务用例执行", "执行业务用例",
                "执行计划运行", "执行计划取消", "业务执行历史", "quality.run_plan.execute_http",
                "quality.run_plan.cancel_http", "query.quality.run_plan_case_execution"))
            score += 260 if case_execution else -120
            if case_execution and tool.tool_id == "quality.run_plan.cancel_http" and any(
                    phrase in intent_text for phrase in ("cancel", "stop", "取消", "停止")):
                score += 100
        # Frozen-input investigation must retain its read tools as the catalog
        # grows; unrelated write-tool descriptions otherwise crowd them out.
        if any(word in intent_text for word in ("evidence", "source text", "证据", "原文")):
            if tool.tool_id in {"query.system_image.evidence.list", "query.system_image.evidence.read"}:
                score += 110
        if any(word in intent_text for word in ("frozen", "revision", "snapshot", "固定", "修订", "候选")):
            if tool.tool_id.startswith("query.system_image.revisions."):
                score += 40
        if tool.tool_id.startswith(("query.system_image.code_indexes.", "system_image.code_indexes.")):
            lifecycle = any(word in intent_text for word in ("code index", "code_indexes", "代码索引", "索引状态", "索引取消"))
            score += 220 if lifecycle else -100
            if lifecycle and tool.tool_id.endswith(".cancel") and any(word in intent_text for word in ("cancel", "stop", "取消", "停止")):
                score += 100
        if tool.tool_id == "query.system_image.sources.delta":
            delta_intent = any(word in intent_text for word in (
                "source delta", "source revisions", "snapshot diff", "compare revisions", "代码变更", "来源差异", "比较修订", tool.tool_id))
            score += 180 if delta_intent else -100
        if tool.tool_id == "system_image.build.gaps.assign":
            ownership_intent = any(word in intent_text for word in (
                "gap owner", "gap responsibilities", "assign gaps", "缺口负责人", "缺口责任", "分配缺口", tool.tool_id))
            score += 220 if ownership_intent else -100
        if tool.tool_id in {"query.system_image.context.change_impact", "system_image.context.invalidate"}:
            impact_intent = any(word in intent_text for word in (
                "context change impact", "context dependencies", "stale context", "上下文影响", "派生依赖", "上下文失效", tool.tool_id))
            score += 180 if impact_intent else -100
        if tool.tool_id == "query.system_image.sources.context_roots":
            root_intent = any(word in intent_text for word in (
                "source context roots", "source context dependencies", "affected contexts", "all context roots",
                "来源关联上下文", "受影响上下文", "全部上下文", tool.tool_id))
            score += 180 if root_intent else -100
        if any(word in intent_text for word in ("acceptance", "implements", "asserts", "验收条件", "语义关联")):
            if tool.tool_id == "query.system_image.links.screened_candidates":
                score += 110
            if tool.tool_id == "query.system_image.links.candidates":
                score += 100
        if any(word in intent_text for word in ("oracle", "authority", "批准需求", "验收依据", "撤回需求")):
            if tool.tool_id in {"query.quality.acceptance_specification", "quality.acceptance_specification.review"}:
                score += 150
        if any(word in intent_text for word in ("business rule", "业务规则", "规则批准", "撤回规则")):
            if tool.tool_id in {"query.quality.business_rule", "quality.business_rule.review"}:
                score += 150
        if tool.tool_id in {"query.quality.test_design_scope", "quality.test_design_scope.review"}:
            scope_intent = any(word in intent_text for word in
                ("test-design scope", "test design scope", "risk contract", "测试设计范围", "风险范围", "权限矩阵", tool.tool_id))
            # A long review schema mentions generation/execution only to deny
            # permission. Those words must not displace actual workflow actions.
            score += 180 if scope_intent else -100
        if tool.tool_id == "query.quality.test_design_generation":
            generation_preflight = any(word in intent_text for word in
                ("generation input", "generation preflight", "测试生成输入", "生成预检查", tool.tool_id))
            score += 180 if generation_preflight else -100
        if tool.tool_id == "query.quality.automation_history":
            script_history = any(word in intent_text for word in (
                "script history", "script command history", "脚本历史", "脚本生成历史", tool.tool_id))
            score += 220 if script_history else -100
        if tool.tool_id in {"query.quality.native_build_preview", "quality.native_build.prepare",
                "query.quality.native_build", "quality.native_build.cancel"}:
            native_build = any(word in intent_text for word in (
                "native build", "native_build", "build pinned source", "offline build",
                "原生构建", "离线构建", "构建固定源码", "编译源码", tool.tool_id))
            score += 260 if native_build else -120
            if native_build and tool.tool_id == "quality.native_build.cancel" and any(
                word in intent_text for word in ("cancel", "stop", "取消", "停止")
            ):
                score += 100
        if tool.tool_id.startswith(("quality.http_fixture.", "query.quality.http_fixture")):
            fixture_intent = any(word in intent_text for word in (
                "http fixture", "http_fixture", "fixture operation", "fixture consent", "fixture definition",
                "test data", "测试数据", "数据准备", "数据清理", tool.tool_id))
            score += 260 if fixture_intent else -120
            if fixture_intent and tool.tool_id == "quality.http_fixture.cancel" and any(
                word in intent_text for word in ("cancel", "stop", "取消", "停止")
            ):
                score += 100
        if tool.tool_id in {"query.quality.run_plan_locators", "quality.run_plan.record_locators",
                "query.quality.run_plan_locator_record"}:
            locator_intent = any(word in intent_text for word in (
                "locator", "source route", "api location", "请求定位", "源码定位", "接口定位", tool.tool_id))
            score += 260 if locator_intent else -120
        if tool.tool_id in {"query.quality.run_plan_preview", "quality.run_plan.prepare", "query.quality.run_plan_build_preview",
                "quality.run_plan.bind_native_build", "query.quality.run_plan_build", "query.quality.run_plan_environment",
                "quality.run_plan.record_environment", "query.quality.run_plan_environment_record",
                "quality.run_plan.record_health", "query.quality.run_plan_health_record",
                "quality.run_plan.record_observations", "query.quality.run_plan_observations"}:
            run_plan = any(word in intent_text for word in (
                "runplan", "run plan", "run_plan", "execution plan", "执行计划", "environment evidence",
                "target environment", "环境观察", "环境登记", tool.tool_id))
            score += 240 if run_plan else -120
        if tool.tool_id in {"query.quality.automation_execution", "quality.automation.generate"}:
            automation_draft = any(word in intent_text for word in (
                "reviewed case", "script draft", "automation budget", "原用例脚本", "脚本草稿", "自动化预算", tool.tool_id))
            score += 220 if automation_draft else -100
        if tool.tool_id in {"query.quality.automation_review", "quality.automation.review"}:
            script_review = any(word in intent_text for word in (
                "script review", "review scripts", "脚本审阅", "审阅脚本", tool.tool_id))
            score += 220 if script_review else -100
        if tool.tool_id in {"query.quality.test_design_execution", "query.quality.test_design_batches", "quality.test_design.generate",
                "query.quality.test_design_job", "quality.test_design.recover", "quality.test_design.cancel"}:
            native_generation = any(word in intent_text for word in
                ("native test design", "fixed test design", "generation budget", "原生测试生成", "固定画像生成", "生成预算", tool.tool_id))
            score += 200 if native_generation else -100
        if tool.tool_id == "query.quality.test_design_jobs":
            history_intent = any(word in intent_text for word in
                ("generation history", "test design jobs", "生成历史", "测试生成任务", tool.tool_id))
            score += 220 if history_intent else -100
        if tool.tool_id == "query.quality.test_design_review_drafts":
            draft_review_intent = any(word in intent_text for word in
                ("draft review", "review drafts", "archived drafts", "draft cases", "草稿审阅", "审阅草稿", "已归档草稿", "草稿用例", tool.tool_id))
            score += 240 if draft_review_intent else -100
        if tool.tool_id in {"query.quality.test_design_mapping", "quality.test_design_mapping.review",
                "quality.test_design_mapping.stage_part", "quality.test_design_mapping.finalize"}:
            mapping_intent = any(word in intent_text for word in
                ("assertion mapping", "mapping review", "映射审阅", "断言映射", "用例映射", tool.tool_id))
            score += 220 if mapping_intent else -100
        if any(word in intent_text for word in ("contextpack", "context pack", "test-design context", "上下文包")):
            if tool.tool_id.startswith("query.system_image.context.") or tool.tool_id == "system_image.context.compile":
                score += 150
        if tool.tool_id in {"system_image.context.register_authorities", "query.system_image.context.authority_backfill"}:
            registration = any(word in intent_text for word in (
                "historical context dependencies", "register authorities", "historical dependency queue",
                "历史上下文依赖", "补登记批准依赖", "待补登记上下文", tool.tool_id))
            score += 220 if registration else -150
        if context_retrieval and tool.tool_id in {
            "query.system_image.context.retrieval_preview", "system_image.context.retrieve",
            "query.system_image.context.retrieval", "system_image.context.cancel_retrieval",
        }:
            score += 220
            if tool.tool_id == "system_image.context.cancel_retrieval" and any(
                word in intent_text for word in ("cancel", "stop", "取消", "停止")
            ):
                score += 100
        if any(word in intent_text for word in ("image publication", "publish image", "publish the image", "publish knowledge", "发布画像", "画像发布", "发布系统画像")):
            if tool.tool_id.startswith("query.system_image.publication") or tool.tool_id in {"system_image.revisions.review_publication", "baseline.promote", "system_image.revisions.review_rollback", "baseline.rollback"}:
                score += 160
        if any(word in intent_text for word in ("semantic", "implements", "asserts", "语义")):
            if any(word in intent_text for word in ("review", "decision", "history", "审阅", "裁决", "历史")):
                if tool.tool_id == "query.system_image.links.semantic_decisions":
                    score += 100
        if any(word in intent_text for word in ("applicability", "reingest", "cross-revision", "跨修订", "重新摄入", "适用性")):
            if tool.tool_id == "query.system_image.links.decision_applicability":
                score += 110
        if any(word in intent_text for word in ("reference", "references", "traceability", "引用", "关联")):
            if tool.tool_id in {"system_image.links.propose_references", "query.system_image.references.read"}:
                score += 40
            if any(word in intent_text for word in ("review", "reject", "accept", "defer", "审阅", "拒绝", "接受", "暂缓")):
                if tool.tool_id in {"system_image.links.review", "query.system_image.links.decisions"}:
                    score += 50
            if any(word in intent_text for word in ("freeze", "snapshot", "冻结", "固定")):
                if tool.tool_id in {"system_image.revisions.freeze_links", "query.system_image.revisions.read"}:
                    score += 60
        score += 8 * len(intent_tokens.intersection(_tokens(searchable)))
        score += 3 * len(available_context.intersection(tool.required_context))
        if tool.tool_id in intent_text:
            score += 80
        scored.append((score, -index, tool))

    payload = {
        "available_count": len(catalog),
        **planner_registry_fields([tool.tool_id for tool in catalog]),
        "relevant_tools": [],
    }
    ranked = [
        {
            "tool_id": tool.tool_id,
            "label": tool.label,
            "description": tool.description[:240],
            "risk_level": tool.risk_level,
            "confirmation_mode": tool.confirmation_mode,
            "required_context": tool.required_context,
        }
        for _, _, tool in sorted(scored, reverse=True)
    ]
    payload["relevant_tools"] = _budgeted_details(payload, ranked, min(len(ranked), max(1, relevant_limit)), max_bytes)
    return _serialize_with_byte_budget(payload, max_bytes)


def _budgeted_details(payload: dict, ranked: list[dict], count: int, max_bytes: int) -> list[dict]:
    base_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    costs = [len(json.dumps({**tool, "label": tool["label"][:1], "description": tool["description"][:1]},
                           ensure_ascii=False, separators=(",", ":")).encode("utf-8")) for tool in ranked]
    used = base_bytes + max(0, count - 1)
    selected = []
    for index, tool in enumerate(ranked):
        remaining = count - len(selected) - 1
        if remaining < 0:
            break
        suffix = costs[index + 1:]
        # Keep complete lower-ranked contracts only when an oversized detail
        # cannot fit; the lossless registry still advertises every tool ID.
        if len(suffix) >= remaining and used + costs[index] + sum(sorted(suffix)[:remaining]) <= max_bytes:
            selected.append(tool)
            used += costs[index]
    if len(selected) != count or used > max_bytes:
        raise ValueError("tool catalog metadata exceeds the planner byte budget")
    return selected


def _serialize_with_byte_budget(payload: dict, max_bytes: int) -> str:
    descriptions = [tool["description"] for tool in payload["relevant_tools"]]

    def serialize(cap: int, *, compact_labels=False) -> str:
        details = [{**tool, "description": description[:cap],
                    "label": tool["label"][:cap] if compact_labels else tool["label"]}
                   for tool, description in zip(payload["relevant_tools"], descriptions)]
        return json.dumps({**payload, "relevant_tools": details}, ensure_ascii=False, separators=(",", ":"))

    full = serialize(240)
    if len(full.encode("utf-8")) <= max_bytes:
        return full
    result = serialize(1)
    compact_labels = len(result.encode("utf-8")) > max_bytes
    if compact_labels:
        result = serialize(1, compact_labels=True)
    if len(result.encode("utf-8")) > max_bytes:
        raise ValueError("tool catalog metadata exceeds the planner byte budget")
    # Labels are explanatory, not identifiers. Keep them intact unless the
    # entire registry no longer fits with one-character descriptions.
    # Never remove IDs, required inputs,
    # risk or confirmation fields to make a larger registry appear to fit.
    lower, upper = 1, 239
    while lower <= upper:
        cap = (lower + upper) // 2
        candidate = serialize(cap, compact_labels=compact_labels)
        if len(candidate.encode("utf-8")) <= max_bytes:
            result, lower = candidate, cap + 1
        else:
            upper = cap - 1
    return result


def _intent_text(conversation: ConversationSession) -> str:
    recent_user_text = " ".join(
        block.text
        for message in conversation.messages[-8:]
        if message.role == "user"
        for block in message.blocks
        if block.type == "text" and block.text
    )
    return " ".join(
        (
            conversation.space_type,
            conversation.title,
            recent_user_text[-3000:],
        )
    ).lower()


def _tokens(value: str) -> set[str]:
    # Verbose safety descriptions must not outrank task actions just by sharing
    # articles and conjunctions with the user's request.
    stop_words = {"an", "the", "of", "to", "in", "on", "for", "and", "or", "with", "from",
                  "is", "are", "be", "by", "as", "this", "that", "should", "must", "shall", "it", "them", "then"}
    return {
        token
        for token in re.findall(r"[a-z0-9_]+", value.lower())
        if len(token) > 1 and token not in stop_words
    }


__all__ = ["compact_tool_catalog_json"]
