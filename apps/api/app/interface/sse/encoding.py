from __future__ import annotations

import json

from ...application.platform.tool_models import EventPayload


SSE_RESPONSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def encode_event(event: EventPayload) -> str:
    payload = json.dumps(event.model_dump(), separators=(",", ":"))
    return f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload}\n\n"


def encode_heartbeat() -> str:
    return ": heartbeat\n\n"


__all__ = ["SSE_RESPONSE_HEADERS", "encode_event", "encode_heartbeat"]
