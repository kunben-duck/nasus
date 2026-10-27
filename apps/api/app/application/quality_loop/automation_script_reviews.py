"""Review uses the script application port, never code/quality repositories."""
from typing import Protocol
from pydantic import ValidationError

from .automation_script_review_inputs import ScriptReviewRequest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.automation_script_review import (
    SCRIPT_REVIEW_SCHEMA, ScriptReviewChanged, ScriptReviewIntegrityError, assess_script_review,
)
from ...domain.system_image.source_access import SourceAccessDenied


class ScriptDraftReadPort(Protocol):
    def read(self, project_id, script_revision_id): ...


class ScriptReviewRepositoryPort(Protocol):
    def history(self, project_id, script_revision_id): ...
    def revision(self, project_id, revision_id): ...
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, ref, digest, *, require_current): ...


class ScriptReviewArtifactPort(Protocol):
    def put(self, project_id, payload): ...
    def read(self, project_id, ref, digest): ...


class AutomationScriptReviewApplicationService:
    def __init__(self, scripts: ScriptDraftReadPort, authorization, repository: ScriptReviewRepositoryPort,
                 artifacts: ScriptReviewArtifactPort):
        self.scripts, self.authorization, self.repository, self.artifacts = scripts, authorization, repository, artifacts

    def _draft(self, request, *, current=False):
        value = self.scripts.read(request.project_id, request.script_revision_id)
        if value["metadata"]["artifact_hash"] != request.script_artifact_hash:
            raise ScriptReviewIntegrityError("script review draft pin mismatch")
        if current and not value["current_use"]["input_current"]:
            raise ScriptReviewChanged("script inputs or independent mapping are no longer current")
        return value

    @staticmethod
    def _pin(draft):
        value = draft["result"]
        prepared = value["prepared"]
        return {"script_revision_id": value["script_revision_id"], "artifact_hash": draft["metadata"]["artifact_hash"],
            "input_digest": value["request"]["input_digest"], "proposal_hash": acceptance_digest(value["proposal"]),
            **{key: prepared[key] for key in ("context_pin", "scope_pin", "generation_pin", "mapping_pin")}}

    @staticmethod
    def _assessment(request, draft):
        return assess_script_review(draft["result"]["proposal"],
            request.model_dump(mode="json")["actions"], request.model_dump(mode="json")["assertions"]) if request.decision == "review" else None

    def _history(self, project_id, script_revision_id, draft):
        values = self.repository.history(project_id, script_revision_id)
        verified = []
        for stored in values:
            meta = stored["revision"]
            payload = self.artifacts.read(project_id, stored["artifact_ref"], meta["artifact_hash"])
            try:
                request = ScriptReviewRequest.model_validate(payload["request"])
            except (ValidationError, KeyError, TypeError):
                raise ScriptReviewIntegrityError("script review archive request invalid") from None
            if (acceptance_digest(payload) != meta["artifact_hash"] or payload.get("schema") != SCRIPT_REVIEW_SCHEMA
                    or payload.get("project_id") != project_id or request.project_id != project_id
                    or request.script_revision_id != script_revision_id
                    or request.script_artifact_hash != draft["metadata"]["artifact_hash"]
                    or request.expected_previous_revision_id != meta["previous_revision_id"]
                    or acceptance_digest(request.model_dump(mode="json")) != meta["request_hash"]
                    or payload.get("script_pin") != self._pin(draft)
                    or payload.get("assessment") != self._assessment(request, draft)
                    or meta["status"] != ("reviewed" if request.decision == "review" else "withdrawn")
                    or any(payload.get(key) != meta[key] for key in ("authority_actor", "invocation_id", "recorded_at"))):
                raise ScriptReviewIntegrityError("script review history provenance mismatch")
            verified.append({"revision": meta, "request": request.model_dump(mode="json"),
                "script_pin": payload["script_pin"], "assessment": payload["assessment"]})
        return verified

    def inspect(self, request):
        access = self.authorization.scope(request.project_id)
        draft = self._draft(request)
        history = self._history(request.project_id, request.script_revision_id, draft)
        self.authorization.require_current(access)
        return {"project_id": request.project_id, "script_revision_id": request.script_revision_id,
            "script_artifact_hash": request.script_artifact_hash, "script_pin": self._pin(draft),
            "head": history[-1] if history else None, "history": [value["revision"] for value in history],
            "input_current": draft["current_use"]["input_current"],
            "can_review": access.effective_project_role in {"qa_lead", "project_admin", "platform_admin"},
            "execution_authorized": False}

    def review(self, request, *, invocation_id, recorded_at):
        request = ScriptReviewRequest.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("script review requires a current project reviewer")
        require_access = lambda: self.authorization.require_current(access)
        prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id, require_access=require_access)
        if prior is not None:
            value = self.read(request.project_id, prior["revision_id"])
            if value["request"] != request.model_dump(mode="json"):
                raise ScriptReviewIntegrityError("script review recovery request mismatch")
            require_access()
            return prior
        draft = self._draft(request, current=request.decision == "review")
        history = self._history(request.project_id, request.script_revision_id, draft)
        previous = history[-1]["revision"]["revision_id"] if history else None
        if previous != request.expected_previous_revision_id:
            raise ScriptReviewChanged("script review head changed; reload and confirm again")
        payload = {"schema": SCRIPT_REVIEW_SCHEMA, "project_id": request.project_id,
            "request": request.model_dump(mode="json"), "script_pin": self._pin(draft),
            "assessment": self._assessment(request, draft), "authority_actor": access.actor_id,
            "invocation_id": invocation_id, "recorded_at": recorded_at}
        require_access()
        ref, digest = self.artifacts.put(request.project_id, payload)
        if acceptance_digest(payload) != digest:
            raise ScriptReviewIntegrityError("script review archive write mismatch")

        def current():
            fresh = self._draft(request, current=request.decision == "review")
            if self._pin(fresh) != payload["script_pin"]:
                raise ScriptReviewIntegrityError("script derivation changed before review commit")
            self._history(request.project_id, request.script_revision_id, fresh)
            require_access()

        metadata = self.repository.record(request, payload, ref, digest, require_current=current)
        require_access()
        return metadata

    def receipt(self, request):
        view = self.inspect(request)
        head = view["head"]
        metadata = head["revision"] if head else None
        return {**request.model_dump(mode="json"), "history_digest": acceptance_digest(view["history"]),
            "head_revision_id": metadata["revision_id"] if metadata else None,
            "head_artifact_hash": metadata["artifact_hash"] if metadata else None,
            "status": metadata["status"] if metadata else "unreviewed", "input_current": view["input_current"],
            "review_complete": bool(head and metadata["status"] == "reviewed" and view["input_current"]
                and head["assessment"]["review_complete"]), "execution_authorized": False,
            "observation": "query_time_requires_revalidation"}

    def read(self, project_id, revision_id):
        return self.read_with_script(project_id, revision_id)[0]

    def read_with_script(self, project_id, revision_id):
        """Return only the parent fully verified by this read, never a cached head."""
        access = self.authorization.scope(project_id)
        stored = self.repository.revision(project_id, revision_id)
        draft = self.scripts.read(project_id, stored["script_revision_id"])
        history = self._history(project_id, stored["script_revision_id"], draft)
        value = next((item for item in history if item["revision"]["revision_id"] == revision_id), None)
        if value is None:
            raise ScriptReviewIntegrityError("script review history missing its selected revision")
        current = (history[-1]["revision"]["revision_id"] == revision_id
            and value["revision"]["status"] == "reviewed" and draft["current_use"]["input_current"])
        self.authorization.require_current(access)
        return {**value, "historical_not_live": True, "current_use": {"review_current": current,
            "review_complete": bool(current and value["assessment"] and value["assessment"]["review_complete"]),
            "execution_authorized": False}}, draft
