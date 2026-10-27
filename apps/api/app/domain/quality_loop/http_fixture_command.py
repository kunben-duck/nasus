"""Original command provenance is distinct from fixture or business authority."""
from datetime import datetime

from .acceptance_specification import acceptance_digest
from .http_fixtures import HttpFixtureInvalid


FIXTURE_COMMAND_TOOL = "quality.http_fixture.execute"
FIXTURE_QUERY_TOOL = "query.quality.http_fixture_execution"
FIXTURE_CANCEL_TOOL = "quality.http_fixture.cancel"
FIXTURE_HISTORY_LIST_TOOL = "query.quality.http_fixture_operations"
FIXTURE_HISTORY_READ_TOOL = "query.quality.http_fixture_operation"
FIXTURE_OBSERVATION_TOOL = "query.quality.http_fixture_operation_observation"
FIXTURE_JOB_TOOLS = frozenset({FIXTURE_COMMAND_TOOL, FIXTURE_QUERY_TOOL, FIXTURE_CANCEL_TOOL,
    FIXTURE_HISTORY_LIST_TOOL, FIXTURE_HISTORY_READ_TOOL, FIXTURE_OBSERVATION_TOOL})
FIXTURE_COMMAND_SCHEMA = "nasus.http-fixture-command.v1"
FIXTURE_DISPATCH_COMMAND_SCHEMA = "nasus.http-fixture-dispatch-command.v1"
FIXTURE_CANONICAL_DISPATCH_SCHEMA = "nasus.http-fixture-dispatch.v4"
FALSE_AUTHORITIES = ("execution_authorized", "canonical_execution_committed", "business_coverage_verified", "baseline_restored")


def verify_fixture_command(snapshot, request, *, invocation_id, request_digest, actor_id, historical=False, now=None):
    """Verify the complete canonical input, not only a client-provided selection."""
    try:
        if (type(actor_id) is not str or not actor_id.strip() or len(actor_id) > 128
                or any(ord(char) < 32 for char in actor_id)):
            raise HttpFixtureInvalid("fixture command requires its exact independent confirming actor")
        payload = snapshot["input_payload"]
        if (snapshot["id"] != invocation_id or snapshot["tool_id"] != FIXTURE_COMMAND_TOOL
                or type(payload) is not dict or payload.get("confirmed_by_user") is not True
                or payload.get("confirmed_actor_id") != actor_id
                or snapshot["status"] not in ({"running", "completed", "failed", "cancelled"} if historical else {"running"})
                or acceptance_digest({"tool_id": snapshot["tool_id"], "input_payload": payload}) != request_digest
                or any(payload.get(key) != value for key, value in request.items())):
            raise HttpFixtureInvalid("fixture execution requires its unchanged independently confirmed original command")
        confirmed = datetime.fromisoformat(payload["confirmed_at"])
        if confirmed.tzinfo is None:
            raise HttpFixtureInvalid("fixture command confirmation requires a timezone")
        if not historical and (now is None or now.tzinfo is None
                or not 0 <= (now - confirmed).total_seconds() <= 900):
            raise HttpFixtureInvalid("fixture command confirmation is not fresh by PostgreSQL time")
        return confirmed
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        if isinstance(exc, HttpFixtureInvalid):
            raise
        raise HttpFixtureInvalid("fixture original command cannot be verified") from exc
