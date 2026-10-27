"""Bind actual HTTP observations to original cases, without target authority."""
from copy import deepcopy
import hashlib
import json

from .acceptance_specification import acceptance_digest
from .automation_scripts import script_http_protocol, validate_script_proposal, verify_script_input
from .http_runner_observations import HTTP_RUNNER_RECEIPT_SCHEMA, verify_http_runner_observations
from .http_bindings import HTTP_FIXTURE_RECEIPT_SCHEMA
from .http_runner_oracles import strict_http_json
from .run_plan import RUN_PLAN_SCHEMA, RUN_PLAN_BINDING_SCHEMA, RUN_PLAN_FIXTURE_SCHEMA, compile_run_plan


OBSERVATION_SCHEMA = "nasus.run-plan-case-observation.v1"
COLLECTION_SCHEMA = "nasus.run-plan-observations.v1"
ATTEMPT_SCHEMA = "nasus.run-plan-unverified-attempt.v1"
ATTEMPT_COLLECTION_SCHEMA = "nasus.run-plan-attempt-observations.v1"


class RunPlanObservationInvalid(ValueError):
    pass


def _require(condition):
    if not condition:
        raise RunPlanObservationInvalid("RunPlan observation does not preserve its original fixed inputs")


def verify_plan(plan):
    try:
        _require(type(plan) is dict and plan["schema"] in {RUN_PLAN_SCHEMA, RUN_PLAN_BINDING_SCHEMA, RUN_PLAN_FIXTURE_SCHEMA}
            and plan["execution_authorized"] is False
            and all(type(plan[key]) is int and plan[key] == 0 for key in
                ("automated_count", "executed_on_target_count", "passed_count")))
        _require(acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"}) == plan["plan_digest"])
        prepared, proposal = plan["prepared"], plan["proposal"]
        verify_script_input(prepared)
        _require(1 <= len(prepared["cases"]) <= 512 and len(prepared["cases"]) == len(set(prepared["selected_case_ids"]))
            and len(prepared["selected_case_ids"]) == len(set(prepared["selected_case_ids"])))
        _require(acceptance_digest(validate_script_proposal(prepared, {key: proposal[key] for key in
            ("input_digest", "scripts", "gaps")}, http_protocol=script_http_protocol(proposal))) == acceptance_digest(proposal))
        _require(plan["script_pin"]["proposal_hash"] == acceptance_digest(proposal)
            and plan["script_pin"]["input_digest"] == prepared["input_digest"])
        # Rebuild only the saved contract, not a current review or an authorization.
        script = plan["script_pin"]
        review = plan["review_pin"]
        draft = {"result": {"prepared": prepared, "proposal": proposal}, "metadata": {
            "project_id": plan["project_id"], "script_revision_id": script["script_revision_id"], "artifact_hash": script["artifact_hash"]}}
        decision = {"revision": {**review, "project_id": plan["project_id"], "status": "reviewed",
            "script_revision_id": script["script_revision_id"], "script_artifact_hash": script["artifact_hash"]},
            "assessment": {"review_complete": True}}
        _require(acceptance_digest(compile_run_plan(draft, decision, plan["selection"], plan["source_pin"])) == acceptance_digest(plan))
    except (ValueError, KeyError, TypeError, IndexError, UnicodeError, RecursionError):
        raise RunPlanObservationInvalid("RunPlan observation inputs cannot be verified") from None
    return plan


def compile_case_jobs(plan, *, run_id, timeout_ms):
    verify_plan(plan)
    _require(type(run_id) is str and 1 <= len(run_id) <= 128 and run_id.strip()
        and not any(ord(char) < 32 or ord(char) == 127 for char in run_id)
        and type(timeout_ms) is int and 1000 <= timeout_ms <= 120000)
    try:
        run_id.encode("utf-8", errors="strict")
    except UnicodeError:
        raise RunPlanObservationInvalid("RunPlan attempt identity contains invalid Unicode") from None
    scripts = {script["case_id"]: script for script in plan["proposal"]["scripts"]}
    jobs = []
    for case in plan["prepared"]["cases"]:
        script = scripts[case["case_id"]]
        _require(script["kind"] == "http" and 1 <= len(script["actions"]) <= 100)
        for action in script["actions"]:
            for value in action.values():
                if type(value) is str:
                    try:
                        value.encode("utf-8", errors="strict")
                    except UnicodeError:
                        raise RunPlanObservationInvalid("HTTP operands contain invalid Unicode") from None
                    _require(not any(ord(char) == 127 for char in value))
            if action["action"] == "request":
                headers, body = strict_http_json(action["headers_json"]), strict_http_json(action["body_json"])
                _require(not any(ord(char) == 127 for value in headers.values() for char in value)
                    and (action["method"] not in {"GET", "HEAD"} or body is None))
            elif action["action"] == "assert_json":
                strict_http_json(action["value_json"])
            elif action["action"] == "assert_header":
                _require(len(action["name"]) <= 128)
        metadata = {"run_id": run_id, "plan_digest": plan["plan_digest"], "case_id": case["case_id"],
            "case_digest": acceptance_digest(case), "script_revision_id": plan["script_pin"]["script_revision_id"],
            "review_revision_id": plan["review_pin"]["revision_id"],
            "context_id": plan["prepared"]["context_pin"]["context_id"]}
        ident = acceptance_digest([run_id, plan["plan_digest"], case["case_id"], timeout_ms]).split(":", 1)[1]
        jobs.append(dict(job_id="run-plan-case-" + ident, project_id=plan["project_id"], us_id=case["case_id"],
            execution_kind="http", receipt_protocol=script_http_protocol(plan["proposal"]), metadata=metadata,
            base_url=plan["selection"]["environment"]["base_url"], steps=deepcopy(script["actions"]), timeout_ms=timeout_ms))
    return tuple(jobs)


def job_request_hash(job):
    wire = json.dumps(job, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(wire).hexdigest()


def map_case_observation(plan, job, receipt, *, fixture_input=None):
    case_id = job["metadata"]["case_id"]
    case = next(item for item in plan["prepared"]["cases"] if item["case_id"] == case_id)
    script = next(item for item in plan["proposal"]["scripts"] if item["case_id"] == case_id)
    fixture = next(item for item in plan["selection"]["fixtures"] if item["case_id"] == case_id)
    bound = job["receipt_protocol"] == HTTP_FIXTURE_RECEIPT_SCHEMA
    _require(bound or fixture_input is None)
    wire_job = {**job, "fixture_input": fixture_input} if bound else job
    checked = verify_http_runner_observations(receipt, job_id=job["job_id"], project_id=job["project_id"], us_id=job["us_id"],
        request_hash=job_request_hash(wire_job), steps=tuple(job["steps"]), status=receipt["execution_status"], protocol=job["receipt_protocol"],
        **({"fixture_input": fixture_input, "base_url": job["base_url"], "metadata": job["metadata"]} if bound else {}))
    actions = [dict(action_index=index, action_digest=acceptance_digest(action),
        source_step_indices=deepcopy(action["source_step_indices"]), status=checked["steps"][index]["status"])
        for index, action in enumerate(script["actions"])]
    oracles = [{key: assertion[key] for key in ("row_id", "action_index", "source_step_index", "oracle_digest")}
        | {"status": checked["steps"][assertion["action_index"]]["status"]} for assertion in script["assertions"]]
    value = dict(schema="nasus.run-plan-case-observation.v2" if bound else OBSERVATION_SCHEMA,
        **({"fixture_input_digest": acceptance_digest(fixture_input),
            "fixture_capture_digest": job["metadata"]["fixture_capture_digest"]} if bound else {}),
        project_id=plan["project_id"], plan_digest=plan["plan_digest"],
        run_id=job["metadata"]["run_id"], timeout_ms=job["timeout_ms"], case_id=case_id, case_digest=acceptance_digest(case),
        context_pin=deepcopy(plan["prepared"]["context_pin"]), scope_pin=deepcopy(plan["prepared"]["scope_pin"]),
        generation_pin=deepcopy(plan["prepared"]["generation_pin"]), mapping_pin=deepcopy(plan["prepared"]["mapping_pin"]),
        script_pin=deepcopy(plan["script_pin"]), review_pin=deepcopy(plan["review_pin"]), fixture_digest=acceptance_digest(fixture),
        status=checked["execution_status"], actions=actions, oracles=oracles, runner_receipt=checked,
        execution_authorized=False, business_coverage_verified=False, target_build_verified=False,
        automated_count=0, executed_on_target_count=0, passed_count=0)
    return {**value, "observation_digest": acceptance_digest(value)}


def collect_run_plan_observations(plan, observations):
    verify_plan(plan)
    _require(type(observations) is list and len(observations) <= len(plan["prepared"]["cases"]))
    by_case, attempt, jobs_by_case = {}, None, {}
    try:
        for observed in observations:
            _require(type(observed) is dict and observed["case_id"] not in by_case)
            current = (observed["run_id"], observed["timeout_ms"])
            if attempt is None:
                attempt = current
                jobs_by_case = {item["metadata"]["case_id"]: item for item in
                    compile_case_jobs(plan, run_id=observed["run_id"], timeout_ms=observed["timeout_ms"])}
            _require(current == attempt)
            job = jobs_by_case[observed["case_id"]]
            rebuilt = map_case_observation(plan, job, observed["runner_receipt"])
            _require(acceptance_digest(rebuilt) == acceptance_digest(observed))
            by_case[observed["case_id"]] = rebuilt
    except (ValueError, KeyError, TypeError, StopIteration, UnicodeError, RecursionError):
        raise RunPlanObservationInvalid("RunPlan case observations cannot be verified") from None
    cases = [dict(case_id=case["case_id"], case_digest=acceptance_digest(case),
        status=by_case[case["case_id"]]["status"] if case["case_id"] in by_case else "not_executed",
        observation_digest=by_case[case["case_id"]]["observation_digest"] if case["case_id"] in by_case else None)
        for case in plan["prepared"]["cases"]]
    value = dict(schema=COLLECTION_SCHEMA, project_id=plan["project_id"], plan_digest=plan["plan_digest"], cases=cases,
        case_count=len(cases), observed_case_count=len(by_case), not_executed_case_count=len(cases) - len(by_case),
        passed_observation_count=sum(item["status"] == "passed" for item in cases),
        failed_observation_count=sum(item["status"] == "failed" for item in cases),
        execution_authorized=False, business_coverage_verified=False, target_build_verified=False,
        automated_count=0, executed_on_target_count=0, passed_count=0)
    return {**value, "collection_digest": acceptance_digest(value)}


def map_unverified_case_attempt(plan, job, *, runner_status, runner_result_hash):
    """An adapter error without native proof is unknown, never a target failure."""
    _require(runner_status in {"error", "timed_out"} and type(runner_result_hash) is str
        and len(runner_result_hash) == 71 and runner_result_hash.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in runner_result_hash[7:]))
    case_id = job["metadata"]["case_id"]
    case = next(item for item in plan["prepared"]["cases"] if item["case_id"] == case_id)
    script = next(item for item in plan["proposal"]["scripts"] if item["case_id"] == case_id)
    value = dict(schema=ATTEMPT_SCHEMA, project_id=plan["project_id"], plan_digest=plan["plan_digest"],
        run_id=job["metadata"]["run_id"], timeout_ms=job["timeout_ms"], case_id=case_id,
        case_digest=acceptance_digest(case), runner_job_id=job["job_id"], request_hash=job_request_hash(job),
        runner_status=runner_status, runner_result_hash=runner_result_hash,
        context_pin=deepcopy(plan["prepared"]["context_pin"]), scope_pin=deepcopy(plan["prepared"]["scope_pin"]),
        generation_pin=deepcopy(plan["prepared"]["generation_pin"]), mapping_pin=deepcopy(plan["prepared"]["mapping_pin"]),
        script_pin=deepcopy(plan["script_pin"]), review_pin=deepcopy(plan["review_pin"]),
        actions=[dict(action_index=index, action_digest=acceptance_digest(action),
            source_step_indices=deepcopy(action["source_step_indices"]), status="unknown")
            for index, action in enumerate(script["actions"])],
        oracles=[{key: assertion[key] for key in ("row_id", "action_index", "source_step_index", "oracle_digest")}
            | {"status": "unknown"} for assertion in script["assertions"]],
        status="outcome_unknown", reason="native_execution_receipt_missing", native_dispatch_verified=False,
        retry_requires_new_explicit_attempt=True,
        execution_authorized=False, business_coverage_verified=False, target_build_verified=False,
        automated_count=0, executed_on_target_count=0, passed_count=0)
    return {**value, "attempt_digest": acceptance_digest(value)}


def collect_run_plan_attempt_observations(plan, observations, unverified_attempts, *, run_id, timeout_ms):
    """Preserve submitted errors separately from missing and verified results."""
    verified = collect_run_plan_observations(plan, observations)
    _require(type(unverified_attempts) is list and len(unverified_attempts) <= len(plan["prepared"]["cases"]))
    jobs = {item["metadata"]["case_id"]: item for item in compile_case_jobs(plan, run_id=run_id, timeout_ms=timeout_ms)}
    by_case = {item["case_id"]: item for item in observations}
    unknown = {}
    try:
        _require(all((item["run_id"], item["timeout_ms"]) == (run_id, timeout_ms) for item in observations))
        for item in unverified_attempts:
            ident = item["case_id"]
            _require(ident not in unknown and ident not in by_case)
            rebuilt = map_unverified_case_attempt(plan, jobs[ident], runner_status=item["runner_status"],
                runner_result_hash=item["runner_result_hash"])
            _require(acceptance_digest(rebuilt) == acceptance_digest(item))
            unknown[ident] = rebuilt
    except (ValueError, KeyError, TypeError, StopIteration, UnicodeError, RecursionError):
        raise RunPlanObservationInvalid("unverified RunPlan attempts cannot be completely matched") from None
    cases = [dict(case_id=case["case_id"], case_digest=acceptance_digest(case),
        status=by_case[case["case_id"]]["status"] if case["case_id"] in by_case else
            "outcome_unknown" if case["case_id"] in unknown else "not_observed",
        observation_digest=by_case[case["case_id"]]["observation_digest"] if case["case_id"] in by_case else None,
        attempt_digest=unknown[case["case_id"]]["attempt_digest"] if case["case_id"] in unknown else None)
        for case in plan["prepared"]["cases"]]
    value = {key: value for key, value in verified.items() if key not in {"schema", "cases", "collection_digest", "not_executed_case_count"}}
    value.update(schema=ATTEMPT_COLLECTION_SCHEMA, cases=cases, run_id=run_id, timeout_ms=timeout_ms,
        outcome_unknown_case_count=len(unknown), no_result_case_count=len(cases) - len(by_case) - len(unknown))
    return {**value, "collection_digest": acceptance_digest(value)}
