"""Real Temporal histories from the old contract, replayed by the new workflow."""
import asyncio
import os
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Replayer, Worker

from apps.api.app.infrastructure.workflow.nasus_generation_workflow import NasusTestDesignGenerationWorkflow
from apps.api.tests.legacy_generation_workflow_fixture import LegacyGenerationWorkflow


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicit isolated Temporal task queue")
@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_old_generation_history_replays_after_batch_deadline_patch_without_executing_activities(outcome):
    invocation_id = "legacy-history-fixture-" + uuid4().hex
    observed = []

    @activity.defn(name="run_test_design_generation")
    async def run(ident: str) -> str:
        observed.append(("run", ident))
        if outcome == "failed":
            raise ApplicationError("Explicit replay fixture failure, no model or database", non_retryable=True)
        return "completed"

    @activity.defn(name="fail_test_design_generation")
    async def fail(ident: str) -> str:
        observed.append(("fail", ident))
        return "failed"

    async def verify():
        client = await Client.connect(os.environ["TEST_TEMPORAL_ADDRESS"],
            namespace=os.getenv("NASUS_TEMPORAL_NAMESPACE", "default"))
        queue = "nasus-generation-history-fixture-" + uuid4().hex
        async with Worker(client, task_queue=queue, workflows=[LegacyGenerationWorkflow], activities=[run, fail]):
            handle = await client.start_workflow(LegacyGenerationWorkflow.run, invocation_id,
                id="nasus-test-design-replay-fixture:" + invocation_id, task_queue=queue)
            assert await asyncio.wait_for(handle.result(), 30) == outcome
            history = await handle.fetch_history()
        scheduled = [event.activity_task_scheduled_event_attributes for event in history.events
            if event.HasField("activity_task_scheduled_event_attributes")]
        assert scheduled[0].start_to_close_timeout.seconds == 600
        assert scheduled[0].schedule_to_close_timeout.seconds == 1800
        assert not any(event.HasField("marker_recorded_event_attributes") for event in history.events)
        before_replay = list(observed)
        result = await Replayer(workflows=[NasusTestDesignGenerationWorkflow]).replay_workflow(history)
        assert result.replay_failure is None and observed == before_replay

    asyncio.run(verify())
    assert observed == [("run", invocation_id)] + ([("fail", invocation_id)] if outcome == "failed" else [])
