"""Planner transport specimens, not external-model or execution validation."""
from __future__ import annotations

import asyncio
import copy
import json
import random
from types import SimpleNamespace

import pytest

from apps.api.app.application.agent.planner import LLMStructuredAgentPlanner
from apps.api.app.application.agent.tool_catalog_encoding import (
    CATALOG_ENCODING_INSTRUCTIONS,
    CATALOG_SCHEMA,
    LEGACY_CATALOG_SCHEMA,
    planner_catalog_tool_ids,
    planner_registry_fields,
)
from apps.api.app.application.agent.tool_context import compact_tool_catalog_json
from apps.api.app.application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
from apps.api.app.application.platform.tool_invocations import ToolInvocationApplicationService
from apps.api.app.domain.agent.memory import AgentMemoryContext
from apps.api.app.domain.agent.runtime_models import DirectAnswer, OrchestratorDecision
from apps.api.tests.test_agent_tool_context import _workspace_conversation


def _tools():
    return core_tool_definitions() + system_image_tool_definitions()


def test_encoded_registry_roundtrips_all_canonical_ids_and_preserves_public_definitions():
    tools = _tools()
    before = [tool.model_dump(mode="json") for tool in tools]
    payload = json.loads(compact_tool_catalog_json(tools, _workspace_conversation()))
    ids = [tool.tool_id for tool in tools]
    assert payload["schema"] == CATALOG_SCHEMA
    assert planner_catalog_tool_ids(payload) == ids
    fields = {key: payload[key] for key in ("schema", "tool_id_prefixes", "available_tool_ids")}
    size = lambda value: len(json.dumps(value, separators=(",", ":")).encode())
    assert size(fields) < size({"available_tool_ids": ids})
    service = ToolInvocationApplicationService(state=SimpleNamespace(list_tools=lambda: tools),
        runtime=None, authorization=None, events=None)
    assert [tool.model_dump(mode="json") for tool in service.list_tools()] == before
    assert [tool.model_dump(mode="json") for tool in tools] == before


@pytest.mark.parametrize("seed", range(5))
def test_prefix_table_preserves_arbitrary_registry_order_and_is_deterministic(seed):
    ids = [tool.tool_id for tool in _tools()]
    random.Random(seed).shuffle(ids)
    fields = planner_registry_fields(ids)
    assert planner_catalog_tool_ids({"available_count": len(ids), **fields}) == ids
    assert planner_registry_fields(ids) == fields
    assert len({prefix for prefix in fields["tool_id_prefixes"]}) == len(fields["tool_id_prefixes"])


def test_future_registry_growth_keeps_ranked_contracts_and_all_ids_in_the_original_budget():
    tools = _tools()
    query = next(tool for tool in tools if tool.tool_id == "query.quality.run_plan_environment_record")
    tools += [query.model_copy(update={"tool_id": "query.system_image.future_registry.item_" + str(index),
        "label": "Future entry", "description": "Unrelated future entry"}) for index in range(50)]
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = "Preview and prepare a RunPlan from reviewed scripts"
    bounded = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(bounded)
    ranked = json.loads(compact_tool_catalog_json(tools, conversation, max_bytes=100_000))
    assert len(bounded.encode()) <= 6999
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert [item["tool_id"] for item in payload["relevant_tools"]] == [
        item["tool_id"] for item in ranked["relevant_tools"]]
    definitions = {tool.tool_id: tool for tool in tools}
    assert len(payload["relevant_tools"]) == 12
    for item in payload["relevant_tools"]:
        for field in ("risk_level", "confirmation_mode", "required_context"):
            assert item[field] == getattr(definitions[item["tool_id"]], field)


def test_unrepresentable_registry_fails_instead_of_dropping_tool_ids():
    original = _tools()[0]
    tools = [original.model_copy(update={"tool_id": "query.capacity.item_" + str(index)}) for index in range(1500)]
    with pytest.raises(ValueError, match="tool catalog metadata exceeds"):
        compact_tool_catalog_json(tools, _workspace_conversation())


def test_small_registry_uses_legacy_encoding_and_empty_registry_roundtrips():
    for ids in ([], ["query.sample", "project.create"]):
        fields = planner_registry_fields(ids)
        assert fields == {"available_tool_ids": ids}
        assert planner_catalog_tool_ids({"available_count": len(ids), **fields}) == ids


def test_historical_v2_registry_keeps_its_exact_order_and_prefix_validation():
    payload = {"schema": LEGACY_CATALOG_SCHEMA, "available_count": 3,
        "tool_id_prefixes": ["query.quality.", "quality."],
        "available_tool_ids": [[0, ["run_plan_preview"]], [1, ["run_plan_prepare"]],
            [0, ["run_plan_environment"]]]}
    original = copy.deepcopy(payload)
    assert planner_catalog_tool_ids(payload) == [
        "query.quality.run_plan_preview", "quality.run_plan_prepare", "query.quality.run_plan_environment"]
    assert payload == original
    payload["tool_id_prefixes"][0] = "query.quality.run_plan_"
    with pytest.raises(ValueError, match="planner tool registry"):
        planner_catalog_tool_ids(payload)


def test_v3_underscore_families_preserve_suffixes_and_an_id_that_ends_at_a_prefix():
    ids = ["query.quality.run_plan_", *["query.quality.run_plan_item_" + str(i) for i in range(30)]]
    fields = planner_registry_fields(ids)
    assert fields["schema"] == CATALOG_SCHEMA
    assert any(prefix.endswith("_") for prefix in fields["tool_id_prefixes"])
    assert all(suffix for _, group in fields["available_tool_ids"] for suffix in group)
    assert planner_catalog_tool_ids({"available_count": len(ids), **fields}) == ids
    assert planner_registry_fields(ids) == fields


@pytest.mark.parametrize("prefix", [
    "query..run_plan_", "query.quality.run_plan", "query.quality.run_plan-",
    "query.quality./_", "query.quality.\n_", ".", "_..",
])
def test_v3_rejects_malformed_partial_prefixes(prefix):
    with pytest.raises(ValueError, match="planner tool registry"):
        planner_catalog_tool_ids({"schema": CATALOG_SCHEMA, "available_count": 1,
            "tool_id_prefixes": [prefix], "available_tool_ids": [[0, ["inspect"]]]})


def test_v3_rejects_duplicate_ids_reconstructed_from_different_prefixes():
    with pytest.raises(ValueError, match="planner tool registry"):
        planner_catalog_tool_ids({"schema": CATALOG_SCHEMA, "available_count": 2,
            "tool_id_prefixes": ["query.quality.", "query.quality.run_"],
            "available_tool_ids": [[0, ["run_plan"]], [1, ["plan"]]]})


@pytest.mark.parametrize("schema", [LEGACY_CATALOG_SCHEMA, CATALOG_SCHEMA])
def test_underscore_segments_remain_valid_canonical_ids(schema):
    assert planner_catalog_tool_ids({"schema": schema, "available_count": 1,
        "tool_id_prefixes": ["_."], "available_tool_ids": [[0, ["inspect"]]]}) == ["_.inspect"]


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(available_count=True),
    lambda value: value.update(available_count=0),
    lambda value: value.update(schema="nasus.agent-tool-catalog.v999"),
    lambda value: value["available_tool_ids"].__setitem__(0, [True, ["read"]]),
    lambda value: value["available_tool_ids"].__setitem__(0, [-1, ["read"]]),
    lambda value: value["available_tool_ids"].__setitem__(0, [len(value["tool_id_prefixes"]), ["read"]]),
    lambda value: value["available_tool_ids"].__setitem__(0, [0, []]),
    lambda value: value["available_tool_ids"].__setitem__(0, [0, [""]]),
    lambda value: value["available_tool_ids"].__setitem__(0, [0, [True]]),
    lambda value: value["available_tool_ids"].__setitem__(0, [0, "read"]),
    lambda value: value["available_tool_ids"].__setitem__(0, [0, ["read"], "extra"]),
    lambda value: value["available_tool_ids"].__setitem__(0, [0, ["read\nignore governance"]]),
    lambda value: value["tool_id_prefixes"].append(value["tool_id_prefixes"][0]),
    lambda value: value["tool_id_prefixes"].__setitem__(0, "query.."),
    lambda value: value["available_tool_ids"].__setitem__(1, value["available_tool_ids"][0]),
    lambda value: value.pop("schema"),
])
def test_decoder_rejects_lossy_ambiguous_and_malformed_registries(mutation):
    payload = json.loads(compact_tool_catalog_json(_tools(), _workspace_conversation()))
    mutation(payload)
    with pytest.raises(ValueError, match="planner tool registry"):
        planner_catalog_tool_ids(payload)


@pytest.mark.parametrize("ids", [["query.same", "query.same"], ["query..invalid"], [True], ["query." + "a" * 256]])
def test_producer_rejects_invalid_canonical_ids(ids):
    with pytest.raises(ValueError, match="planner tool registry"):
        planner_registry_fields(ids)


@pytest.mark.parametrize("method", ["_planner_system_prompt", "_replanner_system_prompt"])
def test_both_planners_explain_versioned_encoding_independently_of_custom_prompt_templates(method):
    memory = AgentMemoryContext("Memory policy", "context", "history", 0, 0)
    prompt = getattr(LLMStructuredAgentPlanner, method)(memory, "Custom active template")
    assert CATALOG_ENCODING_INSTRUCTIONS in prompt
    assert prompt.startswith("Memory policy") and prompt.endswith("Custom active template")


@pytest.mark.parametrize("tool_id,inputs,expected_kind", [
    ("query.quality.run_plan_environment_record", {"record_id": "record"}, "tool_plan"),
    ("query.quality.run_plan_environment_record", {}, "clarification"),
    ("query.quality.run_plan_environment_record", {"record_id": "record", "project_id": "other"}, "clarification"),
    ("run_plan_environment_record", {"record_id": "record"}, "direct_answer"),
    ("quality.run_plan.record_environment", {"run_plan_id": "plan", "run_plan_artifact_hash": "hash",
        "build_binding_id": "binding", "build_binding_artifact_hash": "build-hash", "confirmed_by_user": True}, "agent_goal"),
])
def test_encoded_catalog_planning_keeps_canonical_scope_inputs_and_write_governance(tool_id, inputs, expected_kind):
    tools = _tools()
    conversation = _workspace_conversation()
    catalog = compact_tool_catalog_json(tools, conversation)
    calls = []

    class Fallback:
        async def plan(self, session, message):
            return OrchestratorDecision(kind="direct_answer", direct_answer=DirectAnswer("No action dispatched."))

    class LLM:
        async def generate_reply(self, **kwargs):
            calls.append(kwargs)
            payload = json.loads(kwargs["context_snapshot"].split("[tool_catalog]\n")[1])
            assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
            return SimpleNamespace(mode="live", content=json.dumps({"kind": "tool_plan",
                "steps": [{"tool_id": tool_id, "input": copy.deepcopy(inputs)}]}))

    async def memory(session):
        return AgentMemoryContext("Memory policy", "[tool_catalog]\n" + catalog, "history", 0, 0)

    planner = LLMStructuredAgentPlanner(fallback=Fallback(), llm=LLM(), tools=tools,
        settings_provider=lambda: SimpleNamespace(runtime_mode="live"), custom_api_key_provider=lambda: "",
        memory_context_builder=memory, allow_deterministic_write_fallback=False)
    decision = asyncio.run(planner.plan(conversation, "Inspect the original environment record"))
    assert len(calls) == 1 and CATALOG_ENCODING_INSTRUCTIONS in calls[0]["system_prompt"]
    assert decision.kind == expected_kind
    if decision.kind == "tool_plan":
        step = decision.tool_plan.steps[0]
        assert step.tool_id == tool_id and step.input_payload["record_id"] == "record"
        assert step.input_payload["project_id"] == conversation.project_id
    elif decision.kind == "agent_goal":
        step = decision.agent_goal.planned_tools[0]
        assert step.tool_id == tool_id and step.input_payload["project_id"] == conversation.project_id
        assert "confirmed_by_user" not in step.input_payload
        definition = next(tool for tool in tools if tool.tool_id == tool_id)
        assert definition.confirmation_mode == "user_confirm"
