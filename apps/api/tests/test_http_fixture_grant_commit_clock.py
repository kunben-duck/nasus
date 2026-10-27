"""Transaction/clock specimens; actual PG rollback is verified separately."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_SECONDS, grant_metadata
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.environment_observation_repository import EnvironmentObservationRepository
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.http_fixture_grant_models import HttpFixtureGrantRecord
from apps.api.app.infrastructure.persistence.http_fixture_grant_repository import HttpFixtureGrantRepository
from apps.api.app.infrastructure.persistence.http_fixture_work_repository import PostgresHttpFixtureWorkRepository
from apps.api.app.infrastructure.persistence.test_design_scope_repository import TestDesignScopeRepository
from apps.api.tests.test_http_fixture_grants import grant_specimen


def transaction_specimen(monkeypatch, *, historical=False):
    _, request, grants, original = grant_specimen()
    payload = deepcopy(grants["grants"][original["record_id"]])
    confirmed = datetime.fromisoformat(original["recorded_at"])
    state = {"now": confirmed, "checks": 0, "writes": [], "events": [], "committed": False, "rolled_back": False}
    command = SimpleNamespace(id=original["invocation_id"], conversation_id="original-conversation",
        input_payload={"confirmed_at": confirmed.isoformat()})
    columns = {column.name for column in HttpFixtureGrantRecord.__table__.columns} - {"payload", "content_hash"}
    existing = HttpFixtureGrantRecord(**{key: original[key] for key in columns}, payload=payload,
        content_hash="unused-specimen-digest") if historical else None

    class Session:
        def scalar(self, query):
            if "clock_timestamp()" in str(query):
                return state["now"]
            if "invocation_id =" in str(query):
                return existing
            return None

        def scalars(self, query):
            return SimpleNamespace(all=lambda: [])

        def get(self, model, ident):
            assert model is ToolInvocationRecord and ident == command.id
            return command

        def add(self, row):
            state["writes"].append(row)

        def flush(self):
            pass

    @contextmanager
    def scope():
        try:
            yield Session()
        except BaseException:
            state["rolled_back"] = True
            raise
        else:
            state["committed"] = True

    monkeypatch.setattr("apps.api.app.infrastructure.persistence.http_fixture_grant_repository.session_scope", scope)
    monkeypatch.setattr(TestDesignScopeRepository, "_lock", staticmethod(lambda *args: None))
    monkeypatch.setattr(TestDesignScopeRepository, "_actor", staticmethod(lambda *args: None))
    monkeypatch.setattr(PostgresHttpFixtureWorkRepository, "_actor_current", staticmethod(lambda *args: None))
    monkeypatch.setattr(EnvironmentObservationRepository, "_canonical", classmethod(lambda cls, *args, **kwargs: command))
    monkeypatch.setattr(HttpFixtureGrantRepository, "_parents", staticmethod(lambda *args: {}))
    monkeypatch.setattr(HttpFixtureGrantRepository, "_verify", classmethod(lambda cls, session, row: grant_metadata(row.payload)))
    monkeypatch.setattr(EventOutboxRepository, "append", lambda repo, event, **kwargs: state["events"].append(event))
    from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
    return HttpFixtureGrantRepository(), request, HttpFixtureScope(**original["scope"]), original, state


@pytest.mark.parametrize("expires_after_check", [1, 2])
def test_new_grant_rechecks_pg_confirmation_after_each_full_source_guard(monkeypatch, expires_after_check):
    repository, request, scope, original, state = transaction_specimen(monkeypatch)

    def require_access():
        state["checks"] += 1
        if state["checks"] == expires_after_check:
            state["now"] += timedelta(seconds=GRANT_SECONDS + 1)

    with pytest.raises(RunPlanIntegrityError, match="PostgreSQL time"):
        repository.issue(request, scope, original["source_scope_digest"], actor_id=original["actor_id"],
            invocation_id=original["invocation_id"], require_access=require_access)
    assert state["checks"] == expires_after_check and state["rolled_back"] and not state["committed"]
    assert bool(state["writes"]) is (expires_after_check == 2)
    assert len(state["events"]) == (1 if expires_after_check == 2 else 0)


def test_fresh_grant_keeps_original_exact_lifetime_and_transaction(monkeypatch):
    repository, request, scope, original, state = transaction_specimen(monkeypatch)
    result = repository.issue(request, scope, original["source_scope_digest"], actor_id=original["actor_id"],
        invocation_id=original["invocation_id"], require_access=lambda: None)
    assert state["committed"] and not state["rolled_back"] and len(state["events"]) == 1
    assert datetime.fromisoformat(result["expires_at"]) - datetime.fromisoformat(result["recorded_at"]) == timedelta(seconds=GRANT_SECONDS)
    assert result["execution_authorized"] is result["fixtures_verified"] is result["business_coverage_verified"] is False


def test_existing_grant_recovery_does_not_rebase_expiry_or_repeat_fact(monkeypatch):
    repository, request, scope, original, state = transaction_specimen(monkeypatch, historical=True)
    state["now"] += timedelta(seconds=GRANT_SECONDS + 1)
    result = repository.issue(request, scope, original["source_scope_digest"], actor_id=original["actor_id"],
        invocation_id=original["invocation_id"], require_access=lambda: None)
    assert result == original and state["committed"] and not state["writes"] and not state["events"]
