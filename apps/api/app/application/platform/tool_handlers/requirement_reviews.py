import asyncio

from ...quality_loop.requirement_review_models import (
    EVALUATE_REQUIREMENT, CONFIRM_REQUIREMENT, EvaluateRequirement, ConfirmRequirement, ReviewSelection,
)
from ..tool_models import ToolResult
from .query_input import query_payload


class RequirementReviewToolHandler:
    def __init__(self, application, events, access):
        self.application, self.events, self.access = application, events, access

    async def handle(self, invocation):
        try:
            receipt = None
            self.access.require_invocation_project_scope(invocation)
            payload = {k: v for k, v in query_payload(invocation.input_payload,
                preserve=frozenset({"version_id"})).items() if k not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == EVALUATE_REQUIREMENT:
                value = await self.application.evaluate(EvaluateRequirement.model_validate(payload), invocation_id=invocation.id)
            elif invocation.tool_id == CONFIRM_REQUIREMENT:
                value = await asyncio.to_thread(self.application.confirm, ConfirmRequirement.model_validate(payload), invocation_id=invocation.id)
            else:
                value = await asyncio.to_thread(self.application.read, ReviewSelection.model_validate(payload))
                receipt = {key: value[key] for key in ("project_id", "version_id", "revision_id", "status", "current", "generation_authorized")}
                if value["evaluation"] and value["status"] not in {"review_failed", "review_pending", "image_changed"}:
                    receipt["assessment"] = value["evaluation"]["payload"]["assessment"]
            self.access.require_invocation_project_scope(invocation)
            summary = "Requirement review recorded. Inspect its questions and approval state; no test or release was performed."
            result = ToolResult(invocation_id=invocation.id, status="completed", summary=summary,
                object_refs=["requirement_revision:" + payload["revision_id"]], requires_followup=True, requirement_review=receipt)
        except (ValueError, KeyError, PermissionError, RuntimeError, OSError, asyncio.TimeoutError):
            # Model/provider exceptions can contain secrets; do not broadcast them.
            result = ToolResult(invocation_id=invocation.id, status="failed",
                summary="需求评审未完成：请检查模型连接、最新需求修订、来源权限或独立审核条件。原记录已保留，不会自动批准。",
                followup_reason="requirement_review_failed")
        await self.events.emit_tool_status(invocation.id, result.status, result.summary,
            [["version-requirements", invocation.input_payload.get("project_id"), invocation.input_payload.get("version_id")]], result)
