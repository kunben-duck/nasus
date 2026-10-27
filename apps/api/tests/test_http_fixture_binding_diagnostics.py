"""Binding boundary fault specimens; no PG or target-execution claim."""
import logging

import pytest

from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence.http_fixture_command_models import HttpFixtureCommandRecord as Intent
from apps.api.app.infrastructure.persistence.http_fixture_command_repository import HttpFixtureGrantRepository
from apps.api.app.infrastructure.persistence.http_fixture_preparation_repository import HttpFixturePreparationJournal
from apps.api.tests.test_http_fixture_commands import command_specimen, native_grant, spec


PRIVATE = "private://source?credential=never-log&body=private-evidence"
LOGGER = "apps.api.app.application.quality_loop.http_fixture_diagnostics"


@pytest.mark.parametrize("phase", ["bind_canonical", "bind_live_permission", "bind_preparation", "bind_prior_effects",
    "bind_intent_persistence", "bind_preparation_receipt", "bind_intent_verification", "bind_event_persistence",
    "bind_current_authority", "bind_existing_intent"])
def test_binding_failure_reports_only_fixed_phase_and_original_error(command_specimen, monkeypatch, caplog, phase):
    value = command_specimen
    value.events.clear()
    if phase != "bind_existing_intent":
        value.rows.pop((Intent, value.command.id))
    error = HttpFixtureInvalid(PRIVATE)

    def fail(*args, **kwargs):
        raise error

    require_current = fail if phase == "bind_current_authority" else lambda: None
    if phase == "bind_canonical":
        monkeypatch.setattr(value.repository, "_canonical", fail)
    elif phase == "bind_live_permission":
        monkeypatch.setattr(HttpFixtureGrantRepository, "require_live_in_session", fail)
    elif phase == "bind_preparation":
        monkeypatch.setattr(HttpFixturePreparationJournal, "verify", fail)
    elif phase == "bind_prior_effects":
        original = value.session.scalar
        def scalar(query):
            if query.column_descriptions[0].get("entity") is Intent:
                raise error
            return original(query)
        monkeypatch.setattr(value.session, "scalar", scalar)
    elif phase == "bind_intent_persistence":
        monkeypatch.setattr(value.session, "flush", fail)
    elif phase == "bind_preparation_receipt":
        monkeypatch.setattr(HttpFixturePreparationJournal, "bind", fail)
    elif phase in {"bind_intent_verification", "bind_existing_intent"}:
        monkeypatch.setattr(value.repository, "_verify", fail)
    elif phase == "bind_event_persistence":
        monkeypatch.setattr(value.repository, "_event", fail)
    caplog.clear()
    with pytest.raises(HttpFixtureInvalid) as raised:
        value.repository.bind(value.inputs, value.authority, require_current=require_current)
    assert raised.value is error and not value.events
    failures = [item for item in caplog.records if item.name == LOGGER and item.levelno == logging.WARNING]
    assert len(failures) == 1 and failures[0].args[:2] == (phase, "HttpFixtureInvalid")
    assert failures[0].exc_info is None and PRIVATE not in caplog.text
