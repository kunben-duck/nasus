from __future__ import annotations

import json
import re
from typing import Iterable

from .agent_models import ConversationSession
from ..platform.tool_models import ToolDefinition


_SPACE_TOOL_PREFIXES: dict[str, tuple[str, ...]] = {
    "build": ("project.", "system_image.", "query."),
    "dashboard": ("project.", "version.", "run.", "release.", "query.", "progress.", "risk."),
    "project": ("project.", "system_image.", "system-image.", "version.", "quality.", "release."),
    "version": ("version.", "us.", "quality.", "automation.", "run.", "release."),
    "workspace": ("us.", "quality.", "automation.", "run.", "failure.", "healing.", "release."),
    "knowledge": ("system_image.", "system-image.", "query.knowledge", "query.system_image"),
    "runs": ("run.", "failure.", "healing.", "query."),
    "governance": ("approval.", "release.", "resolution.", "conflicts.", "query.governance"),
    "documentation": ("query.",),
}

_INTENT_TOOL_PREFIXES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("project", "workspace", "项目"), ("project.",)),
    (("system image", "system_image", "code", "knowledge", "画像", "代码", "知识"), ("system_image.", "system-image.")),
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
) -> str:
    """Serialize a bounded planner view without weakening the canonical registry."""

    catalog = tuple(tools)
    intent_text = _intent_text(conversation)
    intent_tokens = _tokens(intent_text)
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
        score += 8 * len(intent_tokens.intersection(_tokens(searchable)))
        score += 3 * len(available_context.intersection(tool.required_context))
        if tool.tool_id in intent_text:
            score += 80
        scored.append((score, -index, tool))

    relevant = [
        tool
        for _, _, tool in sorted(scored, reverse=True)[: max(1, relevant_limit)]
    ]
    payload = {
        "available_count": len(catalog),
        "available_tool_ids": [tool.tool_id for tool in catalog],
        "relevant_tools": [
            {
                "tool_id": tool.tool_id,
                "label": tool.label,
                "description": tool.description[:240],
                "risk_level": tool.risk_level,
                "confirmation_mode": tool.confirmation_mode,
                "required_context": tool.required_context,
            }
            for tool in relevant
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


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
    return {
        token
        for token in re.findall(r"[a-z0-9_]+", value.lower())
        if len(token) > 1
    }


__all__ = ["compact_tool_catalog_json"]
