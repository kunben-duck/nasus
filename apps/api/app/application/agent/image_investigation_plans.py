"""Consume verified investigation proposals through application ports, not ORM."""
from __future__ import annotations

from typing import Protocol

from ...domain.agent.runtime_models import ToolPlanStep
from ...domain.agent.plan_policy import AgentPlanPolicyViolation
from ...domain.agent.image_plan_phases import active_phase_start, phase_target_refs
from ..system_image.image_query_models import ImagePageInput, ImageDocumentInput, ImageReferenceInput
from ..system_image.investigations import INVESTIGATE_TOOL
from ..system_image.investigations import InvestigationInput
from ..system_image.reference_links import PROPOSE_REFERENCES_TOOL, ReferenceProposalInput, ReferenceProposalPage
from ..system_image.structure_builds import StructureBuildInput
from ..platform.tool_handlers.query_input import query_payload
from ...domain.system_image.investigation import REFERENCE_INVESTIGATION_POLICY
from ...domain.system_image.reference_links import REFERENCE_METHOD
from ...domain.system_image.image_revision import ImageRevisionPageTooLarge


class AgentInvestigationPlanPort(Protocol):
    def followup(self, goal) -> list[ToolPlanStep]: ...
    def after_structure(self, goal) -> list[ToolPlanStep]: ...
    def after_reference(self, goal) -> list[ToolPlanStep]: ...


class AgentReferenceReadPort(Protocol):
    def read(self, project_id: str, proposal_id: str, *, section: str,
             offset: int, limit: int) -> ReferenceProposalPage: ...


class AgentInvestigationPlanApplicationService:
    def __init__(self, invocations, investigations, structures, *, references: AgentReferenceReadPort | None = None):
        self.invocations, self.investigations = invocations, investigations
        self.structures = structures
        self.references = references

    def after_structure(self, goal):
        if (goal.goal_template not in {"system_image_build", "system_image_investigation"}
                or goal.status != "paused" or goal.pause_reason != "structural_candidate_review"):
            return []
        blocked = [step for step in goal.steps[active_phase_start(goal):] if step.phase == "acting" and step.status == "blocked"]
        if len(blocked) != 1 or blocked[0].selected_tool_id != "system_image.build.structure":
            raise AgentPlanPolicyViolation("structure_review_checkpoint_changed", "Continue requires the original blocked structural step.")
        step = blocked[0]
        invocation = self.invocations.get_tool_invocation(step.tool_invocation_id)
        if (invocation.status != "completed" or invocation.tool_id != step.selected_tool_id
                or invocation.conversation_id != goal.conversation_id
                or invocation.input_payload.get("agent_goal_id") != goal.id
                or invocation.result is None or invocation.result.status != "completed"
                or invocation.result.followup_reason != "structural_candidate_review"):
            raise AgentPlanPolicyViolation("structure_review_receipt_changed", "Continue requires the original completed structural command.")
        payload = query_payload(invocation.input_payload)
        request = StructureBuildInput.model_validate({key: value for key, value in payload.items()
            if key not in {"confirmed_at", "confirmed_by_user"}})
        if (request.project_id != goal.project_id or f"build_plan:{request.plan_id}" not in phase_target_refs(goal)
                or any(step.tool_input_payload.get(key) != value for key, value in request.model_dump().items())):
            raise AgentPlanPolicyViolation("structure_review_scope_changed", "Continue cannot replace the original project, plan or target.")
        candidate = self.structures.read_completed(request, invocation_id=invocation.id)
        if set(invocation.result.object_refs) != {f"build_plan:{request.plan_id}", f"image_revision:{candidate.image_revision_id}"}:
            raise AgentPlanPolicyViolation("structure_review_receipt_changed", "Structural result does not match its committed artifact.")
        body = InvestigationInput(project_id=request.project_id, plan_id=request.plan_id,
            plan_digest=request.plan_digest, goal_id=goal.id,
            image_revision_id=candidate.image_revision_id, image_artifact_hash=candidate.artifact_hash)
        self.investigations.require_access(body)
        header, _ = self.investigations.images.frozen_snapshot(request.project_id, candidate.image_revision_id)
        if (header.artifact_hash != candidate.artifact_hash or header.baseline_id != request.target_baseline_id
                or header.manifest_id != candidate.manifest_id or header.manifest_hash != candidate.manifest_hash):
            raise AgentPlanPolicyViolation("structure_review_artifact_changed", "Structural archive failed its fixed-input verification.")
        return [ToolPlanStep(INVESTIGATE_TOOL, body.model_dump(exclude_none=True),
            reason="Inspect evidence and propose gap-driven work for this committed candidate; separate confirmation is required.")]

    def followup(self, goal):
        completed = [step for step in goal.steps[active_phase_start(goal):] if step.phase == "acting" and step.status == "completed"]
        if not completed or completed[-1].selected_tool_id != INVESTIGATE_TOOL:
            return []
        revision = self._investigation(goal, completed[-1])
        if revision.review.state != "investigation_ready":
            return []
        steps = []
        for item in revision.review.work_items:
            model = {"query.system_image.revisions.read": ImagePageInput,
                     "query.system_image.revisions.document": ImageDocumentInput}.get(item.tool_id)
            if item.tool_id == PROPOSE_REFERENCES_TOOL and revision.review.policy_version == REFERENCE_INVESTIGATION_POLICY:
                model = ReferenceProposalInput
            if model is None or item.max_model_calls != 0 or item.max_attempts != 1 or item.authorization_state != "not_granted":
                raise AgentPlanPolicyViolation("investigation_capability_changed", "Only reviewed bounded evidence work may expand this plan.")
            body = model.model_validate(item.input_payload)
            if body.project_id != goal.project_id or body.image_revision_id != revision.request.image_revision_id:
                raise AgentPlanPolicyViolation("investigation_scope_changed", "Investigation follow-up differs from its fixed image.")
            steps.append(ToolPlanStep(tool_id=item.tool_id, input_payload=body.model_dump(exclude_none=True), reason=item.reason))
        return steps

    def _investigation(self, goal, step):
        invocation = self.invocations.get_tool_invocation(step.tool_invocation_id)
        receipt = invocation.result.investigation if invocation.result else None
        if (invocation.status != "completed" or invocation.tool_id != INVESTIGATE_TOOL
                or invocation.conversation_id != goal.conversation_id or receipt is None
                or receipt.project_id != goal.project_id or invocation.result.status != "completed"
                or invocation.result.object_refs != [f"image_investigation:{receipt.revision_id}"]):
            raise AgentPlanPolicyViolation("investigation_receipt_missing", "Investigation expansion requires its verified completed command.")
        revision = self.investigations.read(goal.project_id, receipt.revision_id)
        request = revision.request
        payload = query_payload(invocation.input_payload)
        body = InvestigationInput.model_validate({key: value for key, value in payload.items()
            if key not in {"confirmed_at", "confirmed_by_user"}})
        planned = query_payload(step.tool_input_payload)
        original = InvestigationInput.model_validate({key: value for key, value in planned.items()
            if key not in {"confirmed_at", "confirmed_by_user"}})
        if (revision.revision_hash != receipt.revision_hash or request.goal_id != goal.id
                or f"build_plan:{request.plan_id}" not in phase_target_refs(goal)
                or invocation.input_payload.get("agent_goal_id") != goal.id or body != request or original != request):
            raise AgentPlanPolicyViolation("investigation_scope_changed", "Investigation work cannot move to another goal or plan.")
        return revision

    def after_reference(self, goal):
        if (goal.goal_template not in {"system_image_build", "system_image_investigation"}
                or goal.status != "paused" or goal.pause_reason != "reference_candidate_review"):
            return []
        phase = goal.steps[active_phase_start(goal):]
        blocked = [step for step in phase if step.phase == "acting" and step.status == "blocked"]
        if len(blocked) != 1 or blocked[0].selected_tool_id != PROPOSE_REFERENCES_TOOL:
            raise AgentPlanPolicyViolation("reference_review_checkpoint_changed", "Reference review requires its original blocked proposal step.")
        step = blocked[0]
        earlier = phase[:phase.index(step)]
        completed = [item for item in earlier if item.phase == "acting" and item.status == "completed"
            and item.selected_tool_id == INVESTIGATE_TOOL]
        if not completed or self.references is None:
            raise AgentPlanPolicyViolation("reference_review_investigation_missing", "Reference work requires the original independent investigation.")
        revision = self._investigation(goal, completed[-1])
        if revision.review.policy_version != REFERENCE_INVESTIGATION_POLICY or revision.review.state != "investigation_ready":
            raise AgentPlanPolicyViolation("reference_review_investigation_changed", "This investigation did not propose reference work.")
        invocation = self.invocations.get_tool_invocation(step.tool_invocation_id)
        if (invocation.status != "completed" or invocation.tool_id != PROPOSE_REFERENCES_TOOL
                or invocation.conversation_id != goal.conversation_id
                or invocation.input_payload.get("agent_goal_id") != goal.id or invocation.result is None
                or invocation.result.status != "completed" or invocation.result.followup_reason != "reference_candidate_review"):
            raise AgentPlanPolicyViolation("reference_review_receipt_changed", "Reference review requires its original completed command.")
        body = ReferenceProposalInput.model_validate(query_payload(invocation.input_payload))
        expected = ReferenceProposalInput(project_id=goal.project_id, image_revision_id=revision.request.image_revision_id)
        if (body != expected or ReferenceProposalInput.model_validate(query_payload(step.tool_input_payload)) != expected
                or not any(item.tool_id == PROPOSE_REFERENCES_TOOL and item.input_payload == expected.model_dump()
                    and item.max_model_calls == 0 and item.max_attempts == 1 and item.authorization_state == "not_granted"
                    for item in revision.review.work_items)):
            raise AgentPlanPolicyViolation("reference_review_scope_changed", "Reference work differs from the original fixed investigation.")
        refs = invocation.result.object_refs
        if len(refs) != 1 or not refs[0].startswith("image_reference_proposal:") or not refs[0].split(":", 1)[1]:
            raise AgentPlanPolicyViolation("reference_review_receipt_changed", "Reference result must identify exactly one proposal.")
        proposal_id = refs[0].split(":", 1)[1]
        page = self.references.read(goal.project_id, proposal_id, section="assertions", offset=0, limit=1)
        if (page.proposal_id != proposal_id or page.image_revision_id != body.image_revision_id
                or page.image_artifact_hash != revision.request.image_artifact_hash or page.method_version != REFERENCE_METHOD
                or page.status != "proposed" or page.publication != "not_in_image_membership"
                or any(type(count) is not int or not 0 <= count <= 10000 for count in (page.assertion_count, page.gap_count))):
            raise AgentPlanPolicyViolation("reference_review_artifact_changed", "Reference artifact failed its fixed-image verification.")
        steps = []
        minimum_pages = sum(max(1, (count + 49) // 50) for count in (page.assertion_count, page.gap_count))
        self._require_reference_step_budget(goal, minimum_pages)
        for section, count in (("assertions", page.assertion_count), ("gaps", page.gap_count)):
            offset, limit = 0, 50
            while True:
                try:
                    verified = self.references.read(goal.project_id, proposal_id,
                        section=section, offset=offset, limit=limit)
                except ImageRevisionPageTooLarge:
                    if limit == 1:
                        raise
                    limit = (limit + 1) // 2
                    continue
                end = min(offset + limit, count)
                expected_next = end if end < count else None
                if (any(getattr(verified, key) != getattr(page, key) for key in (
                        "proposal_id", "digest", "image_revision_id", "image_artifact_hash", "method_version",
                        "status", "publication", "document_count", "assertion_count", "gap_count"))
                        or verified.section != section or len(verified.items) != end - offset
                        or verified.next_offset != expected_next):
                    raise AgentPlanPolicyViolation("reference_review_pagination_changed",
                        "Reference pagination must retain the complete original report.")
                # Retain every page, including empty sections. A byte-limited
                # response may shrink a page, but cannot drop any candidates.
                request = ImageReferenceInput(project_id=goal.project_id, proposal_id=proposal_id,
                    section=section, offset=offset, limit=limit)
                steps.append(ToolPlanStep("query.system_image.references.read", request.model_dump(),
                    reason="Inspect every fixed reference candidate and gap; do not accept relations or claim coverage."))
                self._require_reference_step_budget(goal, len(steps))
                if expected_next is None:
                    break
                offset = expected_next
        return steps

    @staticmethod
    def _require_reference_step_budget(goal, page_count):
        if goal.steps_completed + 2 * page_count + 3 > goal.max_steps:
            raise AgentPlanPolicyViolation("reference_review_budget_insufficient", "The original step ceiling cannot account for the complete reference report.")
