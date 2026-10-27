"""Fixed reviewed inputs through ports, with historical replay and live ACL."""
from contextlib import contextmanager, nullcontext
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .run_plan_inputs import RunPlanCommandScope, RunPlanSelection, RunPlanRequest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan import (run_plan_artifact_schema, RunPlanChanged, RunPlanIntegrityError, compile_run_plan)
from ...domain.system_image.source_access import SourceAccessDenied


class RunPlanSourcePort(Protocol):
    def run_plan_sources(self, prepared): ...


class RunPlanReviewPort(Protocol):
    def read(self, project_id, revision_id): ...
    def read_with_script(self, project_id, revision_id): ...


class RunPlanRepositoryPort(Protocol):
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, ref, digest, *, require_current): ...
    def read(self, project_id, run_plan_id): ...


class RunPlanArtifactPort(Protocol):
    def put(self, project_id, payload): ...
    def read(self, project_id, ref, digest): ...


class RunPlanApplicationService:
    def __init__(self, scripts, reviews: RunPlanReviewPort, sources: RunPlanSourcePort, authorization,
                 repository: RunPlanRepositoryPort, artifacts: RunPlanArtifactPort):
        self.scripts, self.reviews, self.sources = scripts, reviews, sources
        self.authorization, self.repository, self.artifacts = authorization, repository, artifacts

    @contextmanager
    def verified_read_session(self):
        read_session = getattr(self.sources, "verified_read_session", None)
        live_session = getattr(self.authorization, "live_read_session", None)
        # Share transport, not ACL/head results; immutable source proof stays local.
        with live_session() if live_session else nullcontext():
            with read_session() if read_session else nullcontext():
                yield

    def require_command_inputs_access(self, scope: RunPlanCommandScope):
        self.require_command_inputs_access_many((scope,))

    def _parents(self, scope):
        reader = getattr(self.reviews, "read_with_script", None)
        if callable(reader):
            review, draft = reader(scope.project_id, scope.review_revision_id)
            return draft, review
        draft = self.scripts.read(scope.project_id, scope.script_revision_id)
        return draft, self.reviews.read(scope.project_id, scope.review_revision_id)

    def require_command_inputs_access_many(self, scopes):
        """Authorize original receipt inputs without preparing or executing a plan."""
        if not 1 <= len(scopes) <= 128:
            raise RunPlanIntegrityError("RunPlan receipt authorization scope exceeds its bound")
        scopes = tuple(RunPlanCommandScope.model_validate(item.model_dump(mode="json")) for item in scopes)
        access = {item.project_id: self.authorization.scope(item.project_id) for item in scopes}
        with self.verified_read_session():
            for item in scopes:
                draft, review = self._parents(item)
                script, decision = draft["metadata"], review["revision"]
                if (script["project_id"] != item.project_id or script["script_revision_id"] != item.script_revision_id
                        or script["artifact_hash"] != item.script_artifact_hash
                        or decision["project_id"] != item.project_id or decision["revision_id"] != item.review_revision_id
                        or decision["artifact_hash"] != item.review_artifact_hash
                        or decision["script_revision_id"] != item.script_revision_id
                        or decision["script_artifact_hash"] != item.script_artifact_hash):
                    raise RunPlanIntegrityError("RunPlan receipt original parent pins differ")
                sources = self.sources.run_plan_sources(draft["result"]["prepared"])
                context = draft["result"]["prepared"]["context_pin"]
                if (sources["project_id"] != item.project_id or sources["image_revision_id"] != context["image_revision_id"]
                        or sources["image_artifact_hash"] != context["image_artifact_hash"]):
                    raise RunPlanIntegrityError("RunPlan receipt original source scope differs")
            current_many = getattr(self.authorization, "require_current_many", None)
            if callable(current_many):
                current_many(tuple(access.values()))
            else:
                for scope in access.values():
                    self.authorization.require_current(scope)

    def _compile(self, selection, *, current):
        with self.verified_read_session():
            draft, review = self._parents(selection)
            if current and (not draft["current_use"]["input_current"] or not review["current_use"]["review_complete"]):
                raise RunPlanChanged("script review or original inputs changed; prepare a newly confirmed plan")
            sources = self.sources.run_plan_sources(draft["result"]["prepared"])
            plan = compile_run_plan(draft, review, selection.model_dump(mode="json"), sources)
        return plan, draft, review

    def preview(self, selection: RunPlanSelection):
        selection = RunPlanSelection.model_validate(selection.model_dump(mode="json"))
        access = self.authorization.scope(selection.project_id)
        plan, _, _ = self._compile(selection, current=True)
        self.authorization.require_current(access)
        request = RunPlanRequest(**selection.model_dump(mode="json"), plan_digest=plan["plan_digest"],
            source_scope_digest=access.fingerprint)
        return {"request": request.model_dump(mode="json"), "case_count": len(plan["prepared"]["cases"]),
            "obligation_count": plan["prepared"]["obligation_denominator"],
            "status": "preview", "target_verification": plan["target_verification"],
            "execution_authorized": False, "remaining_gates": ["fresh_prepare_confirmation", *plan["remaining_gates"]]}

    def prepare(self, request: RunPlanRequest, *, invocation_id, recorded_at):
        request = RunPlanRequest.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("RunPlan preparation requires a current project reviewer")
        require_access = lambda: self.authorization.require_current(access)
        prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id,
            require_access=require_access)
        if prior is not None:
            view = self.read(request.project_id, prior["run_plan_id"])
            if view["artifact"]["request"] != request.model_dump(mode="json"):
                raise RunPlanIntegrityError("RunPlan command recovery was rebound")
            require_access()
            return prior
        plan, _, _ = self._compile(request.selection(), current=True)
        if plan["plan_digest"] != request.plan_digest or access.fingerprint != request.source_scope_digest:
            raise RunPlanChanged("RunPlan preview or source access changed; inspect and confirm again")
        payload = {"schema": run_plan_artifact_schema(request.policy_revision), "project_id": request.project_id,
            "run_plan_id": str(uuid5(NAMESPACE_URL, "nasus:run-plan:" + invocation_id)),
            "request": request.model_dump(mode="json"), "plan": plan, "actor_id": access.actor_id,
            "invocation_id": invocation_id, "recorded_at": recorded_at}
        ref, digest = self.artifacts.put(request.project_id, payload)
        if acceptance_digest(payload) != digest:
            raise RunPlanIntegrityError("RunPlan archive write mismatch")

        def current():
            fresh, _, _ = self._compile(request.selection(), current=True)
            if fresh != plan:
                raise RunPlanChanged("RunPlan upstream inputs changed before commit")
            require_access()

        value = self.repository.record(request, payload, ref, digest, require_current=current)
        require_access()
        return value

    def read(self, project_id, run_plan_id):
        with self.verified_read_session():
            return self._read(project_id, run_plan_id)

    def _read(self, project_id, run_plan_id):
        access = self.authorization.scope(project_id)
        stored = self.repository.read(project_id, run_plan_id)
        metadata = stored["metadata"]
        try:
            request = RunPlanRequest.model_validate(stored["request"])
        except (ValueError, KeyError, TypeError):
            raise RunPlanIntegrityError("RunPlan archive request invalid") from None
        if request.project_id != project_id:
            raise RunPlanIntegrityError("RunPlan archive project mismatch")
        # Original source authorization and history precede reading the plan body.
        plan, draft, review = self._compile(request.selection(), current=False)
        payload = self.artifacts.read(project_id, stored["artifact_ref"], metadata["artifact_hash"])
        if (payload.get("schema") != run_plan_artifact_schema(request.policy_revision) or acceptance_digest(payload) != metadata["artifact_hash"]
                or payload.get("request") != request.model_dump(mode="json")
                or any(payload.get(key) != metadata[key] for key in
                    ("project_id", "run_plan_id", "actor_id", "invocation_id", "recorded_at"))
                or payload.get("plan") != plan or request.plan_digest != plan["plan_digest"]
                or metadata["plan_digest"] != request.plan_digest
                or any(metadata[key] != plan["source_pin"][key] for key in ("image_revision_id", "manifest_id"))
                or metadata["context_id"] != plan["prepared"]["context_pin"]["context_id"]
                or acceptance_digest(payload["request"]) != metadata["request_hash"]):
            raise RunPlanIntegrityError("RunPlan original archive or derivation cannot be verified")
        self.authorization.require_current(access)
        return {"metadata": metadata, "artifact": payload, "historical_not_live": True,
            "current_use": {"inputs_current": bool(draft["current_use"]["input_current"]
                and review["current_use"]["review_complete"]), "target_verified": False, "execution_authorized": False}}
