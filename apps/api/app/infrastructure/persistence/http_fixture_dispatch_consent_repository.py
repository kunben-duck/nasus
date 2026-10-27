"""Consume exact operation permission in the original journal/ownership transaction."""
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import select

from ...application.quality_loop.http_fixture_dispatch_consent import HttpFixtureDispatchConsent
from ...application.quality_loop.http_fixtures import HttpFixtureScope
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.quality_loop.http_fixtures import HttpFixtureInvalid
from .db_models import ToolInvocationRecord
from .http_fixture_dispatch_consent_models import HttpFixtureDispatchConsentRecord as Consent
from .http_fixture_grant_models import HttpFixtureGrantRecord as Grant
from .http_fixture_grant_repository import HttpFixtureGrantRepository
from .http_fixture_journal_models import HttpFixtureDispatchRecord as Dispatch
from .http_fixture_work_repository import verify_dispatch_ownership


CONSENT_SCHEMA = "nasus.http-fixture-dispatch-consent.v1"
FALSE_AUTHORITY = ("execution_authorized", "canonical_execution_committed", "business_coverage_verified", "baseline_restored")


def _operation(phase):
    if phase == "setup":
        return "setup"
    if type(phase) is str and phase.startswith("cleanup:") and len(phase) > 8:
        return "cleanup"
    raise HttpFixtureInvalid("fixture consent requires an exact original phase")


def verify_dispatch_consent(session, dispatch):
    """Historical verification never renews permission or grants another dispatch."""
    try:
        return _verify_dispatch_consent(session, dispatch)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        if isinstance(exc, HttpFixtureInvalid):
            raise
        raise HttpFixtureInvalid("original fixture dispatch consent cannot be verified") from exc


def _verify_dispatch_consent(session, dispatch):
    row = session.get(Consent, dispatch["claim_id"])
    if row is None:
        if dispatch.get("schema") in {"nasus.http-fixture-dispatch.v3", "nasus.http-fixture-dispatch.v4"} or "operation_consent" in dispatch:
            raise HttpFixtureInvalid("original fixture dispatch consent is missing; never downgrade it")
        return None
    value = row.payload
    columns = {column.name for column in Consent.__table__.columns} - {"payload", "content_hash"}
    if (type(value) is not dict or set(value) != columns | {"schema", *FALSE_AUTHORITY}
            or acceptance_digest(value) != row.content_hash
            or acceptance_digest({key: value.get(key) for key in columns}) != acceptance_digest({key: getattr(row, key) for key in columns})
            or value.get("schema") != CONSENT_SCHEMA or value.get("project_id") != dispatch["project_id"]
            or value.get("claim_id") != dispatch["claim_id"]
            or value.get("dispatch_digest") != acceptance_digest(dispatch)
            or any(value.get(key) is not False for key in FALSE_AUTHORITY)
            or dispatch.get("schema") not in {"nasus.http-fixture-dispatch.v3", "nasus.http-fixture-dispatch.v4"}
            or dispatch.get("operation_consent") != {key: value[key] for key in
                ("grant_id", "grant_digest", "source_scope_digest")}):
        raise HttpFixtureInvalid("fixture dispatch consent lost its original immutable binding")
    scope = HttpFixtureScope(**dispatch["scope"])
    grant = session.get(Grant, value["grant_id"])
    original = HttpFixtureGrantRepository._verify(session, grant)
    command = session.get(ToolInvocationRecord, grant.invocation_id)
    if (command.status != "completed" or scope.project_id != dispatch["project_id"]
            or original["grant_digest"] != value["grant_digest"]
            or original["project_id"] != scope.project_id or original["actor_id"] != dispatch["actor_id"]
            or original["scope_digest"] != scope.digest or value["scope_digest"] != scope.digest
            or acceptance_digest(original["scope"]) != acceptance_digest(asdict(scope))
            or original["operation"] != value["operation"] or value["operation"] != _operation(dispatch["phase"])
            or original["source_scope_digest"] != value["source_scope_digest"]
            or value["recorded_at"] != dispatch["recorded_at"]
            or type(value["consumed_at"]) is not str or len(value["consumed_at"]) > 64
            or not datetime.fromisoformat(original["recorded_at"]) <= datetime.fromisoformat(value["consumed_at"]) < datetime.fromisoformat(original["expires_at"])
            or verify_dispatch_ownership(session, dispatch) is None):
        raise HttpFixtureInvalid("fixture dispatch permission differs from its original grant, phase or worker")
    parent = HttpFixtureGrantRepository._parents(session, HttpFixtureGrantRepository._request(command))
    if any(parent[key] != dispatch[key] for key in ("run_plan_id", "run_plan_artifact_hash", "plan_digest")):
        raise HttpFixtureInvalid("fixture dispatch consent cannot change its original RunPlan")
    return value


class PostgresHttpFixtureConsentFence:
    def __init__(self, repository: HttpFixtureGrantRepository, consent: HttpFixtureDispatchConsent):
        if not isinstance(consent, HttpFixtureDispatchConsent):
            raise HttpFixtureInvalid("fixture transaction needs independently validated permission pins")
        self.repository, self.consent = repository, consent

    def consent_pin(self, scope, phase):
        self.consent.require_phase(scope, phase)
        return self.consent.pin

    def require(self, session, scope, phase, command):
        self.consent.require_phase(scope, phase)
        if (acceptance_digest(command.metadata.get("fixture_scope")) != acceptance_digest(asdict(scope))
                or command.metadata.get("fixture_phase") != phase):
            raise HttpFixtureInvalid("fixture permission cannot authorize a different command scope")
        value = self.repository.require_live_in_session(session, scope.project_id, self.consent.grant_id,
            actor_id=self.consent.actor_id, scope=scope, operation=self.consent.operation,
            source_scope_digest=self.consent.source_scope_digest)
        if value["grant_digest"] != self.consent.grant_digest:
            raise HttpFixtureInvalid("fixture permission differs from the independently verified original grant")

    def claim(self, session, dispatch):
        scope = HttpFixtureScope(**dispatch["scope"])
        self.consent.require_phase(scope, dispatch["phase"])
        if (dispatch.get("schema") not in {"nasus.http-fixture-dispatch.v3", "nasus.http-fixture-dispatch.v4"}
                or dispatch["actor_id"] != self.consent.actor_id
                or dispatch.get("operation_consent") != self.consent.pin or session.get(Consent, dispatch["claim_id"]) is not None):
            raise HttpFixtureInvalid("fixture consent cannot replace or adopt a different original claim")
        row = session.get(Dispatch, dispatch["claim_id"])
        if row is None or row.content_hash != acceptance_digest(dispatch) or verify_dispatch_ownership(session, dispatch) is None:
            raise HttpFixtureInvalid("fixture consent needs this transaction's original worker-owned dispatch")
        original = self.repository.require_live_in_session(session, scope.project_id, self.consent.grant_id,
            actor_id=self.consent.actor_id, scope=scope, operation=self.consent.operation,
            source_scope_digest=self.consent.source_scope_digest)
        consumed_at = session.scalar(select(self.repository._clock()))
        if (original["grant_digest"] != self.consent.grant_digest
                or not datetime.fromisoformat(original["recorded_at"]) <= consumed_at < datetime.fromisoformat(original["expires_at"])):
            raise HttpFixtureInvalid("fixture consent expired before its original transaction consumption")
        value = {"schema": CONSENT_SCHEMA, "claim_id": dispatch["claim_id"], "project_id": scope.project_id,
            **self.consent.pin, "operation": self.consent.operation, "scope_digest": scope.digest,
            "dispatch_digest": acceptance_digest(dispatch), "recorded_at": dispatch["recorded_at"],
            "consumed_at": consumed_at.isoformat(),
            **{key: False for key in FALSE_AUTHORITY}}
        columns = {column.name for column in Consent.__table__.columns} - {"payload", "content_hash"}
        session.add(Consent(**{key: value[key] for key in columns}, payload=value, content_hash=acceptance_digest(value)))

    def complete(self, session, dispatch):
        value = verify_dispatch_consent(session, dispatch)
        if value is None or any(value[key] != item for key, item in self.consent.pin.items()):
            raise HttpFixtureInvalid("fixture completion cannot replace its original dispatch permission")
