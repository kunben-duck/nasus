"""Register and reauthorize complete fixture definitions through ports only."""
from contextlib import nullcontext
from copy import deepcopy
from typing import Protocol

from pydantic import model_validator

from .environment_observation_records import EnvironmentRecordQuery
from .test_design_output import Digest, GenerationValue, Id
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixtures import bind_run_plan_fixture, validate_http_fixture_manifest
from ...domain.quality_loop.http_fixture_recipe import (
    RECIPE_SCHEMA, RECIPE_PARENT_FIELDS, recipe_identity, validate_recipe_archive,
)
from ...domain.quality_loop.run_plan import RunPlanIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied


class HttpFixtureRecipeRequest(GenerationValue):
    project_id: Id
    run_plan_id: Id
    run_plan_artifact_hash: Digest
    manifest: dict

    @model_validator(mode="after")
    def complete_manifest(self):
        validate_http_fixture_manifest(self.manifest)
        return self


class HttpFixtureRecipeRepositoryPort(Protocol):
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, ref, metadata, *, require_access): ...
    def read(self, project_id, record_id): ...


class HttpFixtureRecipeApplicationService:
    def __init__(self, plans, artifacts, repository: HttpFixtureRecipeRepositoryPort):
        self.plans, self.artifacts, self.repository = plans, artifacts, repository
        self.authorization = plans.authorization

    def _session(self):
        operation = getattr(self.plans, "verified_read_session", None)
        return operation() if operation else nullcontext()

    def verified_read_session(self):
        return self._session()

    def _access(self, project_id):
        access = self.authorization.scope(project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("fixture recipe registration/history requires a current reviewer")
        return access

    def _inputs(self, request):
        saved = self.plans.read(request.project_id, request.run_plan_id)
        if (saved["metadata"]["project_id"] != request.project_id
                or saved["metadata"]["run_plan_id"] != request.run_plan_id
                or saved["metadata"]["artifact_hash"] != request.run_plan_artifact_hash):
            raise RunPlanIntegrityError("fixture recipe references a different saved RunPlan")
        bind_run_plan_fixture(saved["artifact"]["plan"], request.manifest)
        return saved

    def record(self, request: HttpFixtureRecipeRequest, *, invocation_id, recorded_at):
        request = HttpFixtureRecipeRequest.model_validate(request.model_dump(mode="json"))
        access = self._access(request.project_id)
        current = lambda: self.authorization.require_current(access)
        with self._session():
            saved = self._inputs(request)
            prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id,
                require_access=current)
            if prior is not None:
                view = self._read(request.project_id, prior["record_id"])
                if acceptance_digest(view["metadata"]) != acceptance_digest(prior):
                    raise RunPlanIntegrityError("fixture recipe replay cannot replace original history")
                return prior
            plan = saved["artifact"]["plan"]
            binding = bind_run_plan_fixture(plan, request.manifest)
            payload = {"schema": RECIPE_SCHEMA, "project_id": request.project_id,
                "record_id": recipe_identity(invocation_id), "invocation_id": invocation_id,
                "actor_id": access.actor_id, "recorded_at": recorded_at, "request": request.model_dump(mode="json"),
                "parents": {"plan_digest": plan["plan_digest"], **{key: plan["source_pin"][key]
                    for key in RECIPE_PARENT_FIELDS if key != "plan_digest"}}, "fixture_digest": binding["fixture_digest"]}
            metadata = validate_recipe_archive(payload, payload["request"], saved)
            current()
            ref, digest = self.artifacts.put(request.project_id, payload)
            if digest != metadata["artifact_hash"]:
                raise RunPlanIntegrityError("fixture recipe archive write differs")

            def verify_before_commit():
                original = self.artifacts.read(request.project_id, ref, digest)
                if (acceptance_digest(original) != acceptance_digest(payload)
                        or acceptance_digest(validate_recipe_archive(original, payload["request"], self._inputs(request)))
                            != acceptance_digest(metadata)):
                    raise RunPlanIntegrityError("fixture recipe original changed before commit")
                current()

            result = self.repository.record(request, payload, ref, metadata, require_access=verify_before_commit)
            current()
            return result

    def _read_with_plan(self, project_id, record_id):
        access = self._access(project_id)
        stored = self.repository.read(project_id, record_id)
        request = HttpFixtureRecipeRequest.model_validate(stored["request"])
        if request.project_id != project_id or stored["metadata"]["record_id"] != record_id:
            raise RunPlanIntegrityError("fixture recipe history scope differs")
        saved = self._inputs(request)
        self.authorization.require_current(access)
        archive = self.artifacts.read(project_id, stored["artifact_ref"], stored["metadata"]["artifact_hash"])
        if acceptance_digest(validate_recipe_archive(archive, stored["request"], saved)) != acceptance_digest(stored["metadata"]):
            raise RunPlanIntegrityError("fixture recipe metadata differs from original private bytes")
        self.authorization.require_current(access)
        return {"metadata": deepcopy(stored["metadata"]), "archive": archive, "historical_not_live": True}, saved

    def _read(self, project_id, record_id):
        return self._read_with_plan(project_id, record_id)[0]

    def read(self, project_id, record_id):
        with self._session():
            return self._read(project_id, record_id)

    def read_with_plan(self, project_id, record_id):
        """Return the exact fully verified parent from this read, never a cached head."""
        with self._session():
            return self._read_with_plan(project_id, record_id)

    def receipt(self, project_id, record_id):
        return {"metadata": self.read(project_id, record_id)["metadata"], "historical_not_live": True}

    def authorize_receipts(self, values):
        if not 1 <= len(values) <= 128:
            raise RunPlanIntegrityError("fixture recipe receipt cohort exceeds its bound")
        accesses = {scope.project_id: self._access(scope.project_id) for scope, _ in values}
        with self._session():
            for scope, receipt in values:
                if receipt is None:
                    if isinstance(scope, EnvironmentRecordQuery):
                        self._read(scope.project_id, scope.record_id)
                    else:
                        self._inputs(scope)
                    continue
                if (type(receipt) is not dict or set(receipt) != {"metadata", "historical_not_live"}
                        or receipt["historical_not_live"] is not True or type(receipt["metadata"]) is not dict):
                    raise RunPlanIntegrityError("fixture recipe receipt invalid")
                view = self._read(scope.project_id, receipt["metadata"].get("record_id"))
                if acceptance_digest(view["metadata"]) != acceptance_digest(receipt["metadata"]):
                    raise RunPlanIntegrityError("fixture recipe receipt changed")
                if isinstance(scope, EnvironmentRecordQuery):
                    if scope.record_id != view["metadata"]["record_id"]:
                        raise RunPlanIntegrityError("fixture recipe record rebound")
                elif view["archive"]["request"] != scope.model_dump(mode="json"):
                    raise RunPlanIntegrityError("fixture recipe original command rebound")
        for access in accesses.values():
            self.authorization.require_current(access)
