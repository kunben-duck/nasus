"""Original command recognition precedes private input reads, not execution consent renewal."""
from datetime import datetime

from .acceptance_specification import acceptance_digest
from .run_plan_case_execution import (
    RunPlanCaseExecutionInvalid, restore_case_scope, case_work_schema, execution_state,
    require_case_selection, require_id, verify_case_command_selection,
)


CASE_PREPARATION_SCHEMA = "nasus.run-plan-case-preparation.v1"
CASE_PREPARATION_BINDING_SCHEMA = "nasus.run-plan-case-preparation-binding.v1"
CASE_PREPARATION_MARKER = "case_claim_protocol"
FALSE_AUTHORITIES = ("business_coverage_verified", "canonical_execution_committed", "execution_authorized")


def verify_case_preparation(snapshot, selection, value):
    try:
        selection = require_case_selection(selection)
        if (type(value) is not dict or set(value) != {"schema", "invocation_id", "project_id", "run_id",
                "selection_digest", "command_digest", "actor_id", "confirmed_at", "recorded_at", *FALSE_AUTHORITIES}
                or value["schema"] != CASE_PREPARATION_SCHEMA
                or snapshot["input_payload"].get(CASE_PREPARATION_MARKER) != CASE_PREPARATION_SCHEMA
                or any(value[key] is not False for key in FALSE_AUTHORITIES)):
            raise RunPlanCaseExecutionInvalid("case preparation lost its original claim protocol")
        for key in ("invocation_id", "project_id", "run_id", "actor_id"):
            require_id(value[key])
        digest = verify_case_command_selection(snapshot, selection, actor_id=value["actor_id"],
            invocation_id=value["invocation_id"], historical=True)
        confirmed = datetime.fromisoformat(value["confirmed_at"])
        recorded = datetime.fromisoformat(value["recorded_at"])
        if (any(value[key] != selection[key] for key in ("project_id", "run_id"))
                or value["selection_digest"] != acceptance_digest(selection)
                or acceptance_digest({key: snapshot["input_payload"][key] for key in selection}) != value["selection_digest"]
                or value["command_digest"] != digest
                or value["confirmed_at"] != snapshot["input_payload"]["confirmed_at"]
                or recorded.tzinfo is None or not 0 <= (recorded - confirmed).total_seconds() <= 900):
            raise RunPlanCaseExecutionInvalid("case preparation lost its original request, actor or PostgreSQL claim time")
        return value
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise RunPlanCaseExecutionInvalid("original case preparation cannot be verified") from None


def verify_case_preparation_binding(preparation, work, value):
    try:
        scope = restore_case_scope(work["scope"])
        roster = tuple(work["roster"])
        execution_state(scope, roster, [], [], cancelled=False)
        if (type(value) is not dict or set(value) != {"schema", "invocation_id", "project_id", "run_id", "work_id",
                "preparation_digest", "work_digest", "recorded_at", *FALSE_AUTHORITIES}
                or value["schema"] != CASE_PREPARATION_BINDING_SCHEMA or work["schema"] != case_work_schema(scope)
                or any(value[key] is not False for key in FALSE_AUTHORITIES)
                or any(value[key] != preparation[key] or value[key] != work[key]
                    or value[key] != getattr(scope, key) for key in ("invocation_id", "project_id", "run_id"))
                or scope.actor_id != preparation["actor_id"] or scope.command_digest != preparation["command_digest"]
                or scope.request_digest != preparation["selection_digest"]
                or work["scope_digest"] != scope.digest or work["work_id"] != scope.work_id
                or value["work_id"] != scope.work_id or work["roster_digest"] != acceptance_digest(roster)
                or [item["case_id"] for item in roster] != [item["case_id"] for item in scope.selection["fixture_setups"]]
                or any(work[key] != getattr(scope, key) for key in ("actor_id", "run_plan_id", "run_plan_artifact_hash",
                    "plan_digest", "image_revision_id", "manifest_id"))
                or value["preparation_digest"] != acceptance_digest(preparation)
                or value["work_digest"] != acceptance_digest(work) or value["recorded_at"] != work["recorded_at"]
                or datetime.fromisoformat(value["recorded_at"]) < datetime.fromisoformat(preparation["recorded_at"])):
            raise RunPlanCaseExecutionInvalid("case preparation binding cannot replace its original command or work")
        return value
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise RunPlanCaseExecutionInvalid("original case preparation binding cannot be verified") from None
