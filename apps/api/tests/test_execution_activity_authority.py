"""Activity policy specimens; not PG consent or real target execution evidence."""
import asyncio
from types import SimpleNamespace

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError

from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from apps.api.app.infrastructure.workflow.http_fixture_runtime import build_http_fixture_activities
from apps.api.app.infrastructure.workflow.run_plan_case_runtime import build_run_plan_case_activities


ACTIVITIES = (
    (build_http_fixture_activities, "http_fixture_jobs", "HttpFixture"),
    (build_run_plan_case_activities, "run_plan_case_jobs", "RunPlanCase"),
)


@pytest.mark.parametrize("factory,service,prefix", ACTIVITIES)
@pytest.mark.parametrize("failure", (
    PermissionError("private expired grant"), SourceAccessDenied("private revoked source"),
    StaleSourceAccessScope("private changed authority"),
    PlatformApplicationError("source_access_denied", "private forbidden source", 403),
))
def test_authority_denial_is_non_retryable_redacted_and_stops_heartbeat(monkeypatch, factory, service, prefix, failure):
    import apps.api.app.bootstrap as bootstrap
    calls, beats = [], []

    async def run(ident):
        calls.append(ident)
        await asyncio.sleep(0)
        raise failure

    monkeypatch.setattr(activity, "heartbeat", lambda value: beats.append(value))
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(**{
        service: SimpleNamespace(run=run)}))

    async def verify():
        before = asyncio.all_tasks()
        with pytest.raises(ApplicationError) as raised:
            await factory()[0]("original-command")
        assert raised.value.type == prefix + "AuthorityDenied"
        assert raised.value.non_retryable is True
        assert "private" not in str(raised.value) and raised.value.__cause__ is None
        assert asyncio.all_tasks() == before

    asyncio.run(verify())
    assert calls == ["original-command"] and beats == [{"invocation_id": "original-command"}]


@pytest.mark.parametrize("factory,service,prefix", ACTIVITIES)
@pytest.mark.parametrize("failure", (
    OSError("private temporary transport fault"), RuntimeError("private archive acknowledgement lost"),
    PlatformApplicationError("source_unavailable", "private temporary source outage", 503),
))
def test_transient_failure_retains_existing_same_id_retry_policy(monkeypatch, factory, service, prefix, failure):
    import apps.api.app.bootstrap as bootstrap

    async def run(ident):
        assert ident == "original-command"
        await asyncio.sleep(0)
        raise failure

    monkeypatch.setattr(activity, "heartbeat", lambda value: None)
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(**{
        service: SimpleNamespace(run=run)}))
    with pytest.raises(ApplicationError) as raised:
        asyncio.run(factory()[0]("original-command"))
    assert raised.value.type == prefix + "InfrastructureFailure"
    assert raised.value.non_retryable is False
    assert "private" not in str(raised.value) and raised.value.__cause__ is None


@pytest.mark.parametrize("factory,service,prefix", ACTIVITIES)
def test_cancellation_is_not_converted_to_an_authority_or_infrastructure_error(monkeypatch, factory, service, prefix):
    import apps.api.app.bootstrap as bootstrap

    async def run(ident):
        await asyncio.sleep(0)
        raise asyncio.CancelledError()

    monkeypatch.setattr(activity, "heartbeat", lambda value: None)
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(**{
        service: SimpleNamespace(run=run)}))

    async def verify():
        before = asyncio.all_tasks()
        with pytest.raises(asyncio.CancelledError):
            await factory()[0]("original-command")
        assert asyncio.all_tasks() == before

    asyncio.run(verify())


@pytest.mark.parametrize("factory,service,prefix", ACTIVITIES)
def test_original_finalizer_fence_remains_retryable_without_rerunning_work(monkeypatch, factory, service, prefix):
    import apps.api.app.bootstrap as bootstrap
    calls = []

    async def fail(ident):
        calls.append(ident)
        raise RuntimeError("private original worker still owns its lease")

    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(**{
        service: SimpleNamespace(fail=fail)}))
    with pytest.raises(ApplicationError) as raised:
        asyncio.run(factory()[1]("original-command"))
    assert raised.value.type == prefix + "TerminationFailure" and raised.value.non_retryable is False
    assert "private" not in str(raised.value) and calls == ["original-command"]
