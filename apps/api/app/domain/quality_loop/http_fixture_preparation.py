"""A preparation receipt proves an original claim, never target permission."""
from datetime import datetime

from .acceptance_specification import acceptance_digest
from .http_fixture_command import FALSE_AUTHORITIES, verify_fixture_command
from .http_fixtures import HttpFixtureInvalid


PREPARATION_SCHEMA = "nasus.http-fixture-preparation.v1"
PREPARATION_BINDING_SCHEMA = "nasus.http-fixture-preparation-binding.v1"
PREPARATION_MARKER = "fixture_claim_protocol"


def verify_preparation(snapshot, value):
    try:
        if (type(value) is not dict or set(value) != {"schema", "invocation_id", "project_id",
                "request_digest", "actor_id", "confirmed_at", "recorded_at", *FALSE_AUTHORITIES}
                or value["schema"] != PREPARATION_SCHEMA
                or snapshot["input_payload"].get(PREPARATION_MARKER) != PREPARATION_SCHEMA
                or any(value[key] is not False for key in FALSE_AUTHORITIES)):
            raise HttpFixtureInvalid("fixture preparation receipt is not its original protocol")
        for key in ("invocation_id", "project_id", "actor_id"):
            ident = value[key]
            if type(ident) is not str or not ident.strip() or len(ident) > 128 or any(ord(c) < 32 for c in ident):
                raise HttpFixtureInvalid("fixture preparation requires exact original identities")
        confirmed = verify_fixture_command(snapshot, {"project_id": value["project_id"]},
            invocation_id=value["invocation_id"], request_digest=value["request_digest"],
            actor_id=value["actor_id"], historical=True)
        recorded = datetime.fromisoformat(value["recorded_at"])
        if (snapshot["input_payload"]["confirmed_at"] != value["confirmed_at"]
                or recorded.tzinfo is None or not 0 <= (recorded - confirmed).total_seconds() <= 900):
            raise HttpFixtureInvalid("fixture preparation lost its original confirmation or PostgreSQL claim time")
        return value
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        if isinstance(exc, HttpFixtureInvalid):
            raise
        raise HttpFixtureInvalid("fixture preparation history cannot be verified") from exc


def verify_preparation_binding(preparation, intent, value):
    try:
        if (type(value) is not dict or set(value) != {"schema", "invocation_id", "project_id",
                "preparation_digest", "intent_digest", "recorded_at", *FALSE_AUTHORITIES}
                or value["schema"] != PREPARATION_BINDING_SCHEMA
                or value["invocation_id"] != preparation["invocation_id"]
                or value["project_id"] != preparation["project_id"]
                or value["preparation_digest"] != acceptance_digest(preparation)
                or value["intent_digest"] != acceptance_digest(intent)
                or any(value[key] is not False for key in FALSE_AUTHORITIES)
                or any(intent[key] != preparation[key] for key in
                    ("invocation_id", "project_id", "request_digest", "actor_id"))
                or value["recorded_at"] != intent["recorded_at"]
                or datetime.fromisoformat(value["recorded_at"]) < datetime.fromisoformat(preparation["recorded_at"])):
            raise HttpFixtureInvalid("fixture binding receipt lost its exact original preparation or intent")
        return value
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        if isinstance(exc, HttpFixtureInvalid):
            raise
        raise HttpFixtureInvalid("fixture preparation binding cannot be verified") from exc
