from __future__ import annotations

import json
import os
import re
import sys
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from apps.api.app.application.quality_loop.generation import fallback_generation_output


HOST = os.getenv("NASUS_MODEL_FIXTURE_HOST", "127.0.0.1")
PORT = int(os.getenv("NASUS_MODEL_FIXTURE_PORT", "18110"))
TOKEN = os.getenv("NASUS_MODEL_FIXTURE_TOKEN", "nasus-model-fixture-token")
COUNTERS = {"chat": 0, "embedding": 0, "rerank": 0}


def _vector(text: str, dimensions: int = 32) -> list[float]:
    digest = sha256(text.encode("utf-8")).digest()
    return [round((digest[index % len(digest)] / 127.5) - 1.0, 6) for index in range(dimensions)]


def _extract_us_id(text: str) -> str:
    match = re.search(r"\bUS\s+([A-Za-z0-9_.:-]+)", text)
    return match.group(1).rstrip(".,") if match else "contract_us"


def _conversation_input(text: str) -> str:
    marker = "Conversation input:\n"
    if marker not in text:
        return text.strip()
    conversation_input = text.split(marker, 1)[1]
    return conversation_input.split("\n\nWorkspace context:", 1)[0].strip()


def _extract_system_image_source_specs(text: str) -> list[dict[str, str]]:
    text = _conversation_input(text)
    source_specs: list[dict[str, str]] = []
    patterns = (
        ("code", "Code repository", r"code path\s+(.+?)(?=,\s*US docs path|,\s*tests path|$)"),
        ("us_doc", "Historical US documents", r"US docs path\s+(.+?)(?=,\s*tests path|$)"),
        ("test_asset", "Historical test assets", r"tests path\s+(.+?)\s*$"),
    )
    for source_type, label, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is None:
            continue
        source_uri = match.group(1).strip().rstrip(",")
        if source_uri:
            source_specs.append(
                {
                    "source_type": source_type,
                    "source_uri": source_uri,
                    "label": label,
                }
            )
    return source_specs


def _system_image_agent_goal(user_prompt: str) -> dict[str, Any]:
    source_specs = _extract_system_image_source_specs(user_prompt)
    register_input: dict[str, Any] = {}
    if source_specs:
        register_input["source_specs"] = source_specs
    steps = [
        {
            "tool_id": "system_image.sources.register",
            "input": register_input,
            "reason": "Register the source references explicitly supplied by the user.",
            "target_scope": "central",
        },
        {
            "tool_id": "system_image.sources.ingest",
            "input": {},
            "reason": "Ingest the registered code, requirement, and test evidence.",
            "target_scope": "central",
        },
        {
            "tool_id": "system_image.context.materialize",
            "input": {},
            "reason": "Materialize governed context objects, relationships, and quality metrics.",
            "target_scope": "central",
        },
        {
            "tool_id": "system_image.baseline.initialize",
            "input": {},
            "reason": "Promote the materialized context through the required confirmation gate.",
            "target_scope": "central",
        },
    ]
    return {
        "kind": "agent_goal",
        "goal_template": "system_image_build",
        "title": "Build Official System Image",
        "summary": "Build the project baseline from the supplied system sources.",
        "goal_description": (
            "Register sources, ingest durable evidence, materialize context, and initialize the official baseline."
        ),
        "suggested_autonomy_level": "semi_auto",
        "estimated_steps": len(steps) * 2 + 2,
        "steps": steps,
        "kickoff_message": "I will build the Official System Image through the governed tool chain.",
    }


def _chat_content(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return "{}"
    system_prompt = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if isinstance(message, dict) and message.get("role") == "system"
    )
    user_prompt = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    )
    if "Reply with exactly READY." in system_prompt:
        return "READY"

    if "Nasus observe/replan planner" in system_prompt:
        return json.dumps(
            {
                "action": "keep",
                "rationale": "The validated pending tool plan remains correct after the persisted observation.",
                "confidence": 0.99,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    if "Nasus structured agent planner" in system_prompt:
        conversation_input = _conversation_input(user_prompt)
        lowered_user_prompt = conversation_input.lower()
        if "system image" in lowered_user_prompt:
            return json.dumps(
                _system_image_agent_goal(conversation_input),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return json.dumps(
            {
                "kind": "clarification",
                "question": "Which governed Nasus outcome should I plan?",
                "reason": "model_fixture_unsupported_goal",
                "missing_context": ["supported_goal"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    stage = next(
        (
            candidate
            for marker, candidate in (
                ("quality scope planner", "scope"),
                ("test scenario planner", "scenarios"),
                ("verification planner", "verification_plan"),
                ("structured test case author", "cases"),
                ("Playwright automation architect", "automation"),
                ("quality change-document author", "change_document"),
            )
            if marker in system_prompt
        ),
        None,
    )
    if stage is not None:
        output = fallback_generation_output(stage, _extract_us_id(user_prompt))
        return json.dumps(output, ensure_ascii=False, separators=(",", ":"))

    # Non-planner calls that are outside the production contract fixture remain
    # deliberately empty so callers must validate their own structured schema.
    return "{}"


class ModelProviderHandler(BaseHTTPRequestHandler):
    server_version = "NasusModelContract/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._write_json(200, {"status": "ok"})
            return
        if self.path == "/__stats":
            if not self._authorized():
                return
            self._write_json(200, {"requests": dict(COUNTERS)})
            return
        self._write_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        payload = self._read_json()
        if payload is None:
            return
        if self.path == "/v1/chat/completions":
            COUNTERS["chat"] += 1
            self._write_json(
                200,
                {
                    "id": f"chatcmpl-contract-{COUNTERS['chat']}",
                    "object": "chat.completion",
                    "model": payload.get("model", "nasus-contract-chat"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": _chat_content(payload)},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
            return
        if self.path == "/v1/embeddings":
            COUNTERS["embedding"] += 1
            raw_inputs = payload.get("input", [])
            inputs = [raw_inputs] if isinstance(raw_inputs, str) else raw_inputs
            if not isinstance(inputs, list):
                self._write_json(400, {"error": "input_must_be_string_or_list"})
                return
            self._write_json(
                200,
                {
                    "object": "list",
                    "model": payload.get("model", "nasus-contract-embedding"),
                    "data": [
                        {"object": "embedding", "index": index, "embedding": _vector(str(text))}
                        for index, text in enumerate(inputs)
                    ],
                },
            )
            return
        if self.path == "/v1/rerank":
            COUNTERS["rerank"] += 1
            documents = payload.get("documents", [])
            if not isinstance(documents, list):
                self._write_json(400, {"error": "documents_must_be_list"})
                return
            self._write_json(
                200,
                {
                    "model": payload.get("model", "nasus-contract-rerank"),
                    "results": [
                        {
                            "index": index,
                            "relevance_score": round(1.0 - (index / max(len(documents), 1)), 6),
                        }
                        for index in range(len(documents))
                    ],
                },
            )
            return
        self._write_json(404, {"error": "not_found"})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"model-contract {self.address_string()} {format % args}\n")

    def _authorized(self) -> bool:
        if self.headers.get("Authorization") == f"Bearer {TOKEN}":
            return True
        self._write_json(401, {"error": "invalid_token"})
        return False

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self._write_json(400, {"error": "invalid_json"})
            return None
        if not isinstance(payload, dict):
            self._write_json(400, {"error": "json_object_required"})
            return None
        return payload

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), ModelProviderHandler).serve_forever()
