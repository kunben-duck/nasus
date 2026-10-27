"""Internal projection of verified setup reads, not a wire verifier or authority."""
from dataclasses import asdict, dataclass, field
import re

from .acceptance_specification import acceptance_digest
from .http_bindings import HTTP_BINDING_RECEIPT_SCHEMA, http_binding_value_hash
from .http_fixtures import bind_run_plan_fixture, fixture_bindings
from .run_plan_case_execution import RunPlanCaseExecutionInvalid, execution_roster, require_hash, require_id


CAPTURE_SCHEMA = "nasus.run-plan-case-fixture-captures.v1"
_PROOF_FIELDS = {"invocation_id", "history_digest", "scope", "parent", "native_environment",
    "manifest", "receipt", "setup_request_hash", "setup_result_hash"}
_SCOPE_FIELDS = {"project_id", "attempt_id", "case_id", "parent_digest", "data_manifest_hash",
    "environment_id", "artifact_hash", "inventory_hash", "timeout_ms"}
_CAPTURE_FIELDS = {"binding_id", "step_index", "request_id", "pointer", "response_hash", "value", "value_hash"}


def _require(condition):
    if not condition:
        raise RunPlanCaseExecutionInvalid("fixture captures must retain their complete original case and source")


@dataclass(frozen=True)
class FixtureResourceCapture:
    binding_id: str
    step_index: int
    request_id: str
    pointer: str
    response_hash: str
    value: str = field(repr=False)
    value_hash: str

    def __post_init__(self):
        _require(type(self.binding_id) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", self.binding_id) is not None)
        _require(type(self.step_index) is int and 0 <= self.step_index < 100)
        require_id(self.request_id)
        _require(type(self.pointer) is str and len(self.pointer) <= 4096
            and not any(ord(char) < 32 or ord(char) == 127 for char in self.pointer)
            and (not self.pointer or self.pointer.startswith("/"))
            and re.search(r"~(?![01])", self.pointer) is None)
        try:
            self.pointer.encode("utf-8", errors="strict")
        except UnicodeError:
            raise RunPlanCaseExecutionInvalid("fixture capture pointer contains invalid Unicode") from None
        require_hash(self.response_hash)
        require_hash(self.value_hash)
        _require(http_binding_value_hash(self.value) == self.value_hash)


@dataclass(frozen=True)
class CaseFixtureCaptures:
    scope_digest: str
    project_id: str
    run_plan_id: str
    run_plan_artifact_hash: str
    plan_digest: str
    case_id: str
    setup_invocation_id: str
    setup_history_digest: str
    fixture_attempt_id: str
    data_manifest_hash: str
    environment_id: str
    target_artifact_hash: str
    inventory_hash: str
    environment_record_id: str
    environment_record_artifact_hash: str
    operator_policy_digest: str
    setup_request_hash: str
    setup_result_hash: str
    captures: tuple[FixtureResourceCapture, ...] = field(repr=False)
    schema: str = CAPTURE_SCHEMA

    def __post_init__(self):
        for key in ("project_id", "run_plan_id", "case_id", "setup_invocation_id", "fixture_attempt_id",
                "environment_id", "environment_record_id"):
            require_id(getattr(self, key))
        for key in ("scope_digest", "run_plan_artifact_hash", "plan_digest", "setup_history_digest",
                "data_manifest_hash", "target_artifact_hash", "inventory_hash", "environment_record_artifact_hash",
                "operator_policy_digest", "setup_request_hash", "setup_result_hash"):
            require_hash(getattr(self, key))
        _require(self.schema == CAPTURE_SCHEMA and type(self.captures) is tuple and 1 <= len(self.captures) <= 16)
        _require(all(type(item) is FixtureResourceCapture for item in self.captures))
        _require(len({item.binding_id for item in self.captures}) == len(self.captures))
        _require(len({item.request_id for item in self.captures}) == len(self.captures))
        _require(tuple(item.step_index for item in self.captures) == tuple(sorted({item.step_index for item in self.captures})))

    @property
    def digest(self):
        return acceptance_digest(asdict(self))


def collect_case_fixture_captures(plan, scope, proofs):
    """Project all physical read-port results; callers must still reauthorize/reverify them.

    No caller-supplied verified flag, resource value or digest authorizes dispatch.
    The original setup reader owns wire verification; this function owns the
    immutable, complete handoff. Legacy scripts do not consume these values.
    """
    roster = execution_roster(plan, scope)
    _require(type(proofs) is tuple and len(proofs) == len(roster))
    values = []
    try:
        for case, selected, proof in zip(roster, scope.selection["fixture_setups"], proofs):
            _require(type(proof) is dict and set(proof) == _PROOF_FIELDS)
            _require(proof["invocation_id"] == selected["invocation_id"] and selected["case_id"] == case["case_id"])
            original = proof["scope"]
            parent, native, manifest, receipt = (proof[key] for key in ("parent", "native_environment", "manifest", "receipt"))
            _require(type(original) is dict and set(original) == _SCOPE_FIELDS)
            _require(type(parent) is dict and set(parent) == {"project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest"})
            _require(all(parent[key] == getattr(scope, key) for key in parent))
            _require(type(native) is dict and set(native) == {"record_id", "artifact_hash", "inventory_hash", "operator_policy_digest"})
            _require(native["record_id"] == scope.selection["environment_record_id"]
                and native["artifact_hash"] == scope.selection["environment_record_artifact_hash"]
                and native["inventory_hash"] == scope.inventory_hash)
            _require(original["case_id"] == case["case_id"] and original["parent_digest"] == scope.plan_digest
                and all(original[key] == getattr(scope, key) for key in ("project_id", "environment_id", "inventory_hash"))
                and original["artifact_hash"] == scope.target_artifact_hash
                and type(original["timeout_ms"]) is int and 1000 <= original["timeout_ms"] <= 120000)
            bind_run_plan_fixture(plan, manifest)
            _require(manifest["case_id"] == case["case_id"] and original["data_manifest_hash"] == acceptance_digest(manifest))
            _require(type(receipt) is dict and receipt["schema"] == HTTP_BINDING_RECEIPT_SCHEMA
                and receipt["project_id"] == scope.project_id and receipt["us_id"] == case["case_id"]
                and receipt["execution_status"] == "passed" and receipt["request_hash"] == proof["setup_request_hash"]
                and receipt["runner_job_id"] == "http-fixture-" + acceptance_digest([acceptance_digest(original), "setup"])[7:])
            steps, observed = manifest["setup_steps"], receipt["steps"]
            _require(type(observed) is list and len(observed) == len(steps) == receipt["step_count"]
                and all(type(item) is dict and type(item["step_index"]) is int and item["step_index"] == index
                    and item["action"] == steps[index]["action"] and item["status"] == "passed"
                    for index, item in enumerate(observed)))
            captures = receipt["bindings"]
            _require(type(captures) is list and tuple(item["binding_id"] for item in captures) == fixture_bindings(manifest))
            _require(type(receipt["requests"]) is list)
            _require([item["request_id"] for item in receipt["requests"]] ==
                [item["request_id"] for item in steps if item["action"] == "request"])
            requests = {item["request_id"]: item for item in receipt["requests"]}
            _require(len(requests) == len(receipt["requests"]))
            projected = []
            expected = [(index, item) for index, item in enumerate(steps) if item["action"] == "capture_json"]
            for (index, step), capture in zip(expected, captures):
                _require(type(capture) is dict and set(capture) == _CAPTURE_FIELDS)
                value = FixtureResourceCapture(**capture)
                _require(value.step_index == index and value.binding_id == step["binding_id"]
                    and value.request_id == step["request_id"] and value.pointer == step["pointer"]
                    and observed[index]["step_index"] == index and observed[index]["action"] == "capture_json"
                    and observed[index]["kind"] == "action")
                request = requests[value.request_id]
                _require(request["response_hash"] == value.response_hash and type(request["response_status"]) is int
                    and 200 <= request["response_status"] < 300)
                projected.append(value)
            values.append(CaseFixtureCaptures(scope_digest=scope.digest, project_id=scope.project_id,
                run_plan_id=scope.run_plan_id, run_plan_artifact_hash=scope.run_plan_artifact_hash,
                plan_digest=scope.plan_digest, case_id=case["case_id"], setup_invocation_id=proof["invocation_id"],
                setup_history_digest=proof["history_digest"], fixture_attempt_id=original["attempt_id"],
                data_manifest_hash=original["data_manifest_hash"], environment_id=scope.environment_id,
                target_artifact_hash=scope.target_artifact_hash, inventory_hash=scope.inventory_hash,
                environment_record_id=native["record_id"], environment_record_artifact_hash=native["artifact_hash"],
                operator_policy_digest=native["operator_policy_digest"], setup_request_hash=proof["setup_request_hash"],
                setup_result_hash=proof["setup_result_hash"], captures=tuple(projected)))
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError, RecursionError):
        raise RunPlanCaseExecutionInvalid("complete original fixture captures cannot be projected") from None
    _require(len({item.setup_invocation_id for item in values}) == len(values))
    _require(len({(item.fixture_attempt_id, item.case_id) for item in values}) == len(values))
    return tuple(values)
