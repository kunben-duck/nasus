"""Explicit transaction/session specimens; PG and target verification are separate."""
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.http_fixture_dispatch_consent import HttpFixtureDispatchConsent
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureLifecycleApplicationService, HttpFixtureScope
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.infrastructure.persistence.http_fixture_dispatch_consent_models import HttpFixtureDispatchConsentRecord as Consent
from apps.api.app.infrastructure.persistence.http_fixture_dispatch_consent_repository import (
    CONSENT_SCHEMA, FALSE_AUTHORITY, PostgresHttpFixtureConsentFence, verify_dispatch_consent,
)
from apps.api.app.infrastructure.persistence.http_fixture_grant_models import HttpFixtureGrantRecord as Grant
from apps.api.app.infrastructure.persistence.http_fixture_grant_repository import HttpFixtureGrantRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.tests.test_http_fixture_grants import grant_specimen
from apps.api.tests.test_http_fixture_work import ownership_session


def consent_specimen():
    service, request, state, value = grant_specimen()
    scope = HttpFixtureScope(**value["scope"])
    return service.dispatch_consent(request.project_id, value["record_id"], scope, "setup"), value


@pytest.mark.parametrize("field,item", [("grant_id", ""), ("grant_id", "\n"), ("grant_id", "x" * 129),
    ("actor_id", True), ("actor_id", "bad\x7f"), ("operation", "both"), ("operation", []),
    ("grant_digest", "bad"), ("source_scope_digest", True), ("scope", None)])
def test_transaction_permission_requires_exact_original_identity_scope_and_single_operation(field, item):
    value, _ = consent_specimen()
    with pytest.raises(HttpFixtureInvalid): replace(value, **{field: item})


@pytest.mark.parametrize("phase", ["cleanup:resource", "cleanup:", None, "other"])
def test_preparation_consent_cannot_authorize_cleanup_or_an_unspecified_phase(phase):
    value, _ = consent_specimen()
    with pytest.raises(HttpFixtureInvalid): value.require_phase(value.scope, phase)


def test_cleanup_permission_is_independent_and_allows_only_its_original_scope():
    value, _ = consent_specimen()
    cleanup = replace(value, operation="cleanup")
    cleanup.require_phase(value.scope, "cleanup:session")
    with pytest.raises(HttpFixtureInvalid): cleanup.require_phase(value.scope, "setup")
    with pytest.raises(HttpFixtureInvalid): cleanup.require_phase(replace(value.scope, attempt_id="other"), "cleanup:session")


def test_live_permission_is_checked_on_the_supplied_journal_session_not_another_transaction():
    consent, value = consent_specimen()
    calls = []
    repository = SimpleNamespace(require_live_in_session=lambda session, project, ident, **kwargs:
        (calls.append((session, project, ident, kwargs)), value)[1])
    fence = PostgresHttpFixtureConsentFence(repository, consent)
    session = object()
    command = HttpFixtureLifecycleApplicationService._command(consent.scope, "setup", ())
    fence.require(session, consent.scope, "setup", command)
    assert calls == [(session, consent.scope.project_id, consent.grant_id, {
        "actor_id": consent.actor_id, "scope": consent.scope, "operation": "setup",
        "source_scope_digest": consent.source_scope_digest})]
    assert fence.consent_pin(consent.scope, "setup") == consent.pin
    assert not hasattr(consent, "execution_authorized")


@pytest.mark.parametrize("mutation", ["grant", "phase", "scope"])
def test_pretransaction_validation_cannot_replace_the_actual_live_permission_check(mutation):
    consent, value = consent_specimen()
    value = deepcopy(value)
    command = HttpFixtureLifecycleApplicationService._command(consent.scope, "setup", ())
    if mutation == "grant": value["grant_digest"] = acceptance_digest("different consent")
    elif mutation == "phase": command.metadata["fixture_phase"] = "cleanup:session"
    else: command.metadata["fixture_scope"]["timeout_ms"] = 1000
    fence = PostgresHttpFixtureConsentFence(SimpleNamespace(require_live_in_session=lambda *args, **kwargs: value), consent)
    with pytest.raises(HttpFixtureInvalid): fence.require(object(), consent.scope, "setup", command)


def dispatch_session(monkeypatch):
    _, _, state, value = grant_specimen()
    scope = HttpFixtureScope(**value["scope"])
    # This session deliberately substitutes parent and ownership reads. It only
    # tests immutable consent verification, not source ACLs or real dispatch.
    dispatch = {"schema": "nasus.http-fixture-dispatch.v3", "claim_id": "original-dispatch",
        "project_id": scope.project_id, "scope": asdict(scope), "phase": "setup", "actor_id": value["actor_id"],
        "recorded_at": value["recorded_at"], "operation_consent": {"grant_id": value["record_id"],
            "grant_digest": value["grant_digest"], "source_scope_digest": value["source_scope_digest"]},
        "run_plan_id": "original-plan", "run_plan_artifact_hash": acceptance_digest("original-plan"),
        "plan_digest": scope.parent_digest}
    payload = {"schema": CONSENT_SCHEMA, "claim_id": dispatch["claim_id"], "project_id": scope.project_id,
        **dispatch["operation_consent"], "operation": "setup", "scope_digest": scope.digest,
        "dispatch_digest": acceptance_digest(dispatch), "recorded_at": dispatch["recorded_at"], "consumed_at": value["recorded_at"],
        **{key: False for key in FALSE_AUTHORITY}}
    columns = {column.name for column in Consent.__table__.columns} - {"payload", "content_hash"}
    row = Consent(**{key: payload[key] for key in columns}, payload=payload, content_hash=acceptance_digest(payload))
    original = SimpleNamespace(invocation_id=value["invocation_id"])
    command = SimpleNamespace(status="completed")
    rows = {Consent: row, Grant: original, ToolInvocationRecord: command}
    session = SimpleNamespace(get=lambda model, ident: rows.get(model))
    module = "apps.api.app.infrastructure.persistence.http_fixture_dispatch_consent_repository"
    monkeypatch.setattr(HttpFixtureGrantRepository, "_verify", classmethod(lambda *args: value))
    monkeypatch.setattr(HttpFixtureGrantRepository, "_request", staticmethod(lambda *args: object()))
    parent = {key: dispatch[key] for key in ("run_plan_id", "run_plan_artifact_hash", "plan_digest")}
    monkeypatch.setattr(HttpFixtureGrantRepository, "_parents", staticmethod(lambda *args: parent))
    worker = {"value": {"owner_id": "original-worker"}}
    monkeypatch.setattr(module + ".verify_dispatch_ownership", lambda *args: worker["value"])
    return session, dispatch, rows, value, worker, parent


def test_original_consent_is_historical_without_renewing_its_expired_grant(monkeypatch):
    session, dispatch, rows, value, _, _ = dispatch_session(monkeypatch)
    original = deepcopy(rows[Consent].payload)
    assert verify_dispatch_consent(session, dispatch) == original
    assert original["grant_digest"] == value["grant_digest"]
    assert all(original[key] is False for key in FALSE_AUTHORITY)


@pytest.mark.parametrize("mutation", ["missing", "rehashed_actor", "rehashed_phase", "rehashed_target", "rehashed_scope",
    "rehashed_grant", "rehashed_authority", "extra_authority", "missing_worker", "incomplete_command", "other_plan", "downgrade",
    "expired_consumption", "future_consumption", "missing_grant", "other_project"])
def test_rehashed_history_cannot_rebind_permission_target_phase_parent_or_authority(monkeypatch, mutation):
    session, dispatch, rows, value, worker, parent = dispatch_session(monkeypatch)
    row = rows[Consent]
    if mutation == "missing": rows.pop(Consent)
    elif mutation == "rehashed_actor": dispatch["actor_id"] = "other-admin"
    elif mutation == "rehashed_phase": dispatch["phase"] = "cleanup:session"
    elif mutation == "rehashed_target": dispatch["scope"]["artifact_hash"] = acceptance_digest("another build")
    elif mutation == "rehashed_scope": row.payload["scope_digest"] = acceptance_digest("another scope")
    elif mutation == "rehashed_grant": row.payload["grant_digest"] = acceptance_digest("another grant")
    elif mutation == "rehashed_authority": row.payload["execution_authorized"] = 1
    elif mutation == "extra_authority": row.payload["passed_count"] = 1
    elif mutation == "missing_worker": worker["value"] = None
    elif mutation == "incomplete_command": rows[ToolInvocationRecord].status = "failed"
    elif mutation == "other_plan": parent["run_plan_id"] = "another-plan"
    elif mutation == "expired_consumption": row.payload["consumed_at"] = value["expires_at"]
    elif mutation == "future_consumption": row.payload["consumed_at"] = "2026-01-01T00:00:00+00:00"
    elif mutation == "missing_grant": rows.pop(Grant)
    elif mutation == "other_project":
        dispatch["project_id"] = "another-project"
        row.payload["project_id"] = "another-project"
    else: dispatch["schema"] = "nasus.http-fixture-dispatch.v2"
    row.payload["dispatch_digest"] = acceptance_digest(dispatch)
    if mutation == "rehashed_grant": dispatch["operation_consent"]["grant_digest"] = row.payload["grant_digest"]
    columns = {column.name for column in Consent.__table__.columns} - {"payload", "content_hash"}
    row.payload["dispatch_digest"] = acceptance_digest(dispatch)
    for key in columns: setattr(row, key, row.payload[key])
    row.content_hash = acceptance_digest(row.payload)
    with pytest.raises(HttpFixtureInvalid): verify_dispatch_consent(session, dispatch)


@pytest.mark.parametrize("schema", ["nasus.http-fixture-dispatch.v1", "nasus.http-fixture-dispatch.v2"])
def test_legacy_history_does_not_acquire_consent_but_an_inserted_marker_requires_it(monkeypatch, schema):
    session, dispatch, rows, _, _, _ = dispatch_session(monkeypatch)
    rows.pop(Consent)
    dispatch["schema"] = schema
    pin = dispatch.pop("operation_consent")
    assert verify_dispatch_consent(session, dispatch) is None
    dispatch["operation_consent"] = pin
    with pytest.raises(HttpFixtureInvalid): verify_dispatch_consent(session, dispatch)


@pytest.mark.parametrize("schema", ["nasus.http-fixture-dispatch.v3", "nasus.http-fixture-dispatch.v4"])
def test_consented_versions_require_original_worker_and_never_downgrade_missing_ownership(schema):
    from apps.api.app.infrastructure.persistence.http_fixture_work_repository import verify_dispatch_ownership
    session, dispatch, rows = ownership_session()
    dispatch["schema"] = schema
    from apps.api.app.infrastructure.persistence.http_fixture_work_models import HttpFixtureDispatchOwnershipRecord as Ownership
    row = rows[Ownership]
    row.payload["dispatch_digest"] = acceptance_digest(dispatch)
    row.dispatch_digest = row.payload["dispatch_digest"]
    row.content_hash = acceptance_digest(row.payload)
    assert verify_dispatch_ownership(session, dispatch)["owner_id"] == "worker-original"
    rows.pop(Ownership)
    with pytest.raises(HttpFixtureInvalid): verify_dispatch_ownership(session, dispatch)


@pytest.mark.parametrize("orphan", ["ownership", "consent", "command"])
def test_missing_dispatch_with_surviving_private_history_cannot_become_a_fresh_request(orphan):
    from apps.api.app.infrastructure.persistence.http_fixture_journal_repository import PostgresHttpFixtureDispatchJournal
    from apps.api.app.infrastructure.persistence.http_fixture_work_models import HttpFixtureDispatchOwnershipRecord as Ownership
    from apps.api.app.infrastructure.persistence.http_fixture_command_models import HttpFixtureDispatchCommandRecord as Command
    consent, _ = consent_specimen()
    surviving = {"ownership": Ownership, "consent": Consent, "command": Command}[orphan]
    session = SimpleNamespace(get=lambda model, ident: object() if model is surviving else None)
    journal = object.__new__(PostgresHttpFixtureDispatchJournal)
    with pytest.raises(HttpFixtureInvalid, match="never redispatch"):
        journal._records(session, {}, consent.scope, "setup", object())
