"""Confirm and archive an original native inspection through independent ports."""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from ..operation_read_scope import OperationReadScope
from .run_plan_environments import RunPlanEnvironmentQuery
from .test_design_output import GenerationValue, Id
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.environment_observation_record import (
    ENVIRONMENT_RECORD_SCHEMA, environment_record_metadata, record_identity, validate_environment_archive,
)
from ...domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied, SourceAccessScope


class EnvironmentRecordQuery(GenerationValue):
    project_id: Id
    record_id: Id


class EnvironmentRecordRepositoryPort(Protocol):
    def committed(self, request, *, actor_id, invocation_id, require_access): ...
    def record(self, request, payload, ref, metadata, *, require_access): ...
    def read(self, project_id, record_id): ...


@dataclass(frozen=True)
class _CaseParentRead:
    request: RunPlanEnvironmentQuery
    record_id: str
    access: SourceAccessScope
    parents: tuple[dict, dict, dict]


class EnvironmentObservationRecordApplicationService:
    def __init__(self, inspections, artifacts, repository: EnvironmentRecordRepositoryPort):
        self.inspections, self.artifacts, self.repository = inspections, artifacts, repository
        self._case_parents = ContextVar("case_environment_verified_parent_read", default=None)

    def _read_session(self):
        operation = getattr(self.inspections.plans, "verified_read_session", None)
        return operation() if callable(operation) else nullcontext()

    def record(self, request: RunPlanEnvironmentQuery, *, invocation_id, recorded_at):
        request = RunPlanEnvironmentQuery.model_validate(request.model_dump(mode="json"))
        access = self.inspections._access(request.project_id)
        current = lambda: self.inspections.authorization.require_current(access)
        with self._read_session():
            # Verify original inputs and the independently confirmed command before Docker work.
            self.inspections.original_inputs(request)
            prior = self.repository.committed(request, actor_id=access.actor_id, invocation_id=invocation_id,
                require_access=current)
            if prior is not None:
                view = self._read(request.project_id, prior["record_id"])
                if view["metadata"] != prior:
                    raise RunPlanIntegrityError("committed environment record differs")
                current()
                return prior
            parents = self.inspections.original_inputs(request, current=True)
            observed = self.inspections.observe(request)
            plan, binding = observed["plan"], observed["binding"]
            if (plan, binding) != parents:
                raise RunPlanChanged("original inputs changed before environment archival")
            receipt, original = observed["receipt"], observed["observation"]
            payload = {"schema": ENVIRONMENT_RECORD_SCHEMA, "project_id": request.project_id,
                "record_id": record_identity(invocation_id), "invocation_id": invocation_id, "actor_id": access.actor_id,
                "recorded_at": recorded_at, "request": request.model_dump(mode="json"),
                "parents": {**{key: plan["metadata"][key] for key in ("plan_digest", "image_revision_id", "manifest_id")},
                    **{key: receipt[key] for key in ("environment_id", "operator_policy_digest", "target_artifact_hash")}},
                "observation": {"inventory": deepcopy(original.inventory), "inventory_hash": original.inventory_hash,
                    "observed_at": original.observed_at}}
            validate_environment_archive(payload, payload["request"], plan, binding)
            current()
            ref, digest = self.artifacts.put(request.project_id, payload)
            metadata = environment_record_metadata(payload)
            if digest != metadata["artifact_hash"]:
                raise RunPlanIntegrityError("environment archive write differs")

            def verify_before_commit():
                if self.inspections.original_inputs(request, current=True) != parents:
                    raise RunPlanChanged("original inputs changed before environment commit")
                archived = self.artifacts.read(request.project_id, ref, digest)
                validate_environment_archive(archived, payload["request"], plan, binding)
                if archived != payload:
                    raise RunPlanIntegrityError("original environment inventory changed before commit")
                current()

            value = self.repository.record(request, payload, ref, metadata, require_access=verify_before_commit)
            current()
            return value

    def _registered_observation(self, project_id, record_id, *, expected=None):
        access = self.inspections._access(project_id)
        stored = self.repository.read(project_id, record_id)
        request = RunPlanEnvironmentQuery.model_validate(stored["request"])
        if (request.project_id != project_id or stored["metadata"]["record_id"] != record_id
                or expected is not None and request != expected):
            raise RunPlanIntegrityError("environment record read scope differs")
        return access, stored, request

    def _verified_observation(self, access, stored, request, plan, binding):
        self.inspections.authorization.require_current(access)
        archive = self.artifacts.read(request.project_id, stored["artifact_ref"], stored["metadata"]["artifact_hash"])
        validate_environment_archive(archive, stored["request"], plan, binding)
        if environment_record_metadata(archive) != stored["metadata"]:
            raise RunPlanIntegrityError("environment metadata differs from the independently archived inventory")
        self.inspections.authorization.require_current(access)
        return {"metadata": deepcopy(stored["metadata"]), "archive": archive, "historical_not_live": True}

    def _read_with_parents(self, project_id, record_id, *, expected=None, current=False):
        access, stored, request = self._registered_observation(project_id, record_id, expected=expected)
        # Authorization of the complete original sources precedes private inventory bytes.
        plan, binding = self.inspections.original_inputs(request, **({"current": True} if current else {}))
        return self._verified_observation(access, stored, request, plan, binding), plan, binding

    def _read(self, project_id, record_id):
        return self._read_with_parents(project_id, record_id)[0]

    def read_with_plan(self, project_id, record_id):
        """Read the original archive, sharing its exact verified parent only within a case read."""
        with self._read_session():
            scope = self._case_parents.get()
            if scope is not None and scope.is_current:
                original = scope.value
                if (project_id, record_id) == (original.request.project_id, original.record_id):
                    access, stored, request = self._registered_observation(project_id, record_id, expected=original.request)
                    if access != original.access:
                        raise SourceAccessDenied("case environment original source access changed during verification")
                    before, plan, binding = original.parents
                    view = self._verified_observation(access, stored, request, plan, binding)
                    if view != before:
                        raise RunPlanIntegrityError("case environment archive changed during verification")
                    return view, deepcopy(plan)
            view, plan, _ = self._read_with_parents(project_id, record_id)
            return view, deepcopy(plan)

    def read_with_parents(self, expected: RunPlanEnvironmentQuery, record_id, *, current=False):
        """Verify one observation and its exact requested plan/build, without live target effects."""
        expected = RunPlanEnvironmentQuery.model_validate(expected.model_dump(mode="json"))
        with self._read_session():
            view, plan, binding = self._read_with_parents(expected.project_id, record_id, expected=expected, current=current)
            return view, deepcopy(plan), deepcopy(binding)

    def case_locator_plan(self, project_id, run_plan_id, artifact_hash, *, access):
        """Lend the exact case plan while its independent closing read is still owed."""
        scope = self._case_parents.get()
        if scope is None or not scope.is_current:
            raise RunPlanIntegrityError("locator requires an active original case parent read")
        parent = scope.value
        if (project_id, run_plan_id, artifact_hash) != (parent.request.project_id, parent.request.run_plan_id,
                parent.request.run_plan_artifact_hash):
            raise RunPlanIntegrityError("locator cannot adopt another case plan")
        if access != parent.access:
            raise SourceAccessDenied("locator original case source access changed")
        self.inspections.authorization.require_current(access)
        return deepcopy(parent.parents[1])

    @contextmanager
    def case_parent_read_session(self, expected: RunPlanEnvironmentQuery, record_id, *, current=False):
        """Bracket one case input resolution with independent full reads of common parents."""
        expected = RunPlanEnvironmentQuery.model_validate(expected.model_dump(mode="json"))
        access = self.inspections._access(expected.project_id)
        parents = self.read_with_parents(expected, record_id, current=current)
        self.inspections.authorization.require_current(access)
        scope = OperationReadScope(_CaseParentRead(expected, record_id, access, deepcopy(parents)))
        token = self._case_parents.set(scope)
        try:
            yield parents
        finally:
            scope.close()
            self._case_parents.reset(token)
        if self.read_with_parents(expected, record_id, current=current) != scope.value.parents:
            raise RunPlanChanged("original case plan, build or environment changed during verification")
        self.inspections.authorization.require_current(access)

    def read(self, project_id, record_id):
        with self._read_session():
            return self._read(project_id, record_id)

    def receipt(self, project_id, record_id):
        return {"metadata": self.read(project_id, record_id)["metadata"], "historical_not_live": True}

    def authorize_receipts(self, values):
        if not 1 <= len(values) <= 128:
            raise RunPlanIntegrityError("environment record receipts require a bounded cohort")
        accesses = {}
        with self._read_session():
            for scope, receipt in values:
                accesses.setdefault(scope.project_id, self.inspections._access(scope.project_id))
                if receipt is None:
                    if isinstance(scope, EnvironmentRecordQuery):
                        self._read(scope.project_id, scope.record_id)
                    else:
                        self.inspections.original_inputs(scope)
                    continue
                if type(receipt) is not dict or set(receipt) != {"metadata", "historical_not_live"} or receipt["historical_not_live"] is not True:
                    raise RunPlanIntegrityError("environment record receipt invalid")
                metadata = receipt["metadata"]
                if type(metadata) is not dict or not isinstance(metadata.get("record_id"), str):
                    raise RunPlanIntegrityError("environment record receipt lacks identity")
                view = self._read(scope.project_id, metadata["record_id"])
                if acceptance_digest({"metadata": view["metadata"], "historical_not_live": True}) != acceptance_digest(receipt):
                    raise RunPlanIntegrityError("environment record receipt differs from original fact")
                if isinstance(scope, EnvironmentRecordQuery):
                    if scope.record_id != metadata["record_id"]:
                        raise RunPlanIntegrityError("environment record query rebound")
                elif any(metadata[key] != value for key, value in scope.model_dump(mode="json").items()):
                    raise RunPlanIntegrityError("environment record command rebound")
            operation = getattr(self.inspections.authorization, "require_current_many", None)
            if callable(operation):
                operation(tuple(accesses.values()))
            else:
                for access in accesses.values():
                    self.inspections.authorization.require_current(access)
