"""Internal preflight port: verify original current inputs, never approve execution."""
from copy import deepcopy
from typing import Callable, Protocol

from .run_plan_environments import RunPlanEnvironmentQuery
from ...domain.quality_loop.native_environment import NativeEnvironmentInvalid
from ...domain.quality_loop.native_environment_health import NativeEnvironmentHealthObservation
from ...domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError


class NativeTargetHealthPort(Protocol):
    def policy_digest(self, project_id: str, environment_id: str, *, require_work: Callable[[], None]) -> str: ...
    def inspect_health(self, project_id: str, environment_id: str, artifact_hash: str,
                       *, require_work: Callable[[], None]) -> NativeEnvironmentHealthObservation: ...


class RunPlanEnvironmentHealthApplicationService:
    def __init__(self, original_inputs, health: NativeTargetHealthPort):
        self.original_inputs, self.health = original_inputs, health

    def inspect(self, request: RunPlanEnvironmentQuery, *, require_work: Callable[[], None] = None):
        request = RunPlanEnvironmentQuery.model_validate(request.model_dump(mode="json"))
        if require_work is not None:
            require_work()
        access = self.original_inputs._access(request.project_id)

        def current():
            if require_work is not None:
                require_work()
            self.original_inputs.authorization.require_current(access)
            if require_work is not None:
                require_work()

        current()
        plan, binding = self.original_inputs.original_inputs(request, current=True)
        current()
        declaration = plan["artifact"]["plan"]["selection"]["environment"]
        if declaration["kind"] != "local" or declaration["base_url"] != "http://127.0.0.1:8080":
            raise NativeEnvironmentInvalid("health preflight requires the exact original owned local target")
        environment_id = declaration["environment_id"]
        policy = self.health.policy_digest(request.project_id, environment_id, require_work=current)
        if policy != declaration["inventory_hash"]:
            raise RunPlanChanged("health preflight operator policy differs from original inputs")
        target_hash = binding["metadata"]["target_artifact_hash"]
        value = self.health.inspect_health(request.project_id, environment_id, target_hash, require_work=current)
        if not isinstance(value, NativeEnvironmentHealthObservation):
            raise RunPlanIntegrityError("health preflight requires an original typed observation")
        observed = NativeEnvironmentHealthObservation(deepcopy(value.inventory), value.inventory_hash,
            deepcopy(value.checks), value.observed_at)
        if (observed.inventory["project_id"] != request.project_id
                or observed.inventory["environment_id"] != environment_id
                or observed.inventory["operator_policy_digest"] != policy
                or observed.inventory["artifact_hash"] != target_hash):
            raise RunPlanIntegrityError("health preflight observation differs from original target")
        if (self.health.policy_digest(request.project_id, environment_id, require_work=current) != policy
                or self.original_inputs.original_inputs(request, current=True) != (plan, binding)):
            raise RunPlanChanged("health preflight original inputs changed during inspection")
        current()
        return {"request": request.model_dump(mode="json"), "observation": observed,
            "dependency_health_verified": observed.dependency_health_verified,
            "target_health_verified": observed.target_health_verified, "historical_not_live": True,
            "execution_authorized": False, "environment_fully_verified": False, "fixtures_verified": False,
            "locators_verified": False, "business_coverage_verified": False,
            "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0}
