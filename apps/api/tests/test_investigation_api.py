from dataclasses import asdict
import json

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.system_image.investigations import INVESTIGATE_TOOL, INVESTIGATION_READ_TOOL
from apps.api.app.infrastructure.persistence.investigation_models import InvestigationRevisionRecord
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord, AgentGoalRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_structure_build_api import request, submit, confirm
from apps.api.tests.test_agent_build_plan_api import goal_request, READ_BUILD_PLAN_TOOL
from apps.api.tests.test_document_projection_api import documents


@pytest.fixture(autouse=True)
def investigation_diagnostics(monkeypatch):
    from apps.api.app.application.system_image.investigations import InvestigationApplicationService
    original = InvestigationApplicationService.create

    def create(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except Exception as exc:
            print("Investigation test diagnostic:", type(exc).__name__, str(exc))
            raise

    monkeypatch.setattr(InvestigationApplicationService, "create", create)


@pytest.fixture
def investigation(evidence_api):
    v = evidence_api
    structure = request(v)
    built = confirm(v, submit(v, structure))
    assert built["status"] == "completed", built
    image_id = next(ref.split(":", 1)[1] for ref in built["result"]["object_refs"] if ref.startswith("image_revision:"))
    image = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/revisions/{image_id}", headers=v["headers"]).json()["revision"]
    goal = goal_request(v, structure, [(READ_BUILD_PLAN_TOOL, {"project_id": v["project_id"], "plan_id": structure["plan_id"]})])
    assert goal.status_code == 200, goal.text
    v["investigation_input"] = {"project_id": v["project_id"], "plan_id": structure["plan_id"],
        "plan_digest": structure["plan_digest"], "goal_id": goal.json()["id"],
        "image_revision_id": image_id, "image_artifact_hash": image["artifact_hash"]}
    return v


def investigate(v, *, payload=None, key=None, headers=None, confirmed=True):
    response = v["client"].post("/v1/tool-invocations", headers=headers or v["headers"], json={
        "tool_id": INVESTIGATE_TOOL, "conversation_id": v["conversation"].json()["id"],
        "input": payload or v["investigation_input"], "idempotency_key": key})
    assert response.status_code == 200, response.text
    item = response.json()
    if confirmed and item["status"] == "waiting_confirmation":
        item = confirm(v, item["id"])
    return item


def read(v, ident, *, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/system-image/build-investigations/{ident}", headers=headers or v["headers"])


def revision_count(session, v):
    return session.scalar(select(func.count()).select_from(InvestigationRevisionRecord).where(
        InvestigationRevisionRecord.project_id == v["project_id"]))


def test_confirmed_revision_same_goal_fixed_evidence_and_private_replay(investigation, monkeypatch):
    v = investigation
    pending = investigate(v, key="fixed-investigation", confirmed=False)
    assert pending["status"] == "waiting_confirmation"
    with session_scope() as session:
        assert revision_count(session, v) == 0
    item = confirm(v, pending["id"])
    assert item["status"] == "completed", item
    receipt = item["result"]["investigation"]
    result = read(v, receipt["revision_id"])
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store", result.text
    saved = result.json()
    assert saved["revision_hash"] == receipt["revision_hash"] and saved["request"]["goal_id"] == v["investigation_input"]["goal_id"]
    assert saved["revision_number"] == 1 and saved["request"]["parent_revision_id"] is None
    assert saved["review"]["verified_evidence"]
    assert all(item["coverage"] is None for item in saved["review"]["readiness"].values())
    assert not saved["review"]["publication_allowed"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        observed = app.state.container.tool_evidence.describe(item["id"], v["project_id"])
    assert observed["review"] == asdict(app.state.container.investigations.repository.read(v["project_id"], receipt["revision_id"]).review)
    v["path"].write_text("class LaterVersion:\n    pass\n")
    v["invoke"]("system_image.sources.ingest")
    v["path"].unlink()
    assert read(v, receipt["revision_id"]).json() == saved
    assert investigate(v, key="fixed-investigation")["id"] == item["id"]
    with session_scope() as session:
        events = session.scalars(select(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.entity_id == receipt["revision_id"])).all()
        assert len(events) == 1
        assert "evidence_signature" not in json.dumps([event.event_payload for event in events])
    for secret in ("private Orders", "class Orders", "orders.py", "local-object://", "s3://"):
        assert secret not in json.dumps(item) + result.text
    for statement in (update(InvestigationRevisionRecord).values(revision_hash="changed"), delete(InvestigationRevisionRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(InvestigationRevisionRecord.revision_id == receipt["revision_id"]))


def test_parent_cas_repeated_no_progress_pause_and_no_silent_goal_replacement(investigation):
    v = investigation
    current = None
    for number in range(1, 5):
        body = {**v["investigation_input"], **({"parent_revision_id": current["revision_id"],
            "parent_revision_hash": current["revision_hash"]} if current else {})}
        result = investigate(v, payload=body)
        assert result["status"] == "completed", result
        current = read(v, result["result"]["investigation"]["revision_id"]).json()
        assert current["revision_number"] == number and current["review"]["no_progress_rounds"] == number - 1
        assert current["review"]["consumed_review_calls"] == number
        assert current["request"]["goal_id"] == v["investigation_input"]["goal_id"]
    assert current["review"]["state"] == "paused_no_progress" and not current["review"]["work_items"]
    stale = investigate(v)
    assert stale["status"] == "failed"
    paused = investigate(v, payload={**v["investigation_input"], "parent_revision_id": current["revision_id"],
                                   "parent_revision_hash": current["revision_hash"]})
    assert paused["status"] == "failed"
    with session_scope() as session:
        assert revision_count(session, v) == 4


def test_legacy_investigation_replays_and_keeps_its_original_policy_on_child_creation(investigation, monkeypatch):
    import apps.api.app.application.system_image.investigations as module

    v = investigation
    original = module.propose_investigation

    def legacy(*args, **kwargs):
        return original(*args, **{**kwargs, "policy_version": "nasus.image-investigation-revision.v1"})

    monkeypatch.setattr(module, "propose_investigation", legacy)
    command = investigate(v)
    assert command["status"] == "completed", command
    parent = read(v, command["result"]["investigation"]["revision_id"]).json()
    assert parent["review"]["policy_version"] == "nasus.image-investigation-revision.v1"
    monkeypatch.setattr(module, "propose_investigation", original)
    assert read(v, parent["revision_id"]).json() == parent
    child = investigate(v, payload={**v["investigation_input"], "parent_revision_id": parent["revision_id"],
        "parent_revision_hash": parent["revision_hash"]})
    assert child["status"] == "completed", child
    saved = read(v, child["result"]["investigation"]["revision_id"]).json()
    assert saved["review"]["policy_version"] == parent["review"]["policy_version"]
    assert saved["revision_number"] == 2
    assert read(v, parent["revision_id"]).json() == parent


@pytest.mark.parametrize("change", [{"goal_id": "foreign"}, {"plan_digest": "sha256:" + "0" * 64},
    {"image_artifact_hash": "sha256:" + "0" * 64}, {"image_revision_id": "foreign"},
    {"parent_revision_id": "foreign"}, {"execute_repository": True}])
def test_wrong_pins_unknown_fields_and_partial_parent_never_commit(investigation, change):
    v = investigation
    response = v["client"].post("/v1/tool-invocations", headers=v["headers"], json={
        "tool_id": INVESTIGATE_TOOL, "conversation_id": v["conversation"].json()["id"],
        "input": {**v["investigation_input"], **change}})
    if response.status_code == 200:
        item = response.json()
        if item["status"] == "waiting_confirmation":
            item = confirm(v, item["id"])
        assert item["status"] == "failed", item
    else:
        assert response.status_code == 403 and response.json()["error"]["code"] == "tool_invocation_access_denied", response.text
    with session_scope() as session:
        assert revision_count(session, v) == 0


def test_current_source_access_controls_history_and_confirmation(investigation):
    v = investigation
    item = investigate(v, key="investigation-private")
    assert item["status"] == "completed", item
    grant_member(v)
    policy(v, (v["member"]["id"],))
    ident = item["result"]["investigation"]["revision_id"]
    assert read(v, ident, headers=v["member_headers"]).status_code == 200
    policy(v)
    assert read(v, ident, headers=v["member_headers"]).status_code == 403
    denied = v["client"].get(f"/v1/tool-invocations/{item['id']}", headers=v["member_headers"])
    assert denied.status_code == 403 and "evidence_signature" not in denied.text


def test_late_scope_failure_rolls_back_revision_and_metadata_event(investigation, monkeypatch):
    from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
    v = investigation
    repository = app.state.container.investigations.repository
    original = repository.record

    def record(*args, **kwargs):
        kwargs["require_current"] = lambda: (_ for _ in ()).throw(StaleSourceAccessScope("private policy detail"))
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "record", record)
    item = investigate(v)
    assert item["status"] == "failed" and "private policy" not in str(item)
    with session_scope() as session:
        assert revision_count(session, v) == 0
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.build.investigation.revised",
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"])) == 0


def test_actual_agent_expands_gap_read_tasks_in_same_goal_and_keeps_completion_review(evidence_api):
    v = evidence_api
    v["path"].write_text("\n".join(f"class Evidence{i}:\n    def observe(self):\n        return {i}\n" for i in range(16)))
    v["invoke"]("system_image.sources.ingest")
    v["image"] = v["client"].get(f"/v1/projects/{v['project_id']}/system-image", headers=v["headers"]).json()
    fixed = request(v)
    built = confirm(v, submit(v, fixed))
    assert built["status"] == "completed", built
    image_id = next(ref.split(":", 1)[1] for ref in built["result"]["object_refs"] if ref.startswith("image_revision:"))
    image = v["client"].get(f"/v1/projects/{v['project_id']}/system-image/revisions/{image_id}", headers=v["headers"]).json()["revision"]
    body = {"project_id": v["project_id"], "plan_id": fixed["plan_id"], "plan_digest": fixed["plan_digest"],
            "image_revision_id": image_id, "image_artifact_hash": image["artifact_hash"]}
    response = goal_request(v, fixed, [(INVESTIGATE_TOOL, body)])
    assert response.status_code == 200, response.text
    goal = response.json()
    assert goal["status"] == "paused" and goal["pause_reason"] == "waiting_confirmation", goal
    resumed = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
    assert resumed.status_code == 200, resumed.text
    final = resumed.json()
    assert final["status"] == "paused" and final["pause_reason"] == "build_completion_review", final
    acting = [step for step in final["steps"] if step["phase"] == "acting"]
    assert acting[0]["selected_tool_id"] == INVESTIGATE_TOOL and len(acting) > 1
    assert all(step["status"] == "completed" for step in acting)
    first = v["client"].get(f"/v1/tool-invocations/{acting[0]['tool_invocation_id']}", headers=v["headers"]).json()
    saved = read(v, first["result"]["investigation"]["revision_id"]).json()
    assert saved["request"]["goal_id"] == goal["id"] and saved["review"]["state"] == "investigation_ready"
    assert [step["selected_tool_id"] for step in acting[1:]] == [task["tool_id"] for task in saved["review"]["work_items"]]
    for step, task in zip(acting[1:], saved["review"]["work_items"]):
        assert all(step["tool_input_payload"].get(key) == value for key, value in task["input_payload"].items())
    for step in acting:
        tool = v["client"].get(f"/v1/tool-invocations/{step['tool_invocation_id']}", headers=v["headers"]).json()
        assert tool["input_payload"]["agent_goal_id"] == goal["id"]
        assert tool["input_payload"]["image_revision_id"] == image_id
    retry = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": final}).json()
    assert retry["pause_reason"] == "build_completion_review"
    assert [step["tool_invocation_id"] for step in retry["steps"] if step["phase"] == "acting"] == [step["tool_invocation_id"] for step in acting]


def test_two_confirmed_root_writers_cannot_fork_or_replace_investigation_head(investigation):
    from concurrent.futures import ThreadPoolExecutor
    v = investigation
    first = investigate(v, confirmed=False)
    second = investigate(v, confirmed=False)
    assert first["id"] != second["id"] and first["status"] == second["status"] == "waiting_confirmation"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda ident: confirm(v, ident), (first["id"], second["id"])))
    assert sorted(item["status"] for item in results) == ["completed", "failed"], results
    with session_scope() as session:
        assert revision_count(session, v) == 1
        saved = session.scalars(select(InvestigationRevisionRecord).where(
            InvestigationRevisionRecord.project_id == v["project_id"])).one()
        assert saved.revision_number == 1 and saved.parent_revision_id is None


def test_code_requirements_and_cases_drive_field_investigation_without_oracle_upgrade(documents):
    v = documents
    v["image"] = v["client"].get(v["image_url"], headers=v["headers"]).json()
    fixed = request(v)
    built = confirm(v, submit(v, fixed))
    assert built["status"] == "completed", built
    image_id = next(ref.split(":", 1)[1] for ref in built["result"]["object_refs"] if ref.startswith("image_revision:"))
    image = v["client"].get(f"{v['image_url']}/revisions/{image_id}", headers=v["headers"]).json()["revision"]
    body = {"project_id": v["project_id"], "plan_id": fixed["plan_id"], "plan_digest": fixed["plan_digest"],
            "image_revision_id": image_id, "image_artifact_hash": image["artifact_hash"]}
    goal = goal_request(v, fixed, [(INVESTIGATE_TOOL, body)]).json()
    assert goal["pause_reason"] == "waiting_confirmation", goal
    result = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"], json={"expected_goal": goal})
    assert result.status_code == 200, result.text
    review = result.json()
    assert review["pause_reason"] == "reference_candidate_review", review
    assert review["id"] == goal["id"] and review["model_calls_used"] == 0
    proposal_step = next(step for step in review["steps"] if step["phase"] == "acting"
        and step["selected_tool_id"] == "system_image.links.propose_references")
    assert proposal_step["status"] == "blocked"
    proposal_command = v["client"].get(f"/v1/tool-invocations/{proposal_step['tool_invocation_id']}",
        headers=v["headers"]).json()
    assert proposal_command["status"] == "completed"
    assert proposal_command["input_payload"]["image_revision_id"] == image_id
    assert proposal_command["input_payload"]["agent_goal_id"] == goal["id"]
    proposal_id = next(ref.split(":", 1)[1] for ref in proposal_command["result"]["object_refs"]
        if ref.startswith("image_reference_proposal:"))
    proposal_url = f"{v['image_url']}/reference-proposals/{proposal_id}"
    proposal = v["client"].get(proposal_url, headers=v["headers"]).json()
    assert proposal["assertion_count"] == 1 and proposal["gap_count"] == 0
    assert proposal["items"][0]["reference_id"] == "US-17"
    assert proposal["publication"] == "not_in_image_membership"
    assert all(item["status"] == "proposed" and item["predicate"] == "references" for item in proposal["items"])
    result = v["client"].post(f"/v1/agent-goals/{goal['id']}/resume", headers=v["headers"],
        json={"expected_goal": review})
    assert result.status_code == 200, result.text
    final = result.json()
    assert final["id"] == goal["id"] and final["pause_reason"] == "build_completion_review", final
    acting = [step for step in final["steps"] if step["phase"] == "acting"]
    assert all(step["status"] == "completed" for step in acting)
    reference_reads = [step for step in acting if step["selected_tool_id"] == "query.system_image.references.read"]
    assert {step["tool_input_payload"]["section"] for step in reference_reads} == {"assertions", "gaps"}
    assert all(step["tool_input_payload"]["proposal_id"] == proposal_id for step in reference_reads)
    assert v["client"].get(proposal_url, headers=v["headers"]).json() == proposal
    command = v["client"].get(f"/v1/tool-invocations/{acting[0]['tool_invocation_id']}", headers=v["headers"]).json()
    saved = read(v, command["result"]["investigation"]["revision_id"]).json()
    codes = {gap["code"] for gap in saved["review"]["gaps"]}
    assert {"document_semantics_unreviewed", "business_oracle_authority_unresolved", "runtime_evidence_unresolved"} <= codes
    assert not {"us_doc_unavailable", "test_asset_unavailable"} & codes
    fields = [step for step in acting if step["selected_tool_id"] == "query.system_image.revisions.document"]
    assert len(fields) == 3
    with actor_scope(UserProfile.model_validate(v["owner"])):
        observations = [app.state.container.tool_evidence.describe(step["tool_invocation_id"], v["project_id"]) for step in fields]
    assert observations and all(observation is not None for observation in observations)
    assert saved["review"]["readiness"]["behavior"]["coverage"] is None
    assert not saved["review"]["publication_allowed"]


def test_goal_stop_before_commit_does_not_create_revision_or_invalidate_old_history(investigation, monkeypatch):
    v = investigation
    saved = investigate(v)
    assert saved["status"] == "completed", saved
    ident = saved["result"]["investigation"]["revision_id"]
    first = read(v, ident).json()
    body = {**v["investigation_input"], "parent_revision_id": ident, "parent_revision_hash": first["revision_hash"]}
    repository = app.state.container.investigations.repository
    original = repository.record

    def cancelled(*args, **kwargs):
        with session_scope() as session:
            session.get(AgentGoalRecord, v["investigation_input"]["goal_id"]).status = "cancelled"
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "record", cancelled)
    result = investigate(v, payload=body)
    assert result["status"] == "failed", result
    assert read(v, ident).json() == first
    with session_scope() as session:
        assert revision_count(session, v) == 1
