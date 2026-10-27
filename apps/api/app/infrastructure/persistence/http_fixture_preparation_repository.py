"""Claim and binding receipts use the caller's original PostgreSQL transaction."""
from sqlalchemy import func, select

from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FALSE_AUTHORITIES
from ...domain.quality_loop.http_fixture_preparation import (
    PREPARATION_SCHEMA, PREPARATION_BINDING_SCHEMA, PREPARATION_MARKER,
    verify_preparation, verify_preparation_binding,
)
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid
from .http_fixture_preparation_models import HttpFixturePreparationRecord as Preparation, HttpFixturePreparationBindingRecord as Binding
from .test_design_result_repository import TestDesignResultRepository


class HttpFixturePreparationJournal:
    @staticmethod
    def _snapshot(command):
        return {key: getattr(command, key) for key in ("id", "tool_id", "status", "input_payload")}

    @staticmethod
    def _value(row):
        if row is None:
            raise HttpFixtureInvalid("original fixture preparation receipt is missing")
        columns = {column.name for column in row.__table__.columns} - {"payload", "content_hash"}
        if (type(row.payload) is not dict or acceptance_digest(row.payload) != row.content_hash
                or any(row.payload.get(key) != getattr(row, key) for key in columns)):
            raise HttpFixtureInvalid("original fixture preparation columns or bytes differ")
        return row.payload

    @staticmethod
    def _row(model, value):
        columns = {column.name for column in model.__table__.columns} - {"payload", "content_hash"}
        return model(**{key: value[key] for key in columns}, payload=value, content_hash=acceptance_digest(value))

    def record(self, session, command):
        if command.tool_id != FIXTURE_COMMAND_TOOL:
            return
        if (session.get(Preparation, command.id) is not None or session.get(Binding, command.id) is not None
                or PREPARATION_MARKER in command.input_payload):
            raise HttpFixtureInvalid("fixture execution claim cannot replace an existing preparation")
        command.input_payload = {**command.input_payload, PREPARATION_MARKER: PREPARATION_SCHEMA}
        value = {"schema": PREPARATION_SCHEMA, "invocation_id": command.id,
            "project_id": command.input_payload.get("project_id"),
            "request_digest": acceptance_digest({"tool_id": command.tool_id, "input_payload": command.input_payload}),
            "actor_id": command.input_payload.get("confirmed_actor_id"),
            "confirmed_at": command.input_payload.get("confirmed_at"),
            "recorded_at": session.scalar(select(func.clock_timestamp())).isoformat(),
            **{key: False for key in FALSE_AUTHORITIES}}
        verify_preparation(self._snapshot(command), value)
        TestDesignResultRepository._project_scope(session, command, value["project_id"])
        session.add(self._row(Preparation, value))

    @classmethod
    def verify(cls, session, command, *, intent=None):
        preparation = session.get(Preparation, command.id)
        binding = session.get(Binding, command.id)
        marker = command.input_payload.get(PREPARATION_MARKER)
        if marker is None and preparation is None and binding is None:
            return None
        if marker != PREPARATION_SCHEMA:
            raise HttpFixtureInvalid("fixture preparation cannot downgrade to legacy command history")
        value = verify_preparation(cls._snapshot(command), cls._value(preparation))
        TestDesignResultRepository._project_scope(session, command, value["project_id"])
        if intent is None:
            if binding is not None:
                raise HttpFixtureInvalid("bound fixture preparation lost its original intent; never rebind")
        else:
            verify_preparation_binding(value, intent, cls._value(binding))
        return value

    @classmethod
    def bind(cls, session, command, intent):
        preparation = cls.verify(session, command)
        if preparation is None:
            return
        value = {"schema": PREPARATION_BINDING_SCHEMA, "invocation_id": command.id,
            "project_id": preparation["project_id"], "preparation_digest": acceptance_digest(preparation),
            "intent_digest": acceptance_digest(intent), "recorded_at": intent["recorded_at"],
            **{key: False for key in FALSE_AUTHORITIES}}
        verify_preparation_binding(preparation, intent, value)
        session.add(cls._row(Binding, value))
        session.flush()
