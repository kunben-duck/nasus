"""Opt-in real Temporal handoff with disposable PostgreSQL and a deterministic model."""
import asyncio
import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Replayer, Worker

from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_conversation_memory_api import install_memory
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.infrastructure.config.agent_runtime_config import TemporalGatewayConfig
from apps.api.app.infrastructure.workflow.conversation_memory_runtime import (
    TemporalConversationMemoryRuntime, build_memory_activities,
)
from apps.api.app.infrastructure.workflow.nasus_memory_workflow import NasusConversationMemoryWorkflow


@pytest.mark.skipif(not os.getenv("TEST_TEMPORAL_ADDRESS"), reason="requires explicitly enabled Temporal")
def test_worker_handoff_after_commit_does_not_repeat_summary(evidence_api, monkeypatch):
    import apps.api.app.bootstrap as bootstrap

    conversation, service, model = install_memory(evidence_api, monkeypatch)
    with actor_scope(UserProfile.model_validate(evidence_api["owner"])):
        job = service.schedule(conversation)
    monkeypatch.setenv("NASUS_AGENT_WORKFLOW_RUNTIME", "temporal")
    monkeypatch.setattr(bootstrap, "get_application_container", lambda: SimpleNamespace(conversation_memory=service))

    async def verify():
        config = TemporalGatewayConfig(address=os.environ["TEST_TEMPORAL_ADDRESS"],
            task_queue="memory-handoff-test-" + uuid4().hex)
        client = await asyncio.wait_for(Client.connect(config.address, namespace=config.namespace), 10)
        runtime = TemporalConversationMemoryRuntime(config, client)
        committed = asyncio.Event()
        base_activity = build_memory_activities()[0]

        @activity.defn(name="compact_conversation_memory")
        async def lose_acknowledgement(job_id: str):
            await base_activity(job_id)
            committed.set()
            raise RuntimeError("test-only acknowledgement loss after database commit")

        handle = None
        try:
            async with Worker(client, task_queue=runtime.task_queue,
                    workflows=[NasusConversationMemoryWorkflow], activities=[lose_acknowledgement],
                    graceful_shutdown_timeout=timedelta(seconds=1)):
                assert await runtime.start(job["id"])
                handle = client.get_workflow_handle("nasus-conversation-memory:" + job["id"])
                await asyncio.wait_for(committed.wait(), 20)
            assert model.calls == 1 and service.jobs.get(job["id"])["status"] == "completed"
            async with Worker(client, task_queue=runtime.task_queue,
                    workflows=[NasusConversationMemoryWorkflow], activities=build_memory_activities()):
                result = await asyncio.wait_for(handle.result(), 30)
                assert result["status"] == "completed" and model.calls == 1
                assert result["checkpoint_id"] == service.jobs.get(job["id"])["checkpoint_id"]
                assert await runtime.start(job["id"]) is False
                await Replayer(workflows=[NasusConversationMemoryWorkflow]).replay_workflow(await handle.fetch_history())
        finally:
            if handle is not None:
                await runtime.cancel(job["id"])

    asyncio.run(verify())
