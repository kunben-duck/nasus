"""Fenced original-operation worker; canonical lifecycle is a separate use case."""
from copy import deepcopy
from dataclasses import dataclass
from threading import Event
from typing import Literal, Protocol
from uuid import uuid4

from .http_fixture_dispatch_consent import HttpFixtureDispatchConsent
from .http_fixtures import HttpFixtureScope
from .http_fixture_work import run_with_http_fixture_work
from .run_plan_observation_archives import RunPlanObservationArchiveParent
from .test_design_output import Digest, GenerationValue, Id
from .worker_threads import run_worker_thread
from .http_fixture_commands import HttpFixtureCommandAuthority
from .http_fixture_diagnostics import fixture_phase
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid, validate_http_fixture_manifest


class HttpFixtureExecutionSelection(GenerationValue):
    project_id: Id
    grant_id: Id
    grant_digest: Digest
    operation: Literal["setup", "cleanup"]


class HttpFixtureExecutionStopped(RuntimeError):
    pass


class _NativeEnvironmentPin(GenerationValue):
    record_id: Id
    artifact_hash: Digest
    inventory_hash: Digest
    operator_policy_digest: Digest


@dataclass(frozen=True)
class HttpFixtureExecutionInputs:
    selection: HttpFixtureExecutionSelection
    scope: HttpFixtureScope
    parent: RunPlanObservationArchiveParent
    manifest: dict
    native_environment: dict
    consent: HttpFixtureDispatchConsent
    access_scope: object

    def __post_init__(self):
        selection = HttpFixtureExecutionSelection.model_validate(self.selection.model_dump(mode="json"))
        parent = RunPlanObservationArchiveParent.model_validate(self.parent.model_dump(mode="json"))
        manifest = validate_http_fixture_manifest(deepcopy(self.manifest))
        try:
            native = _NativeEnvironmentPin.model_validate(deepcopy(self.native_environment)).model_dump(mode="json")
        except ValueError as exc:
            raise HttpFixtureInvalid("fixture worker requires an exact typed original native environment pin") from exc
        if (not isinstance(self.scope, HttpFixtureScope) or not isinstance(self.consent, HttpFixtureDispatchConsent)
                or parent.project_id != selection.project_id or self.scope.project_id != selection.project_id
                or self.scope.parent_digest != parent.plan_digest or self.scope.case_id != manifest["case_id"]
                or self.scope.data_manifest_hash != acceptance_digest(manifest)
                or self.consent.scope != self.scope or self.consent.operation != selection.operation
                or self.consent.grant_id != selection.grant_id or self.consent.grant_digest != selection.grant_digest
                or type(native) is not dict or set(native) != {"record_id", "artifact_hash", "inventory_hash", "operator_policy_digest"}
                or native["inventory_hash"] != self.scope.inventory_hash):
            raise HttpFixtureInvalid("fixture worker inputs differ from their complete original consent and parent")
        # Copy mutable source payloads before crossing an asynchronous boundary.
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "parent", parent)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "native_environment", native)


@dataclass(frozen=True)
class HttpFixtureWorkerRuntime:
    lifecycle: object
    repository: object
    lease: object


class HttpFixtureExecutionRuntimePort(Protocol):
    def create(self, inputs, *, owner_id, require_current, command_authority=None) -> HttpFixtureWorkerRuntime: ...
    def history(self, inputs, *, require_current, original_setup=None, include_cleanup=False): ...


class HttpFixtureExecutionApplicationService:
    """Execute one original operation; never turn fixture results into coverage."""
    def __init__(self, grants, runtimes: HttpFixtureExecutionRuntimePort):
        self.grants, self.runtimes = grants, runtimes

    async def execute(self, selection, *, require_current, renew_seconds=15, command_authority=None):
        selection = HttpFixtureExecutionSelection.model_validate(selection.model_dump(mode="json"))
        if command_authority is not None:
            command_authority = HttpFixtureCommandAuthority.model_validate(command_authority.model_dump(mode="json"))
        stopped = Event()

        def current():
            if stopped.is_set():
                raise HttpFixtureExecutionStopped("fixture worker has stopped; no further dispatch or commit")
            require_current()
            if stopped.is_set():
                raise HttpFixtureExecutionStopped("fixture worker stopped during authorization")

        try:
            def resolve():
                current()
                inputs = self.grants.execution_inputs(selection, live=True)
                current()
                return inputs

            with fixture_phase("execution_inputs"):
                inputs = await run_worker_thread(resolve, on_cancel=stopped.set)
            options = {"command_authority": command_authority} if command_authority is not None else {}
            with fixture_phase("execution_runtime"):
                runtime = await run_worker_thread(lambda: self.runtimes.create(inputs, owner_id=uuid4().hex,
                    require_current=current, **options), on_cancel=stopped.set)

            async def operate(require_work):
                def run():
                    current()
                    operation = runtime.lifecycle.prepare if selection.operation == "setup" else runtime.lifecycle.cleanup
                    result = operation(inputs.scope, deepcopy(inputs.manifest), require_work=require_work)
                    current()
                    return result
                return await run_worker_thread(run, on_cancel=stopped.set)

            with fixture_phase("execution_operation"):
                return await run_with_http_fixture_work(runtime.repository, runtime.lease, operate,
                    require_current=current, renew_seconds=renew_seconds)
        finally:
            stopped.set()

    def read(self, selection, *, require_current):
        """Read the original journal after expiry without creating a lease or HTTP job."""
        selection = HttpFixtureExecutionSelection.model_validate(selection.model_dump(mode="json"))
        require_current()
        inputs = self.grants.execution_inputs(selection, live=False)
        result = self.runtimes.history(inputs, require_current=require_current)
        require_current()
        return result
