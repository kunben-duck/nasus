"""New source phases stay on the original goal, without reusing old consent."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api.app.main import app
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.app.infrastructure.persistence.build_authorization_models import BuildAuthorizationRecord, BuildWorkReservationRecord
from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, BaselineRecord, ToolInvocationRecord, VersionRecord
from apps.api.app.infrastructure.persistence.image_plan_phase_models import ImagePlanPhaseRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_build_authorization_api import BUDGET
from apps.api.tests.test_build_plan_revision_api import capture_documents, body, prepare, confirm, history
from apps.api.tests.test_agent_investigation_continuation import replace_graph, start_structure, resume
from apps.api.tests.test_source_access_api import grant_member, policy


TOOL = "system_image.build.plan.activate_revision"


def activation(v, fixed, goal, revision, **changes):
    return {"project_id": v["project_id"], "goal_id": goal["id"], "root_plan_id": fixed["plan_id"],
        "revision_id": revision["revision"]["revision_id"], "revision_hash": revision["revision_hash"],
        "expected_goal": goal, "budget": BUDGET, "parent_phase_id": None, "parent_phase_hash": None, **changes}


def prepare_phase(v, payload, key="phase-one"):
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "conversation_id": v["conversation"].json()["id"], "tool_id": TOOL,
        "idempotency_key": key, "input": payload})
    assert response.status_code == 200, response.text
    return response.json()


def phases(v, fixed, goal, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-plans/{fixed['plan_id']}/phases",
        params={"goal_id": goal["id"]}, headers=headers or v["headers"])


def revised(v, fixed, goal, tmp_path):
    manifest = capture_documents(v, tmp_path)
    result = confirm(v, prepare(v, body(v, fixed, goal, manifest)))
    assert result["status"] == "completed", result
    return history(v, fixed, goal).json()[-1]


def current_goal(v, goal):
    response = v["client"].get(f"/v1/agent-goals/{goal['id']}", headers=v["headers"])
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_original_goal_executes_new_phase_only_after_independent_consent(evidence_api, monkeypatch, tmp_path, graph_kind):
    from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    fixed, original = start_structure(v, authorized=True)
    original_budget, original_consumption = BuildToolBudgetRepository().inspect(original["id"])
    assert {item["invocation_id"] for item in original_consumption} == {
        step["tool_invocation_id"] for step in original["steps"] if step["phase"] == "acting" and step["selected_tool_id"]}
    revision = revised(v, fixed, original, tmp_path)
    old_plan_url = f"/v1/projects/{v['project_id']}/system-image/build-plans/{fixed['plan_id']}"
    old_plan = v["client"].get(old_plan_url, headers=v["headers"]).json()
    pending = prepare_phase(v, activation(v, fixed, original, revision))
    assert pending["status"] == "waiting_confirmation"
    assert phases(v, fixed, original).json() == []
    assert current_goal(v, original) == original
    completed = confirm(v, pending)
    assert completed["status"] == "completed", completed
    response = phases(v, fixed, original)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    saved, = response.json()
    phase = saved["phase"]
    prepared = current_goal(v, original)
    prefix = len(original["steps"])
    assert prepared["id"] == original["id"] and prepared["pause_reason"] == "build_plan_phase_prepared"
    assert prepared["steps"][:prefix] == original["steps"]
    assert phase["plan_id"] == revision["revision"]["plan_id"]
    assert prepared["model_calls_used"] == original["model_calls_used"] == 0
    assert prepared["started_at"] == original["started_at"]
    assert prepared["max_steps"] == original["max_steps"]
    conversation = v["client"].get(f"/v1/conversations/{original['conversation_id']}", headers=v["headers"])
    assert conversation.status_code == 200, conversation.text
    assert next(item for item in conversation.json()["agent_goals"] if item["id"] == original["id"]) == prepared
    with session_scope() as session:
        from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord
        event = session.scalar(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == completed["id"],
            AuditEventRecord.action == "agent.image_plan_phase.activated"))
        assert event is not None and event.status == "paused"
    new_url = f"/v1/projects/{v['project_id']}/system-image/build-plans/{phase['plan_id']}"
    assert v["client"].get(new_url, headers=v["headers"]).json()["execution_authorizations"] == []
    replace_graph(monkeypatch, graph_kind)
    waiting = resume(v, original["id"], expected=prepared)
    assert waiting["pause_reason"] == "waiting_confirmation", waiting
    assert waiting["steps"][:prefix] == original["steps"]
    blocked = [step for step in waiting["steps"][prefix:] if step["status"] == "blocked"]
    assert len(blocked) == 1 and blocked[0]["selected_tool_id"] == "system_image.build.authorize"
    authorization_id = blocked[0]["tool_invocation_id"]
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == original["id"])) == 1
        assert session.get(BuildWorkReservationRecord, authorization_id) is None
        assert session.scalar(select(func.count()).select_from(StructureBuildArtifactRecord).where(StructureBuildArtifactRecord.plan_id == phase["plan_id"])) == 0
    replace_graph(monkeypatch, graph_kind)
    enriched = resume(v, original["id"], expected=waiting)
    assert enriched["pause_reason"] == "structural_candidate_review", enriched
    assert enriched["steps"][:prefix] == original["steps"]
    new_plan = v["client"].get(new_url, headers=v["headers"]).json()
    assert len(new_plan["execution_authorizations"]) == len(new_plan["structural_artifacts"]) == 1
    assert new_plan["execution_authorizations"][0]["goal_id"] == original["id"]
    assert new_plan["execution_authorizations"][0]["budget"] == BUDGET
    assert v["client"].get(old_plan_url, headers=v["headers"]).json() == old_plan
    replace_graph(monkeypatch, graph_kind)
    investigation_pending = resume(v, original["id"], expected=enriched)
    assert investigation_pending["pause_reason"] == "waiting_confirmation"
    replace_graph(monkeypatch, graph_kind)
    reviewed = resume(v, original["id"], expected=investigation_pending)
    assert reviewed["pause_reason"] == "build_completion_review", reviewed
    assert reviewed["steps"][:prefix] == original["steps"]
    assert reviewed["model_calls_used"] == 0
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(AgentGoalRecord).where(AgentGoalRecord.conversation_id == original["conversation_id"])) == 1
        assert session.scalar(select(func.count()).select_from(ImagePlanPhaseRecord).where(ImagePlanPhaseRecord.goal_id == original["id"])) == 1
    assert phases(v, fixed, reviewed).json() == [saved]
    budget, consumption = BuildToolBudgetRepository().inspect(original["id"])
    assert budget == original_budget and consumption[:len(original_consumption)] == original_consumption
    assert {item["invocation_id"] for item in consumption} == {
        step["tool_invocation_id"] for step in reviewed["steps"] if step["phase"] == "acting" and step["selected_tool_id"]
    } | {revision["revision"]["invocation_id"], completed["id"]}


@pytest.mark.parametrize("changed", ["budget", "steps", "parent", "revision", "excess-budget"])
def test_stale_or_changed_phase_proposal_never_changes_goal_or_grants(evidence_api, tmp_path, changed):
    from apps.api.app.infrastructure.persistence.build_tool_budget_repository import BuildToolBudgetRepository

    v = evidence_api
    fixed, goal = start_structure(v, authorized=True)
    revision = revised(v, fixed, goal, tmp_path)
    payload = activation(v, fixed, goal, revision)
    if changed == "parent":
        payload.update(parent_phase_id="another-phase", parent_phase_hash="sha256:" + "a" * 64)
    if changed == "excess-budget":
        payload["budget"] = {**BUDGET, "max_model_calls": 1}
    if changed == "excess-budget":
        denied = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
            "conversation_id": v["conversation"].json()["id"], "tool_id": TOOL, "input": payload})
        assert denied.status_code == 403, denied.text
        assert current_goal(v, goal) == goal and phases(v, fixed, goal).json() == []
        return
    pending = prepare_phase(v, payload)
    if changed in {"budget", "steps"}:
        with session_scope() as session:
            row = session.get(AgentGoalRecord, goal["id"])
            if changed == "budget":
                row.max_steps += 1
            else:
                values = deepcopy(row.steps)
                values[-1]["title"] = "Changed review"
                row.steps = values
    if changed == "revision":
        second_manifest = capture_documents(v, tmp_path, tests=True)
        next_revision = confirm(v, prepare(v, body(v, fixed, goal, second_manifest,
            from_plan_id=revision["revision"]["plan_id"], from_plan_digest=revision["revision"]["plan_digest"],
            parent_revision_id=revision["revision"]["revision_id"], parent_revision_hash=revision["revision_hash"]), key="new-revision"))
        assert next_revision["status"] == "completed", next_revision
    before = current_goal(v, goal)
    original_work = BuildToolBudgetRepository().inspect(goal["id"])
    result = confirm(v, pending)
    assert result["status"] == "failed", result
    assert current_goal(v, goal) == before
    assert phases(v, fixed, goal).json() == []
    assert BuildToolBudgetRepository().inspect(goal["id"]) == original_work
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"])) == 1


def test_phase_commit_rolls_back_when_scope_changes_and_completed_reads_reauthorize(evidence_api, tmp_path, monkeypatch):
    v = evidence_api
    fixed, goal = start_structure(v)
    revision = revised(v, fixed, goal, tmp_path)
    payload = activation(v, fixed, goal, revision)
    repository = app.state.container.build_plans.phases.repository
    original = repository.activate

    def late_failure(*args, **kwargs):
        def revoked():
            raise StaleSourceAccessScope("private revoked")
        return original(*args, **{**kwargs, "require_current": revoked})

    monkeypatch.setattr(repository, "activate", late_failure)
    assert confirm(v, prepare_phase(v, payload))["status"] == "failed"
    assert current_goal(v, goal) == goal and phases(v, fixed, goal).json() == []
    monkeypatch.setattr(repository, "activate", original)
    completed = confirm(v, prepare_phase(v, payload, key="fresh-phase"))
    assert completed["status"] == "completed", completed
    assert phases(v, fixed, goal, v["member_headers"]).status_code == 403
    grant_member(v)
    assert phases(v, fixed, goal, v["member_headers"]).status_code == 200
    policy(v)
    denied = phases(v, fixed, goal, v["member_headers"])
    assert denied.status_code == 403 and "private revoked" not in denied.text
    assert v["client"].get(f"/v1/tool-invocations/{completed['id']}", headers=v["member_headers"]).status_code == 403


def test_concurrent_phase_confirmations_do_not_fork_original_goal(evidence_api, tmp_path):
    v = evidence_api
    fixed, goal = start_structure(v)
    revision = revised(v, fixed, goal, tmp_path)
    payload = activation(v, fixed, goal, revision)
    commands = [prepare_phase(v, payload, key=key) for key in ("phase-a", "phase-b")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda command: confirm(v, command), commands))
    assert sorted(item["status"] for item in outcomes) == ["completed", "failed"]
    assert len(phases(v, fixed, goal).json()) == 1
    assert current_goal(v, goal)["steps"][:len(goal["steps"])] == goal["steps"]


def test_phase_ack_recovery_and_append_only_ledger(evidence_api, tmp_path):
    from sqlalchemy.exc import DBAPIError
    from apps.api.app.application.agent.image_plan_phases import ImagePlanPhaseInput
    from apps.api.app.application.platform.account_models import UserProfile
    from apps.api.app.application.platform.actor_context import actor_scope
    v = evidence_api
    fixed, goal = start_structure(v)
    revision = revised(v, fixed, goal, tmp_path)
    payload = activation(v, fixed, goal, revision)
    completed = confirm(v, prepare_phase(v, payload))
    assert completed["status"] == "completed", completed
    saved, = phases(v, fixed, goal).json()
    before = current_goal(v, goal)
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, completed["id"])
        row.status = "running"
    with actor_scope(UserProfile.model_validate(v["owner"])):
        recovered = app.state.container.build_plans.phases.activate(ImagePlanPhaseInput.model_validate(payload),
            invocation_id=completed["id"], created_at=saved["phase"]["created_at"])
    assert recovered.phase.phase_id == saved["phase"]["phase_id"]
    assert current_goal(v, goal) == before and phases(v, fixed, goal).json() == [saved]
    for operation in ("update", "delete"):
        with pytest.raises(DBAPIError), session_scope() as session:
            row = session.get(ImagePlanPhaseRecord, recovered.phase.phase_id)
            if operation == "update":
                row.phase_hash = "tampered"
            else:
                session.delete(row)
            session.flush()
    assert phases(v, fixed, goal).json() == [saved]


@pytest.mark.parametrize("changed", ["checkpoint", "budget", "revision", "result"])
def test_completed_phase_command_cannot_borrow_a_valid_receipt_with_changed_inputs(evidence_api, tmp_path, changed):
    v = evidence_api
    fixed, goal = start_structure(v)
    revision = revised(v, fixed, goal, tmp_path)
    completed = confirm(v, prepare_phase(v, activation(v, fixed, goal, revision)))
    assert completed["status"] == "completed", completed
    saved = phases(v, fixed, goal).json()
    with session_scope() as session:
        row = session.get(ToolInvocationRecord, completed["id"])
        if changed == "result":
            result = deepcopy(row.result_payload)
            result["object_refs"] = ["build_plan_phase:another", f"build_plan:{revision['revision']['plan_id']}", f"agent_goal:{goal['id']}"]
            row.result_payload = result
        else:
            payload = deepcopy(row.input_payload)
            if changed == "checkpoint":
                payload["expected_goal"]["summary"] = "Changed original checkpoint"
            elif changed == "budget":
                payload["budget"]["max_active_seconds"] -= 1
            else:
                payload["revision_hash"] = "sha256:" + "b" * 64
            row.input_payload = payload
    reads = [(f"/v1/tool-invocations/{completed['id']}", {}),
        ("/v1/tool-invocations", {"tool_id": completed["tool_id"]}),
        ("/v1/audit-events", {"tool_invocation_id": completed["id"]})]
    for url, params in reads:
        denied = v["client"].get(url, headers=v["headers"], params=params)
        assert denied.status_code == 502, denied.text
        assert completed["id"] not in denied.text and "Changed original checkpoint" not in denied.text
    assert phases(v, fixed, goal).json() == saved


@pytest.mark.parametrize("changed", ["prefix", "order", "payload", "orphan"])
def test_changed_durable_phase_is_rejected_before_new_commands(evidence_api, tmp_path, changed):
    v = evidence_api
    fixed, goal = start_structure(v)
    revision = revised(v, fixed, goal, tmp_path)
    completed = confirm(v, prepare_phase(v, activation(v, fixed, goal, revision)))
    assert completed["status"] == "completed", completed
    with session_scope() as session:
        row = session.get(AgentGoalRecord, goal["id"])
        steps = deepcopy(row.steps)
        offset = len(goal["steps"])
        if changed == "prefix":
            steps[0]["title"] = "Overwritten history"
        elif changed == "order":
            steps[offset + 1], steps[offset + 3] = steps[offset + 3], steps[offset + 1]
        elif changed == "payload":
            steps[offset + 5]["tool_input_payload"]["plan_id"] = fixed["plan_id"]
        else:
            row.target_refs = goal["target_refs"]
        row.steps = steps
        before = session.scalar(select(func.count()).select_from(ToolInvocationRecord).where(ToolInvocationRecord.conversation_id == goal["conversation_id"]))
    rejected = phases(v, fixed, goal)
    assert rejected.status_code in {400, 502}, rejected.text
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(ToolInvocationRecord).where(ToolInvocationRecord.conversation_id == goal["conversation_id"])) == before


@pytest.mark.parametrize("graph_kind", ["local", "langgraph_postgres"])
def test_phase_resume_recovers_consumed_checkpoint_without_confirming_next_gate(evidence_api, monkeypatch, tmp_path, graph_kind):
    from apps.api.app.application.agent.graph import LocalAgentGraphRuntime
    v = evidence_api
    replace_graph(monkeypatch, graph_kind)
    fixed, goal = start_structure(v)
    revision = revised(v, fixed, goal, tmp_path)
    assert confirm(v, prepare_phase(v, activation(v, fixed, goal, revision)))["status"] == "completed"
    prepared = current_goal(v, goal)
    original_update = LocalAgentGraphRuntime._update_goal

    async def crash(self, value, *, patch, expected_resume=None):
        await original_update(self, value, patch=patch, expected_resume=expected_resume)
        if value.id == goal["id"] and patch.get("resume_mode") == "image_plan_phase_prepared":
            raise RuntimeError("phase resume acknowledgement lost")

    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", crash)
    with pytest.raises(RuntimeError, match="acknowledgement lost"):
        resume(v, goal["id"], expected=prepared)
    monkeypatch.setattr(LocalAgentGraphRuntime, "_update_goal", original_update)
    assert current_goal(v, goal)["status"] == "running"
    replace_graph(monkeypatch, graph_kind)
    recovered = resume(v, goal["id"], expected=prepared)
    assert recovered["pause_reason"] == "waiting_confirmation", recovered
    gate = next(step for step in recovered["steps"][len(goal["steps"]):] if step["status"] == "blocked")
    replay = resume(v, goal["id"], expected=prepared)
    assert replay == recovered
    with session_scope() as session:
        assert session.get(ToolInvocationRecord, gate["tool_invocation_id"]).status == "waiting_confirmation"
        assert session.scalar(select(func.count()).select_from(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"])) == 0
    assert recovered["steps"][:len(goal["steps"])] == goal["steps"]


def test_second_source_phase_retains_first_phase_and_gets_a_third_independent_grant(evidence_api, tmp_path):
    v = evidence_api
    fixed, original = start_structure(v, authorized=True)
    first_revision = revised(v, fixed, original, tmp_path)
    assert confirm(v, prepare_phase(v, activation(v, fixed, original, first_revision)))["status"] == "completed"
    waiting = resume(v, original["id"])
    first_done = resume(v, original["id"], expected=waiting)
    first_phase, = phases(v, fixed, first_done).json()
    second_manifest = capture_documents(v, tmp_path, tests=True)
    second_command = confirm(v, prepare(v, body(v, fixed, first_done, second_manifest,
        from_plan_id=first_revision["revision"]["plan_id"], from_plan_digest=first_revision["revision"]["plan_digest"],
        parent_revision_id=first_revision["revision"]["revision_id"], parent_revision_hash=first_revision["revision_hash"]), key="second-revision"))
    assert second_command["status"] == "completed", second_command
    second_revision = history(v, fixed, first_done).json()[-1]
    second_phase = confirm(v, prepare_phase(v, activation(v, fixed, first_done, second_revision,
        parent_phase_id=first_phase["phase"]["phase_id"], parent_phase_hash=first_phase["phase_hash"]), key="second-phase"))
    assert second_phase["status"] == "completed", second_phase
    second_waiting = resume(v, original["id"])
    second_done = resume(v, original["id"], expected=second_waiting)
    assert second_done["pause_reason"] == "structural_candidate_review", second_done
    assert second_done["steps"][:len(first_done["steps"])] == first_done["steps"]
    assert phases(v, fixed, second_done).json()[0] == first_phase
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == original["id"])) == 3
        assert session.scalar(select(func.count()).select_from(ImagePlanPhaseRecord).where(ImagePlanPhaseRecord.goal_id == original["id"])) == 2


def test_phase_without_fresh_consent_cannot_reserve_old_grant(evidence_api, tmp_path):
    from apps.api.app.infrastructure.persistence.build_authorization_repository import BuildAuthorizationRepository
    from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
    v = evidence_api
    fixed, goal = start_structure(v, authorized=True)
    revision = revised(v, fixed, goal, tmp_path)
    assert confirm(v, prepare_phase(v, activation(v, fixed, goal, revision)))["status"] == "completed"
    waiting = resume(v, goal["id"])
    authorization = next(step for step in waiting["steps"][len(goal["steps"]):] if step["status"] == "blocked")
    with session_scope() as session:
        invocation = session.get(ToolInvocationRecord, authorization["tool_invocation_id"])
        invocation.tool_id = "system_image.build.structure"
    with pytest.raises(BuildPlanIntegrityError, match="own independent execution consent"):
        BuildAuthorizationRepository().reserve(authorization["tool_invocation_id"], require_current=lambda: None)
    with session_scope() as session:
        assert session.get(BuildWorkReservationRecord, authorization["tool_invocation_id"]) is None
        assert session.scalar(select(func.count()).select_from(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == goal["id"])) == 1


@pytest.mark.parametrize("when", ["before_activation", "before_authorization"])
def test_phase_cannot_retarget_a_baseline_to_another_project_version(evidence_api, tmp_path, when):
    v = evidence_api
    fixed, original = start_structure(v, authorized=True)
    revision = revised(v, fixed, original, tmp_path)
    command = prepare_phase(v, activation(v, fixed, original, revision))
    if when == "before_authorization":
        assert confirm(v, command)["status"] == "completed"
        waiting = resume(v, original["id"])
        before = current_goal(v, original)
    else:
        before = original
    with session_scope() as session:
        version_id = "version_" + uuid4().hex
        session.add(VersionRecord(id=version_id, project_id=v["project_id"], name="Another version", branch_name="another"))
        session.flush()
        session.get(BaselineRecord, fixed["target_baseline_id"]).source_version_id = version_id
    if when == "before_activation":
        assert confirm(v, command)["status"] == "failed"
        assert current_goal(v, original) == before and phases(v, fixed, original).json() == []
    else:
        failed = resume(v, original["id"], expected=waiting)
        assert failed["status"] in {"failed", "paused"}, failed
        assert failed["steps"][:len(original["steps"])] == original["steps"]
        assert failed["steps"][-1]["status"] != "completed"
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(BuildAuthorizationRecord).where(BuildAuthorizationRecord.goal_id == original["id"])) == 1
        assert session.scalar(select(func.count()).select_from(StructureBuildArtifactRecord).where(
            StructureBuildArtifactRecord.plan_id == revision["revision"]["plan_id"])) == 0


@pytest.mark.parametrize("retained", ["phases", "independent_consents"])
def test_phase_migration_preserves_grants_and_refuses_destructive_downgrade(evidence_api, tmp_path, monkeypatch, retained):
    import importlib
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect, text
    from apps.api.app.infrastructure.persistence.database import engine
    v = evidence_api
    fixed, original = start_structure(v, authorized=True)
    revision = revised(v, fixed, original, tmp_path)
    assert confirm(v, prepare_phase(v, activation(v, fixed, original, revision)))["status"] == "completed"
    waiting = resume(v, original["id"])
    assert resume(v, original["id"], expected=waiting)["pause_reason"] == "structural_candidate_review"
    migration = importlib.import_module("apps.api.migrations.versions.0087_image_plan_phases")
    assert engine.url.database.startswith("nasus_test_")
    schema = "nasus_test_plan_phases_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            connection.execute(text("CREATE TABLE image_build_authorizations (LIKE public.image_build_authorizations INCLUDING DEFAULTS)"))
            connection.execute(text("ALTER TABLE image_build_authorizations ADD PRIMARY KEY (authorization_id), ADD CONSTRAINT image_build_authorizations_goal_id_key UNIQUE (goal_id)"))
            connection.execute(text("INSERT INTO image_build_authorizations SELECT * FROM public.image_build_authorizations WHERE goal_id = :goal AND plan_id = :plan"),
                {"goal": original["id"], "plan": fixed["plan_id"]})
            original_rows = connection.execute(text("SELECT * FROM image_build_authorizations")).all()
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            columns = {item["name"]: item for item in inspect(connection).get_columns("agent_image_plan_phases", schema=schema)}
            assert columns.keys() == set(ImagePlanPhaseRecord.__table__.columns.keys())
            for column in ImagePlanPhaseRecord.__table__.columns:
                assert columns[column.name]["nullable"] == column.nullable
                assert columns[column.name]["type"]._type_affinity is column.type._type_affinity
            constraints = inspect(connection).get_unique_constraints("image_build_authorizations", schema=schema)
            assert any(item["name"] == "uq_build_authorization_goal_plan" and item["column_names"] == ["goal_id", "plan_id"] for item in constraints)
            assert connection.execute(text("SELECT * FROM image_build_authorizations")).all() == original_rows
            migration.downgrade()
            assert connection.execute(text("SELECT * FROM image_build_authorizations")).all() == original_rows
            migration.upgrade()
            if retained == "phases":
                connection.execute(text("INSERT INTO agent_image_plan_phases SELECT * FROM public.agent_image_plan_phases WHERE goal_id = :goal"), {"goal": original["id"]})
                message = "populated"
            else:
                connection.execute(text("INSERT INTO image_build_authorizations SELECT * FROM public.image_build_authorizations WHERE goal_id = :goal AND plan_id <> :plan"),
                    {"goal": original["id"], "plan": fixed["plan_id"]})
                message = "independent plan execution consents"
            with pytest.raises(RuntimeError, match=message):
                migration.downgrade()
            assert connection.scalar(text("SELECT count(*) FROM image_build_authorizations")) == (1 if retained == "phases" else 2)
            assert connection.scalar(text("SELECT count(*) FROM agent_image_plan_phases")) == (1 if retained == "phases" else 0)
        finally:
            transaction.rollback()
