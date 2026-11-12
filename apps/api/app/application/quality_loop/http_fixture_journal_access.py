"""Saved-plan binding for private fixture journals; never execution consent."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict
from typing import Protocol

from .execution_work_guard import work_poll
from .http_fixture_diagnostics import fixture_phase
from .http_fixtures import HttpFixtureLifecycleApplicationService
from .run_plan_environment_health import PinnedEnvironmentHealthPort
from .runner_port import AutomationRunnerCommand
from ...domain.quality_loop.environment_observation_record import validate_environment_envelope
from ...domain.quality_loop.native_environment import NativeEnvironmentInvalid
from ...domain.quality_loop.native_environment_health import NativeEnvironmentHealthObservation
from ...domain.quality_loop.run_plan import RunPlanChanged
from .run_plan_observation_archives import RunPlanObservationArchiveParent
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixture_target import native_fixture_environment
from ...domain.quality_loop.http_fixtures import (
    HttpFixtureInvalid, bind_run_plan_fixture, fixture_bindings, resolve_fixture_cleanup, validate_http_fixture_manifest,
)


class HttpFixtureSavedPlanAccessPort(Protocol):
    def verified_read_session(self): ...
    def require_scope(self, scope) -> dict: ...
    def command_with_parent(self, scope, phase, *, setup_receipt=None) -> tuple[dict, AutomationRunnerCommand]: ...
    def cleanup_commands_from_receipt(self, scope, setup_receipt) -> tuple[tuple[str, AutomationRunnerCommand], ...]: ...


class HttpFixtureExecutionArtifactPort(Protocol):
    def put(self, parent, scope, phase, command, execution): ...
    def read(self, parent, scope, phase, command, ref, digest): ...


class HttpFixtureEnvironmentReadPort(Protocol):
    def read(self, project_id, record_id) -> dict: ...
    def read_with_plan(self, project_id, record_id) -> tuple[dict, dict]: ...


class SavedRunPlanHttpFixtureAccess:
    def __init__(self, plans, parent: RunPlanObservationArchiveParent, manifest):
        self.plans = plans
        self.parent = RunPlanObservationArchiveParent.model_validate(parent.model_dump(mode="json"))
        self.manifest = validate_http_fixture_manifest(manifest)

    def verified_read_session(self):
        # Only immutable source proof is shared; the plan port rechecks ACLs,
        # review heads and current use on every call in this task/thread.
        reader = getattr(self.plans, "verified_read_session", None)
        return reader() if callable(reader) else nullcontext()

    def _original_environment(self, view, environment=None):
        return None

    def _scope_inputs(self, scope):
        return self.plans.read(scope.project_id, self.parent.run_plan_id), None

    def require_scope(self, scope):
        self._read_scope(scope)
        return deepcopy(self.parent.model_dump(mode="json"))

    def _read_scope(self, scope):
        return self._read_bound_scope(scope)[0]

    def _require_manifest_identity(self, scope):
        if (scope.project_id != self.parent.project_id or scope.parent_digest != self.parent.plan_digest
                or scope.case_id != self.manifest["case_id"]
                or scope.data_manifest_hash != acceptance_digest(self.manifest)):
            raise HttpFixtureInvalid("fixture scope differs from the original saved plan and manifest")

    def _read_bound_scope(self, scope):
        self._require_manifest_identity(scope)
        with self.verified_read_session():
            view, environment = self._scope_inputs(scope)
            try:
                metadata, artifact = view["metadata"], view["artifact"]
                if (metadata["project_id"] != scope.project_id or metadata["run_plan_id"] != self.parent.run_plan_id
                        or metadata["artifact_hash"] != self.parent.run_plan_artifact_hash
                        or metadata["plan_digest"] != scope.parent_digest
                        or artifact["project_id"] != scope.project_id or artifact["run_plan_id"] != self.parent.run_plan_id
                        or acceptance_digest(artifact) != self.parent.run_plan_artifact_hash):
                    raise HttpFixtureInvalid("fixture original saved plan archive was rebound")
                pin = bind_run_plan_fixture(artifact["plan"], self.manifest)
                if pin["project_id"] != scope.project_id or pin["plan_digest"] != scope.parent_digest:
                    raise HttpFixtureInvalid("fixture plan body differs from its original project and digest")
                selection = artifact["plan"]["selection"]
                if (selection["environment"]["environment_id"] != scope.environment_id
                        or selection["environment"]["base_url"] != "http://127.0.0.1:8080"
                        or selection["target_build"]["artifact_hash"] != scope.artifact_hash):
                    raise HttpFixtureInvalid("fixture target differs from the original RunPlan selection")
                original = self._original_environment(view, environment)
                inventory_hash = (original["metadata"]["inventory_hash"] if original is not None
                                  else selection["environment"]["inventory_hash"])
                if inventory_hash != scope.inventory_hash:
                    raise HttpFixtureInvalid("fixture target differs from the original RunPlan selection")
            except (KeyError, TypeError, UnicodeError, RecursionError):
                raise HttpFixtureInvalid("fixture original saved plan cannot be verified") from None
        return view, original

    def command(self, scope, phase, *, setup_receipt=None):
        return self.command_with_parent(scope, phase, setup_receipt=setup_receipt)[1]

    def command_with_parent(self, scope, phase, *, setup_receipt=None):
        parent = self.require_scope(scope)
        return parent, self._command_for_phase(scope, phase, setup_receipt)

    def cleanup_commands_from_receipt(self, scope, setup_receipt):
        """Derive history lookup keys from a verified receipt; this grants no access or dispatch."""
        self._require_manifest_identity(scope)
        phases = ("cleanup:" + binding for binding in fixture_bindings(self.manifest))
        return tuple((phase, self._command_for_phase(scope, phase, setup_receipt)) for phase in phases)

    def _command_for_phase(self, scope, phase, setup_receipt):
        if phase == "setup":
            steps = tuple(self.manifest["setup_steps"])
        elif type(phase) is str and phase.startswith("cleanup:"):
            binding = phase[len("cleanup:"):]
            if binding not in fixture_bindings(self.manifest) or type(setup_receipt) is not dict:
                raise HttpFixtureInvalid("cleanup needs an original verified setup capture")
            resources = {item["binding_id"]: item["value"] for item in setup_receipt["bindings"]}
            if binding not in resources:
                raise HttpFixtureInvalid("cleanup capture was not observed in the original setup")
            steps = resolve_fixture_cleanup(self.manifest, binding, resources[binding])
        else:
            raise HttpFixtureInvalid("fixture phase is outside the original manifest")
        return HttpFixtureLifecycleApplicationService._command(scope, phase, deepcopy(steps))


class NativeSavedRunPlanHttpFixtureAccess(SavedRunPlanHttpFixtureAccess):
    """An explicit original observation, never latest inventory or legacy promotion."""
    def __init__(self, plans, parent, manifest, environment_records: HttpFixtureEnvironmentReadPort,
                 native_environment, *, environment_health: PinnedEnvironmentHealthPort = None):
        super().__init__(plans, parent, manifest)
        if (environment_records is None or type(native_environment) is not dict
                or set(native_environment) != {"record_id", "artifact_hash", "inventory_hash", "operator_policy_digest"}):
            raise HttpFixtureInvalid("native fixture access needs its exact independently recorded environment")
        self.environment_records = environment_records
        self.native_environment = deepcopy(native_environment)
        self.environment_health = environment_health

    def require_dispatch_scope(self, scope):
        view = self._read_scope(scope)
        if view.get("current_use", {}).get("inputs_current") is not True:
            raise RunPlanChanged("native fixture dispatch requires current original inputs and script review")
        return deepcopy(self.parent.model_dump(mode="json"))

    def _scope_inputs(self, scope):
        reader = getattr(self.environment_records, "read_with_plan", None)
        if not callable(reader):
            return super()._scope_inputs(scope)
        try:
            environment, plan = reader(scope.project_id, self.native_environment["record_id"])
            if type(environment) is not dict or type(plan) is not dict:
                raise HttpFixtureInvalid("native fixture parent port must return the complete verified pair")
            return plan, environment
        except (KeyError, TypeError, ValueError, AttributeError, UnicodeError) as exc:
            if isinstance(exc, HttpFixtureInvalid):
                raise
            raise HttpFixtureInvalid("native fixture original parent cannot be verified") from exc

    def _original_environment(self, view, environment=None):
        try:
            original = environment if environment is not None else self.environment_records.read(
                self.parent.project_id, self.native_environment["record_id"])
            pin = native_fixture_environment(view, self.manifest, original)
            if acceptance_digest(pin) != acceptance_digest(self.native_environment):
                raise HttpFixtureInvalid("native fixture journal cannot substitute a different observed instance")
            return original
        except (KeyError, TypeError, ValueError, AttributeError, UnicodeError) as exc:
            if isinstance(exc, HttpFixtureInvalid):
                raise
            raise HttpFixtureInvalid("native fixture original environment cannot be verified") from exc

    def require_original_dispatch(self, scope, phase, command, *, setup_receipt, require_work):
        """Verify the exact manifest command and return the parent already checked by preflight."""
        expected = self._command_for_phase(scope, phase, setup_receipt)
        if not isinstance(command, AutomationRunnerCommand) or command != expected:
            raise HttpFixtureInvalid("fixture dispatch command is outside the original manifest")
        self.require_dispatch(scope, phase, command, require_work=require_work)
        return self.parent.model_dump(mode="json")

    def require_dispatch(self, scope, phase, command, *, require_work):
        """Transient live gate before a new claim; historical reads never probe Docker."""
        current = work_poll(require_work)
        current()
        if self.environment_health is None:
            raise HttpFixtureInvalid("native fixture dispatch requires an explicit live target health port")
        if (type(phase) is not str or not (phase == "setup" or
                phase.startswith("cleanup:") and phase[8:] in fixture_bindings(self.manifest))):
            raise HttpFixtureInvalid("native fixture dispatch phase is outside the original manifest")
        if not isinstance(command, AutomationRunnerCommand):
            raise HttpFixtureInvalid("native fixture dispatch requires a typed original command")
        expected = HttpFixtureLifecycleApplicationService._command(scope, phase, command.steps)
        if acceptance_digest(asdict(command)) != acceptance_digest(asdict(expected)):
            raise HttpFixtureInvalid("native fixture dispatch command differs from its original scope")
        with fixture_phase("journal_preflight_parent_before"):
            before, original = self._read_bound_scope(scope)
            if before.get("current_use", {}).get("inputs_current") is not True:
                raise RunPlanChanged("native fixture dispatch requires current original inputs and script review")
            pinned = validate_environment_envelope(original["archive"])
        with fixture_phase("journal_preflight_live_health"):
            current()
            value = self.environment_health.probe_pinned_inventory(pinned, require_work=require_work)
            current()
            if not isinstance(value, NativeEnvironmentHealthObservation):
                raise NativeEnvironmentInvalid("native fixture preflight requires the exact original typed health observation")
            observed = NativeEnvironmentHealthObservation(deepcopy(value.inventory), value.inventory_hash,
                deepcopy(value.checks), value.observed_at)
            if (observed.inventory_hash != scope.inventory_hash
                    or acceptance_digest(observed.inventory) != acceptance_digest(original["archive"]["observation"]["inventory"])
                    or not observed.dependency_health_verified or not observed.target_health_verified):
                raise NativeEnvironmentInvalid("native fixture original target epoch or dependency health is no longer valid")
        with fixture_phase("journal_preflight_parent_after"):
            after, latest_environment = self._read_bound_scope(scope)
            if (after.get("current_use", {}).get("inputs_current") is not True
                    or acceptance_digest(after) != acceptance_digest(before)
                    or latest_environment != original):
                raise RunPlanChanged("native fixture original inputs changed during live preflight")
        current()
