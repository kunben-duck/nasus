"""Complete original case roster and once-only dispatch identities, not coverage."""
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from datetime import datetime
import re

from .acceptance_specification import acceptance_digest
from .http_bindings import HTTP_FIXTURE_RECEIPT_SCHEMA
from .run_plan_observations import compile_case_jobs


CASE_WORK_SCHEMA = "nasus.run-plan-case-work.v1"
CASE_FIXTURE_WORK_SCHEMA = "nasus.run-plan-case-work.v2"
CASE_FIXTURE_SCOPE_SCHEMA = "nasus.run-plan-case-fixture-scope.v1"
CASE_CLAIM_SCHEMA = "nasus.run-plan-case-claim.v1"
CASE_OUTCOME_SCHEMA = "nasus.run-plan-case-outcome.v1"
CASE_EXECUTE_TOOL = "quality.run_plan.execute_http"
CASE_CANCEL_TOOL = "quality.run_plan.cancel_http"
CASE_LEASE_SECONDS = 90


class RunPlanCaseExecutionInvalid(ValueError):
    pass


class RunPlanCaseWorkBusy(RuntimeError):
    pass


class RunPlanCaseWorkLost(RuntimeError):
    pass


class RunPlanCaseAlreadyClaimed(RuntimeError):
    pass


def require_id(value):
    if (type(value) is not str or not 1 <= len(value) <= 128 or not value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise RunPlanCaseExecutionInvalid("case execution requires a bounded original identity")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise RunPlanCaseExecutionInvalid("case execution identity contains invalid Unicode") from None


def require_hash(value):
    if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise RunPlanCaseExecutionInvalid("case execution requires an exact original digest")


def require_case_selection(selection):
    fields = {"project_id", "run_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "timeout_ms",
        "build_binding_id", "build_binding_artifact_hash", "environment_record_id", "environment_record_artifact_hash",
        "locator_record_id", "locator_record_artifact_hash", "fixture_setups"}
    if type(selection) is not dict or set(selection) != fields:
        raise RunPlanCaseExecutionInvalid("case execution requires all original build, environment, locator and fixture pins")
    for key in ("project_id", "run_id", "run_plan_id", "build_binding_id", "environment_record_id", "locator_record_id"):
        require_id(selection[key])
    for key in ("run_plan_artifact_hash", "plan_digest", "build_binding_artifact_hash",
                "environment_record_artifact_hash", "locator_record_artifact_hash"):
        require_hash(selection[key])
    if type(selection["timeout_ms"]) is not int or not 1000 <= selection["timeout_ms"] <= 120000:
        raise RunPlanCaseExecutionInvalid("case execution timeout must retain its original bound")
    fixtures = selection["fixture_setups"]
    if type(fixtures) is not list or not 1 <= len(fixtures) <= 512:
        raise RunPlanCaseExecutionInvalid("case execution requires complete original setup command pins")
    for item in fixtures:
        if type(item) is not dict or set(item) != {"case_id", "invocation_id"}:
            raise RunPlanCaseExecutionInvalid("case setup pin must identify an original command, not an outcome flag")
        require_id(item["case_id"])
        require_id(item["invocation_id"])
    if any(len({item[key] for item in fixtures}) != len(fixtures) for key in ("case_id", "invocation_id")):
        raise RunPlanCaseExecutionInvalid("case setup command cannot authorize multiple original cases")
    return deepcopy(selection)


@dataclass(frozen=True)
class RunPlanCaseScope:
    project_id: str
    invocation_id: str
    run_id: str
    run_plan_id: str
    run_plan_artifact_hash: str
    plan_digest: str
    image_revision_id: str
    manifest_id: str
    actor_id: str
    source_scope_digest: str
    request_digest: str
    command_digest: str
    environment_id: str
    target_artifact_hash: str
    inventory_hash: str
    timeout_ms: int
    selection: dict

    def __post_init__(self):
        for key in ("project_id", "invocation_id", "run_id", "run_plan_id", "image_revision_id", "manifest_id",
                    "actor_id", "environment_id"):
            require_id(getattr(self, key))
        for key in ("run_plan_artifact_hash", "plan_digest", "source_scope_digest", "request_digest", "command_digest",
                    "target_artifact_hash", "inventory_hash"):
            require_hash(getattr(self, key))
        if type(self.timeout_ms) is not int or not 1000 <= self.timeout_ms <= 120000:
            raise RunPlanCaseExecutionInvalid("case execution timeout must retain its original bound")
        if type(self.selection) is not dict or acceptance_digest(self.selection) != self.request_digest:
            raise RunPlanCaseExecutionInvalid("case execution must pin its complete independent command request")
        require_case_selection(self.selection)
        if any(type(self.selection.get(key)) is not type(getattr(self, key)) or self.selection.get(key) != getattr(self, key) for key in
               ("project_id", "run_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest", "timeout_ms")):
            raise RunPlanCaseExecutionInvalid("case execution selection differs from its original scope")
        object.__setattr__(self, "selection", deepcopy(self.selection))

    @property
    def work_id(self):
        # Exclude the scope hash: changing a payload must not acquire a new slot.
        return "case_work_" + acceptance_digest([self.project_id, self.run_id])[7:]

    @property
    def digest(self):
        return acceptance_digest(asdict(self))


@dataclass(frozen=True)
class FixtureBoundRunPlanCaseScope(RunPlanCaseScope):
    fixture_input_pins: tuple[dict, ...]
    schema: str = CASE_FIXTURE_SCOPE_SCHEMA

    def __post_init__(self):
        super().__post_init__()
        if (self.schema != CASE_FIXTURE_SCOPE_SCHEMA or type(self.fixture_input_pins) is not tuple
                or len(self.fixture_input_pins) != len(self.selection["fixture_setups"])):
            raise RunPlanCaseExecutionInvalid("fixture case scope requires the complete original input pins")
        for selected, pin in zip(self.selection["fixture_setups"], self.fixture_input_pins):
            if (type(pin) is not dict or set(pin) != {"case_id", "capture_set_digest", "fixture_input_digest"}
                    or pin["case_id"] != selected["case_id"]):
                raise RunPlanCaseExecutionInvalid("fixture case scope cannot omit or reorder original input pins")
            require_hash(pin["capture_set_digest"])
            require_hash(pin["fixture_input_digest"])
        object.__setattr__(self, "fixture_input_pins", deepcopy(self.fixture_input_pins))

    @property
    def base_scope(self):
        # Capture capsules pin the original command scope, avoiding a digest cycle.
        return RunPlanCaseScope(**{item.name: deepcopy(getattr(self, item.name)) for item in fields(RunPlanCaseScope)})


def restore_case_scope(value):
    """Explicit protocol rehydration; never add new nullable fields to old hashes."""
    if type(value) is not dict:
        raise RunPlanCaseExecutionInvalid("case scope must be its exact original payload")
    value = deepcopy(value)
    model = FixtureBoundRunPlanCaseScope if "schema" in value else RunPlanCaseScope
    if set(value) != {item.name for item in fields(model)}:
        raise RunPlanCaseExecutionInvalid("case scope contains missing or unversioned fields")
    if model is FixtureBoundRunPlanCaseScope:
        if type(value["fixture_input_pins"]) not in {list, tuple}:
            raise RunPlanCaseExecutionInvalid("fixture scope needs its complete ordered pin array")
        value["fixture_input_pins"] = tuple(value["fixture_input_pins"])
    return model(**value)


def case_work_schema(scope):
    return CASE_FIXTURE_WORK_SCHEMA if isinstance(scope, FixtureBoundRunPlanCaseScope) else CASE_WORK_SCHEMA


@dataclass(frozen=True)
class RunPlanCaseLease:
    scope: RunPlanCaseScope
    owner_id: str
    epoch: int

    def __post_init__(self):
        if not isinstance(self.scope, RunPlanCaseScope):
            raise RunPlanCaseExecutionInvalid("case worker needs an original typed scope")
        require_id(self.owner_id)
        if type(self.epoch) is not int or not 1 <= self.epoch <= 2147483647:
            raise RunPlanCaseExecutionInvalid("case worker epoch must be a positive bounded integer")

    @property
    def work_id(self):
        return self.scope.work_id


def case_execution_jobs(plan, scope):
    if not isinstance(scope, RunPlanCaseScope):
        raise RunPlanCaseExecutionInvalid("case execution needs an original typed scope")
    # frozen dataclasses still contain JSON; detect mutation before any work.
    scope = restore_case_scope(asdict(scope))
    jobs = compile_case_jobs(plan, run_id=scope.run_id, timeout_ms=scope.timeout_ms)
    if (plan.get("project_id") != scope.project_id or plan.get("plan_digest") != scope.plan_digest
            or plan["source_pin"]["image_revision_id"] != scope.image_revision_id
            or plan["source_pin"]["manifest_id"] != scope.manifest_id
            or plan["selection"]["environment"]["environment_id"] != scope.environment_id
            or plan["selection"]["target_build"]["artifact_hash"] != scope.target_artifact_hash):
        raise RunPlanCaseExecutionInvalid("case worker cannot replace its original plan, image or target")
    if [item["case_id"] for item in scope.selection["fixture_setups"]] != [item["metadata"]["case_id"] for item in jobs]:
        raise RunPlanCaseExecutionInvalid("case execution cannot omit or reorder original fixture setup pins")
    if isinstance(scope, FixtureBoundRunPlanCaseScope):
        if any(job["receipt_protocol"] != HTTP_FIXTURE_RECEIPT_SCHEMA for job in jobs):
            raise RunPlanCaseExecutionInvalid("fixture pins require the explicit v3 business protocol")
        for job, pin in zip(jobs, scope.fixture_input_pins):
            job["metadata"].update(fixture_capture_digest=pin["capture_set_digest"],
                fixture_scope_digest=scope.base_scope.digest)
    return jobs


def case_job_digest(job, scope):
    if isinstance(scope, FixtureBoundRunPlanCaseScope):
        matches = [pin for pin in scope.fixture_input_pins if pin["case_id"] == job["metadata"]["case_id"]]
        if len(matches) != 1:
            raise RunPlanCaseExecutionInvalid("fixture job cannot adopt another original input")
        return acceptance_digest({**job, "fixture_input_digest": matches[0]["fixture_input_digest"]})
    return acceptance_digest(job)


def execution_roster(plan, scope):
    jobs = case_execution_jobs(plan, scope)
    return tuple({"ordinal": index, "case_id": job["metadata"]["case_id"],
        "case_digest": job["metadata"]["case_digest"], "command_digest": case_job_digest(job, scope)}
        for index, job in enumerate(jobs))


def verify_case_command_selection(snapshot, selection, *, actor_id, invocation_id, now=None, historical=False):
    """Reject an unrelated command before resolving any private execution input."""
    try:
        payload = snapshot["input_payload"]
        if (type(selection) is not dict or type(snapshot) is not dict
                or set(snapshot) != {"id", "tool_id", "status", "input_payload"}
                or snapshot["id"] != invocation_id or snapshot["tool_id"] != CASE_EXECUTE_TOOL
                or snapshot["status"] not in ({"running", "completed", "failed", "cancelled"} if historical else {"running"})
                or type(payload) is not dict or payload.get("confirmed_by_user") is not True
                or payload.get("confirmed_actor_id") != actor_id):
            raise RunPlanCaseExecutionInvalid("case work requires its unchanged independently confirmed original command")
        confirmed = datetime.fromisoformat(payload["confirmed_at"])
        if confirmed.tzinfo is None or (not historical and (now is None or now.tzinfo is None
                or not 0 <= (now - confirmed).total_seconds() <= 900)):
            raise RunPlanCaseExecutionInvalid("case command consent must be fresh by PostgreSQL time")
        return acceptance_digest({"tool_id": snapshot["tool_id"], "input_payload": payload})
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise RunPlanCaseExecutionInvalid("original case execution command cannot be verified") from None


def verify_original_case_command(scope, snapshot, selection, *, now=None, historical=False):
    """Fixture consent, a client payload and a lease cannot authorize business jobs."""
    digest = verify_case_command_selection(snapshot, selection, actor_id=scope.actor_id,
        invocation_id=scope.invocation_id, now=now, historical=historical)
    if selection != scope.selection or digest != scope.command_digest:
        raise RunPlanCaseExecutionInvalid("case work requires its unchanged independently confirmed original command")
    return datetime.fromisoformat(snapshot["input_payload"]["confirmed_at"])


def case_claim_id(scope, case_id):
    require_id(case_id)
    return "case_claim_" + acceptance_digest([scope.project_id, scope.run_id, case_id])[7:]


def execution_state(scope, roster, claims, outcomes, *, cancelled):
    """A reserved request without an outcome stays unknown even after cancellation."""
    if (type(roster) is not tuple or not 1 <= len(roster) <= 512 or type(claims) is not list
            or type(outcomes) is not list or type(cancelled) is not bool):
        raise RunPlanCaseExecutionInvalid("case history must preserve its complete original roster")
    for index, item in enumerate(roster):
        if type(item) is not dict or set(item) != {"ordinal", "case_id", "case_digest", "command_digest"}:
            raise RunPlanCaseExecutionInvalid("case history must retain exact original roster fields")
        if type(item["ordinal"]) is not int or item["ordinal"] != index:
            raise RunPlanCaseExecutionInvalid("case history cannot reorder the complete original roster")
        require_id(item["case_id"])
        require_hash(item["case_digest"])
        require_hash(item["command_digest"])
    expected = {item["case_id"]: item for item in roster}
    if len(expected) != len(roster):
        raise RunPlanCaseExecutionInvalid("case history contains duplicate original cases")
    by_claim, by_outcome = {}, {}
    for item in claims:
        fields = {"schema", "claim_id", "project_id", "work_id", "case_id", "ordinal", "owner_id", "epoch",
            "recorded_at", "scope_digest", "case_digest", "command_digest"}
        if type(item) is not dict or set(item) != fields:
            raise RunPlanCaseExecutionInvalid("case claim must have its exact original fields")
        case = expected.get(item.get("case_id"))
        if (case is None or item["case_id"] in by_claim or item.get("schema") != CASE_CLAIM_SCHEMA
                or item.get("claim_id") != case_claim_id(scope, item["case_id"])
                or item.get("project_id") != scope.project_id or item.get("work_id") != scope.work_id
                or item.get("scope_digest") != scope.digest or type(item["ordinal"]) is not int
                or type(item["epoch"]) is not int or not 1 <= item["epoch"] <= 2147483647
                or any(item.get(key) != case[key] for key in ("ordinal", "case_digest", "command_digest"))):
            raise RunPlanCaseExecutionInvalid("case dispatch differs from the original complete roster")
        require_id(item["owner_id"])
        require_id(item["recorded_at"])
        by_claim[item["case_id"]] = item
    for item in outcomes:
        fields = {"schema", "project_id", "claim_id", "case_id", "dispatch_digest", "recorded_at", "status",
            "observation_digest", "artifact_ref", "artifact_hash"}
        if type(item) is not dict or set(item) != fields:
            raise RunPlanCaseExecutionInvalid("case outcome must have its exact original fields")
        claim = by_claim.get(item.get("case_id"))
        if (claim is None or item["case_id"] in by_outcome or item.get("schema") != CASE_OUTCOME_SCHEMA
                or item.get("claim_id") != claim["claim_id"]
                or item.get("project_id") != scope.project_id
                or item.get("dispatch_digest") != acceptance_digest(claim)
                or item.get("status") not in {"passed", "failed", "error", "timed_out"}):
            raise RunPlanCaseExecutionInvalid("case outcome cannot replace or invent its original dispatch")
        require_hash(item.get("artifact_hash"))
        require_hash(item.get("observation_digest"))
        require_id(item["recorded_at"])
        if type(item["artifact_ref"]) is not str or not 1 <= len(item["artifact_ref"]) <= 4096:
            raise RunPlanCaseExecutionInvalid("case output requires its exact private artifact reference")
        by_outcome[item["case_id"]] = item
    cases = [{**deepcopy(item), "claim_id": case_claim_id(scope, item["case_id"]),
        "status": by_outcome[item["case_id"]]["status"] if item["case_id"] in by_outcome else
            "outcome_unknown" if item["case_id"] in by_claim else "not_dispatched",
        "observation_digest": by_outcome[item["case_id"]]["observation_digest"]
            if item["case_id"] in by_outcome else None} for item in roster]
    unknown = len(by_claim) - len(by_outcome)
    state = ("outcome_unknown" if unknown else "observed" if len(by_outcome) == len(roster) else
        "cancelled" if cancelled else "partially_observed" if by_outcome else "not_dispatched")
    fixture = isinstance(scope, FixtureBoundRunPlanCaseScope)
    return {"schema": "nasus.run-plan-case-state.v2" if fixture else "nasus.run-plan-case-state.v1",
        **({"fixture_scope_digest": scope.base_scope.digest, "fixture_input_pins": deepcopy(list(scope.fixture_input_pins))}
            if fixture else {}), "project_id": scope.project_id, "run_id": scope.run_id,
        "invocation_id": scope.invocation_id, "scope_digest": scope.digest, "cases": cases, "state": state,
        "cancelled": cancelled, "case_count": len(roster), "observed_case_count": len(by_outcome),
        "outcome_unknown_case_count": unknown, "not_dispatched_case_count": len(roster) - len(by_claim),
        "business_coverage_verified": False, "canonical_execution_committed": False,
        "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0}
