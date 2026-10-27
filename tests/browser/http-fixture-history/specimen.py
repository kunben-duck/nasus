"""Production DTO compilation with explicit archive/HTTP doubles, never a live target."""
from copy import deepcopy
import json

import pytest

from apps.api.app.application.quality_loop.http_fixture_history import HttpFixtureHistoryTarget
from apps.api.tests.test_http_fixture_history import history_specimen
from apps.api.tests.test_http_fixture_native_grants import native_grant
from apps.api.tests.test_http_fixture_observations import observation_specimen, observed_phase
from apps.api.tests.test_owned_target_environment import spec


def produce(cancelled=False):
    patch = pytest.MonkeyPatch()
    try:
        v = observation_specimen.__wrapped__(history_specimen.__wrapped__(native_grant.__wrapped__(spec.__wrapped__()), patch), patch)
        observed_phase(v)
        if cancelled:
            v.history_state["rows"][1]["command"]["status"] = "cancelled"
            v.history_state["rows"][2]["execution"]["status"] = "cancelled"
            v.job.update(status="cancelled", cancellation_requested=True, cancellation_delivered=True)
        page = v.history.list(v.query.model_copy(update={"limit": 3})).model_dump(mode="json")
        observations = {item["invocation_id"]: v.observations.read(HttpFixtureHistoryTarget(
            project_id=item["project_id"], invocation_id=item["invocation_id"])).model_dump(mode="json") for item in page["items"]}
        return deepcopy({"page": page, "observations": observations})
    finally:
        patch.undo()


if __name__ == "__main__":
    print(json.dumps({"running": produce(), "cancelled": produce(True)}))
