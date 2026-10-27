from __future__ import annotations

import json

import pytest

from apps.api.app.application.agent.agent_models import (
    ConversationMessage,
    ConversationSession,
    MessageBlock,
)
from apps.api.app.application.agent.tool_context import compact_tool_catalog_json
from apps.api.app.application.agent.tool_catalog_encoding import planner_catalog_tool_ids
from apps.api.app.application.platform.tool_catalog import (
    core_tool_definitions,
    system_image_tool_definitions,
)
from apps.api.app.application.platform.tool_models import ToolDefinition
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
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert len(payload["relevant_tools"]) == 12
    relevant_ids = {tool["tool_id"] for tool in payload["relevant_tools"]}
    assert "quality.case.generate" in relevant_ids
    assert "run.start" in relevant_ids
    assert "release.assess" in relevant_ids
    assert not any("http_fixture" in ident for ident in relevant_ids)
    assert all("description" in tool for tool in payload["relevant_tools"])
    assert len(serialized.encode("utf-8")) < 7_000


@pytest.mark.parametrize("intent", ["Inspect HTTP fixture consent and cancel the original fixture operation",
                                   "查看测试数据准备并取消原测试数据操作"])
def test_fixture_discovery_keeps_original_confirmation_and_full_registry(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    selected = {item["tool_id"]: item for item in payload["relevant_tools"]}
    assert len(serialized.encode()) <= 6999 and len(selected) == 12
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert payload["relevant_tools"][0]["tool_id"] == "quality.http_fixture.cancel"
    for original in tools:
        if "http_fixture" in original.tool_id:
            detail = selected[original.tool_id]
            for field in ("risk_level", "confirmation_mode", "required_context"):
                assert detail[field] == getattr(original, field)
    for ident in ("quality.http_fixture.execute", "quality.http_fixture.cancel", "quality.http_fixture.authorize"):
        assert selected[ident]["confirmation_mode"] == "user_confirm"


@pytest.mark.parametrize("intent", [
    "Inspect the test-design ContextPack history for this frozen image",
    "为固定画像执行全部 AC 的上下文检索",
    "审阅后发布系统画像",
    "Inspect assertion mapping review",
])
def test_catalog_byte_budget_preserves_the_entire_governance_contract(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    tools = [tool.model_copy(update={"description": tool.description + " 中文说明\\\"" * 100})
             for tool in core_tool_definitions() + system_image_tool_definitions()]
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    uncompressed = json.loads(compact_tool_catalog_json(tools, conversation, max_bytes=100_000))
    definitions = {tool.tool_id: tool for tool in tools}

    assert len(serialized.encode("utf-8")) < 7_000
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert payload["available_count"] == len(tools)
    assert len(payload["relevant_tools"]) == 12
    selected_ids = [item["tool_id"] for item in payload["relevant_tools"]]
    ranked_ids = [item["tool_id"] for item in uncompressed["relevant_tools"]]
    if selected_ids != ranked_ids:
        minimum = {**uncompressed, "relevant_tools": [{**item, "label": item["label"][:1],
            "description": item["description"][:1]} for item in uncompressed["relevant_tools"]]}
        # Full contracts may replace a filler only when the ranked set cannot
        # fit even at minimum display text; preserve the high-priority prefix.
        assert len(json.dumps(minimum, ensure_ascii=False, separators=(",", ":")).encode()) > 6999
        assert selected_ids[:10] == ranked_ids[:10]
    for item in payload["relevant_tools"]:
        original = definitions[item["tool_id"]]
        assert item["label"] and original.label.startswith(item["label"])
        assert item["risk_level"] == original.risk_level
        assert item["confirmation_mode"] == original.confirmation_mode
        assert item["required_context"] == original.required_context
        assert item["description"] and original.description.startswith(item["description"])


def test_catalog_never_drops_ids_or_governance_fields_to_fit_a_small_budget():
    tools = core_tool_definitions() + system_image_tool_definitions()
    with pytest.raises(ValueError, match="tool catalog metadata exceeds"):
        compact_tool_catalog_json(tools, _workspace_conversation(), max_bytes=100)


def test_catalog_fills_details_with_complete_lower_ranked_contracts_when_a_filler_cannot_fit():
    tools = [ToolDefinition(tool_id="query.sample." + name, label="Sample", description="Sample",
        tool_kind="query", scope="central", risk_level="low", confirmation_mode="none",
        required_context=["project_id", *fields], produced_objects=[])
        for name, fields in (("first", []), ("oversized", ["field_" + str(i) for i in range(200)]), ("last", []))]
    value = compact_tool_catalog_json(tools, _workspace_conversation(), relevant_limit=2, max_bytes=600)
    payload = json.loads(value)
    assert len(value.encode()) <= 600
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert [tool["tool_id"] for tool in payload["relevant_tools"]] == [tools[0].tool_id, tools[2].tool_id]
    for tool, detail in zip((tools[0], tools[2]), payload["relevant_tools"]):
        for field in ("risk_level", "confirmation_mode", "required_context"):
            assert detail[field] == getattr(tool, field)


def test_catalog_refuses_a_budget_that_cannot_fit_the_required_number_of_complete_contracts():
    tools = [ToolDefinition(tool_id="query.sample." + str(i), label="Sample", description="Sample",
        tool_kind="query", scope="central", risk_level="low", confirmation_mode="none",
        required_context=["project_id", *("field_" + str(j) for j in range(200))], produced_objects=[])
        for i in range(3)]
    with pytest.raises(ValueError, match="tool catalog metadata exceeds"):
        compact_tool_catalog_json(tools, _workspace_conversation(), relevant_limit=2, max_bytes=600)


@pytest.mark.parametrize("title", ["Budget persistence", "Budget update"])
def test_unrelated_build_budget_context_keeps_all_ids_without_native_build_details(title):
    conversation = _workspace_conversation()
    conversation.space_type = "build"
    conversation.title = title
    conversation.messages = []
    conversation.project_id = conversation.version_id = conversation.us_id = None
    tools = core_tool_definitions() + system_image_tool_definitions()
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    assert len(serialized.encode()) <= 6999
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert len(payload["relevant_tools"]) == 12
    assert not any("native_build" in tool["tool_id"] or "run_plan" in tool["tool_id"]
                   for tool in payload["relevant_tools"])


@pytest.mark.parametrize("intent", ["Inspect native build and cancel the original offline build",
                                   "查看原生构建并取消离线构建"])
def test_native_build_discovery_preserves_pinned_inputs_and_separate_confirmation(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(serialized.encode()) <= 6999 and len(definitions) == 12
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert payload["relevant_tools"][0]["tool_id"] == "quality.native_build.cancel"
    for tool in tools:
        if tool.tool_id in {"quality.native_build.prepare", "quality.native_build.cancel",
                "query.quality.native_build_preview", "query.quality.native_build"}:
            selected = definitions[tool.tool_id]
            for field in ("risk_level", "confirmation_mode", "required_context"):
                assert selected[field] == getattr(tool, field)


@pytest.mark.parametrize("intent", ["Preview and prepare a RunPlan from reviewed scripts", "预览并准备执行计划"])
def test_run_plan_discovery_preserves_declarations_without_granting_execution(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(serialized.encode()) <= 6999 and len(definitions) == 12
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    locator_tools = {"query.quality.run_plan_locators", "quality.run_plan.record_locators",
        "query.quality.run_plan_locator_record"}
    execution_tools = {"quality.run_plan.execute_http", "quality.run_plan.cancel_http",
        "query.quality.run_plan_case_execution"}
    assert not execution_tools.intersection(definitions)
    for tool in tools:
        if "run_plan" in tool.tool_id and tool.tool_id not in locator_tools | execution_tools:
            selected = definitions[tool.tool_id]
            for field in ("risk_level", "confirmation_mode", "required_context"):
                assert selected[field] == getattr(tool, field)
    assert not locator_tools.intersection(definitions)


@pytest.mark.parametrize("intent", [
    "Inspect business case execution and cancel RunPlan HTTP",
    "查看业务用例执行并取消执行计划运行",
    "quality.run_plan.execute_http",
])
def test_case_execution_discovery_keeps_original_inputs_and_independent_confirmation(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    details = {item["tool_id"]: item for item in payload["relevant_tools"]}
    assert len(serialized.encode()) <= 6999 and len(details) == 12
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    case_tools = {"quality.run_plan.execute_http", "quality.run_plan.cancel_http", "query.quality.run_plan_case_execution"}
    for original in tools:
        if original.tool_id in case_tools:
            selected = details[original.tool_id]
            for field in ("risk_level", "confirmation_mode", "required_context"):
                assert selected[field] == getattr(original, field)
    assert details["quality.run_plan.execute_http"]["confirmation_mode"] == "user_confirm"
    assert details["quality.run_plan.cancel_http"]["confirmation_mode"] == "user_confirm"
    assert details["query.quality.run_plan_case_execution"]["confirmation_mode"] == "none"
    if "cancel" in intent or "取消" in intent:
        assert payload["relevant_tools"][0]["tool_id"] == "quality.run_plan.cancel_http"


@pytest.mark.parametrize("intent", [
    "Inspect and record fixed source locators for this RunPlan",
    "查看执行计划的源码定位并独立登记请求定位证据",
    "query.quality.run_plan_locator_record",
])
def test_locator_phase_discovery_keeps_full_registry_and_exact_confirmation_contract(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(serialized.encode()) <= 6999 and len(definitions) == 12
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    originals = {tool.tool_id: tool for tool in tools}
    for ident in ("query.quality.run_plan_locators", "quality.run_plan.record_locators",
            "query.quality.run_plan_locator_record"):
        selected = definitions[ident]
        for field in ("risk_level", "confirmation_mode", "required_context"):
            assert selected[field] == getattr(originals[ident], field)
    assert definitions["quality.run_plan.record_locators"]["confirmation_mode"] == "user_confirm"
    assert definitions["query.quality.run_plan_locator_record"]["confirmation_mode"] == "none"


def test_catalog_compresses_display_labels_without_losing_registry_or_governance():
    tools = [tool.model_copy(update={"label": tool.label + " descriptive display text" * 100})
             for tool in core_tool_definitions() + system_image_tool_definitions()]
    payload = json.loads(compact_tool_catalog_json(tools, _workspace_conversation()))
    originals = {tool.tool_id: tool for tool in tools}
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert len(payload["relevant_tools"]) == 12
    for item in payload["relevant_tools"]:
        original = originals[item["tool_id"]]
        assert item["label"] and original.label.startswith(item["label"])
        assert item["description"] and original.description.startswith(item["description"])
        for field in ("risk_level", "confirmation_mode", "required_context"):
            assert item[field] == getattr(original, field)


@pytest.mark.parametrize("intent", ["Assign gaps and confirm gap responsibilities", "分配缺口并确认缺口负责人"])
def test_gap_ownership_discovery_keeps_original_report_checkpoint_and_confirmation(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    serialized = compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation)
    definitions = {item["tool_id"]: item for item in json.loads(serialized)["relevant_tools"]}
    tool = definitions["system_image.build.gaps.assign"]
    assert tool["confirmation_mode"] == "user_confirm" and tool["risk_level"] == "medium"
    assert tool["required_context"] == ["project_id", "completion_invocation_id", "completion_report_hash", "expected_goal", "assignments"]
    assert len(serialized.encode()) <= 6999


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_catalog_rejects_invalid_byte_budgets(budget):
    with pytest.raises(ValueError, match="tool catalog byte budget"):
        compact_tool_catalog_json(core_tool_definitions(), _workspace_conversation(), max_bytes=budget)


@pytest.mark.parametrize("intent", ["Compare revisions with a source delta", "查看代码变更并比较修订的来源差异"])
def test_source_delta_discovery_keeps_explicit_revision_pins_and_tool_budget(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    delta = definitions["query.system_image.sources.delta"]
    assert delta["confirmation_mode"] == "none"
    assert delta["required_context"] == ["project_id", "before_revision_id", "after_revision_id"]


@pytest.mark.parametrize("intent", ["Inspect and cancel code indexes", "查看代码索引状态并取消索引"])
def test_code_index_discovery_keeps_exact_source_pins_and_independent_confirmation(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    serialized = compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation)
    definitions = {tool["tool_id"]: tool for tool in json.loads(serialized)["relevant_tools"]}
    assert len(serialized.encode("utf-8")) < 7000
    assert definitions["query.system_image.code_indexes.list"]["required_context"] == ["project_id", "binding_id"]
    assert definitions["query.system_image.code_indexes.status"]["required_context"] == ["project_id", "generation_id"]
    cancel = definitions["system_image.code_indexes.cancel"]
    assert cancel["confirmation_mode"] == "user_confirm" and cancel["risk_level"] == "medium"
    assert cancel["required_context"] == ["project_id", "generation_id", "expected_generation_hash"]


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


@pytest.mark.parametrize("intent", ["Preview generation budget for fixed test design", "查看固定画像生成的预算并执行原生测试生成"])
def test_native_generation_discovery_keeps_source_budget_confirmation_contract(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    assert definitions["query.quality.test_design_execution"]["confirmation_mode"] == "none"
    assert definitions["quality.test_design.generate"]["confirmation_mode"] == "user_confirm"
    assert "execution" in definitions["quality.test_design.generate"]["required_context"]


@pytest.mark.parametrize("intent", ["Inspect generation history for this fixed scope", "查看固定范围的测试生成任务和生成历史"])
def test_generation_history_discovery_keeps_bounded_read_only_contract(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    history = definitions["query.quality.test_design_jobs"]
    assert history["confirmation_mode"] == "none"
    assert history["required_context"] == ["project_id", "scope_revision_id", "scope_artifact_hash"]


@pytest.mark.parametrize("intent", ["Inspect assertion mapping review", "检查用例映射和断言映射审阅"])
def test_mapping_review_discovery_keeps_independent_confirmation_and_tool_budget(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    assert definitions["query.quality.test_design_mapping"]["confirmation_mode"] == "none"
    assert definitions["quality.test_design_mapping.review"]["confirmation_mode"] == "user_confirm"


@pytest.mark.parametrize("space", ["project", "knowledge", "workspace"])
@pytest.mark.parametrize("intent", ["Generate a script draft from reviewed cases with an automation budget", "按已审阅用例生成脚本草稿并检查自动化预算"])
def test_fixed_script_drafts_are_discoverable_with_exact_inputs_and_separate_consent(space, intent):
    conversation = _workspace_conversation()
    conversation.space_type = space
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(serialized.encode()) <= 6999 and len(definitions) == 12
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    preview = definitions["query.quality.automation_execution"]
    generate = definitions["quality.automation.generate"]
    selection = ["project_id", "mapping_revision_id", "mapping_artifact_hash", "case_ids", "model_config_id", "budget"]
    assert preview["confirmation_mode"] == "none" and preview["required_context"] == selection
    assert generate["confirmation_mode"] == "user_confirm" and generate["risk_level"] == "high"
    assert generate["required_context"] == selection + ["input_digest", "model_config_digest", "execution"]


@pytest.mark.parametrize("space", ["project", "knowledge", "workspace"])
@pytest.mark.parametrize("intent", ["Inspect script command history", "检查脚本生成历史"])
def test_script_history_discovery_is_readonly_bounded_and_keeps_the_same_tool_budget(space, intent):
    conversation = _workspace_conversation()
    conversation.space_type = space
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(serialized.encode()) <= 6999 and len(definitions) == 12
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    history = definitions["query.quality.automation_history"]
    assert history["confirmation_mode"] == "none"
    assert history["required_context"] == ["project_id", "mapping_revision_id", "mapping_artifact_hash"]


@pytest.mark.parametrize("intent", ["Inspect script review and review scripts", "检查脚本审阅并审阅脚本"])
def test_independent_script_review_keeps_read_and_confirmed_write_separate(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    serialized = compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation)
    definitions = {tool["tool_id"]: tool for tool in json.loads(serialized)["relevant_tools"]}
    assert len(definitions) == 12 and len(serialized.encode()) <= 6999
    assert definitions["query.quality.automation_review"]["confirmation_mode"] == "none"
    assert definitions["quality.automation.review"]["confirmation_mode"] == "user_confirm"
    assert {"actions", "assertions", "expected_previous_revision_id"} <= set(definitions["quality.automation.review"]["required_context"])


@pytest.mark.parametrize("space", ["project", "knowledge", "workspace"])
@pytest.mark.parametrize("intent", ["List archived drafts for review", "查看已归档草稿并审阅草稿"])
def test_review_drafts_are_discoverable_without_admin_generation_or_model_permissions(space, intent):
    conversation = _workspace_conversation()
    conversation.space_type = space
    conversation.messages[-1].blocks[0].text = intent
    payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    query = definitions["query.quality.test_design_review_drafts"]
    assert query["confirmation_mode"] == "none" and query["required_context"] == ["project_id"]
    assert query["risk_level"] == "low" and len(query["description"]) <= 240


def test_context_pack_investigation_keeps_read_and_confirmed_write_contracts_discoverable():
    conversation = _workspace_conversation()
    for text in ("Inspect the test-design ContextPack history for this frozen image", "检查系统画像的测试设计上下文包及其历史"):
        conversation.messages[-1].blocks[0].text = text
        payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
        definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
        assert {"query.system_image.context.preview", "query.system_image.context.list", "query.system_image.context.read", "system_image.context.compile"} <= definitions.keys()
        assert definitions["system_image.context.compile"]["confirmation_mode"] == "user_confirm"


@pytest.mark.parametrize("intent", ["Inspect the historical dependency queue", "查看待补登记上下文及历史上下文依赖"])
def test_historical_dependency_discovery_keeps_confirmed_registration_separate(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    assert definitions["query.system_image.context.authority_backfill"]["confirmation_mode"] == "none"
    assert definitions["system_image.context.register_authorities"]["confirmation_mode"] == "user_confirm"


@pytest.mark.parametrize("space", ["project", "knowledge", "workspace"])
@pytest.mark.parametrize("intent", ["Inspect code evidence", "查看代码原文和证据"])
def test_evidence_queries_remain_discoverable_in_the_expanded_catalog(space, intent):
    conversation = _workspace_conversation()
    conversation.space_type = space
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    serialized = compact_tool_catalog_json(tools, conversation)
    payload = json.loads(serialized)
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert all(len(tool["description"]) <= 240 for tool in definitions.values())
    for tool_id in ("query.system_image.evidence.list", "query.system_image.evidence.read"):
        assert definitions[tool_id]["confirmation_mode"] == "none"
        assert "source_revision_id" in definitions[tool_id]["required_context"]


@pytest.mark.parametrize("intent", ["Publish the image after review", "审阅后发布系统画像"])
def test_publication_chain_is_discoverable_without_bypassing_confirmation(intent):
    conversation = _workspace_conversation()
    conversation.messages[-1].blocks[0].text = intent
    payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    for tool in ("query.system_image.publication.head", "query.system_image.publication"):
        assert definitions[tool]["confirmation_mode"] == "none"
    assert definitions["system_image.revisions.review_publication"]["confirmation_mode"] == "user_confirm"
    assert definitions["baseline.promote"]["confirmation_mode"] == "approval_required"


@pytest.mark.parametrize("space", ["project", "knowledge", "workspace"])
@pytest.mark.parametrize("intent", [
    "为固定画像执行全部 AC 的上下文检索", "停止当前的上下文检索任务",
    "Retrieve all AC queries for the published context pack", "Cancel the running AC retrieval",
])
def test_complete_retrieval_chain_remains_discoverable_and_governed(space, intent):
    conversation = _workspace_conversation()
    conversation.space_type = space
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    payload = json.loads(compact_tool_catalog_json(tools, conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12 and payload["available_count"] == len(tools)
    assert planner_catalog_tool_ids(payload) == [tool.tool_id for tool in tools]
    assert all(len(tool["description"]) <= 240 for tool in definitions.values())
    for tool in ("query.system_image.context.retrieval_preview", "query.system_image.context.retrieval", "system_image.context.cancel_retrieval"):
        assert definitions[tool]["confirmation_mode"] == "none"
    execute = definitions["system_image.context.retrieve"]
    assert execute["confirmation_mode"] == "user_confirm"
    assert {"project_id", "publication_id", "generation_id", "expected_plan_digest"} <= set(execute["required_context"])
    if "Cancel" in intent or "停止" in intent:
        assert payload["relevant_tools"][0]["tool_id"] == "system_image.context.cancel_retrieval"


@pytest.mark.parametrize("space", ["project", "knowledge", "workspace"])
@pytest.mark.parametrize("intent", ["Review the test-design scope and risk contract", "审阅测试设计范围和权限矩阵"])
def test_reviewed_test_design_scope_is_discoverable_but_requires_confirmation(space, intent):
    conversation = _workspace_conversation()
    conversation.space_type = space
    conversation.messages[-1].blocks[0].text = intent
    payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    assert definitions["query.quality.test_design_scope"]["confirmation_mode"] == "none"
    assert definitions["quality.test_design_scope.review"]["confirmation_mode"] == "user_confirm"


@pytest.mark.parametrize("space", ["project", "knowledge", "workspace"])
@pytest.mark.parametrize("intent", ["Inspect the fixed test-design generation input", "检查测试生成输入和固定约束分母"])
def test_generation_preflight_is_discoverable_without_displacing_real_write_actions(space, intent):
    conversation = _workspace_conversation()
    conversation.space_type = space
    conversation.messages[-1].blocks[0].text = intent
    payload = json.loads(compact_tool_catalog_json(core_tool_definitions() + system_image_tool_definitions(), conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12
    preview = definitions["query.quality.test_design_generation"]
    assert preview["confirmation_mode"] == "none"
    assert set(preview["required_context"]) == {"project_id", "scope_revision_id", "scope_artifact_hash"}


@pytest.mark.parametrize("space", ["project", "knowledge", "workspace"])
@pytest.mark.parametrize("intent", ["Inspect context change impact and context dependencies", "检查上下文影响和派生依赖"])
def test_context_impact_is_discoverable_as_a_read_only_fixed_query(space, intent):
    conversation = _workspace_conversation()
    conversation.space_type = space
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    payload = json.loads(compact_tool_catalog_json(tools, conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12 and payload["available_count"] == len(tools)
    query = definitions["query.system_image.context.change_impact"]
    assert query["confirmation_mode"] == "none"
    definition = next(tool for tool in tools if tool.tool_id == query["tool_id"])
    assert definition.tool_kind == "query" and definition.produced_objects == []
    assert set(query["required_context"]) == {"project_id", "context_id", "context_artifact_hash",
                                             "before_revision_id", "after_revision_id"}
    invalidate = definitions["system_image.context.invalidate"]
    assert invalidate["confirmation_mode"] == "user_confirm"
    assert set(invalidate["required_context"]) == {"project_id", "context_id", "context_artifact_hash",
        "before_revision_id", "after_revision_id", "expected_impact_hash", "reason"}


@pytest.mark.parametrize("space", ["project", "knowledge", "workspace"])
@pytest.mark.parametrize("intent", ["Find affected contexts across all context roots", "查看来源关联上下文和全部上下文"])
def test_reverse_source_context_lookup_is_discoverable_without_a_known_context_id(space, intent):
    conversation = _workspace_conversation()
    conversation.space_type = space
    conversation.messages[-1].blocks[0].text = intent
    tools = core_tool_definitions() + system_image_tool_definitions()
    payload = json.loads(compact_tool_catalog_json(tools, conversation))
    definitions = {tool["tool_id"]: tool for tool in payload["relevant_tools"]}
    assert len(definitions) == 12 and payload["available_count"] == len(tools)
    query = definitions["query.system_image.sources.context_roots"]
    assert query["confirmation_mode"] == "none"
    assert set(query["required_context"]) == {"project_id", "before_revision_id", "after_revision_id"}
