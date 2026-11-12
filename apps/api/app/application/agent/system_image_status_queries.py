"""Recognize bounded status questions without granting build authority."""

import re

from ...domain.agent.runtime_models import OrchestratorDecision, ToolInvocationPlan, ToolPlanStep


_CHINESE_RESULT = r"(?:完成\s*构建|构建\s*(?:完成|成功|好了)|完成|做好)"
_CHINESE_STATUS = re.compile(
    r"(?:请帮我|帮我|请)?\s*(?:看看|看一下|查看|查询)?\s*"
    r"(?:(?:当前|这个|本)项目的?|当前的?)?\s*系统画像\s*"
    rf"(?:(?:是不是|是否|有没有)\s*(?:已经|已)?\s*{_CHINESE_RESULT}\s*了?"
    rf"|(?:已经|已)?\s*{_CHINESE_RESULT}\s*了?\s*吗"
    r"|(?:的)?(?:构建)?(?:进度|状态)(?:怎么样|如何|是什么)?(?:了)?"
    r"|(?:构建)?(?:到哪一步|得怎么样|怎么样|如何)了?)\s*[？?。]?"
)
_ENGLISH_SUBJECT = r"(?:the\s+)?(?:current\s+)?(?:project(?:'s)?\s+)?system\s+image"
_ENGLISH_STATUS = re.compile(
    rf"(?:has\s+{_ENGLISH_SUBJECT}\s+(?:already\s+)?been\s+(?:successfully\s+)?built"
    rf"|is\s+{_ENGLISH_SUBJECT}\s+build\s+(?:complete|finished)"
    rf"|did\s+{_ENGLISH_SUBJECT}\s+build\s+succeed"
    rf"|(?:what is|what's)\s+{_ENGLISH_SUBJECT}\s+(?:build\s+)?(?:status|progress)"
    rf"|is\s+{_ENGLISH_SUBJECT}\s+(?:ready|done))\s*[?.]?",
    re.I,
)


def is_build_status_question(message: str) -> bool:
    if len(message) > 2048 or "\n" in message or "\r" in message:
        return False
    value = message.strip()
    return bool(_CHINESE_STATUS.fullmatch(value) or _ENGLISH_STATUS.fullmatch(value))


def system_image_status_query(project_id: str, *, recommend_initialization: bool = False) -> OrchestratorDecision:
    return OrchestratorDecision(
        kind="tool_plan",
        tool_plan=ToolInvocationPlan(
            intent_kind="system_image_query",
            confidence=0.88,
            steps=[ToolPlanStep(
                tool_id="query.system_image.status",
                input_payload={"project_id": project_id},
                reason="Summarize source freshness, baseline readiness, relationships, and quality metrics.",
            )],
            recommended_next_tools=["system_image.baseline.initialize"] if recommend_initialization else [],
        ),
    )
