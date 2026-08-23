from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from apps.api.app.application.platform.prompts import (
    PromptRegistryApplicationService,
)
from apps.api.app.domain.platform.prompt_registry import BUILTIN_PROMPTS, PromptDefinition
from apps.api.app.infrastructure.persistence.database import init_database
from apps.api.app.infrastructure.persistence.prompt_repository import (
    SQLAlchemyPromptRegistry,
)


def _prompt(version: str, body: str, rollback_to: str | None = None) -> PromptDefinition:
    return PromptDefinition(
        prompt_id="test.production.prompt",
        name="Production prompt registry test",
        version=version,
        purpose="Verify immutable prompt versions and active selection.",
        input_schema_ref="test-input/v1",
        output_schema_ref="test-output/v1",
        safety_rules_ref="test-safety/v1",
        rollback_to=rollback_to,
        system_template=body,
    )


def test_prompt_registry_persists_versions_and_active_selection() -> None:
    init_database()
    service = PromptRegistryApplicationService(SQLAlchemyPromptRegistry())
    v1 = _prompt("1.0.0", "Return version one.")
    v2 = _prompt("1.1.0", "Return version two.", rollback_to="1.0.0")

    service.register_defaults((v1, v2))

    assert service.get_active(v1.prompt_id).version in {"1.0.0", "1.1.0"}
    activated = service.activate(v1.prompt_id, "1.1.0")
    assert activated.version == "1.1.0"
    assert service.get_active(v1.prompt_id).system_template == "Return version two."
    assert {item.version for item in service.list_versions(v1.prompt_id)} >= {
        "1.0.0",
        "1.1.0",
    }


def test_prompt_registry_rejects_mutating_an_existing_version() -> None:
    init_database()
    repository = SQLAlchemyPromptRegistry()
    original = _prompt("2.0.0", "Immutable content.")
    repository.register(original)

    with pytest.raises(RuntimeError, match="publish a new version"):
        repository.register(_prompt("2.0.0", "Silently changed content."))


def test_builtin_registry_covers_agent_and_quality_model_call_prompts() -> None:
    prompt_ids = {definition.prompt_id for definition in BUILTIN_PROMPTS}

    assert {
        "agent_runtime_guardrails",
        "agent_conversation_reply",
        "platform_query_tool_reply",
        "agent_loop_planner",
        "agent_loop_replanner",
        "quality.scope.generate",
        "quality.scenario.generate",
        "quality.plan.generate",
        "quality.case.generate",
        "automation.generate",
        "quality.change-doc.generate",
    } <= prompt_ids


def test_agent_planner_prompt_migration_matches_the_immutable_builtin() -> None:
    migration = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "migrations"
            / "versions"
            / "0029_agent_planner_prompt.py"
        )
    )
    planner = next(
        definition
        for definition in BUILTIN_PROMPTS
        if definition.prompt_id == "agent_loop_planner"
    )

    assert planner.version == migration["VERSION"] == "1.1.0"
    assert planner.rollback_to == migration["ROLLBACK_TO"] == "1.0.0"
    assert planner.content_hash == migration["_content_hash"]()
