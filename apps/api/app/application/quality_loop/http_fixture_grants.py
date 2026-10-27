"""Separate preparation/cleanup consent; never bypass live target or worker gates."""
from dataclasses import asdict, dataclass
from typing import Literal, Optional, Protocol

from pydantic import Field, StrictInt, model_serializer, model_validator

from .environment_observation_records import EnvironmentRecordQuery
from .http_fixtures import HttpFixtureScope
from .http_fixture_dispatch_consent import HttpFixtureDispatchConsent
from .http_fixture_diagnostics import fixture_phase
from .test_design_output import Digest, GenerationValue, Id
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixture_grant import NATIVE_GRANT_SCHEMA, validate_grant_request, grant_metadata
from ...domain.quality_loop.http_fixture_target import native_fixture_environment
from ...domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied


class HttpFixtureGrantRequest(GenerationValue):
    project_id: Id
    recipe_id: Id
    recipe_artifact_hash: Digest
    attempt_id: Id
    operation: Literal["setup", "cleanup"]
    timeout_ms: StrictInt = Field(ge=1000, le=120000)
    policy_revision: Optional[Literal["nasus.http-fixture-grant.v2"]] = None
    environment_record_id: Optional[Id] = None
    environment_record_artifact_hash: Optional[Digest] = None

    @model_serializer(mode="wrap")
    def preserve_original_v1(self, handler):
        value = handler(self)
        if self.policy_revision is None:
            for key in ("policy_revision", "environment_record_id", "environment_record_artifact_hash"):
                value.pop(key, None)
        return value

    @model_validator(mode="after")
    def exact_scope(self):
        native = self.policy_revision == NATIVE_GRANT_SCHEMA
        if (native and (self.environment_record_id is None or self.environment_record_artifact_hash is None)
                or not native and (self.environment_record_id is not None or self.environment_record_artifact_hash is not None)):
            raise ValueError("native fixture consent requires an explicit complete environment record pair")
        validate_grant_request(self.model_dump(mode="json"))
        return self


class HttpFixtureGrantRepositoryPort(Protocol):
    def issue(self, request, scope, source_scope_digest, *, actor_id, invocation_id, require_access, native_environment=None): ...
    def read(self, project_id, record_id): ...
    def require_live(self, project_id, record_id, *, actor_id, scope, operation, source_scope_digest): ...


@dataclass(frozen=True)
class _VerifiedGrantInputs:
    metadata: dict
    request: HttpFixtureGrantRequest
    scope: HttpFixtureScope
    native_environment: Optional[dict]
    recipe: dict


class HttpFixtureGrantApplicationService:
    def __init__(self, recipes, repository: HttpFixtureGrantRepositoryPort, *, environment_records=None):
        self.recipes, self.repository = recipes, repository
        self.authorization = recipes.authorization
        self.environment_records = environment_records

    def _access(self, project_id):
        access = self.authorization.scope(project_id)
        if access.effective_project_role not in {"project_admin", "platform_admin"}:
            raise SourceAccessDenied("fixture operation consent requires a current project administrator")
        return access

    def _resolved_inputs(self, request, *, current=False):
        scope, native, _ = self._resolved_inputs_with_recipe(request, current=current)
        return scope, native

    def _resolved_inputs_with_recipe(self, request, *, current=False):
        read_with_plan = getattr(self.recipes, "read_with_plan", None)
        with fixture_phase("grant_recipe_parent"):
            if callable(read_with_plan):
                recipe, saved = read_with_plan(request.project_id, request.recipe_id)
            else:
                recipe = self.recipes.read(request.project_id, request.recipe_id)
                original = recipe["archive"]["request"]
                saved = self.recipes.plans.read(request.project_id, original["run_plan_id"])
        if recipe["metadata"]["artifact_hash"] != request.recipe_artifact_hash:
            raise RunPlanIntegrityError("fixture consent cannot replace the original registered definition")
        original = recipe["archive"]["request"]
        if (saved["metadata"]["project_id"] != request.project_id
                or saved["metadata"]["run_plan_id"] != original["run_plan_id"]
                or saved["metadata"]["artifact_hash"] != original["run_plan_artifact_hash"]):
            raise RunPlanIntegrityError("fixture consent lost its original verified RunPlan")
        if current and request.operation == "setup" and saved["current_use"]["inputs_current"] is not True:
            raise RunPlanChanged("fixture preparation inputs changed; inspect a new original plan")
        plan = saved["artifact"]["plan"]
        selection = plan["selection"]
        if selection["environment"]["base_url"] != "http://127.0.0.1:8080":
            raise RunPlanIntegrityError("fixture consent is restricted to the original owned target protocol")
        native = None
        inventory_hash = selection["environment"]["inventory_hash"]
        if request.policy_revision == NATIVE_GRANT_SCHEMA:
            if self.environment_records is None:
                raise RunPlanIntegrityError("original native environment reader is required; no legacy fallback")
            with fixture_phase("grant_environment_record"):
                view = self.environment_records.read(request.project_id, request.environment_record_id)
            native = native_fixture_environment(saved, original["manifest"], view)
            if (native["record_id"] != request.environment_record_id
                    or native["artifact_hash"] != request.environment_record_artifact_hash):
                raise RunPlanIntegrityError("native fixture consent environment record was rebound")
            inventory_hash = native["inventory_hash"]
        scope = HttpFixtureScope(project_id=request.project_id, attempt_id=request.attempt_id,
            case_id=recipe["metadata"]["case_id"], parent_digest=plan["plan_digest"],
            data_manifest_hash=recipe["metadata"]["data_manifest_hash"],
            environment_id=selection["environment"]["environment_id"],
            artifact_hash=selection["target_build"]["artifact_hash"],
            inventory_hash=inventory_hash, timeout_ms=request.timeout_ms)
        self.authorization.require_current(self._access(request.project_id))
        return scope, native, recipe

    def _inputs(self, request, *, current=False):
        return self._resolved_inputs(request, current=current)[0]

    def issue(self, request, *, invocation_id):
        request = HttpFixtureGrantRequest.model_validate(request.model_dump(mode="json"))
        access = self._access(request.project_id)
        with self.recipes.verified_read_session():
            scope, native = self._resolved_inputs(request, current=True)

            def require_access():
                if self._resolved_inputs(request, current=True) != (scope, native):
                    raise RunPlanIntegrityError("fixture consent original scope changed before commit")
                self.authorization.require_current(access)

            options = {"native_environment": native} if native is not None else {}
            result = self.repository.issue(request, scope, access.fingerprint, actor_id=access.actor_id,
                invocation_id=invocation_id, require_access=require_access, **options)
            require_access()
            return result

    def read(self, project_id, record_id):
        original = self._read_with_inputs(project_id, record_id)
        return {"metadata": original.metadata, "historical_not_live": True}

    def _read_with_inputs(self, project_id, record_id, *, current=False):
        access = self._access(project_id)
        with self.recipes.verified_read_session():
            payload = self.repository.read(project_id, record_id)
            metadata = grant_metadata(payload)
            request = HttpFixtureGrantRequest.model_validate(payload["request"])
            scope, native, recipe = self._resolved_inputs_with_recipe(request, current=current)
            if (payload["project_id"] != project_id or payload["record_id"] != record_id
                    or acceptance_digest(asdict(scope)) != metadata["scope_digest"]
                    or acceptance_digest(native) != acceptance_digest(payload.get("native_environment"))):
                raise RunPlanIntegrityError("fixture grant original scope differs from the complete private recipe")
            self.authorization.require_current(access)
            return _VerifiedGrantInputs(metadata, request, scope, native, recipe)

    def require_operation(self, project_id, record_id, scope, operation):
        """Dispatch must additionally verify target, lease and original journal claims."""
        with self.recipes.verified_read_session():
            access = self._access(project_id)
            original = self._read_with_inputs(project_id, record_id, current=True)
            value, request = original.metadata, original.request
            if (not isinstance(scope, HttpFixtureScope) or type(operation) is not str
                    or operation != request.operation or original.scope != scope
                    or value["actor_id"] != access.actor_id or value["source_scope_digest"] != access.fingerprint):
                raise SourceAccessDenied("fixture grant is not this actor's exact current operation and scope")
            with fixture_phase("grant_live_permission"):
                self.repository.require_live(project_id, record_id, actor_id=access.actor_id, scope=scope,
                    operation=operation, source_scope_digest=access.fingerprint)
            self.authorization.require_current(access)
            return value

    def dispatch_consent(self, project_id, record_id, scope, operation):
        value = self.require_operation(project_id, record_id, scope, operation)
        return HttpFixtureDispatchConsent(grant_id=value["record_id"], grant_digest=value["grant_digest"],
            actor_id=value["actor_id"], source_scope_digest=value["source_scope_digest"], scope=scope, operation=operation)

    def execution_inputs(self, selection, *, live):
        """Resolve complete original native inputs; historical reads grant no new work."""
        from .http_fixture_execution import HttpFixtureExecutionInputs, HttpFixtureExecutionSelection
        from .run_plan_observation_archives import RunPlanObservationArchiveParent
        selection = HttpFixtureExecutionSelection.model_validate(selection.model_dump(mode="json"))
        with self.recipes.verified_read_session():
            access = self._access(selection.project_id)
            original_inputs = self._read_with_inputs(selection.project_id, selection.grant_id, current=live)
            metadata = original_inputs.metadata
            if (metadata["schema"] != NATIVE_GRANT_SCHEMA or metadata["grant_digest"] != selection.grant_digest
                    or metadata["operation"] != selection.operation):
                raise RunPlanIntegrityError("fixture worker needs its exact original native operation permission")
            scope, native = original_inputs.scope, original_inputs.native_environment
            consent = HttpFixtureDispatchConsent(grant_id=selection.grant_id, grant_digest=metadata["grant_digest"],
                actor_id=metadata["actor_id"], source_scope_digest=metadata["source_scope_digest"],
                scope=scope, operation=selection.operation)
            if live:
                # Dispatch independently rechecks the complete current inputs and PG permission.
                if consent != self.dispatch_consent(selection.project_id, selection.grant_id, scope, selection.operation):
                    raise RunPlanIntegrityError("fixture permission changed before worker input resolution")
            recipe = original_inputs.recipe
            original = recipe["archive"]["request"]
            parent = RunPlanObservationArchiveParent(project_id=selection.project_id,
                run_plan_id=original["run_plan_id"], run_plan_artifact_hash=original["run_plan_artifact_hash"],
                plan_digest=scope.parent_digest)
            self.authorization.require_current(access)
            return HttpFixtureExecutionInputs(selection, scope, parent, original["manifest"], native, consent, access)

    def inspect_history_request(self, request):
        """Verify a saved command's inputs without issuing or renewing a grant."""
        request = HttpFixtureGrantRequest.model_validate(request.model_dump(mode="json"))
        with self.recipes.verified_read_session():
            access = self._access(request.project_id)
            self._resolved_inputs(request, current=False)
            self.authorization.require_current(access)

    def history_request(self, project_id, grant_id):
        """Return the exact verified original selection through an application port."""
        with self.recipes.verified_read_session():
            access = self._access(project_id)
            metadata = self.read(project_id, grant_id)["metadata"]
            original = self.repository.read(project_id, grant_id)
            if grant_metadata(original) != metadata:
                raise RunPlanIntegrityError("fixture history cannot replace the original grant")
            request = HttpFixtureGrantRequest.model_validate(original["request"])
            self.authorization.require_current(access)
            return request

    def authorize_receipts(self, values):
        if not 1 <= len(values) <= 128:
            raise RunPlanIntegrityError("fixture grant receipt cohort exceeds its bound")
        for scope, receipt in values:
            if receipt is None:
                if isinstance(scope, EnvironmentRecordQuery):
                    self.read(scope.project_id, scope.record_id)
                else:
                    self._access(scope.project_id)
                    self._inputs(scope)
                continue
            if type(receipt) is not dict or set(receipt) != {"metadata", "historical_not_live"} or receipt["historical_not_live"] is not True:
                raise RunPlanIntegrityError("fixture grant receipt invalid")
            original = self.read(scope.project_id, receipt["metadata"]["record_id"])
            if acceptance_digest(original) != acceptance_digest(receipt):
                raise RunPlanIntegrityError("fixture grant receipt cannot replace original consent")
            if isinstance(scope, EnvironmentRecordQuery):
                if scope.record_id != original["metadata"]["record_id"]:
                    raise RunPlanIntegrityError("fixture grant receipt identity differs")
            else:
                payload = self.repository.read(scope.project_id, original["metadata"]["record_id"])
                if acceptance_digest(payload["request"]) != acceptance_digest(scope.model_dump(mode="json")):
                    raise RunPlanIntegrityError("fixture grant command input was rebound")
