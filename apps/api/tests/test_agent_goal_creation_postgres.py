"""Goal creation claims use real PG sessions and independent OS processes."""
from concurrent.futures import ThreadPoolExecutor
import json
import selectors
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import event

from apps.api.app.application.agent.agent_models import AgentGoal, ConversationSession
from apps.api.app.domain.agent.goal_creation import ActiveAgentGoalExists
from apps.api.app.domain.agent.plan_policy import AgentPlanPolicyViolation
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.database import SessionLocal, engine
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord


@pytest.fixture
def creation_scope():
    assert engine.dialect.name == "postgresql", "Run through test-api-postgres.py"
    assert engine.url.database.startswith("nasus_test_"), "Use a disposable test database"
    suffix = uuid4().hex
    repository = ConversationRepository()
    conversation = ConversationSession(id="claim_conversation_" + suffix, session_id="claim_session_" + suffix,
        title="Creation claim", space_type="project", space_id="claim_project_" + suffix, project_id="claim_project_" + suffix)
    repository.upsert_conversation(conversation)
    goal = AgentGoal(id="claim_goal_" + uuid4().hex, conversation_id=conversation.id, project_id=conversation.project_id,
        title="Fixed input", summary="Independent consent remains required", status="pending", steps=[],
        workflow_id="claim_workflow_" + uuid4().hex)
    return repository, goal


@pytest.mark.parametrize("status", ["pending", "running", "paused", "blocked"])
def test_new_repository_cannot_create_a_second_active_controller(creation_scope, status):
    repository, goal = creation_scope
    goal.status = status
    repository.create_goal(goal)
    second = goal.model_copy(update={"id": "loser_" + uuid4().hex})
    with pytest.raises(ActiveAgentGoalExists) as conflict:
        ConversationRepository().create_goal(second)
    assert conflict.value.goal_id == goal.id
    assert ConversationRepository().list_agent_goals(conversation_id=goal.conversation_id) == [goal]


@pytest.mark.parametrize("status", ["completed", "cancelled", "failed"])
def test_terminal_history_does_not_prevent_a_new_controller(creation_scope, status):
    repository, goal = creation_scope
    repository.create_goal(goal)
    goal.status = status
    repository.upsert_goal(goal)
    second = goal.model_copy(update={"id": "next_" + uuid4().hex, "status": "pending"})
    repository.create_goal(second)
    assert repository.get_agent_goal(goal.id) == goal
    assert repository.get_agent_goal(second.id) == second


@pytest.mark.parametrize("change", ["project", "conversation"])
def test_creation_cannot_move_to_a_foreign_or_missing_conversation(creation_scope, change):
    repository, goal = creation_scope
    invalid = goal.model_copy(update={"project_id" if change == "project" else "conversation_id": "foreign"})
    with pytest.raises(ValueError if change == "project" else KeyError):
        repository.create_goal(invalid)
    assert repository.get_agent_goal(goal.id) is None


def test_ambiguous_legacy_controllers_are_not_silently_selected(creation_scope):
    repository, goal = creation_scope
    repository.upsert_goal(goal)
    second = goal.model_copy(update={"id": "legacy_" + uuid4().hex})
    repository.upsert_goal(second)
    with pytest.raises(AgentPlanPolicyViolation) as conflict:
        repository.create_goal(goal.model_copy(update={"id": "third_" + uuid4().hex}))
    assert conflict.value.code == "active_agent_goal_ambiguous"
    assert len(repository.list_agent_goals(conversation_id=goal.conversation_id)) == 2


def test_failed_creation_transaction_releases_the_claim_without_partial_goal(creation_scope):
    repository, goal = creation_scope

    def reject(session, *args):
        if any(isinstance(row, AgentGoalRecord) and row.id == goal.id for row in session.new):
            raise RuntimeError("injected creation failure")

    event.listen(SessionLocal, "before_flush", reject)
    try:
        with pytest.raises(RuntimeError, match="injected creation failure"):
            repository.create_goal(goal)
    finally:
        event.remove(SessionLocal, "before_flush", reject)
    assert repository.list_agent_goals(conversation_id=goal.conversation_id) == []
    ConversationRepository().create_goal(goal)
    assert repository.get_agent_goal(goal.id) == goal


_CHILD = """
import json, sys
from apps.api.app.application.agent.agent_models import AgentGoal
from apps.api.app.domain.agent.goal_creation import ActiveAgentGoalExists
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
print('ready', flush=True)
goal = AgentGoal.model_validate(json.loads(sys.stdin.readline()))
try:
    ConversationRepository().create_goal(goal)
    print(json.dumps({'status': 'created', 'goal_id': goal.id}), flush=True)
except ActiveAgentGoalExists as conflict:
    print(json.dumps({'status': 'existing', 'goal_id': conflict.goal_id}), flush=True)
"""


@pytest.mark.parametrize("attempt", range(3))
def test_two_independent_processes_claim_one_empty_conversation(creation_scope, attempt):
    repository, goal = creation_scope
    contenders = [goal, goal.model_copy(update={"id": "competing_" + uuid4().hex})]
    processes = [subprocess.Popen([sys.executable, "-c", _CHILD], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in contenders]
    try:
        for process in processes:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=20), "Child did not become ready"
            assert process.stdout.readline().strip() == "ready"

        def submit(item):
            process, candidate = item
            output, errors = process.communicate(json.dumps(candidate.model_dump(mode="json")) + "\n", timeout=20)
            assert process.returncode == 0, errors
            return json.loads(output)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(submit, zip(processes, contenders)))
        assert sorted(item["status"] for item in results) == ["created", "existing"]
        winner_id = next(item["goal_id"] for item in results if item["status"] == "created")
        assert {item["goal_id"] for item in results} == {winner_id}
        saved = repository.list_agent_goals(conversation_id=goal.conversation_id)
        assert len(saved) == 1 and saved[0].id == winner_id
        assert saved[0].workflow_id == goal.workflow_id
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()
