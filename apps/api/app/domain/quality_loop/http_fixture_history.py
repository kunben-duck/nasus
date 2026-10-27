"""Discovery is an observation of original commands, never operation authority."""
from .http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_CANCEL_TOOL, FIXTURE_HISTORY_LIST_TOOL, FIXTURE_HISTORY_READ_TOOL
from .http_fixture_grant import GRANT_TOOL


FIXTURE_HISTORY_TOOLS = frozenset({FIXTURE_HISTORY_LIST_TOOL, FIXTURE_HISTORY_READ_TOOL})
FIXTURE_HISTORY_STAGES = {GRANT_TOOL: "grant", FIXTURE_COMMAND_TOOL: "execute", FIXTURE_CANCEL_TOOL: "cancel"}
FIXTURE_HISTORY_SCHEMA = "nasus.http-fixture-operation-history.v1"
FIXTURE_HISTORY_OBSERVATION = "original_command_metadata_not_target_observation"


class HttpFixtureHistoryUnavailable(RuntimeError):
    pass


def validate_history_inventory(rows, total, after_id, limit, next_after_id):
    ids = [row["invocation_id"] for row in rows]
    if (type(total) is not int or total < len(rows) or not 1 <= limit <= 5
            or len(rows) > limit or ids != sorted(set(ids)) or any(ident <= after_id for ident in ids)
            or next_after_id is not None and (len(rows) != limit or next_after_id != ids[-1])):
        from .http_fixtures import HttpFixtureInvalid
        raise HttpFixtureInvalid("fixture history must preserve its complete visible count and exact page")
