import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.api.app.domain.agent.resume_checkpoint import AgentResumeCheckpoint, InvalidAgentResumeCheckpoint
from apps.api.app.infrastructure.agent.application_ports import LegacyAgentGraphStateAdapter
from apps.api.tests.agent_resume_fixtures import paused_goal, resume_transition


ROOT = Path(__file__).resolve().parents[3]


def method(path, class_name, name):
    tree = ast.parse((ROOT / path).read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def test_conditional_resume_adapter_does_not_fall_back_to_unconditional_projection():
    calls = []
    state = LegacyAgentGraphStateAdapter(None, None, None, SimpleNamespace(project_goal=calls.append))
    goal = paused_goal()
    checkpoint = AgentResumeCheckpoint.capture(goal.model_dump(mode="json"))
    with pytest.raises(InvalidAgentResumeCheckpoint, match="not configured"):
        state.persist_goal_at_checkpoint(resume_transition(goal), checkpoint)
    assert calls == []


def test_structural_continuation_pins_before_compilation_and_uses_conditional_commit():
    prepare = method("apps/api/app/application/agent/graph.py", "LocalAgentGraphRuntime", "prepare_resume")
    capture = next(node for node in ast.walk(prepare) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "capture")
    compile_call = next(node for node in ast.walk(prepare) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "compile_structure_continuation")
    assert capture.lineno < compile_call.lineno
    assert any(isinstance(node, ast.Call) and any(keyword.arg == "expected_resume" for keyword in node.keywords)
        for node in ast.walk(prepare))
    update = method("apps/api/app/application/agent/graph.py", "LocalAgentGraphRuntime", "_update_goal")
    assert "persist_goal_at_checkpoint" in ast.unparse(update)
    composition = (ROOT / "apps/api/app/infrastructure/agent/sqlalchemy_application_ports.py").read_text()
    assert "resume_commits=SQLAlchemyAgentResumeCommit(conversations)" in composition


def test_conditional_goal_write_locks_compares_and_updates_steps_in_one_transaction():
    save = method("apps/api/app/infrastructure/persistence/conversation_repository.py", "ConversationRepository", "upsert_goal")
    transactions = [node for node in save.body if isinstance(node, ast.With)]
    assert len(transactions) == 1
    calls = [node for node in ast.walk(transactions[0]) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    lock = next(node for node in calls if node.func.attr == "with_for_update")
    compare = next(node for node in calls if node.func.attr == "require_matches")
    write = next(node for node in calls if node.func.attr == "_write_goal")
    assert lock.lineno < compare.lineno < write.lineno
    aggregate_write = method("apps/api/app/infrastructure/persistence/conversation_repository.py", "ConversationRepository", "_write_goal")
    assigned = {target.attr for node in ast.walk(aggregate_write) if isinstance(node, ast.Assign)
                for target in node.targets if isinstance(target, ast.Attribute)}
    assert {"steps", "active_runtime_ms", "active_started_at", "status", "workflow_id", "target_refs"} <= assigned
    assert "raise AgentResumeCheckpointChanged()" in ast.unparse(transactions[0])


def test_budget_and_source_retries_pass_the_original_pin_to_their_complete_write():
    prepare = method("apps/api/app/application/agent/graph.py", "LocalAgentGraphRuntime", "prepare_resume")
    updates = [node for node in ast.walk(prepare) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == "_update_goal"]
    for mode in ("budget_released", "source_binding_supplied"):
        update = next(node for node in updates if any(isinstance(value, ast.Constant) and value.value == mode
                                                     for value in ast.walk(node)))
        pin = next(keyword.value for keyword in update.keywords if keyword.arg == "expected_resume")
        assert isinstance(pin, ast.Name) and pin.id == "expected_resume"
    source_branch = next(node for node in ast.walk(prepare) if isinstance(node, ast.If)
                         and ast.unparse(node.test) == "pause_reason == 'missing_source_binding'")
    assert sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "_update_goal" for node in ast.walk(source_branch)) == 1
