import asyncio
from datetime import datetime, timezone

from ...system_image.publications import (PublicationTarget, PublicationReviewInput, PublicationPublishInput, PublicationHeadInput,
    RollbackTarget, RollbackReviewInput, RollbackPublishInput)
from ....domain.system_image.publication import (PUBLICATION_REVIEW_TOOL, PUBLICATION_QUERY_TOOL, PUBLICATION_HEAD_TOOL,
    ROLLBACK_QUERY_TOOL, ROLLBACK_REVIEW_TOOL, ROLLBACK_TOOL, PublicationChanged)
from ..tool_models import ToolResult
from .query_input import query_payload


class ImagePublicationToolHandler:
    def __init__(self, application, events, access, legacy=None):
        self.application, self.events, self.access, self.legacy = application, events, access, legacy

    async def handle(self, invocation):
        await self.events.emit_tool_status(invocation.id, "running", "Verifying pinned image publication and approval scope", [])
        try:
            self.access.require_invocation_project_scope(invocation)
            payload = {k: v for k, v in query_payload(invocation.input_payload).items() if k not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == "baseline.promote" and "image_revision_id" not in payload:
                if await asyncio.to_thread(self.application.has_heads, payload.get("project_id", "")):
                    raise PublicationChanged("This project uses pinned image heads; unversioned promotion is disabled")
                await self.legacy.promote_baseline(invocation)
                return
            if invocation.tool_id == PUBLICATION_HEAD_TOOL:
                request = PublicationHeadInput.model_validate(payload)
                receipt = await asyncio.to_thread(self.application.head_receipt, request)
                result = ToolResult(invocation_id=invocation.id, status="completed", summary="Current source-authorized publication head resolved; pin it in a new preview.",
                    image_publication_head=receipt, next_recommended_tools=[PUBLICATION_QUERY_TOOL])
            elif invocation.tool_id in {PUBLICATION_QUERY_TOOL, ROLLBACK_QUERY_TOOL}:
                rollback = invocation.tool_id == ROLLBACK_QUERY_TOOL
                request = (RollbackTarget if rollback else PublicationTarget).model_validate(payload)
                receipt = await asyncio.to_thread(self.application.receipt, request)
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary="Exact-image publication preview verified. Review its fixed target and head; this does not authorize quality generation or release.",
                    image_publication=receipt,
                    next_recommended_tools=[ROLLBACK_REVIEW_TOOL if rollback else PUBLICATION_REVIEW_TOOL])
            else:
                review = invocation.tool_id in {PUBLICATION_REVIEW_TOOL, ROLLBACK_REVIEW_TOOL}
                rollback = invocation.tool_id in {ROLLBACK_REVIEW_TOOL, ROLLBACK_TOOL}
                model = (RollbackReviewInput if review else RollbackPublishInput) if rollback else (PublicationReviewInput if review else PublicationPublishInput)
                request = model.model_validate(payload)
                operation = self.application.review if review else self.application.publish
                value = await asyncio.to_thread(operation, request, invocation_id=invocation.id,
                    recorded_at=datetime.now(timezone.utc).isoformat())
                result = ToolResult(invocation_id=invocation.id, status="completed",
                    summary=("Pinned image rollback review recorded." if rollback else "Pinned image publication review recorded.") if review else
                        ("Historical knowledge image restored. Deployment, source heads and business approvals are unchanged." if rollback else
                         "Immutable image head published. Source authority, test coverage and release quality are unchanged."),
                    object_refs=[f"publication_review:{value['review_id']}", f"approval:{value['review_id']}"] if review else [f"image_publication:{value['publication_id']}", f"image_revision:{value['image_revision_id']}"],
                    next_recommended_tools=[ROLLBACK_TOOL if rollback else "baseline.promote"] if review and value["decision"] == "approve" else [ROLLBACK_QUERY_TOOL if rollback else PUBLICATION_QUERY_TOOL])
            self.access.require_invocation_project_scope(invocation)
        except Exception as exc:
            result = ToolResult(invocation_id=invocation.id, status="failed", requires_followup=True,
                followup_reason="publication_inputs_changed" if isinstance(exc, PublicationChanged) else "publication_verification_failed",
                summary="Publication could not be verified. Inspect the exact image, source access, current head and approval again.",
                next_recommended_tools=[PUBLICATION_QUERY_TOOL])
        await self.events.emit_tool_status(invocation.id, result.status, result.summary, [], result)
