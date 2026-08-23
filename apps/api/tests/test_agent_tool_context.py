from __future__ import annotations

import json

from apps.api.app.application.agent.agent_models import (
    ConversationMessage,
    ConversationSession,
    MessageBlock,
)
from apps.api.app.application.agent.tool_context import compact_tool_catalog_json
from apps.api.app.application.platform.tool_catalog import (
    core_tool_definitions,
    system_image_tool_definitions,
)
from apps.api.app.domain.agent.memory import AgentMemoryContext, memory_context_summary


def _workspace_conversation() -> ConversationSession:
    return ConversationSession(
        id="conversation_tool_context",
        session_id="session_tool_context",
        title="Checkout quality workspace",
        space_type="workspace",
        space_id="us_checkout",
        project_id="project_checkout",
        version_id="version_checkout",
        us_id="us_checkout",
        status="active",
        messages=[
            ConversationMessage(
                id="message_tool_context",
                role="user",
                created_at="2026-08-09T00:00:00+00:00",
                blocks=[
                    MessageBlock(
                        type="text",
                        text="Generate test cases, execute them, and assess release risk.",
                    )
                ],
            )
        ],
    )


def test_tool_catalog_context_keeps_all_ids_but_bounds_detailed_contracts() -> None:
    tools = core_tool_definitions() + system_image_tool_definitions()

    serialized = compact_tool_catalog_json(tools, _workspace_conversation())
    payload = json.loads(serialized)

    assert payload["available_count"] == len(tools)
    assert payload["available_tool_ids"] == [tool.tool_id for tool in tools]
    assert len(payload["relevant_tools"]) == 12
    relevant_ids = {tool["tool_id"] for tool in payload["relevant_tools"]}
    assert "quality.case.generate" in relevant_ids
    assert "run.start" in relevant_ids
    assert "release.assess" in relevant_ids
    assert all("description" in tool for tool in payload["relevant_tools"])
    assert len(serialized.encode("utf-8")) < 7_000


def test_memory_context_summary_never_interprets_json_arrays_as_section_names() -> None:
    memory = AgentMemoryContext(
        system_prompt="system",
        context_snapshot=(
            "[space]\n"
            "space_type=project\n"
            "[tool_catalog]\n"
            '[{"tool_id":"project.create","description":"Create a project"}]'
        ),
        history_snapshot="history",
        recent_turn_count=2,
        checkpoint_count=1,
    )

    summary = memory_context_summary(memory)

    assert summary == "sections=space, tool_catalog; recent_turns=2; checkpoints=1"
    assert "project.create" not in summary
