"""Inspect a saved plan's original build through ports, never deploy or dispatch it."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal, Protocol, Tuple

from pydantic import Field, StrictInt, StrictStr, model_validator

from .native_environment_ports import NativeTargetEnvironmentPort
from .test_design_output import GenerationValue, Id, Digest
from ...domain.quality_loop.native_environment import NativeEnvironmentInvalid, NativeEnvironmentObservation
from ...domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied


RUN_PLAN_ENVIRONMENT_QUERY_TOOL = "query.quality.run_plan_environment"
ENVIRONMENT_RECEIPT_SCHEMA = "nasus.run-plan-environment-observation.v1"
REMAINING_ENVIRONMENT_GATES = ["network_egress_and_host_denial", "dependency_health", "fixture_setup_cleanup_verification",
    "locator_verification", "independent_execution_authorization", "canonical_run_plan_execution"]


class RunPlanEnvironmentQuery(GenerationValue):
    project_id: Id
    run_plan_id: Id
    run_plan_artifact_hash: Digest
    build_binding_id: Id
    build_binding_artifact_hash: Digest


class RunPlanEnvironmentReceipt(GenerationValue):
    schema_version: Literal["nasus.run-plan-environment-observation.v1"] = Field(alias="schema")
    query: RunPlanEnvironmentQuery
    environment_id: Id
    inventory_hash: Digest
    operator_policy_digest: Digest
    target_artifact_hash: Digest
    observed_at: StrictStr = Field(max_length=64)
    observation_scope: Literal["native_artifact_and_selected_configuration_only"]
    historical_not_live: Literal[True]
    native_artifact_attested: Literal[True]
    isolation_configuration_attested: Literal[True]
    durable_native_observation_verified: Literal[False]
    environment_fully_verified: Literal[False]
    execution_authorized: Literal[False]
    external_egress_denial_verified: Literal[False]
    host_access_denial_verified: Literal[False]
    dependency_health_verified: Literal[False]
    fixtures_verified: Literal[False]
    locators_verified: Literal[False]
    business_coverage_verified: Literal[False]
    automated_count: StrictInt = Field(ge=0, le=0)
    executed_on_target_count: StrictInt = Field(ge=0, le=0)
    passed_count: StrictInt = Field(ge=0, le=0)
    remaining_gates: Tuple[Id, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="before")
    @classmethod
    def strict_flags(cls, value):
        if not isinstance(value, dict) or any(type(value.get(key)) is not bool for key in (
                "historical_not_live", "native_artifact_attested", "isolation_configuration_attested",
                "durable_native_observation_verified", "environment_fully_verified", "execution_authorized",
                "external_egress_denial_verified", "host_access_denial_verified", "dependency_health_verified",
                "fixtures_verified", "locators_verified", "business_coverage_verified")):
            raise ValueError("target receipt flags must be exact booleans")
        return value

    @model_validator(mode="after")
    def historical_scope(self):
        if list(self.remaining_gates) != REMAINING_ENVIRONMENT_GATES:
            raise ValueError("target receipt cannot omit remaining independent gates")
        instant = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() != timezone.utc.utcoffset(instant):
            raise ValueError("target receipt requires a UTC observation time")
        return self


class RunPlanEnvironmentBindingReadPort(Protocol):
    def read(self, project_id, binding_id): ...
    def read_with_plan(self, project_id, binding_id): ...


class RunPlanEnvironmentApplicationService:
    def __init__(self, plans, bindings: RunPlanEnvironmentBindingReadPort, authorization, environments: NativeTargetEnvironmentPort):
        self.plans, self.bindings, self.authorization, self.environments = plans, bindings, authorization, environments

    def _access(self, project_id):
        access = self.authorization.scope(project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("target inspection requires a current project reviewer")
        return access

    def _inputs(self, query, *, current):
        reader = getattr(self.bindings, "read_with_plan", None)
        if callable(reader):
            binding, plan = reader(query.project_id, query.build_binding_id)
        else:
            plan = self.plans.read(query.project_id, query.run_plan_id)
            binding = self.bindings.read(query.project_id, query.build_binding_id)
        metadata, build_metadata = plan["metadata"], binding["metadata"]
        if (metadata["artifact_hash"] != query.run_plan_artifact_hash
                or build_metadata["artifact_hash"] != query.build_binding_artifact_hash
                or metadata["project_id"] != query.project_id or metadata["run_plan_id"] != query.run_plan_id
                or build_metadata["project_id"] != query.project_id or build_metadata["binding_id"] != query.build_binding_id
                or build_metadata["run_plan_id"] != query.run_plan_id
                or build_metadata["run_plan_artifact_hash"] != query.run_plan_artifact_hash
                or build_metadata["plan_digest"] != metadata["plan_digest"]
                or build_metadata["target_artifact_hash"] != plan["artifact"]["plan"]["selection"]["target_build"]["artifact_hash"]
                or any(build_metadata[key] != metadata[key] for key in ("image_revision_id", "manifest_id"))):
            raise RunPlanIntegrityError("target inspection must use the exact original plan and build binding")
        if current and (plan["current_use"]["inputs_current"] is not True or binding["current_use"]["inputs_current"] is not True):
            raise RunPlanChanged("target inspection requires current original inputs and script review")
        return deepcopy(plan), deepcopy(binding)

    def require_receipt_inputs_access(self, query):
        self.require_receipt_inputs_access_many((query,))

    def require_receipt_inputs_access_many(self, queries):
        if not 1 <= len(queries) <= 128:
            raise RunPlanIntegrityError("target receipt authorization requires a bounded original cohort")
        scopes = {query.project_id: self._access(query.project_id) for query in queries}
        read_session = getattr(self.plans, "verified_read_session", None)
        with read_session() if read_session else nullcontext():
            for query in queries:
                if not isinstance(query, RunPlanEnvironmentQuery):
                    raise RunPlanIntegrityError("invalid original target query")
                self._inputs(query, current=False)
        for scope in scopes.values():
            self.authorization.require_current(scope)

    def authorize_historical_receipt(self, query, receipt):
        return self.authorize_historical_receipts(((query, receipt),))[0]

    def authorize_historical_receipts(self, receipts):
        if not 1 <= len(receipts) <= 128:
            raise RunPlanIntegrityError("historical target observations require a bounded original cohort")
        values = []
        for query, receipt in receipts:
            if not isinstance(query, RunPlanEnvironmentQuery):
                raise RunPlanIntegrityError("invalid historical target query")
            value = RunPlanEnvironmentReceipt.model_validate(receipt)
            if value.query != query:
                raise RunPlanIntegrityError("historical target observation query was rebound")
            values.append(value)
        accesses = {query.project_id: self._access(query.project_id) for query, _ in receipts}
        read_session = getattr(self.plans, "verified_read_session", None)
        with read_session() if read_session else nullcontext():
            for (query, _), value in zip(receipts, values):
                plan, binding = self._inputs(query, current=False)
                declaration = plan["artifact"]["plan"]["selection"]["environment"]
                if (value.environment_id != declaration["environment_id"]
                        or value.operator_policy_digest != declaration["inventory_hash"]
                        or value.target_artifact_hash != binding["metadata"]["target_artifact_hash"]):
                    raise RunPlanIntegrityError("historical target observation original inputs differ")
        current_many = getattr(self.authorization, "require_current_many", None)
        if callable(current_many):
            current_many(tuple(accesses.values()))
        else:
            for access in accesses.values():
                self.authorization.require_current(access)
        # This is a historical tool statement, not a persisted native attestation
        # or a lease on current Docker resources. Never repeat inspection here.
        return [value.model_dump(mode="json", by_alias=True) for value in values]

    def original_inputs(self, query: RunPlanEnvironmentQuery, *, current=False):
        access = self._access(query.project_id)
        read_session = getattr(self.plans, "verified_read_session", None)
        with read_session() if read_session else nullcontext():
            result = self._inputs(query, current=current)
            self.authorization.require_current(access)
            return result

    def observe(self, query: RunPlanEnvironmentQuery):
        query = RunPlanEnvironmentQuery.model_validate(query.model_dump(mode="json"))
        access = self._access(query.project_id)
        current = lambda: self.authorization.require_current(access)
        read_session = getattr(self.plans, "verified_read_session", None)
        with read_session() if read_session else nullcontext():
            plan, binding = self._inputs(query, current=True)
            declaration = plan["artifact"]["plan"]["selection"]["environment"]
            if declaration["kind"] != "local" or declaration["base_url"] != "http://127.0.0.1:8080":
                raise NativeEnvironmentInvalid("only the exact operator-owned local namespace is supported")
            environment_id = declaration["environment_id"]
            policy = self.environments.policy_digest(query.project_id, environment_id, require_work=current)
            if declaration["inventory_hash"] != policy:
                raise RunPlanChanged("original environment policy differs from the current operator registry")
            artifact_hash = binding["metadata"]["target_artifact_hash"]
            observed = self.environments.inspect(query.project_id, environment_id, artifact_hash, require_work=current)
            observation = NativeEnvironmentObservation(deepcopy(observed.inventory), observed.inventory_hash, observed.observed_at)
            inventory = observation.inventory
            if (inventory["project_id"] != query.project_id or inventory["environment_id"] != environment_id
                    or inventory["operator_policy_digest"] != policy or inventory["artifact_hash"] != artifact_hash
                    or inventory["namespace_origin"] != declaration["base_url"]):
                raise RunPlanIntegrityError("native environment observation was rebound")
            if self.environments.policy_digest(query.project_id, environment_id, require_work=current) != policy:
                raise RunPlanChanged("operator environment policy changed during inspection")
            after = self._inputs(query, current=True)
            if after != (plan, binding):
                raise RunPlanChanged("original target inputs changed during inspection")
            current()
        receipt = {"schema": ENVIRONMENT_RECEIPT_SCHEMA, "query": query.model_dump(mode="json"), "environment_id": environment_id,
            "inventory_hash": observation.inventory_hash, "operator_policy_digest": policy,
            "target_artifact_hash": artifact_hash, "observed_at": observation.observed_at,
            "observation_scope": "native_artifact_and_selected_configuration_only", "historical_not_live": True,
            "native_artifact_attested": True, "isolation_configuration_attested": True,
            "durable_native_observation_verified": False,
            "environment_fully_verified": False, "execution_authorized": False,
            "external_egress_denial_verified": False, "host_access_denial_verified": False,
            "dependency_health_verified": False, "fixtures_verified": False, "locators_verified": False,
            "business_coverage_verified": False, "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0,
            "remaining_gates": list(REMAINING_ENVIRONMENT_GATES)}
        receipt = RunPlanEnvironmentReceipt.model_validate(receipt).model_dump(mode="json", by_alias=True)
        return {"receipt": receipt, "observation": observation, "plan": plan, "binding": binding}

    def inspect(self, query: RunPlanEnvironmentQuery):
        return self.observe(query)["receipt"]
