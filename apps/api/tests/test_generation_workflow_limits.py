"""Workflow deadlines are bounded separately from canonical egress budgets."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from apps.api.app.application.quality_loop.generation_execution_inputs import GENERATION_TIMEOUT_SECONDS
from apps.api.app.infrastructure.workflow import nasus_generation_workflow as module


@pytest.mark.parametrize("complete_batches", [False, True])
def test_workflow_patch_preserves_old_history_and_allows_complete_confirmed_batch_deadlines(monkeypatch, complete_batches):
    activity = AsyncMock(return_value="completed")
    versions = []
    monkeypatch.setattr(module.workflow, "patched", lambda key: versions.append(key) or complete_batches)
    monkeypatch.setattr(module.workflow, "execute_activity", activity)
    assert asyncio.run(module.NasusTestDesignGenerationWorkflow().run("canonical-only-id")) == "completed"
    assert versions == ["test-design-complete-batch-timeout-v1"]
    args, options = activity.await_args
    assert args == ("run_test_design_generation", "canonical-only-id")
    if complete_batches:
        assert options["start_to_close_timeout"] == timedelta(seconds=64 * GENERATION_TIMEOUT_SECONDS + 600)
        assert options["schedule_to_close_timeout"] == options["start_to_close_timeout"] * 3 + timedelta(minutes=30)
    else:
        assert options["start_to_close_timeout"] == timedelta(minutes=10)
        assert options["schedule_to_close_timeout"] == timedelta(minutes=30)
    assert options["heartbeat_timeout"] == timedelta(seconds=15)
    assert options["retry_policy"].maximum_attempts == 3
    assert options["cancellation_type"] == module.workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED
