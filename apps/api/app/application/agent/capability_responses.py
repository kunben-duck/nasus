"""Explain known capability gaps without inventing commands or confirmations."""
import re

from ...domain.agent.runtime_models import ClarificationRequest, OrchestratorDecision


def unavailable_project_action(content, tool_ids):
    if "project.delete" in tool_ids:
        return None
    prefix = r"(?:请(?:帮我)?|帮我|麻烦你|确认)?\s*"
    scope = r"(?:(?:当前|我的|全部|所有|现有|已有|这个|本|的)\s*)*项目"
    zh = re.fullmatch(prefix + r"(?:(?:删除|移除|清空|删掉)\s*" + scope
        + r"|把\s*" + scope + r"(?:都|全部|全都)?(?:删除|删掉|清空|移除))[。！!]?", content.strip())
    en = re.fullmatch(r"(?:please\s+)?(?:delete|remove|clear)\s+"
        r"(?:(?:all|of|the|my|current|existing|these|this)\s+)*projects?[.!]?", content.strip(), re.I)
    if not (zh or en):
        return None
    return OrchestratorDecision(kind="clarification", clarification=ClarificationRequest(
        question=(
            "当前版本尚未实现项目删除（包括批量删除），没有可调用的删除工具。"
            "这不是缺少项目名称或上下文；本次未执行删除，现有项目和数据均保留。"
            "补齐项目删除功能后，才能先预览受影响的项目，再由你单独确认执行。"
            if zh else
            "This version does not support project deletion, including bulk deletion; no deletion tool is available. "
            "This is a missing capability, not missing project context. No projects or data were deleted. "
            "The feature must be implemented before an affected-project preview and a separate confirmation can be offered."
        ), reason="capability_unavailable:project.delete", missing_context=[],
    ))
