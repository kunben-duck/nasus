"""Canonical lifecycle delegates effects to the fenced original-operation worker."""
import asyncio
import logging
from typing import Protocol

from ..platform.actor_context import actor_scope
from .http_fixture_execution import HttpFixtureExecutionSelection
from .http_fixture_history import HttpFixtureHistoryApplicationService, HttpFixtureHistoryRepositoryPort, HttpFixtureHistoryQuery, HttpFixtureHistoryTarget
from .http_fixture_diagnostics import fixture_phase
from .test_design_output import GenerationValue, Id
from .worker_threads import run_worker_thread
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid
from ...domain.system_image.source_access import SourceAccessDenied

logger = logging.getLogger(__name__)


class HttpFixtureJobTarget(GenerationValue):
    project_id: Id
    invocation_id: Id


class HttpFixtureJobRepositoryPort(HttpFixtureHistoryRepositoryPort, Protocol):
    def execution(self, invocation_id): ...
    def command(self, invocation_id): ...
    def delivery(self, invocation_id): ...
    def failure_command(self, invocation_id): ...
    def bind(self, inputs, authority, *, require_current): ...
    def require_running(self, selection, authority, actor_id): ...
    def preparation_state(self, inputs, authority): ...
    def state(self, inputs, authority, history): ...
    def finish(self, authority, status, *, inputs=None, history=None, require_current=None): ...
    def cancel(self, target, *, control_id, actor_id, require_current): ...
    def cancellation_delivered(self, target): ...


class HttpFixtureWorkflowPort(Protocol):
    async def start(self, invocation_id): ...
    async def cancel(self, invocation_id): ...


class HttpFixtureJobApplicationService:
    def __init__(self, execution, repository: HttpFixtureJobRepositoryPort, workflow: HttpFixtureWorkflowPort):
        self.execution, self.repository, self.workflow = execution, repository, workflow
        self.grants = execution.grants
        self.history = HttpFixtureHistoryApplicationService(self, repository)
        from .http_fixture_observations import HttpFixtureObservationApplicationService
        self.observations = HttpFixtureObservationApplicationService(self)

    def _access(self, project_id):
        access = self.grants.authorization.scope(project_id)
        if access.effective_project_role not in {"project_admin", "platform_admin"}:
            raise SourceAccessDenied("fixture lifecycle requires a current project administrator")
        return access

    def _prepare(self, selection, invocation_id):
        with fixture_phase("prepare_access"):
            access = self._access(selection.project_id)
        with fixture_phase("prepare_original_command"):
            original, actor, authority = self.repository.execution(invocation_id)
            if original != selection or actor.id != access.actor_id:
                raise HttpFixtureInvalid("fixture dispatch cannot replace the original command or confirming actor")

        def current():
            self.grants.authorization.require_current(access)
            self.repository.require_running(selection, authority, access.actor_id)

        with fixture_phase("prepare_current_authority"):
            current()
        with fixture_phase("prepare_inputs"):
            inputs = self.grants.execution_inputs(selection, live=True)
        with fixture_phase("prepare_binding"):
            self.repository.bind(inputs, authority, require_current=current)
        with fixture_phase("prepare_final_authority"):
            current()
        return authority

    async def dispatch(self, selection, invocation_id):
        selection = HttpFixtureExecutionSelection.model_validate(selection.model_dump(mode="json"))
        authority = await run_worker_thread(lambda: self._prepare(selection, invocation_id))
        # An unknown acknowledgement is redelivered with this same workflow ID.
        await self._start_original(invocation_id, authority)

    async def _start_original(self, invocation_id, authority):
        with fixture_phase("workflow_delivery"):
            delivery = await run_worker_thread(lambda: self.repository.delivery(invocation_id))
        if delivery["authority"] != authority:
            raise HttpFixtureInvalid("fixture workflow delivery lost its original preparation input")
        if delivery["status"] != "running":
            return delivery["status"]
        if not delivery["bound"]:
            raise HttpFixtureInvalid("fixture workflow cannot start before its durable original binding")
        with fixture_phase("workflow_start"):
            started = await self.workflow.start(invocation_id)
        if not started:
            return await self.fail(invocation_id)
        return "running"

    async def deliver(self, invocation_id):
        delivery = await run_worker_thread(lambda: self.repository.delivery(invocation_id))
        if delivery["status"] != "running":
            return delivery["status"]
        if not delivery["bound"]:
            try:
                selection, actor, authority = await run_worker_thread(lambda: self.repository.execution(invocation_id))
                if authority != delivery["authority"]:
                    raise HttpFixtureInvalid("fixture preparation delivery cannot replace its original input")
                with actor_scope(actor):
                    await run_worker_thread(lambda: self._prepare(selection, invocation_id))
            except (ValueError, KeyError, PermissionError):
                return await self.fail(invocation_id)
        # Do not turn transient preparation/RPC faults into failure or create a
        # new attempt. The reconciler retries only this same canonical identity.
        return await self._start_original(invocation_id, delivery["authority"])

    def _read(self, target):
        access = self._access(target.project_id)
        selection, _, authority = self.repository.command(target.invocation_id)
        if selection.project_id != target.project_id:
            raise SourceAccessDenied("fixture command belongs to another project")
        current = lambda: self.grants.authorization.require_current(access)
        current()
        inputs = self.grants.execution_inputs(selection, live=False)
        preparation = self.repository.preparation_state(inputs, authority)
        if preparation is not None:
            current()
            return preparation
        history = self.execution.read(selection, require_current=current)
        result = self.repository.state(inputs, authority, history)
        current()
        return result

    def read(self, target):
        return self._read(HttpFixtureJobTarget.model_validate(target.model_dump(mode="json")))

    def authorize_receipts(self, invocations):
        from ..platform.errors import PlatformApplicationError
        from ..platform.tool_handlers.query_input import query_payload
        from ...domain.quality_loop.acceptance_specification import acceptance_digest
        from ...domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_QUERY_TOOL

        if len(invocations) > 128:
            raise PlatformApplicationError("fixture_receipt_unavailable", "Fixture receipt batch is too large.", 503)
        for invocation in invocations:
            value = {key: item for key, item in query_payload(invocation.input_payload).items()
                if key not in {"confirmed_by_user", "confirmed_at"}}
            from ...domain.quality_loop.http_fixture_history import FIXTURE_HISTORY_TOOLS, FIXTURE_HISTORY_LIST_TOOL
            from ...domain.quality_loop.http_fixture_observation import FIXTURE_OBSERVATION_TOOL
            if invocation.tool_id == FIXTURE_OBSERVATION_TOOL:
                from ...domain.quality_loop.http_fixture_observation import HttpFixtureObservationChanged
                target = HttpFixtureHistoryTarget.model_validate(value)
                receipt = invocation.result.http_fixture_observation if invocation.result is not None else None
                if invocation.status == "completed":
                    if (invocation.result is None or invocation.result.invocation_id != invocation.id
                            or invocation.result.status != "completed" or receipt is None
                            or invocation.result.http_fixture_job is not None or invocation.result.http_fixture_history is not None
                            or invocation.result.object_refs):
                        raise HttpFixtureInvalid("original journal query is missing its exact observation")
                    try:
                        self.observations.verify_receipt(target, receipt)
                    except HttpFixtureObservationChanged as exc:
                        raise PlatformApplicationError("fixture_observation_changed",
                            "Original journal changed; explicitly inspect the same command again.", 409) from exc
                else:
                    if receipt is not None:
                        raise HttpFixtureInvalid("unfinished journal query cannot invent an observation")
                    self.observations.read(target)
                continue
            if invocation.result is not None and invocation.result.http_fixture_observation is not None:
                raise HttpFixtureInvalid("another fixture command cannot contain an original journal query receipt")
            if invocation.tool_id in FIXTURE_HISTORY_TOOLS:
                target = (HttpFixtureHistoryQuery if invocation.tool_id == FIXTURE_HISTORY_LIST_TOOL
                    else HttpFixtureHistoryTarget).model_validate(value)
                receipt = invocation.result.http_fixture_history if invocation.result is not None else None
                if invocation.status == "completed":
                    if (invocation.result is None or invocation.result.invocation_id != invocation.id
                            or invocation.result.status != "completed" or receipt is None):
                        raise HttpFixtureInvalid("fixture history query is missing its exact original observation")
                    self.history.verify_receipt(target, receipt)
                else:
                    if receipt is not None:
                        raise HttpFixtureInvalid("unfinished fixture discovery cannot invent a completed observation")
                    (self.history.list if invocation.tool_id == FIXTURE_HISTORY_LIST_TOOL else self.history.read)(target)
                continue
            if invocation.tool_id == FIXTURE_COMMAND_TOOL:
                selection = HttpFixtureExecutionSelection.model_validate(value)
            else:
                target = HttpFixtureJobTarget.model_validate(value)
                selection, _, _ = self.repository.command(target.invocation_id)
                if selection.project_id != target.project_id:
                    raise SourceAccessDenied("fixture receipt belongs to another project")
            access = self._access(selection.project_id)
            self.grants.execution_inputs(selection, live=False)
            result = invocation.result
            receipt = result.http_fixture_job if result is not None else None
            if receipt is not None and (invocation.tool_id != FIXTURE_QUERY_TOOL or invocation.status != "completed"):
                raise HttpFixtureInvalid("fixture write status cannot contain an invented observation")
            if invocation.status == "completed":
                if result is None or result.invocation_id != invocation.id or result.status != "completed":
                    raise HttpFixtureInvalid("completed fixture receipt is missing its exact result")
                if invocation.tool_id == FIXTURE_QUERY_TOOL:
                    if type(receipt) is not dict:
                        raise HttpFixtureInvalid("fixture query is missing its exact observation")
                    if acceptance_digest(receipt) != acceptance_digest(self.read(target)):
                        raise PlatformApplicationError("fixture_observation_changed",
                            "Original fixture state changed; explicitly inspect it again.", 409)
            self.grants.authorization.require_current(access)

    async def run(self, invocation_id):
        with fixture_phase("worker_command"):
            selection, status, authority = await run_worker_thread(lambda: self.repository.command(invocation_id))
        if status != "running":
            return status
        with fixture_phase("worker_original_command"):
            original, actor, current_authority = await run_worker_thread(lambda: self.repository.execution(invocation_id))
            if original != selection or current_authority != authority:
                raise HttpFixtureInvalid("fixture workflow cannot adopt a changed canonical command")
        with actor_scope(actor):
            with fixture_phase("worker_access"):
                access = await run_worker_thread(lambda: self._access(selection.project_id))

            def current():
                self.grants.authorization.require_current(access)
                self.repository.require_running(selection, authority, actor.id)

            with fixture_phase("worker_execute"):
                await self.execution.execute(selection, require_current=current, command_authority=authority)
            # Re-read the complete original archive; a worker return value is not
            # itself durable output, and unknown phases cannot become completion.
            with fixture_phase("worker_archive_inputs"):
                inputs = await run_worker_thread(lambda: self.grants.execution_inputs(selection, live=False))
            with fixture_phase("worker_archive_history"):
                history = await run_worker_thread(lambda: self.execution.read(selection, require_current=current))
            with fixture_phase("worker_commit"):
                return await run_worker_thread(lambda: self.repository.finish(authority, "completed",
                    inputs=inputs, history=history, require_current=current))

    async def fail(self, invocation_id):
        status, authority = await run_worker_thread(lambda: self.repository.failure_command(invocation_id))
        if status != "running":
            return status
        # The repository refuses to terminate a still-owned operation. Activity
        # failure delivery must wait for its original lease to expire.
        return await run_worker_thread(lambda: self.repository.finish(authority, "failed"))

    async def cancel(self, target, *, control_id):
        target = HttpFixtureJobTarget.model_validate(target.model_dump(mode="json"))
        access = await run_worker_thread(lambda: self._access(target.project_id))
        await run_worker_thread(lambda: self.read(target))
        status = await run_worker_thread(lambda: self.repository.cancel(target, control_id=control_id,
            actor_id=access.actor_id, require_current=lambda: self.grants.authorization.require_current(access)))
        if status == "cancelled":
            try:
                await self.workflow.cancel(target.invocation_id)
                await run_worker_thread(lambda: self.repository.cancellation_delivered(target))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Fixture cancellation delivery deferred")
        return status
