"""Read the exact canonical setup and all cleanup slots without granting new work."""
from copy import deepcopy
from dataclasses import asdict, dataclass, field

from .http_fixture_commands import HttpFixtureCommandAuthority
from .http_fixture_execution import HttpFixtureExecutionSelection
from .http_fixture_history import HttpFixtureHistoryTarget
from .http_fixtures import HttpFixtureLifecycleApplicationService, HttpFixturePhaseRecord
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixtures import fixture_bindings
from ...domain.quality_loop.http_fixture_binding_input import MAX_FIXTURE_SOURCE_BYTES
from ...domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from ...domain.shared.native_build_source import byte_digest


@dataclass(frozen=True)
class OriginalCaseFixtureWire:
    proof: dict = field(repr=False)
    request_body: bytes = field(repr=False)
    result_body: bytes = field(repr=False)

    def __post_init__(self):
        if (type(self.proof) is not dict
                or any(type(body) is not bytes or not 0 < len(body) <= MAX_FIXTURE_SOURCE_BYTES
                    for body in (self.request_body, self.result_body))
                or byte_digest(self.request_body) != self.proof.get("setup_request_hash")
                or byte_digest(self.result_body) != self.proof.get("setup_result_hash")):
            raise RunPlanCaseExecutionInvalid("fixture handoff requires the complete original native bytes")
        object.__setattr__(self, "proof", deepcopy(self.proof))


class RunPlanCaseFixtureApplicationService:
    def __init__(self, jobs, verifier):
        self.jobs, self.verifier = jobs, verifier

    def read(self, project_id, invocation_id, *, require_current, historical=False):
        return self._read(project_id, invocation_id, require_current=require_current, historical=historical, native=False)

    def read_native(self, project_id, invocation_id, *, require_current, historical=False):
        return self._read(project_id, invocation_id, require_current=require_current, historical=historical, native=True)

    def _read(self, project_id, invocation_id, *, require_current, historical, native):
        if type(historical) is not bool:
            raise RunPlanCaseExecutionInvalid("fixture history mode must be an exact boolean")
        require_current()
        target = HttpFixtureHistoryTarget(project_id=project_id, invocation_id=invocation_id)
        selected = self.jobs.history.read(target)
        if selected.stage != "execute" or selected.operation != "setup" or selected.status != "completed":
            raise RunPlanCaseExecutionInvalid("business case prerequisites require an original completed setup command")
        inputs = self.jobs.grants.execution_inputs(HttpFixtureExecutionSelection(project_id=project_id,
            grant_id=selected.grant_id, grant_digest=selected.grant_digest, operation="setup"), live=False)
        if (inputs.scope.case_id != selected.case_id or inputs.scope.attempt_id != selected.attempt_id
                or inputs.parent.run_plan_id != selected.run_plan_id
                or inputs.parent.run_plan_artifact_hash != selected.run_plan_artifact_hash):
            raise RunPlanCaseExecutionInvalid("business case setup lost its original history ancestry")
        authority = HttpFixtureCommandAuthority(invocation_id=invocation_id, request_digest=selected.request_digest)
        phases = self.jobs.execution.runtimes.history(inputs, require_current=require_current,
            original_setup=authority, include_cleanup=True)
        expected = ("setup", *("cleanup:" + binding for binding in fixture_bindings(inputs.manifest)))
        if (type(phases) is not tuple or len(phases) != len(expected)
                or tuple(item[0] for item in phases if type(item) is tuple and len(item) == 2) != expected
                or any(record is not None and not isinstance(record, HttpFixturePhaseRecord) for _, record in phases)):
            raise RunPlanCaseExecutionInvalid("business case setup requires every original cleanup slot, without truncation")
        prepared = phases[0][1]
        command = HttpFixtureLifecycleApplicationService._command(inputs.scope, "setup", tuple(inputs.manifest["setup_steps"]))
        if (not isinstance(prepared, HttpFixturePhaseRecord) or prepared.command != command
                or prepared.execution is None or (not historical and any(record is not None for _, record in phases[1:]))):
            raise RunPlanCaseExecutionInvalid("setup is unknown, rebound or cleanup was already dispatched")
        require_current()
        receipt = self.verifier.verify(command, prepared.execution, environment_id=inputs.scope.environment_id,
            inventory_hash=inputs.scope.inventory_hash)
        if (prepared.execution.result.status != "passed"
                or tuple(item["binding_id"] for item in receipt["bindings"]) != fixture_bindings(inputs.manifest)):
            raise RunPlanCaseExecutionInvalid("business case setup must preserve all successfully observed original captures")
        require_current()
        # A changed command/journal during the read is not a stable prerequisite.
        if (self.jobs.history.read(target) != selected
                or self.jobs.execution.runtimes.history(inputs, require_current=require_current,
                    original_setup=authority, include_cleanup=True) != phases):
            raise RunPlanCaseExecutionInvalid("original setup changed while reading; inspect the same operation again")
        require_current()
        proof = {"invocation_id": invocation_id, "history_digest": acceptance_digest(selected.model_dump(mode="json")),
            "scope": asdict(inputs.scope), "parent": inputs.parent.model_dump(mode="json"),
            "native_environment": deepcopy(inputs.native_environment),
            "manifest": deepcopy(inputs.manifest), "receipt": deepcopy(receipt),
            "setup_request_hash": byte_digest(prepared.execution.request_body),
            "setup_result_hash": byte_digest(prepared.execution.result_body)}
        return OriginalCaseFixtureWire(proof, prepared.execution.request_body, prepared.execution.result_body) if native else proof
