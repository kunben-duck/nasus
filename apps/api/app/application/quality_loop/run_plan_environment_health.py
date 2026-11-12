"""Internal preflight port: verify original current inputs, never approve execution."""
from copy import deepcopy
from typing import Callable, Protocol

from .execution_work_guard import ExecutionWorkGuard, work_poll
from .run_plan_environments import RunPlanEnvironmentQuery
from ...domain.quality_loop.native_environment import NativeEnvironmentInvalid, NativeEnvironmentObservation
from ...domain.quality_loop.native_environment_health import NativeEnvironmentHealthObservation
from ...domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError


class NativeTargetHealthPort(Protocol):
    def policy_digest(self, project_id: str, environment_id: str, *, require_work: Callable[[], None]) -> str: ...
    def inspect_health(self, project_id: str, environment_id: str, artifact_hash: str,
                       *, require_work: Callable[[], None]) -> NativeEnvironmentHealthObservation: ...


class PinnedEnvironmentHealthPort(Protocol):
    def probe_pinned_inventory(self, original: NativeEnvironmentObservation,
                               *, require_work: Callable[[], None]) -> NativeEnvironmentHealthObservation: ...


class RunPlanEnvironmentHealthApplicationService:
    def __init__(self, original_inputs, health: NativeTargetHealthPort):
        self.original_inputs, self.health = original_inputs, health

    def _guards(self, project_id, require_work):
        check_work = work_poll(require_work)
        if check_work is not None:
            check_work()
        access = self.original_inputs._access(project_id)

        def current():
            if check_work is not None:
                check_work()
            self.original_inputs.authorization.require_current(access)
            if check_work is not None:
                check_work()

        def probe():
            require_work.poll()
            self.original_inputs.authorization.require_current(access)

        return current, probe if isinstance(require_work, ExecutionWorkGuard) else current

    def _probe(self, project_id, environment_id, target_hash, expected_policy, *, check_probe):
        policy = self.health.policy_digest(project_id, environment_id, require_work=check_probe)
        if policy != expected_policy:
            raise RunPlanChanged("health preflight operator policy differs from original inputs")
        value = self.health.inspect_health(project_id, environment_id, target_hash, require_work=check_probe)
        if not isinstance(value, NativeEnvironmentHealthObservation):
            raise RunPlanIntegrityError("health preflight requires an original typed observation")
        observed = NativeEnvironmentHealthObservation(deepcopy(value.inventory), value.inventory_hash,
            deepcopy(value.checks), value.observed_at)
        if (observed.inventory["project_id"] != project_id
                or observed.inventory["environment_id"] != environment_id
                or observed.inventory["operator_policy_digest"] != policy
                or observed.inventory["artifact_hash"] != target_hash):
            raise RunPlanIntegrityError("health preflight observation differs from original target")
        if self.health.policy_digest(project_id, environment_id, require_work=check_probe) != policy:
            raise RunPlanChanged("health preflight original inputs changed during inspection")
        return observed

    def probe_pinned_inventory(self, original: NativeEnvironmentObservation, *, require_work: Callable[[], None]):
        """Internal read-only probe; caller verifies the original parent before and after."""
        if not isinstance(original, NativeEnvironmentObservation):
            raise RunPlanIntegrityError("health preflight requires a typed original inventory")
        original = NativeEnvironmentObservation(deepcopy(original.inventory), original.inventory_hash, original.observed_at)
        inventory = original.inventory
        if inventory["namespace_origin"] != "http://127.0.0.1:8080":
            raise NativeEnvironmentInvalid("health preflight requires the exact original owned local target")
        current, check_probe = self._guards(inventory["project_id"], require_work)
        current()
        observed = self._probe(inventory["project_id"], inventory["environment_id"], inventory["artifact_hash"],
            inventory["operator_policy_digest"], check_probe=check_probe)
        if observed.inventory_hash != original.inventory_hash or observed.inventory != inventory:
            raise NativeEnvironmentInvalid("health preflight target epoch differs from the original inventory")
        current()
        return observed

    def inspect(self, request: RunPlanEnvironmentQuery, *, require_work: Callable[[], None] = None):
        request = RunPlanEnvironmentQuery.model_validate(request.model_dump(mode="json"))
        current, check_probe = self._guards(request.project_id, require_work)
        current()
        plan, binding = self.original_inputs.original_inputs(request, current=True)
        current()
        declaration = plan["artifact"]["plan"]["selection"]["environment"]
        if declaration["kind"] != "local" or declaration["base_url"] != "http://127.0.0.1:8080":
            raise NativeEnvironmentInvalid("health preflight requires the exact original owned local target")
        observed = self._probe(request.project_id, declaration["environment_id"], binding["metadata"]["target_artifact_hash"],
            declaration["inventory_hash"], check_probe=check_probe)
        if self.original_inputs.original_inputs(request, current=True) != (plan, binding):
            raise RunPlanChanged("health preflight original inputs changed during inspection")
        current()
        return {"request": request.model_dump(mode="json"), "observation": observed,
            "dependency_health_verified": observed.dependency_health_verified,
            "target_health_verified": observed.target_health_verified, "historical_not_live": True,
            "execution_authorized": False, "environment_fully_verified": False, "fixtures_verified": False,
            "locators_verified": False, "business_coverage_verified": False,
            "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0}
