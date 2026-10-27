"""Original confirmed cancellation verification; no target I/O or consent renewal."""
from datetime import datetime

from ...application.platform.tool_handlers.query_input import query_payload
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from ...domain.quality_loop.run_plan_case_job import (
    CASE_JOB_CANCELLATION_SCHEMA, CASE_JOB_DELIVERY_SCHEMA, verify_case_job_cancellation,
)
from .db_models import ToolInvocationRecord
from .run_plan_case_job_models import RunPlanCaseJobCancellationRecord as Cancellation, RunPlanCaseJobCancellationDeliveryRecord as Delivery
from .run_plan_case_preparation_repository import RunPlanCasePreparationJournal as PreparationJournal
from .test_design_result_repository import TestDesignResultRepository


class RunPlanCaseCancellationJournal:
    @classmethod
    def verify(cls, session, command):
        row, delivery = session.get(Cancellation, command.id), session.get(Delivery, command.id)
        if row is None:
            if delivery is not None:
                raise RunPlanCaseExecutionInvalid("case cancellation delivery lost its original request")
            return None
        preparation = PreparationJournal.verify(session, command)
        value = PreparationJournal._payload(row, CASE_JOB_CANCELLATION_SCHEMA)
        control = session.get(ToolInvocationRecord, value["control_id"])
        if preparation is None or control is None or command.status != "cancelled":
            raise RunPlanCaseExecutionInvalid("case cancellation lost its original command state")
        target = {key: value[key] for key in ("project_id", "invocation_id")}
        request = {key: item for key, item in query_payload(control.input_payload).items()
            if key not in {"confirmed_by_user", "confirmed_at"}}
        if request != target:
            raise RunPlanCaseExecutionInvalid("case cancellation control selected another original command")
        TestDesignResultRepository._project_scope(session, control, target["project_id"])
        snapshot = PreparationJournal.snapshot(control)
        verify_case_job_cancellation(preparation, snapshot, value)
        if delivery is not None:
            delivered = PreparationJournal._payload(delivery, CASE_JOB_DELIVERY_SCHEMA)
            if (set(delivered) != {"schema", "invocation_id", "project_id", "cancellation_digest", "recorded_at"}
                    or delivered["project_id"] != value["project_id"] or delivered["invocation_id"] != command.id
                    or delivered["cancellation_digest"] != acceptance_digest(value)
                    or datetime.fromisoformat(delivered["recorded_at"]) < datetime.fromisoformat(value["recorded_at"])):
                raise RunPlanCaseExecutionInvalid("case cancellation delivery cannot replace its original request")
        return value
