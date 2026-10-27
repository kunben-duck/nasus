"""Original claim and work receipt verification in the caller's PostgreSQL transaction."""
from copy import deepcopy

from sqlalchemy import func, select

from ...application.platform.tool_handlers.query_input import query_payload
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.run_plan_case_execution import (
    CASE_EXECUTE_TOOL, case_work_schema, restore_case_scope, RunPlanCaseExecutionInvalid, require_case_selection, require_id,
)
from ...domain.quality_loop.run_plan_case_preparation import (
    CASE_PREPARATION_SCHEMA, CASE_PREPARATION_BINDING_SCHEMA, CASE_PREPARATION_MARKER, FALSE_AUTHORITIES,
    verify_case_preparation, verify_case_preparation_binding,
)
from .db_models import ToolInvocationRecord
from .run_plan_case_execution_models import RunPlanCaseWorkRecord as Work
from .run_plan_case_preparation_models import RunPlanCasePreparationRecord as Preparation, RunPlanCasePreparationBindingRecord as Binding
from .test_design_result_repository import TestDesignResultRepository
from .unit_of_work import session_scope


class RunPlanCasePreparationJournal:
    @staticmethod
    def selection(command):
        if command is None or command.tool_id != CASE_EXECUTE_TOOL or type(command.input_payload) is not dict:
            raise RunPlanCaseExecutionInvalid("case claim requires its original independent command")
        return require_case_selection({key: value for key, value in query_payload(command.input_payload).items()
            if key not in {"confirmed_by_user", "confirmed_at"}})

    @staticmethod
    def snapshot(command):
        return deepcopy({key: getattr(command, key) for key in ("id", "tool_id", "status", "input_payload")})

    @staticmethod
    def _work_id(selection):
        return "case_work_" + acceptance_digest([selection["project_id"], selection["run_id"]])[7:]

    @staticmethod
    def _payload(row, schema):
        if row is None:
            raise RunPlanCaseExecutionInvalid("original case preparation receipt is missing")
        value = row.payload
        columns = set(row.__table__.columns.keys()) - {"payload", "content_hash"}
        if (type(value) is not dict or value.get("schema") != schema or acceptance_digest(value) != row.content_hash
                or any(getattr(row, key) != value.get(key) for key in columns)):
            raise RunPlanCaseExecutionInvalid("case preparation columns differ from their immutable original payload")
        return deepcopy(value)

    @staticmethod
    def _row(model, value):
        columns = set(model.__table__.columns.keys()) - {"payload", "content_hash"}
        return model(**{key: value[key] for key in columns}, payload=deepcopy(value), content_hash=acceptance_digest(value))

    @staticmethod
    def _work(row):
        columns = set(row.__table__.columns.keys()) - {"content_hash"}
        value = {"schema": case_work_schema(restore_case_scope(row.scope)),
            **{key: deepcopy(getattr(row, key)) for key in columns}}
        if acceptance_digest(value) != row.content_hash:
            raise RunPlanCaseExecutionInvalid("case preparation lost its original complete work")
        return value

    def record(self, session, command):
        if command.tool_id != CASE_EXECUTE_TOOL:
            return
        selection = self.selection(command)
        if (command.status != "running" or CASE_PREPARATION_MARKER in command.input_payload
                or session.get(Preparation, command.id) is not None or session.get(Binding, command.id) is not None
                or session.get(Work, self._work_id(selection)) is not None):
            raise RunPlanCaseExecutionInvalid("case preparation cannot reopen, adopt or repair an original attempt")
        snapshot = self.snapshot(command)
        snapshot["input_payload"][CASE_PREPARATION_MARKER] = CASE_PREPARATION_SCHEMA
        value = {"schema": CASE_PREPARATION_SCHEMA, "invocation_id": command.id,
            "project_id": selection["project_id"], "run_id": selection["run_id"],
            "selection_digest": acceptance_digest(selection),
            "command_digest": acceptance_digest({"tool_id": command.tool_id, "input_payload": snapshot["input_payload"]}),
            "actor_id": command.input_payload.get("confirmed_actor_id"),
            "confirmed_at": command.input_payload.get("confirmed_at"),
            "recorded_at": session.scalar(select(func.clock_timestamp())).isoformat(),
            **{key: False for key in FALSE_AUTHORITIES}}
        verify_case_preparation(snapshot, selection, value)
        TestDesignResultRepository._project_scope(session, command, selection["project_id"])
        command.input_payload = snapshot["input_payload"]
        session.add(self._row(Preparation, value))

    @classmethod
    def verify(cls, session, command):
        if command is None or type(command.input_payload) is not dict:
            raise RunPlanCaseExecutionInvalid("original case command is missing")
        row, binding = session.get(Preparation, command.id), session.get(Binding, command.id)
        marker = command.input_payload.get(CASE_PREPARATION_MARKER)
        if marker is None and row is None and binding is None:
            return None
        if marker != CASE_PREPARATION_SCHEMA:
            raise RunPlanCaseExecutionInvalid("case preparation cannot downgrade to an unrecorded legacy command")
        selection = cls.selection(command)
        preparation = cls._payload(row, CASE_PREPARATION_SCHEMA)
        verify_case_preparation(cls.snapshot(command), selection, preparation)
        TestDesignResultRepository._project_scope(session, command, preparation["project_id"])
        work = session.get(Work, cls._work_id(selection))
        if (work is None) != (binding is None):
            raise RunPlanCaseExecutionInvalid("case preparation/work binding is incomplete; never repair history")
        if work is not None:
            verify_case_preparation_binding(preparation, cls._work(work), cls._payload(binding, CASE_PREPARATION_BINDING_SCHEMA))
        return preparation

    @classmethod
    def bind(cls, session, command, preparation, work):
        if preparation is None:
            return
        original = cls._payload(session.get(Preparation, command.id), CASE_PREPARATION_SCHEMA)
        verify_case_preparation(cls.snapshot(command), cls.selection(command), original)
        if original != preparation or session.get(Binding, command.id) is not None:
            raise RunPlanCaseExecutionInvalid("case work cannot replace or recreate its original preparation binding")
        value = {"schema": CASE_PREPARATION_BINDING_SCHEMA,
            **{key: work[key] for key in ("invocation_id", "project_id", "run_id", "work_id", "recorded_at")},
            "preparation_digest": acceptance_digest(original), "work_digest": acceptance_digest(work),
            **{key: False for key in FALSE_AUTHORITIES}}
        verify_case_preparation_binding(original, work, value)
        session.add(cls._row(Binding, value))


class RunPlanCasePreparationRepository:
    """Worker-only discovery; this is not a public history or permission-grant endpoint."""
    def delivery(self, invocation_id):
        require_id(invocation_id)
        with session_scope() as session:
            command = session.get(ToolInvocationRecord, invocation_id)
            preparation = RunPlanCasePreparationJournal.verify(session, command)
            if preparation is None:
                raise RunPlanCaseExecutionInvalid("legacy case commands cannot be promoted to recoverable preparation")
            return {"status": command.status, "invocation_id": invocation_id,
                "project_id": preparation["project_id"], "run_id": preparation["run_id"],
                "command_digest": preparation["command_digest"],
                "bound": session.get(Binding, invocation_id) is not None,
                **{key: False for key in FALSE_AUTHORITIES}}

    def pending(self, *, after_id=None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise RunPlanCaseExecutionInvalid("case preparation discovery requires a bounded page")
        if after_id is not None:
            require_id(after_id)
        with session_scope() as session:
            query = select(Preparation.invocation_id).join(ToolInvocationRecord,
                Preparation.invocation_id == ToolInvocationRecord.id).where(
                ToolInvocationRecord.tool_id == CASE_EXECUTE_TOOL, ToolInvocationRecord.status == "running")
            if after_id is not None:
                query = query.where(Preparation.invocation_id > after_id)
            return tuple(session.scalars(query.order_by(Preparation.invocation_id).limit(limit)).all())
