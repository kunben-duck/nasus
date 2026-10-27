"""Diagnostic port specimens; not actual PG, target execution or performance gates."""
import asyncio
import logging

import pytest

from apps.api.app.application.quality_loop.http_fixture_diagnostics import fixture_phase, PHASES
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.tests.test_http_fixture_jobs import application_specimen
from apps.api.tests.test_http_fixture_execution import RuntimeSpecimen, selection
from apps.api.app.application.quality_loop.http_fixture_execution import HttpFixtureExecutionApplicationService
from apps.api.app.application.quality_loop.http_fixture_execution import HttpFixtureExecutionStopped
from apps.api.app.application.quality_loop.http_fixture_work import HttpFixtureWorkLost
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureOutcomeUnknown
from apps.api.tests.test_http_fixture_native_grants import native_grant, spec


LOGGER = "apps.api.app.application.quality_loop.http_fixture_diagnostics"
PRIVATE = "private://source?api_key=never-log-this&sql=SELECT-private-body"


@pytest.mark.parametrize("phase", sorted(PHASES))
def test_phase_records_only_fixed_boundary_and_duration(phase, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    with fixture_phase(phase):
        value = PRIVATE
    assert value == PRIVATE and len(caplog.records) == 1
    record = caplog.records[0]
    assert record.args[0] == phase and type(record.args[1]) is int and record.args[1] >= 0
    assert record.exc_info is None and PRIVATE not in caplog.text


@pytest.mark.parametrize("error", [ValueError(PRIVATE), PermissionError(PRIVATE), RuntimeError(PRIVATE),
    asyncio.CancelledError(PRIVATE), KeyboardInterrupt(PRIVATE), StaleSourceAccessScope(PRIVATE),
    HttpFixtureWorkLost(PRIVATE), HttpFixtureOutcomeUnknown(PRIVATE), HttpFixtureExecutionStopped(PRIVATE)])
def test_failures_preserve_original_exception_without_message_or_traceback(error, caplog):
    with pytest.raises(type(error)) as raised:
        with fixture_phase("prepare_inputs"):
            raise error
    assert raised.value is error and len(caplog.records) == 1
    record = caplog.records[0]
    assert record.args[0] == "prepare_inputs"
    assert record.args[1] in {"ValueError", "PermissionError", "CancelledError", "StaleSourceAccessScope", "other",
        "HttpFixtureWorkLost", "HttpFixtureOutcomeUnknown", "HttpFixtureExecutionStopped"}
    assert record.exc_info is None and PRIVATE not in caplog.text


def test_unknown_exception_class_name_and_untrusted_phase_are_not_logged(caplog):
    error = type(PRIVATE, (Exception,), {})(PRIVATE)
    with pytest.raises(Exception) as raised:
        with fixture_phase("prepare_inputs"):
            raise error
    assert raised.value is error and caplog.records[0].args[1] == "other"
    with pytest.raises(ValueError):
        with fixture_phase(PRIVATE):
            pytest.fail("untrusted diagnostic phase must not enter the operation")
    assert len(caplog.records) == 1 and PRIVATE not in caplog.text


@pytest.mark.parametrize("phase", ["prepare_access", "prepare_original_command", "prepare_current_authority",
    "prepare_inputs", "prepare_binding", "prepare_final_authority"])
def test_original_preparation_reports_failure_boundary_without_dispatch_or_recovery(
        application_specimen, monkeypatch, caplog, phase):
    v = application_specimen
    error = ValueError(PRIVATE)
    def fail(*args, **kwargs):
        raise error
    if phase == "prepare_access":
        monkeypatch.setattr(v.jobs, "_access", fail)
    elif phase == "prepare_original_command":
        monkeypatch.setattr(v.jobs.repository, "execution", fail)
    elif phase == "prepare_current_authority":
        monkeypatch.setattr(v.jobs.repository, "require_running", fail)
    elif phase == "prepare_inputs":
        monkeypatch.setattr(v.jobs.grants, "execution_inputs", fail)
    elif phase == "prepare_binding":
        monkeypatch.setattr(v.jobs.repository, "bind", fail)
    else:
        original = v.jobs.repository.require_running
        count = 0
        def final(*args):
            nonlocal count
            count += 1
            if count == 3:
                raise error
            return original(*args)
        monkeypatch.setattr(v.jobs.repository, "require_running", final)
    with pytest.raises(ValueError) as raised:
        asyncio.run(v.jobs.dispatch(v.selected, v.authority.invocation_id))
    assert raised.value is error and v.state["status"] == "running"
    assert "workflow-start" not in v.calls and "execute" not in v.calls
    assert not any(item.startswith("finish:") for item in v.calls)
    failures = [item for item in caplog.records if item.name == LOGGER and item.levelno == logging.WARNING]
    assert len(failures) == 1 and failures[0].args[:2] == (phase, "ValueError")
    assert PRIVATE not in caplog.text


def test_live_grant_fault_retains_original_permission_failure_and_no_dispatch(
        application_specimen, monkeypatch, caplog):
    v = application_specimen
    error = PermissionError(PRIVATE)
    def denied(*args, **kwargs):
        raise error
    monkeypatch.setattr(v.jobs.grants.repository, "require_live", denied)
    with pytest.raises(PermissionError) as raised:
        asyncio.run(v.jobs.dispatch(v.selected, v.authority.invocation_id))
    assert raised.value is error and "bind" not in v.calls and "workflow-start" not in v.calls
    failures = [item.args[:2] for item in caplog.records if item.name == LOGGER and item.levelno == logging.WARNING]
    assert failures == [("grant_live_permission", "PermissionError"), ("prepare_inputs", "PermissionError")]
    assert PRIVATE not in caplog.text


def test_unknown_workflow_acknowledgement_stays_bound_to_original_command(
        application_specimen, monkeypatch, caplog):
    v = application_specimen
    calls = []
    error = RuntimeError(PRIVATE)
    async def unknown(ident):
        calls.append(ident)
        raise error
    monkeypatch.setattr(v.jobs.workflow, "start", unknown)
    with pytest.raises(RuntimeError) as raised:
        asyncio.run(v.jobs.dispatch(v.selected, v.authority.invocation_id))
    assert raised.value is error and calls == [v.authority.invocation_id]
    assert v.state["bound"] is True and v.state["status"] == "running"
    assert not any(item.startswith("finish:") for item in v.calls)
    failures = [item.args[:2] for item in caplog.records if item.name == LOGGER and item.levelno == logging.WARNING]
    assert failures == [("workflow_start", "other")] and PRIVATE not in caplog.text


@pytest.mark.parametrize("phase", ["worker_command", "worker_original_command", "worker_access",
    "worker_execute", "worker_archive_inputs", "worker_archive_history", "worker_commit"])
def test_worker_failure_is_locatable_without_exposing_inputs_or_retrying(
        application_specimen, monkeypatch, caplog, phase):
    v = application_specimen
    error = ValueError(PRIVATE)
    def fail(*args, **kwargs):
        raise error
    async def failed_execution(*args, **kwargs):
        raise error
    if phase == "worker_command":
        monkeypatch.setattr(v.jobs.repository, "command", fail)
    elif phase == "worker_original_command":
        monkeypatch.setattr(v.jobs.repository, "execution", fail)
    elif phase == "worker_access":
        monkeypatch.setattr(v.jobs, "_access", fail)
    elif phase == "worker_execute":
        monkeypatch.setattr(v.jobs.execution, "execute", failed_execution)
    elif phase == "worker_archive_inputs":
        monkeypatch.setattr(v.jobs.grants, "execution_inputs", fail)
    elif phase == "worker_archive_history":
        monkeypatch.setattr(v.jobs.execution, "read", fail)
    else:
        monkeypatch.setattr(v.jobs.repository, "finish", fail)
    with pytest.raises(ValueError) as raised:
        asyncio.run(v.jobs.run(v.authority.invocation_id))
    assert raised.value is error and v.state["status"] == "running"
    assert "finish:completed" not in v.calls and v.calls.count("execute") <= 1
    failures = [item for item in caplog.records if item.name == LOGGER and item.levelno == logging.WARNING]
    assert len(failures) == 1 and failures[0].args[:2] == (phase, "ValueError")
    assert failures[0].exc_info is None and PRIVATE not in caplog.text


@pytest.mark.parametrize("phase", ["execution_inputs", "execution_runtime", "execution_operation"])
def test_worker_runtime_fault_is_logged_without_extra_effects(native_grant, monkeypatch, caplog, phase):
    v = native_grant
    chosen = selection(v)
    factory = RuntimeSpecimen()
    app = HttpFixtureExecutionApplicationService(v.service, factory)
    error = ValueError(PRIVATE)
    def fail(*args, **kwargs):
        raise error
    if phase == "execution_inputs":
        monkeypatch.setattr(v.service, "execution_inputs", fail)
    elif phase == "execution_runtime":
        monkeypatch.setattr(factory, "create", fail)
    else:
        original = factory.create
        def create(*args, **kwargs):
            runtime = original(*args, **kwargs)
            runtime.lifecycle.prepare = fail
            return runtime
        monkeypatch.setattr(factory, "create", create)
    with pytest.raises(ValueError) as raised:
        asyncio.run(app.execute(chosen, require_current=lambda: None))
    assert raised.value is error and not factory.calls and not factory.commits
    failures = [item for item in caplog.records if item.name == LOGGER and item.levelno == logging.WARNING]
    assert len(failures) == 1 and failures[0].args[:2] == (phase, "ValueError")
    assert failures[0].exc_info is None and PRIVATE not in caplog.text
