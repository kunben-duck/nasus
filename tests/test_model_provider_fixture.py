from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from apps.api.app.application.quality_loop.generation import validate_generation_output


def _load_fixture() -> ModuleType:
    path = Path(__file__).parent / "fixtures" / "model-provider" / "openai_compatible_server.py"
    spec = importlib.util.spec_from_file_location("nasus_model_provider_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_chat_content = _load_fixture()._chat_content


def _payload(system_prompt: str, user_prompt: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    }


def test_model_fixture_returns_governed_system_image_agent_goal() -> None:
    content = _chat_content(
        _payload(
            "You are the Nasus structured agent planner.",
            "\n\n".join(
                (
                    "Conversation memory:\nNo prior messages.",
                    (
                        "Conversation input:\nBuild the official system image with "
                        "code path /fixtures/code, "
                        "US docs path /fixtures/us, "
                        "tests path /fixtures/tests"
                    ),
                    "Workspace context:\nCurrent project facts.",
                )
            ),
        )
    )

    decision = json.loads(content)

    assert decision["kind"] == "agent_goal"
    assert decision["goal_template"] == "system_image_build"
    assert [step["tool_id"] for step in decision["steps"]] == [
        "system_image.sources.register",
        "system_image.sources.ingest",
        "system_image.context.materialize",
        "system_image.baseline.initialize",
    ]
    assert decision["steps"][0]["input"]["source_specs"] == [
        {
            "source_type": "code",
            "source_uri": "/fixtures/code",
            "label": "Code repository",
        },
        {
            "source_type": "us_doc",
            "source_uri": "/fixtures/us",
            "label": "Historical US documents",
        },
        {
            "source_type": "test_asset",
            "source_uri": "/fixtures/tests",
            "label": "Historical test assets",
        },
    ]
    assert all("project_id" not in step["input"] for step in decision["steps"])


def test_model_fixture_returns_valid_keep_replan_decision() -> None:
    content = _chat_content(
        _payload(
            "You are the Nasus observe/replan planner.",
            '{"latest_observation":"sources registered"}',
        )
    )

    decision = json.loads(content)

    assert decision == {
        "action": "keep",
        "rationale": "The validated pending tool plan remains correct after the persisted observation.",
        "confidence": 0.99,
    }


def test_model_fixture_clarifies_an_unsupported_planner_goal() -> None:
    content = _chat_content(
        _payload(
            "You are the Nasus structured agent planner.",
            "Do something that is outside this contract fixture.",
        )
    )

    decision = json.loads(content)

    assert decision["kind"] == "clarification"
    assert decision["reason"] == "model_fixture_unsupported_goal"


@pytest.mark.parametrize(
    ("system_prompt", "stage"),
    [
        ("You are Nasus quality scope planner.", "scope"),
        ("You are Nasus test scenario planner.", "scenarios"),
        ("You are Nasus verification planner.", "verification_plan"),
        ("You are Nasus structured test case author.", "cases"),
        ("You are Nasus Playwright automation architect.", "automation"),
        ("You are Nasus quality change-document author.", "change_document"),
    ],
)
def test_model_fixture_returns_valid_quality_generation_output(
    system_prompt: str,
    stage: str,
) -> None:
    content = _chat_content(_payload(system_prompt, "Generate assets for US contract-42."))

    output = json.loads(content)

    assert validate_generation_output(stage, output) == output
