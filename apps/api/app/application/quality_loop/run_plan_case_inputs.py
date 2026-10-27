"""Original-record producer for independent business case execution, not client scope JSON."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Protocol, Tuple

from pydantic import Field, StrictInt, model_validator

from ..platform.tool_handlers.query_input import query_payload
from .run_plan_environments import RunPlanEnvironmentQuery
from .run_plan_case_fixtures import OriginalCaseFixtureWire
from .test_design_output import Digest, GenerationValue, Id
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan_fixture_captures import CaseFixtureCaptures, collect_case_fixture_captures
from ...domain.quality_loop.http_bindings import HTTP_FIXTURE_RECEIPT_SCHEMA
from ...domain.quality_loop.http_fixture_binding_input import build_fixture_input
from ...domain.quality_loop.automation_scripts import script_http_protocol
from ...domain.quality_loop.environment_observation_record import environment_record_metadata, validate_environment_archive
from ...domain.quality_loop.http_fixtures import bind_run_plan_fixture
from ...domain.quality_loop.http_locator_record import validate_locator_archive
from ...domain.quality_loop.native_environment_health import NativeEnvironmentHealthObservation
from ...domain.quality_loop.run_plan import RunPlanChanged
from ...domain.quality_loop.run_plan_case_execution import (
    RunPlanCaseExecutionInvalid, RunPlanCaseScope, execution_roster, verify_case_command_selection,
    verify_original_case_command, require_id, FixtureBoundRunPlanCaseScope, restore_case_scope,
)
from ...domain.system_image.source_access import SourceAccessDenied


class RunPlanCaseFixtureSelection(GenerationValue):
    case_id: Id
    invocation_id: Id

    @model_validator(mode="after")
    def original_ids(self):
        require_id(self.case_id)
        require_id(self.invocation_id)
        return self


class RunPlanCaseExecutionSelection(GenerationValue):
    project_id: Id
    run_id: Id
    run_plan_id: Id
    run_plan_artifact_hash: Digest
    plan_digest: Digest
    timeout_ms: StrictInt = Field(ge=1000, le=120000)
    build_binding_id: Id
    build_binding_artifact_hash: Digest
    environment_record_id: Id
    environment_record_artifact_hash: Digest
    locator_record_id: Id
    locator_record_artifact_hash: Digest
    fixture_setups: Tuple[RunPlanCaseFixtureSelection, ...] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def exact_original_selection(self):
        for key in ("project_id", "run_id", "run_plan_id", "build_binding_id", "environment_record_id", "locator_record_id"):
            require_id(getattr(self, key))
        if any(len({getattr(item, key) for item in self.fixture_setups}) != len(self.fixture_setups)
                for key in ("case_id", "invocation_id")):
            raise RunPlanCaseExecutionInvalid("case execution requires distinct original cases and setup commands")
        return self


class RunPlanCaseCommandReadPort(Protocol):
    def original_command(self, project_id, invocation_id, *, actor_id, require_current): ...


class RunPlanCaseFixtureReadPort(Protocol):
    def read(self, project_id, invocation_id, *, require_current): ...
    def read_native(self, project_id, invocation_id, *, require_current, historical=False): ...


@dataclass(frozen=True)
class PreparedRunPlanCaseInputs:
    scope: RunPlanCaseScope
    plan: dict
    dependencies_digest: str
    fixture_captures: tuple[CaseFixtureCaptures, ...]


@dataclass(frozen=True)
class PreparedFixtureBoundCaseInputs(PreparedRunPlanCaseInputs):
    fixture_inputs: tuple[dict, ...] = field(repr=False)


class RunPlanCaseInputApplicationService:
    def __init__(self, original_inputs, environments, locators, fixtures: RunPlanCaseFixtureReadPort,
                 health, commands: RunPlanCaseCommandReadPort):
        self.original_inputs, self.environments, self.locators = original_inputs, environments, locators
        self.fixtures, self.health, self.commands = fixtures, health, commands
        self.authorization = original_inputs.authorization

    def _access(self, project_id):
        access = self.authorization.scope(project_id)
        if access.effective_project_role not in {"qa_lead", "project_admin", "platform_admin"}:
            raise SourceAccessDenied("business case execution requires a current project execution role")
        self.authorization.require_current(access)
        return access

    def _resolve(self, selection, invocation_id, *, expected_scope=None, require_work=None, historical_scope=None):
        plans = getattr(self.original_inputs, "plans", None)
        read_session = getattr(plans, "verified_read_session", None)
        # Reuse immutable source proof only within this synchronous verification.
        # Each worker fence gets a fresh scope; ACL, heads and health stay live.
        with read_session() if callable(read_session) else nullcontext():
            return self._resolve_original(selection, invocation_id, expected_scope=expected_scope,
                require_work=require_work, historical_scope=historical_scope)

    def _resolve_original(self, selection, invocation_id, *, expected_scope=None, require_work=None, historical_scope=None):
        historical = historical_scope is not None
        require_id(invocation_id)
        selection = RunPlanCaseExecutionSelection.model_validate(selection.model_dump(mode="json"))
        request, access = selection.model_dump(mode="json"), self._access(selection.project_id)

        def current():
            if require_work is not None:
                require_work()
            self.authorization.require_current(access)
            if not historical and expected_scope is not None and (access.actor_id != expected_scope.actor_id
                    or access.fingerprint != expected_scope.source_scope_digest):
                raise SourceAccessDenied("case worker cannot adopt another actor or changed source permissions")
            if require_work is not None:
                require_work()

        def original_command():
            current()
            original = self.commands.original_command(selection.project_id, invocation_id,
                actor_id=access.actor_id, require_current=current)
            if type(original) is not dict or set(original) != {"command", "now"}:
                raise RunPlanCaseExecutionInvalid("case producer requires an original command and PostgreSQL time")
            return original

        original = original_command()
        snapshot = original["command"]
        command_digest = verify_case_command_selection(snapshot, request,
            actor_id=historical_scope.actor_id if historical else access.actor_id,
            invocation_id=invocation_id, now=original["now"], historical=historical)
        command_request = {key: value for key, value in query_payload(snapshot["input_payload"]).items()
            if key not in {"confirmed_by_user", "confirmed_at"}}
        if command_request != request:
            raise RunPlanCaseExecutionInvalid("case producer cannot substitute an independently confirmed selection")
        if historical:
            verify_original_case_command(historical_scope, snapshot, request, historical=True)
        query = RunPlanEnvironmentQuery(**{key: request[key] for key in
            ("project_id", "run_plan_id", "run_plan_artifact_hash", "build_binding_id", "build_binding_artifact_hash")})
        saved, binding = self.original_inputs.original_inputs(query, current=not historical)
        plan, metadata = saved["artifact"]["plan"], saved["metadata"]
        if metadata["plan_digest"] != selection.plan_digest or plan["plan_digest"] != selection.plan_digest:
            raise RunPlanCaseExecutionInvalid("case producer must retain the original complete plan digest")
        current()
        environment = self.environments.read(selection.project_id, selection.environment_record_id)
        if (environment.get("historical_not_live") is not True
                or environment["metadata"]["artifact_hash"] != selection.environment_record_artifact_hash
                or environment["metadata"]["record_id"] != selection.environment_record_id):
            raise RunPlanCaseExecutionInvalid("case producer cannot substitute the original environment record")
        validate_environment_archive(environment["archive"], query.model_dump(mode="json"), saved, binding)
        if environment_record_metadata(environment["archive"]) != environment["metadata"]:
            raise RunPlanCaseExecutionInvalid("case producer environment metadata differs from the original inventory")
        current()
        locator = self.locators.read(selection.project_id, selection.locator_record_id)
        locator_query = {key: request[key] for key in ("project_id", "run_plan_id", "run_plan_artifact_hash")}
        locator_metadata = validate_locator_archive(locator["archive"], locator_query, saved)
        if (locator.get("historical_not_live") is not True or locator_metadata != locator["metadata"]
                or locator_metadata["record_id"] != selection.locator_record_id
                or locator_metadata["artifact_hash"] != selection.locator_record_artifact_hash
                or any(item["status"] != "static_match" for item in locator["archive"]["report"]["locators"])):
            raise RunPlanCaseExecutionInvalid("case producer requires complete original static locator evidence, not runtime flags")
        inventory = environment["archive"]["observation"]
        scope = RunPlanCaseScope(**{key: request[key] for key in
            ("project_id", "run_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "timeout_ms")},
            invocation_id=invocation_id, actor_id=historical_scope.actor_id if historical else access.actor_id,
            source_scope_digest=historical_scope.source_scope_digest if historical else access.fingerprint,
            request_digest=acceptance_digest(request), command_digest=command_digest,
            image_revision_id=metadata["image_revision_id"], manifest_id=metadata["manifest_id"],
            environment_id=plan["selection"]["environment"]["environment_id"],
            target_artifact_hash=plan["selection"]["target_build"]["artifact_hash"],
            inventory_hash=inventory["inventory_hash"], selection=request)
        execution_roster(plan, scope)
        fixture_bound = script_http_protocol(plan["proposal"]) == HTTP_FIXTURE_RECEIPT_SCHEMA
        original_base = historical_scope.base_scope if isinstance(historical_scope, FixtureBoundRunPlanCaseScope) else historical_scope
        if historical and scope != original_base:
            raise RunPlanChanged("historical case inputs differ from the original persisted execution scope")
        proofs, wires = [], []
        for selected in selection.fixture_setups:
            current()
            if fixture_bound:
                wire = self.fixtures.read_native(selection.project_id, selected.invocation_id,
                    require_current=current, historical=historical)
                if type(wire) is not OriginalCaseFixtureWire:
                    raise RunPlanCaseExecutionInvalid("fixture cases require the original typed wire reader")
                wire = OriginalCaseFixtureWire(deepcopy(wire.proof), wire.request_body, wire.result_body)
                wires.append(wire)
                proof = wire.proof
            else:
                proof = self.fixtures.read(selection.project_id, selected.invocation_id, require_current=current,
                    **({"historical": True} if historical else {}))
            bind_run_plan_fixture(plan, proof["manifest"])
            fixture_scope, parent, native = proof["scope"], proof["parent"], proof["native_environment"]
            if (proof["invocation_id"] != selected.invocation_id or fixture_scope["case_id"] != selected.case_id
                    or any(parent[key] != getattr(scope, key) for key in
                        ("project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest"))
                    or any(fixture_scope[key] != getattr(scope, key) for key in
                        ("project_id", "environment_id", "inventory_hash"))
                    or fixture_scope["artifact_hash"] != scope.target_artifact_hash
                    or fixture_scope["parent_digest"] != scope.plan_digest
                    or native["record_id"] != selection.environment_record_id
                    or native["artifact_hash"] != selection.environment_record_artifact_hash
                    or native["inventory_hash"] != scope.inventory_hash
                    or native["operator_policy_digest"] != environment["metadata"]["operator_policy_digest"]):
                raise RunPlanCaseExecutionInvalid("case producer cannot mix fixture, plan, case or native target ancestry")
            proofs.append(deepcopy(proof))
        current()
        if not historical:
            live = self.health.inspect(query, require_work=current)
            observed = live.get("observation") if type(live) is dict else None
            if not isinstance(observed, NativeEnvironmentHealthObservation):
                raise RunPlanCaseExecutionInvalid("case preflight requires a typed original target health observation")
            observed = NativeEnvironmentHealthObservation(deepcopy(observed.inventory), observed.inventory_hash,
                deepcopy(observed.checks), observed.observed_at)
            if (live["request"] != query.model_dump(mode="json") or observed.inventory_hash != scope.inventory_hash
                    or observed.inventory != inventory["inventory"]
                    or not observed.dependency_health_verified or not observed.target_health_verified):
                raise RunPlanCaseExecutionInvalid("case target epoch or dependency health differs from the original inventory")
        if self.original_inputs.original_inputs(query, current=not historical) != (saved, binding):
            raise RunPlanChanged("case execution original plan or build changed during input verification")
        # Do not hash transient health time or promote static/setup observations to coverage.
        dependencies = acceptance_digest({"saved": saved, "binding": binding,
            "environment": environment, "locator": locator, "fixtures": proofs,
            **({"historical_reader": {"actor_id": access.actor_id, "source_scope_digest": access.fingerprint}}
                if historical else {})})
        captures = collect_case_fixture_captures(plan, scope, tuple(proofs))
        if fixture_bound:
            inputs = tuple(build_fixture_input(capture, wire.request_body, wire.result_body)
                for capture, wire in zip(captures, wires))
            pins = tuple({"case_id": capture.case_id, "capture_set_digest": capture.digest,
                "fixture_input_digest": acceptance_digest(value)} for capture, value in zip(captures, inputs))
            scope = FixtureBoundRunPlanCaseScope(**asdict(scope), fixture_input_pins=pins)
            execution_roster(plan, scope)
            if historical and scope != historical_scope:
                raise RunPlanChanged("historical fixture input pins differ from the original persisted work")
            prepared = PreparedFixtureBoundCaseInputs(scope, deepcopy(plan), dependencies, captures, inputs)
        else:
            prepared = PreparedRunPlanCaseInputs(scope, deepcopy(plan), dependencies, captures)
        # Complete evidence verification can outlive consent or cancellation.
        # Re-read the command and PG clock; a prepared result is not a dispatch grant.
        latest = original_command()
        verify_original_case_command(scope, latest["command"], request,
            now=latest["now"], historical=historical)
        current()
        return prepared

    def prepare(self, selection: RunPlanCaseExecutionSelection, *, invocation_id, require_work=None):
        return self._resolve(selection, invocation_id, require_work=require_work)

    def historical_inputs(self, scope: RunPlanCaseScope):
        if not isinstance(scope, RunPlanCaseScope):
            raise RunPlanCaseExecutionInvalid("case history requires its original persisted scope")
        original = restore_case_scope(asdict(scope))
        selection = RunPlanCaseExecutionSelection.model_validate(original.selection)
        return self._resolve(selection, original.invocation_id, historical_scope=original)

    def require_plan_access(self, selection: RunPlanCaseExecutionSelection):
        access = self._access(selection.project_id)
        request = selection.model_dump(mode="json")
        query = RunPlanEnvironmentQuery(**{key: request[key] for key in
            ("project_id", "run_plan_id", "run_plan_artifact_hash", "build_binding_id", "build_binding_artifact_hash")})
        self.original_inputs.original_inputs(query, current=False)
        self.authorization.require_current(access)

    def require_current(self, prepared: PreparedRunPlanCaseInputs, *, require_work=None):
        if not isinstance(prepared, PreparedRunPlanCaseInputs):
            raise RunPlanCaseExecutionInvalid("case worker requires producer-resolved original inputs")
        selection = RunPlanCaseExecutionSelection.model_validate(prepared.scope.selection)
        current = self._resolve(selection, prepared.scope.invocation_id,
            expected_scope=prepared.scope, require_work=require_work)
        if current != prepared:
            raise RunPlanChanged("case execution dependencies changed; never replace the original attempt")
