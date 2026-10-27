"""Canonical case lifecycle identities; cancellation fences work, never rolls back effects."""
from datetime import datetime

from .acceptance_specification import acceptance_digest
from .run_plan_case_execution import CASE_CANCEL_TOOL, CASE_EXECUTE_TOOL, RunPlanCaseExecutionInvalid, require_id


CASE_JOB_QUERY_TOOL = "query.quality.run_plan_case_execution"
CASE_JOB_TOOLS = frozenset({CASE_EXECUTE_TOOL, CASE_CANCEL_TOOL, CASE_JOB_QUERY_TOOL})
CASE_JOB_CANCELLATION_SCHEMA = "nasus.run-plan-case-job-cancellation.v1"
CASE_JOB_DELIVERY_SCHEMA = "nasus.run-plan-case-job-cancel-delivery.v1"


def verify_case_job_control(snapshot, target, *, actor_id, now=None, historical=False):
    try:
        if type(target) is not dict or set(target) != {"project_id", "invocation_id"}:
            raise RunPlanCaseExecutionInvalid("case cancellation must identify the exact original command")
        for ident in (*target.values(), actor_id, snapshot["id"]):
            require_id(ident)
        payload = snapshot["input_payload"]
        if (type(snapshot) is not dict or set(snapshot) != {"id", "tool_id", "status", "input_payload"}
                or snapshot["tool_id"] != CASE_CANCEL_TOOL
                or snapshot["status"] not in ({"running", "completed", "failed", "cancelled"} if historical else {"running"})
                or type(payload) is not dict or payload.get("confirmed_by_user") is not True
                or payload.get("confirmed_actor_id") != actor_id
                or any(payload.get(key) != value for key, value in target.items())):
            raise RunPlanCaseExecutionInvalid("case cancellation requires its unchanged independent confirmation")
        confirmed = datetime.fromisoformat(payload["confirmed_at"])
        if confirmed.tzinfo is None or (not historical and (now is None or now.tzinfo is None
                or not 0 <= (now - confirmed).total_seconds() <= 900)):
            raise RunPlanCaseExecutionInvalid("case cancellation consent must be fresh by PostgreSQL time")
        return acceptance_digest({"tool_id": snapshot["tool_id"], "input_payload": payload})
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise RunPlanCaseExecutionInvalid("original case cancellation cannot be verified") from None


def verify_case_job_cancellation(preparation, control, value):
    try:
        if (type(value) is not dict or set(value) != {"schema", "invocation_id", "project_id", "control_id", "actor_id",
                "command_digest", "preparation_digest", "control_digest", "recorded_at", "status"}
                or value["schema"] != CASE_JOB_CANCELLATION_SCHEMA or value["status"] != "cancelled"
                or any(value[key] != preparation[key] for key in ("invocation_id", "project_id", "command_digest"))
                or value["control_id"] != control["id"]
                or value["preparation_digest"] != acceptance_digest(preparation)):
            raise RunPlanCaseExecutionInvalid("case cancellation lost its original preparation or control")
        target = {key: value[key] for key in ("project_id", "invocation_id")}
        recorded = datetime.fromisoformat(value["recorded_at"])
        digest = verify_case_job_control(control, target, actor_id=value["actor_id"], historical=True)
        confirmed = datetime.fromisoformat(control["input_payload"]["confirmed_at"])
        if (recorded.tzinfo is None or not 0 <= (recorded - confirmed).total_seconds() <= 900
                or digest != value["control_digest"] or recorded < datetime.fromisoformat(preparation["recorded_at"])):
            raise RunPlanCaseExecutionInvalid("case cancellation cannot precede or replace its original command")
        return value
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise RunPlanCaseExecutionInvalid("original case cancellation history cannot be verified") from None
