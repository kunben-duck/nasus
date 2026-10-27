"""Cross-context read ports; never invoke the builder or modify the original plan."""
from contextlib import nullcontext
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .run_plan_build_inputs import RunPlanBuildSelection, RunPlanBuildRequest, RunPlanBuildQuery
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from ...domain.quality_loop.run_plan_build import RUN_PLAN_BUILD_ARTIFACT_SCHEMA, compile_run_plan_build
from ...domain.system_image.source_access import SourceAccessDenied


class RunPlanBuildReadPort(Protocol):
    def read(self, project_id, ident): ...


class RunPlanBuildRepositoryPort(Protocol):
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, ref, digest, *, require_current): ...
    def read(self, project_id, binding_id): ...


class RunPlanBuildApplicationService:
    def __init__(self, plans: RunPlanBuildReadPort, builds: RunPlanBuildReadPort, authorization,
                 repository: RunPlanBuildRepositoryPort, artifacts):
        self.plans, self.builds, self.authorization = plans, builds, authorization
        self.repository, self.artifacts = repository, artifacts

    def require_receipt_inputs_access(self, scope):
        self.require_receipt_inputs_access_many((scope,))

    def require_receipt_inputs_access_many(self, scopes):
        if not 1 <= len(scopes) <= 128:
            raise RunPlanIntegrityError("build receipt access requires a bounded original cohort")
        access = {scope.project_id: self.authorization.scope(scope.project_id) for scope in scopes}
        for scope in scopes:
            if isinstance(scope, RunPlanBuildQuery):
                self.read(scope.project_id, scope.binding_id)
            elif isinstance(scope, RunPlanBuildSelection):
                self._compile(scope, current=False)
            else:
                raise RunPlanIntegrityError("build receipt original scope is invalid")
        # A later source revocation must also invalidate earlier members.
        for original in access.values():
            self.authorization.require_current(original)

    def _compile(self, selection, *, current):
        read_session = getattr(self.plans, "verified_read_session", None)
        with read_session() if read_session else nullcontext():
            plan = self.plans.read(selection.project_id, selection.run_plan_id)
            if current and plan["current_use"]["inputs_current"] is not True:
                raise RunPlanChanged("original plan inputs or script review are no longer current")
            try:
                builds = [self.builds.read(selection.project_id, item.invocation_id) for item in selection.native_builds]
            except ValueError:
                raise RunPlanIntegrityError("original native build archive cannot be verified") from None
        return compile_run_plan_build(plan, selection.model_dump(mode="json"), builds), plan

    def preview(self, selection: RunPlanBuildSelection):
        selection = RunPlanBuildSelection.model_validate(selection.model_dump(mode="json"))
        access = self.authorization.scope(selection.project_id)
        binding, _ = self._compile(selection, current=True)
        self.authorization.require_current(access)
        request = RunPlanBuildRequest(**selection.model_dump(mode="json"), binding_digest=binding["binding_digest"],
            source_scope_digest=access.fingerprint)
        return {"request": request.model_dump(mode="json"), "status": "preview",
            "code_source_count": len(binding["builds"]), "native_build_source_attested": True,
            "target_artifact_hash": binding["target_artifact_hash"], "execution_authorized": False,
            "remaining_gates": ["independent_build_binding_confirmation", *binding["remaining_gates"]]}

    def bind(self, request: RunPlanBuildRequest, *, invocation_id, recorded_at):
        request = RunPlanBuildRequest.model_validate(request.model_dump(mode="json"))
        access = self.authorization.scope(request.project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("binding an original build requires a current project reviewer")
        require_access = lambda: self.authorization.require_current(access)
        prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id,
            require_access=require_access)
        if prior is not None:
            view = self.read(request.project_id, prior["binding_id"])
            if view["artifact"]["request"] != request.model_dump(mode="json"):
                raise RunPlanIntegrityError("build binding recovery was rebound")
            require_access()
            return prior
        binding, _ = self._compile(request.selection(), current=True)
        if binding["binding_digest"] != request.binding_digest or access.fingerprint != request.source_scope_digest:
            raise RunPlanChanged("original build binding or source authority changed; preview and confirm again")
        payload = {"schema": RUN_PLAN_BUILD_ARTIFACT_SCHEMA, "project_id": request.project_id,
            "binding_id": str(uuid5(NAMESPACE_URL, "nasus:run-plan-build:" + invocation_id)),
            "request": request.model_dump(mode="json"), "binding": binding, "actor_id": access.actor_id,
            "invocation_id": invocation_id, "recorded_at": recorded_at}
        ref, digest = self.artifacts.put(request.project_id, payload)
        if acceptance_digest(payload) != digest:
            raise RunPlanIntegrityError("build binding archive write mismatch")

        def current():
            fresh, _ = self._compile(request.selection(), current=True)
            if fresh != binding:
                raise RunPlanChanged("original build binding changed before commit")
            require_access()

        value = self.repository.record(request, payload, ref, digest, require_current=current)
        require_access()
        return value

    def read(self, project_id, binding_id):
        return self._read_with_plan(project_id, binding_id)[0]

    def read_with_plan(self, project_id, binding_id):
        """Return this read's complete verified parent, never a cached plan head."""
        return self._read_with_plan(project_id, binding_id)

    def _read_with_plan(self, project_id, binding_id):
        access = self.authorization.scope(project_id)
        stored = self.repository.read(project_id, binding_id)
        metadata = stored["metadata"]
        try:
            request = RunPlanBuildRequest.model_validate(stored["request"])
        except (ValueError, KeyError, TypeError):
            raise RunPlanIntegrityError("build binding original request invalid") from None
        if request.project_id != project_id:
            raise RunPlanIntegrityError("build binding original project mismatch")
        # Reauthorize all original sources before reading the private binding.
        binding, plan = self._compile(request.selection(), current=False)
        payload = self.artifacts.read(project_id, stored["artifact_ref"], metadata["artifact_hash"])
        if (payload.get("schema") != RUN_PLAN_BUILD_ARTIFACT_SCHEMA or acceptance_digest(payload) != metadata["artifact_hash"]
                or payload.get("request") != request.model_dump(mode="json") or payload.get("binding") != binding
                or any(payload.get(key) != metadata[key] for key in
                    ("project_id", "binding_id", "actor_id", "invocation_id", "recorded_at"))
                or any(metadata[key] != binding[key] for key in
                    ("binding_digest", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "target_artifact_hash"))
                or binding["binding_digest"] != request.binding_digest
                or any(metadata[key] != binding["source_pin"][key] for key in ("image_revision_id", "manifest_id"))
                or metadata["request_hash"] != acceptance_digest(request.model_dump(mode="json"))):
            raise RunPlanIntegrityError("original build binding archive or provenance cannot be verified")
        self.authorization.require_current(access)
        return {"metadata": metadata, "artifact": payload, "historical_not_live": True,
            "current_use": {"inputs_current": plan["current_use"]["inputs_current"],
                "native_build_source_attested": True, "environment_verified": False, "fixtures_verified": False,
                "execution_authorized": False}}, plan

    def receipt(self, project_id, binding_id):
        view = self.read(project_id, binding_id)
        return {"metadata": view["metadata"], "current_use": view["current_use"], "historical_not_live": True}
