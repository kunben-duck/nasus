"""Record fixed source evidence via ports; history never invokes a parser."""
from copy import deepcopy
from typing import Protocol

from .run_plan_locators import RunPlanLocatorQuery
from .environment_observation_records import EnvironmentRecordQuery
from ...domain.quality_loop.http_locator_record import (
    LOCATOR_RECORD_SCHEMA, locator_record_identity, locator_record_metadata, validate_locator_archive,
)
from ...domain.quality_loop.run_plan import RunPlanIntegrityError
from ...domain.quality_loop.acceptance_specification import acceptance_digest


class LocatorRecordRepositoryPort(Protocol):
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, ref, metadata, *, require_access): ...
    def read(self, project_id, record_id): ...


class HttpLocatorRecordApplicationService:
    def __init__(self, locators, artifacts, repository: LocatorRecordRepositoryPort):
        self.locators, self.artifacts, self.repository = locators, artifacts, repository

    def record(self, request: RunPlanLocatorQuery, *, invocation_id, recorded_at):
        request = RunPlanLocatorQuery.model_validate(request.model_dump(mode="json"))
        access = self.locators.authorization.scope(request.project_id)
        current = lambda: self.locators.authorization.require_current(access)
        with self.locators._session():
            self.locators._inputs(request)
            prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id,
                require_access=current)
            if prior is not None:
                view = self._read(request.project_id, prior["record_id"])
                if acceptance_digest(view["metadata"]) != acceptance_digest(prior):
                    raise RunPlanIntegrityError("locator replay cannot replace its independently recorded fact")
                return prior
            view = self.locators.inspect(request)
            plan = self.locators._inputs(request)
            payload = {"schema": LOCATOR_RECORD_SCHEMA, "project_id": request.project_id,
                "record_id": locator_record_identity(invocation_id), "invocation_id": invocation_id,
                "actor_id": access.actor_id, "recorded_at": recorded_at, "request": request.model_dump(mode="json"),
                "parents": {"plan_digest": plan["plan_digest"], **{key: plan["source_pin"][key] for key in
                    ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")}},
                "report": deepcopy(view["report"])}
            saved = self.locators.plans.read(request.project_id, request.run_plan_id)
            metadata = validate_locator_archive(payload, payload["request"], saved)
            self.locators.inventory.verify(plan, payload["report"]["inventory"], require_access=current)
            current()
            ref, digest = self.artifacts.put(request.project_id, payload)
            if digest != metadata["artifact_hash"]:
                raise RunPlanIntegrityError("locator archive write differs")

            def verify_before_commit():
                saved = self.locators.plans.read(request.project_id, request.run_plan_id)
                original = self.artifacts.read(request.project_id, ref, digest)
                if (acceptance_digest(original) != acceptance_digest(payload)
                        or acceptance_digest(validate_locator_archive(original, payload["request"], saved)) != acceptance_digest(metadata)):
                    raise RunPlanIntegrityError("locator original archive changed before commit")
                self.locators.inventory.verify(saved["artifact"]["plan"], original["report"]["inventory"], require_access=current)
                current()

            result = self.repository.record(request, payload, ref, metadata, require_access=verify_before_commit)
            current()
            return result

    def _read(self, project_id, record_id):
        access = self.locators.authorization.scope(project_id)
        current = lambda: self.locators.authorization.require_current(access)
        stored = self.repository.read(project_id, record_id)
        request = RunPlanLocatorQuery.model_validate(stored["request"])
        if request.project_id != project_id or stored["metadata"]["record_id"] != record_id:
            raise RunPlanIntegrityError("locator record read scope differs")
        self.locators._inputs(request)
        current()
        archive = self.artifacts.read(project_id, stored["artifact_ref"], stored["metadata"]["artifact_hash"])
        saved = self.locators.plans.read(project_id, request.run_plan_id)
        if acceptance_digest(validate_locator_archive(archive, stored["request"], saved)) != acceptance_digest(stored["metadata"]):
            raise RunPlanIntegrityError("locator metadata differs from its independently archived bytes")
        self.locators.inventory.verify(saved["artifact"]["plan"], archive["report"]["inventory"], require_access=current)
        current()
        return {"metadata": deepcopy(stored["metadata"]), "archive": archive, "historical_not_live": True}

    def read(self, project_id, record_id):
        with self.locators._session():
            return self._read(project_id, record_id)

    def receipt(self, project_id, record_id):
        return {"metadata": self.read(project_id, record_id)["metadata"], "historical_not_live": True}

    def authorize_receipts(self, values):
        if not 1 <= len(values) <= 128:
            raise RunPlanIntegrityError("locator receipt cohort exceeds its bound")
        accesses = {scope.project_id: self.locators.authorization.scope(scope.project_id) for scope, _ in values}
        with self.locators._session():
            for scope, receipt in values:
                if receipt is None:
                    if isinstance(scope, EnvironmentRecordQuery):
                        self._read(scope.project_id, scope.record_id)
                    else:
                        self.locators.require_receipt_inputs_access(scope)
                    continue
                if (type(receipt) is not dict or set(receipt) != {"metadata", "historical_not_live"}
                        or receipt["historical_not_live"] is not True or type(receipt["metadata"]) is not dict):
                    raise RunPlanIntegrityError("locator record receipt invalid")
                metadata = receipt["metadata"]
                view = self._read(scope.project_id, metadata.get("record_id"))
                if acceptance_digest(metadata) != acceptance_digest(view["metadata"]):
                    raise RunPlanIntegrityError("locator record receipt changed")
                if isinstance(scope, EnvironmentRecordQuery):
                    if scope.record_id != metadata["record_id"]:
                        raise RunPlanIntegrityError("locator history record rebound")
                elif any(metadata[key] != value for key, value in scope.model_dump(mode="json").items()):
                    raise RunPlanIntegrityError("locator history command rebound")
        for access in accesses.values():
            self.locators.authorization.require_current(access)
