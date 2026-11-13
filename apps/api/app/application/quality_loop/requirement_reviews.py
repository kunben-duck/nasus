import asyncio
from typing import Protocol

from .requirement_review_models import ReviewSelection
from .requirement_review_context import RequirementReviewContext


class RequirementReviewRepositoryPort(Protocol):
    def revision(self, selection, *, latest=True): ...
    def events(self, selection): ...
    def record(self, request, revision, kind, payload, **kwargs): ...


class RequirementReviewModelPort(Protocol):
    def prepare(self): ...
    async def evaluate(self, payload, prepared): ...


class RequirementReviewApplicationService:
    def __init__(self, repository: RequirementReviewRepositoryPort, revisions, images,
                 model: RequirementReviewModelPort, acceptance):
        self.repository, self.revisions, self.images = repository, revisions, images
        self.model, self.acceptance = model, acceptance
        self.context = RequirementReviewContext(images)

    def _scope(self, selection, *, latest=True):
        scope, delivery = self.revisions._scope(selection.project_id, selection.version_id)
        revision = self.repository.revision(selection, latest=latest)
        self.images.frozen_header(selection.project_id, revision.image_revision_id)
        return scope, revision, delivery

    def _current(self, selection, revision):
        scope, current, delivery = self._scope(selection)
        if current.content_hash != revision.content_hash:
            raise ValueError("Requirement inputs changed")
        if scope.effective_project_role not in {"project_admin", "platform_admin"}:
            raise PermissionError("Requirement review role is no longer authorized")
        if delivery.iteration_image.image_revision_id != revision.image_revision_id:
            raise ValueError("Iteration image changed; create a new requirement revision against the current image")
        self.images.authorization.require_current(scope)

    def revision(self, selection):
        return self._scope(selection)[1]

    def preview(self, selection):
        scope, revision, _ = self._scope(selection)
        if scope.effective_project_role not in {"project_admin", "platform_admin"}:
            raise PermissionError("Sending source evidence to a review model requires a project administrator")
        payload, digest = self.context.prepare(revision)
        binding = self.model.prepare()[0]
        self._current(selection, revision)
        return {"request": {**selection.model_dump(), "input_digest": digest, "model_digest": binding["digest"]},
            "model": binding, "evidence": payload["evidence"], "omitted_objects": payload["omitted_objects"],
            "notice": "One live model review; selected evidence will be sent. No automatic approval or execution."}

    async def evaluate(self, request, *, invocation_id):
        scope, revision, _ = await asyncio.to_thread(self._scope, request)
        if scope.effective_project_role not in {"project_admin", "platform_admin"}:
            raise PermissionError("Requirement model review requires a project administrator")
        events = await asyncio.to_thread(self.repository.events, request)
        if any(event["invocation_id"] == invocation_id for event in events):
            raise ValueError("This model call was already reserved; inspect the original outcome before starting a new review")
        payload, digest = await asyncio.to_thread(self.context.prepare, revision)
        prepared = self.model.prepare()
        if (digest, prepared[0]["digest"]) != (request.input_digest, request.model_digest):
            raise ValueError("Review inputs or model changed; preview and confirm again")
        check = lambda: self._current(request, revision)
        await asyncio.to_thread(self.repository.record, request, revision, "reserved", {"input": payload, "model": prepared[0]},
            invocation_id=invocation_id, scope=scope, check=check)
        try:
            check()
            assessment, usage = await self.model.evaluate({**payload, "invocation_id": invocation_id}, prepared)
            assessment.validate_refs({item["ref"] for item in payload["evidence"]})
            self.images.authorization.require_current(scope)
            check()
            scope, _, _ = self._scope(request)
            result = {"assessment": assessment.model_dump(mode="json"), "model": usage,
                "input_digest": digest, "projection": None}
            return await asyncio.to_thread(self.repository.record, request, revision, "evaluated", result,
                invocation_id=invocation_id, scope=scope, check=check, complete=True, assessment=assessment)
        except Exception as exc:
            # Keep the original reserved call and a redacted failure, never a mock review.
            await asyncio.to_thread(self.repository.record, request, revision, "failed", {"error_type": type(exc).__name__},
                invocation_id=invocation_id, scope=self.images.authorization.scope(request.project_id), check=check)
            raise

    def read(self, selection):
        scope, revision, delivery = self._scope(selection, latest=False)
        events = self.repository.events(selection)
        latest = self.revisions.repository.list(selection.project_id, selection.version_id,
            us_id=revision.us_id, offset=0, limit=1)[0]
        current = latest.revision_id == revision.revision_id
        evaluation = next((event for event in reversed(events) if event["kind"] == "evaluated"), None)
        confirmation = next((event for event in reversed(events) if event["kind"] == "confirmed"), None)
        last_attempt = next((event for event in reversed(events) if event["kind"] in {"reserved", "evaluated", "failed"}), None)
        status = "draft"
        requests = []
        if evaluation and last_attempt and last_attempt["kind"] == "evaluated" and last_attempt["event_id"] == evaluation["event_id"]:
            payload = evaluation["payload"]
            status = "clarification_required" if any(q["blocking"] for q in payload["assessment"]["questions"]) else "awaiting_confirmation"
            projection = payload["projection"]
            if projection:
                self.images.frozen_header(selection.project_id, projection["image_revision_id"])
                for criterion in projection["criteria"]:
                    authority = self.acceptance.inspect(selection.project_id, projection["image_revision_id"],
                        projection["image_artifact_hash"], criterion["object_id"])
                    requests.append({"title": criterion["title"], "current": authority["head"], "input": {
                        "project_id": selection.project_id, "image_revision_id": projection["image_revision_id"],
                        "image_artifact_hash": projection["image_artifact_hash"], "object_id": criterion["object_id"],
                        "basis_digest": authority["basis_digest"],
                        "expected_previous_revision_id": authority["head"]["revision_id"] if authority["head"] else None,
                        "decision": "approve", "oracle": criterion["oracle"], "authority_basis": "user_confirmed_requirement",
                        "policy_revision": authority["policy_revision"], "reason": "Independent review of requirement " + revision.revision_id}})
            if confirmation and confirmation["payload"]["evaluation_id"] == evaluation["event_id"]:
                expected = confirmation["payload"]["approvals"]
                status = "confirmed" if all(item["current"] and item["current"]["status"] == "approved"
                    and item["current"]["revision_id"] == expected.get(item["input"]["object_id"]) for item in requests) else "approval_invalidated"
        elif last_attempt:
            status = "review_failed" if last_attempt["kind"] == "failed" else "review_pending"
        if status != "confirmed" and delivery.iteration_image.image_revision_id != revision.image_revision_id:
            status = "image_changed"
        if not current:
            status = "superseded"
        self.images.authorization.require_current(scope)
        return {**selection.model_dump(), "us_id": revision.us_id, "status": status, "current": current,
            "evaluation": evaluation, "confirmation": confirmation, "events": events,
            "approval_requests": requests, "can_confirm": current and status in {"awaiting_confirmation", "approval_invalidated"}
                and scope.actor_id != revision.actor_id and scope.actor_id != (evaluation or {}).get("actor_id")
                and scope.effective_project_role in {"project_admin", "platform_admin"},
            "generation_authorized": False}

    def confirm(self, request, *, invocation_id):
        scope, revision, _ = self._scope(request)
        view = self.read(ReviewSelection(**{key: getattr(request, key) for key in ReviewSelection.model_fields}))
        evaluation = view["evaluation"]
        if (not view["can_confirm"] or not evaluation or request.evaluation_id != evaluation["event_id"]
                or request.review_digest != evaluation["content_hash"] or not request.reason.strip()):
            raise ValueError("Confirmation requires a current, unblocked review and an independent reviewer")
        approvals = {}
        for item in view["approval_requests"]:
            head = item["current"]
            if not head or head["status"] != "approved" or head["authority_actor"] != scope.actor_id:
                raise ValueError("Independently approve every proposed acceptance criterion before confirming the requirement")
            approved = self.acceptance.read(request.project_id, head["revision_id"])
            if approved["oracle"] != item["input"]["oracle"]:
                raise ValueError("Approved oracle differs from the reviewed criterion")
            approvals[item["input"]["object_id"]] = head["revision_id"]
        if not approvals:
            raise ValueError("Requirement confirmation has no approved acceptance criteria")
        payload = {"evaluation_id": evaluation["event_id"], "review_digest": request.review_digest,
            "projection": evaluation["payload"]["projection"], "approvals": approvals, "reason": request.reason}
        def check():
            self._current(request, revision)
            current = self.read(ReviewSelection(project_id=request.project_id, version_id=request.version_id, revision_id=request.revision_id))
            if current["evaluation"]["event_id"] != request.evaluation_id:
                raise ValueError("Requirement evaluation changed during confirmation")
            for item in current["approval_requests"]:
                if not item["current"] or item["current"]["status"] != "approved" or approvals.get(item["input"]["object_id"]) != item["current"]["revision_id"]:
                    raise ValueError("Acceptance approval changed during confirmation")
        return self.repository.record(request, revision, "confirmed", payload, invocation_id=invocation_id,
            scope=scope, check=check, complete=True)
