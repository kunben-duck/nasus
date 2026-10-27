"""Real HTTP streaming and PostgreSQL replay; run with test-api-postgres.py."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
import socket
from threading import Event, Thread
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy.engine import make_url
import uvicorn

from apps.api.app.main import app
from apps.api.app.store import get_runtime_assembly
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository


def data_events(lines):
    for line in lines:
        if line.startswith("data: "):
            yield json.loads(line[6:])


def test_real_http_stream_flushes_idle_partial_tokens_and_reconnects_from_pg(monkeypatch):
    assert make_url(os.environ["NASUS_DATABASE_URL"]).database.startswith("nasus_test_")
    monkeypatch.setattr(app.state, "auth_config", replace(app.state.auth_config, mode="required", bearer_token=uuid4().hex))
    client = TestClient(app)
    account = client.post("/v1/auth/register", json={"email": f"sse-{uuid4().hex}@example.com",
        "name": "SSE protocol reviewer", "password": "sse-test-password-123"})
    assert account.status_code == 200
    headers = {"Authorization": "Bearer " + account.json()["access_token"]}
    created = client.post("/v1/conversations", headers=headers,
        json={"space_type": "build", "space_id": f"sse-{uuid4().hex}", "title": "HTTP replay protocol"})
    assert created.status_code == 200
    conversation_id = created.json()["id"]
    runtime = get_runtime_assembly()

    async def seed_closed_loop_waiter():
        queue = runtime.event_stream_buffer.conversation_queue(conversation_id)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.01)

    asyncio.run(seed_closed_loop_waiter())
    finish, finished = Event(), Event()

    async def graph(_request):
        try:
            yield {"kind": "started", "metadata": {"llm_provider": "explicit_http_protocol"}}
            await asyncio.sleep(0.1)
            yield {"kind": "delta", "delta": "First "}
            yield {"kind": "delta", "delta": "pending "}
            while not finish.is_set():
                await asyncio.sleep(0.01)
            yield {"kind": "delta", "delta": "complete"}
            yield {"kind": "completed", "metadata": {"llm_provider": "explicit_http_protocol"}}
            yield {"kind": "turn_result", "result": {"kind": "direct_answer"}}
        finally:
            finished.set()

    monkeypatch.setattr(runtime.conversation_turn_graph, "astream", graph)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="none"))
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            assert thread.is_alive()
            time.sleep(0.01)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=headers, timeout=3) as http:
            url = f"/v1/conversations/{conversation_id}"
            with http.stream("GET", url + "/events") as stream:
                assert stream.status_code == 200
                accepted = http.post(url + "/messages", headers={"Idempotency-Key": "sse-http-one-turn"},
                    json={"content": "Explicit streaming protocol, no external model"})
                assert accepted.status_code == 202 and not finish.is_set()
                duplicate = http.post(url + "/messages", headers={"Idempotency-Key": "sse-http-one-turn"},
                    json={"content": "Explicit streaming protocol, no external model"})
                assert duplicate.status_code == 202 and duplicate.json()["turn_id"] == accepted.json()["turn_id"]
                observed = []
                for item in data_events(stream.iter_lines()):
                    observed.append(item)
                    deltas = [e for e in observed if e["event_type"] == "conversation.message.delta"]
                    if "".join(e["payload"]["delta"] for e in deltas) == "First pending ":
                        break
                assert len(deltas) == 2 and not finish.is_set()
                snapshot = http.get(url).json()
                assistant = next(m for m in snapshot["messages"] if m["role"] == "assistant")
                assert assistant["status"] == "streaming" and assistant["blocks"][0]["text"] == "First pending "
                assert assistant["sequence_max"] == 2
                cursor = deltas[-1]["event_id"]
            with http.stream("GET", url + "/events", headers={"Last-Event-ID": cursor}) as replay:
                assert replay.status_code == 200
                finish.set()
                resumed = []
                for item in data_events(replay.iter_lines()):
                    resumed.append(item)
                    if item["event_type"] == "conversation.turn.completed":
                        break
            resumed_deltas = [e for e in resumed if e["event_type"] == "conversation.message.delta"]
            assert [e["payload"]["delta"] for e in resumed_deltas] == ["complete"]
            assert all(e["event_id"] != cursor for e in resumed)
            final = http.get(url).json()
            assistant = next(m for m in final["messages"] if m["role"] == "assistant")
            assert assistant["status"] == "completed" and assistant["sequence_max"] == 3
            assert assistant["blocks"][0]["text"] == "First pending complete"
            persisted = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=conversation_id, after_event_id=None)
            assert [e.event_id for e in persisted if e.event_type == "conversation.message.delta"] == [e["event_id"] for e in deltas + resumed_deltas]
    finally:
        finish.set()
        finished.wait(5)
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive()
