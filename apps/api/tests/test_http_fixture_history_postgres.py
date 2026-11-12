"""Fast PostgreSQL projection check; rows are specimens, not execution evidence."""
from contextlib import contextmanager

import pytest
from sqlalchemy import insert, text, update

from apps.api.app.application.quality_loop.http_fixture_history import HttpFixtureHistoryQuery
from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_CANCEL_TOOL, FIXTURE_COMMAND_TOOL
from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_TOOL
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence import http_fixture_history_repository as history
from apps.api.app.infrastructure.persistence.http_fixture_job_repository import HttpFixtureJobRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def test_composed_postgres_history_projects_original_commands_and_enforces_source_scope(monkeypatch):
    project, recipe, manifest, grant = "fixture-sql-probe", "recipe", "manifest", "grant"
    digest = "sha256:" + "a" * 64
    execution_payload = {"project_id": project, "grant_id": grant, "grant_digest": digest, "operation": "setup"}
    commands = [
        {"id": "grant-command", "tool_id": GRANT_TOOL, "status": "completed", "input_payload": {
            "project_id": project, "recipe_id": recipe, "recipe_artifact_hash": digest}},
        {"id": "setup-command", "tool_id": FIXTURE_COMMAND_TOOL, "status": "cancelled", "input_payload": execution_payload},
        {"id": "cancel-command", "tool_id": FIXTURE_CANCEL_TOOL, "status": "completed", "input_payload": {
            "project_id": project, "invocation_id": "setup-command"}},
        {"id": "foreign-command", "tool_id": FIXTURE_COMMAND_TOOL, "status": "completed", "input_payload": {
            **execution_payload, "project_id": "foreign-project"}},
    ]
    with session_scope() as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        # Use the migrated column types, but never register a command or a source in durable tables.
        for model in (history.Command, history.Grant, history.Recipe, history.Member):
            name = model.__tablename__
            session.execute(text(f'CREATE TEMP TABLE "{name}" ON COMMIT DROP AS SELECT * FROM public."{name}" WITH NO DATA'))
        session.execute(insert(history.Command.__table__), [{**row, "summary": "SQL specimen"} for row in commands])
        session.execute(insert(history.Grant.__table__), {"project_id": project, "record_id": grant,
            "operation": "setup", "recipe_id": recipe, "recipe_artifact_hash": digest})
        session.execute(insert(history.Recipe.__table__), {"project_id": project, "record_id": recipe,
            "artifact_hash": digest, "manifest_id": manifest})
        bindings = ("code", "requirements")
        session.execute(insert(history.Member.__table__), [{"project_id": project, "manifest_id": manifest,
            "binding_id": binding} for binding in bindings])

        @contextmanager
        def temporary_projection():
            yield session

        monkeypatch.setattr(history, "session_scope", temporary_projection)
        repository = HttpFixtureJobRepository()
        query = HttpFixtureHistoryQuery(project_id=project, limit=2)
        page = repository.list_history(query, binding_ids=bindings)
        assert page["total"] == 3 and page["next_after_id"] == "grant-command"
        assert [item["command"] for item in page["items"]] == [commands[2], commands[0]]
        assert page["lookahead"][0]["command"] == commands[1]
        assert page["items"][0]["execution"] == commands[1] and page["items"][1]["execution"] is None
        next_page = repository.list_history(HttpFixtureHistoryQuery(project_id=project, limit=2,
            after_id=page["next_after_id"]), binding_ids=bindings)
        assert next_page["total"] == page["total"] and next_page["next_after_id"] is None
        assert next_page["items"] == page["lookahead"] and next_page["lookahead"] == []
        detail = repository.read_history(project, "setup-command", binding_ids=bindings)
        assert detail == {"command": commands[1], "execution": None, "recipe_id": recipe, "recipe_artifact_hash": digest}
        hidden = repository.list_history(query, binding_ids=("code",))
        assert hidden == {"items": [], "total": 0, "next_after_id": None, "lookahead": []}
        with pytest.raises(KeyError):
            repository.read_history(project, "setup-command", binding_ids=("code",))
        session.execute(update(history.Command.__table__).where(history.Command.id == "cancel-command")
            .values(input_payload={"project_id": project, "invocation_id": "foreign-command"}))
        with pytest.raises(HttpFixtureInvalid, match="unresolved original ancestry"):
            repository.list_history(query, binding_ids=bindings)
