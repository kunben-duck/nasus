"""Independent canonical command lifecycle around the original fenced case worker."""
import logging
from typing import Protocol
from pydantic import model_validator

from ..platform.actor_context import actor_scope
from ..platform.tool_handlers.query_input import query_payload
from .run_plan_case_inputs import RunPlanCaseExecutionSelection
from .test_design_output import GenerationValue, Id
from .worker_threads import run_worker_thread
from ...domain.quality_loop.run_plan_case_execution import CASE_EXECUTE_TOOL, RunPlanCaseExecutionInvalid, require_id
from ...domain.quality_loop.run_plan_case_job import CASE_JOB_TOOLS
from ...domain.system_image.source_access import SourceAccessDenied

logger = logging.getLogger(__name__)


class RunPlanCaseJobTarget(GenerationValue):
    project_id: Id
    invocation_id: Id

    @model_validator(mode="after")
    def original_ids(self):
        require_id(self.project_id)
        require_id(self.invocation_id)
        return self


class RunPlanCaseJobRepositoryPort(Protocol):
    def command(self, target): ...
    def execution(self, invocation_id, *, require_actor=True): ...
    def require_running(self, selection, invocation_id, command_digest, actor_id): ...
    def finish(self, invocation_id, command_digest, status, *, history=None, require_access=None): ...
    def cancel(self, target, *, control_id, actor_id, require_current): ...
    def cancellation_delivered(self, invocation_id): ...


class RunPlanCaseWorkflowPort(Protocol):
    async def start(self, invocation_id): ...
    async def cancel(self, invocation_id): ...


class RunPlanCaseJobApplicationService:
    def __init__(self, cases, repository: RunPlanCaseJobRepositoryPort, workflow: RunPlanCaseWorkflowPort):
        self.cases, self.repository, self.workflow = cases, repository, workflow
        self.inputs, self.authorization = cases.inputs, cases.inputs.authorization

    def _access(self, project_id):
        access = self.authorization.scope(project_id)
        if access.effective_project_role not in {"project_admin", "platform_admin"}:
            raise SourceAccessDenied("original case lifecycle requires current fixture administrator access")
        self.authorization.require_current(access)
        return access

    def _metadata(self, target):
        access = self._access(target.project_id)
        original = self.repository.command(target)
        self.inputs.require_plan_access(original["selection"])
        self.authorization.require_current(access)
        return access, original

    def read(self, target: RunPlanCaseJobTarget):
        access, original = self._metadata(target)
        history = self.cases.read(original["scope"]) if original["scope"] is not None else None
        if self.repository.command(target) != original:
            raise RunPlanCaseExecutionInvalid("original case lifecycle changed while reading; inspect the same command again")
        self.authorization.require_current(access)
        return {"project_id": target.project_id, "invocation_id": target.invocation_id,
            "run_id": original["selection"].run_id, "status": original["status"], "bound": original["scope"] is not None,
            "history": history, "historical_not_live": True, "business_coverage_verified": False,
            "canonical_execution_committed": False}

    def metadata(self, target):
        value = self.read(target)
        history = value["history"]
        state = history["state"] if history is not None else None
        return {**{key: item for key, item in value.items() if key != "history"},
            "execution_state": state["state"] if state else "cancelled" if value["status"] == "cancelled" else
                "not_dispatched" if value["status"] == "failed" else "preparing",
            **{key: state[key] if state else None for key in
                ("case_count", "observed_case_count", "outcome_unknown_case_count", "not_dispatched_case_count")}}

    def authorize_receipts(self, invocations):
        if not 1 <= len(invocations) <= 128:
            raise RunPlanCaseExecutionInvalid("case receipt authorization requires a bounded original cohort")
        for invocation in invocations:
            if invocation.tool_id not in CASE_JOB_TOOLS:
                raise RunPlanCaseExecutionInvalid("case receipt belongs to another command surface")
            value = {key: item for key, item in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            if invocation.tool_id == CASE_EXECUTE_TOOL:
                selection = RunPlanCaseExecutionSelection.model_validate(value)
                access = self._access(selection.project_id)
                self.inputs.require_plan_access(selection)
                if invocation.status in {"running", "completed", "failed", "cancelled"}:
                    original = self.repository.command(RunPlanCaseJobTarget(project_id=selection.project_id, invocation_id=invocation.id))
                    if original["selection"] != selection:
                        raise RunPlanCaseExecutionInvalid("case receipt selection differs from the original command")
            else:
                target = RunPlanCaseJobTarget.model_validate(value)
                access, original = self._metadata(target)
                receipt = getattr(invocation.result, "run_plan_case_job", None) if invocation.result is not None else None
                if receipt is not None:
                    fields = {"project_id", "invocation_id", "run_id", "status", "bound", "historical_not_live",
                        "business_coverage_verified", "canonical_execution_committed", "execution_state", "case_count",
                        "observed_case_count", "outcome_unknown_case_count", "not_dispatched_case_count"}
                    if (type(receipt) is not dict or set(receipt) != fields or receipt.get("project_id") != target.project_id
                            or receipt.get("invocation_id") != target.invocation_id or receipt.get("run_id") != original["selection"].run_id
                            or receipt.get("historical_not_live") is not True or receipt.get("business_coverage_verified") is not False
                            or receipt.get("canonical_execution_committed") is not False or type(receipt.get("bound")) is not bool
                            or receipt.get("status") not in {"running", "completed", "failed", "cancelled"}
                            or receipt.get("execution_state") not in {"preparing", "not_dispatched", "partially_observed",
                                "observed", "outcome_unknown", "cancelled"}):
                        raise RunPlanCaseExecutionInvalid("case metadata receipt cannot import private observations or authority")
                    counts = [receipt[key] for key in ("case_count", "observed_case_count", "outcome_unknown_case_count", "not_dispatched_case_count")]
                    if receipt["bound"]:
                        if (original["scope"] is None or any(type(value) is not int or not 0 <= value <= 512 for value in counts)
                                or counts[0] != len(original["scope"].selection["fixture_setups"]) or sum(counts[1:]) != counts[0]):
                            raise RunPlanCaseExecutionInvalid("case receipt cannot change the original complete denominator")
                        expected = ("outcome_unknown" if counts[2] else "observed" if counts[1] == counts[0]
                            else "cancelled" if receipt["status"] == "cancelled" else "partially_observed" if counts[1]
                            else "not_dispatched")
                        if (receipt["execution_state"] != expected
                                or (receipt["status"] == "completed" and expected != "observed")):
                            raise RunPlanCaseExecutionInvalid("case metadata cannot present partial or unknown output as completion")
                    else:
                        expected = {"running": "preparing", "failed": "not_dispatched", "cancelled": "cancelled"}.get(receipt["status"])
                        if any(value is not None for value in counts) or expected is None or receipt["execution_state"] != expected:
                            raise RunPlanCaseExecutionInvalid("unbound case receipt must preserve unknown counts and original lifecycle")
            self.authorization.require_current(access)

    async def dispatch(self, selection: RunPlanCaseExecutionSelection, invocation_id):
        selection = RunPlanCaseExecutionSelection.model_validate(selection.model_dump(mode="json"))
        def original():
            access, command = self._metadata(RunPlanCaseJobTarget(project_id=selection.project_id, invocation_id=invocation_id))
            if command["selection"] != selection or command["actor_id"] != access.actor_id:
                raise RunPlanCaseExecutionInvalid("case dispatch cannot substitute the original selection or confirming actor")
            self.repository.require_running(selection, invocation_id, command["command_digest"], access.actor_id)
            return command
        command = await run_worker_thread(original)
        return await self._start(command)

    async def _start(self, command):
        target = RunPlanCaseJobTarget(project_id=command["selection"].project_id, invocation_id=command["invocation_id"])
        latest = await run_worker_thread(lambda: self.repository.command(target))
        if latest["command_digest"] != command["command_digest"]:
            raise RunPlanCaseExecutionInvalid("case workflow delivery cannot replace its original confirmed command")
        if latest["status"] != "running":
            return latest["status"]
        if not await self.workflow.start(command["invocation_id"]):
            return await self.fail(command["invocation_id"])
        return "running"

    async def deliver(self, invocation_id):
        try:
            command, actor = await run_worker_thread(lambda: self.repository.execution(invocation_id))
        except PermissionError:
            return await self.fail(invocation_id)
        if command["status"] != "running":
            return command["status"]
        with actor_scope(actor):
            try:
                access, current = await run_worker_thread(lambda: self._metadata(RunPlanCaseJobTarget(
                    project_id=command["selection"].project_id, invocation_id=invocation_id)))
                await run_worker_thread(lambda: self.repository.require_running(current["selection"], invocation_id,
                    current["command_digest"], access.actor_id))
            except (ValueError, KeyError, PermissionError):
                return await self.fail(invocation_id)
            return await self._start(current)

    async def run(self, invocation_id):
        command, actor = await run_worker_thread(lambda: self.repository.execution(invocation_id))
        if command["status"] != "running":
            return command["status"]
        target = RunPlanCaseJobTarget(project_id=command["selection"].project_id, invocation_id=invocation_id)
        with actor_scope(actor):
            if command["scope"] is not None:
                history = await run_worker_thread(lambda: self.cases.read(command["scope"]))
                if history["state"]["state"] in {"observed", "outcome_unknown", "cancelled"}:
                    # A retry inspects the existing slot before acquiring a new
                    # lease. Unknown effects must not renew ownership and resend.
                    return await self._finish(command, history)
            await self.cases.execute(command["selection"], invocation_id=invocation_id)
            latest = await run_worker_thread(lambda: self.repository.command(target))
            if latest["status"] != "running":
                return latest["status"]
            if latest["scope"] is None:
                raise RunPlanCaseExecutionInvalid("case worker returned without its durable original work")
            history = await run_worker_thread(lambda: self.cases.read(latest["scope"]))
            return await self._finish(latest, history)

    async def _finish(self, command, history):
        status = "completed" if history["state"]["state"] == "observed" else "failed"
        def current():
            self.inputs.historical_inputs(command["scope"])
        return await run_worker_thread(lambda: self.repository.finish(command["invocation_id"], command["command_digest"],
            status, history=history, require_access=current))

    async def fail(self, invocation_id):
        command, _actor = await run_worker_thread(lambda: self.repository.execution(invocation_id, require_actor=False))
        return await run_worker_thread(lambda: self.repository.finish(invocation_id, command["command_digest"], "failed"))

    async def cancel(self, target, *, control_id):
        access, original = await run_worker_thread(lambda: self._metadata(target))
        def current():
            self.authorization.require_current(access)
            self.inputs.require_plan_access(original["selection"])
        status = await run_worker_thread(lambda: self.repository.cancel(target, control_id=control_id,
            actor_id=access.actor_id, require_current=current))
        if status == "cancelled":
            try:
                await self.workflow.cancel(target.invocation_id)
                await run_worker_thread(lambda: self.repository.cancellation_delivered(target.invocation_id))
            except Exception:
                logger.warning("Original case cancellation delivery deferred; durable command remains fenced")
        return status
