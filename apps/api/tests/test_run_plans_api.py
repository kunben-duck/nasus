"""Real PG/private MinIO plans; target and model transport are protocol specimens."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.tool_models import EventPayload
from apps.api.app.application.quality_loop.run_plan_inputs import RunPlanRequest
from apps.api.app.application.quality_loop.run_plan_locators import RUN_PLAN_LOCATOR_QUERY_TOOL
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan import RUN_PLAN_TOOL, RUN_PLAN_PREVIEW_TOOL, RunPlanIntegrityError
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.run_plan_models import RunPlanRecord as Plan
from apps.api.app.infrastructure.persistence.run_plan_repository import RunPlanRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_automation_scripts_api import (
    native_scripts, run_confirmed, read_draft, independent_reviewer, script_review_request, submit_script_review, read_script_review,
    base_evidence_api, evidence_api, documents, publication, design_scope, generation_result, mapping, verify_fixed_exweb_archive,
)
from apps.api.tests.test_semantic_evaluations_api import completed, count, invoke, confirm
from apps.api.tests.test_source_access_api import policy as restrict_source
from apps.api.tests.test_run_plans import selection_for
from apps.api.tests.test_runner_observations_native import native_runner
from apps.api.tests.test_http_bindings_native import binding_target


def reviewed_plan_inputs(v):
    _, response = run_confirmed(v)
    generated = completed(response)
    draft = read_draft(v, generated).json()
    reviewer = independent_reviewer(v)
    reviewed = completed(submit_script_review(reviewer, script_review_request(v, draft)))
    review_id = reviewed["result"]["object_refs"][0].split(":", 1)[1]
    review = read_script_review(v, review_id).json()
    with actor_scope(UserProfile.model_validate(v["owner"])):
        sources = app.state.container.run_plans.sources.run_plan_sources(draft["result"]["prepared"])
    return draft, review, reviewer, selection_for(draft, review, sources)


def select_binding_scripts(v):
    from apps.api.tests.test_http_binding_scripts import binding_script_output
    from apps.api.app.application.quality_loop.automation_script_inputs import ScriptExecutionSelection
    v["script_transport"].output = binding_script_output
    original_preview = deepcopy(v["script_preview"])
    selection = ScriptExecutionSelection.model_validate({**v["script_selection"].model_dump(mode="json"),
        "http_protocol": "nasus.runner-http-execution.v2"})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        v["script_preview"] = v["script_service"].preview(selection)
    assert v["script_preview"]["request"]["execution"]["plan_digest"] != original_preview["request"]["execution"]["plan_digest"]


def preview(v, selection):
    return v["client"].post(f"/v1/projects/{v['project_id']}/quality/run-plan-previews",
        headers=v["headers"], json=selection.model_dump(mode="json"))


def submit(v, request, *, key=None):
    pending = invoke(v, RUN_PLAN_TOOL, request, key=key or uuid4().hex)
    if pending.status_code != 200 or pending.json()["status"] != "waiting_confirmation":
        return pending
    return confirm(v, pending.json())


def read(v, ident, *, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/run-plans/{ident}", headers=headers or v["headers"])


def inspect_http_locators(v, ident, artifact_hash, *, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/run-plans/{ident}/http-locators",
        params={"run_plan_artifact_hash": artifact_hash}, headers=headers or v["headers"])


@pytest.mark.parametrize("lost_receipt", [False, True])
@pytest.mark.parametrize("http_protocol", ["v1", "v2"])
def test_saved_plan_native_observation_archive_rechecks_real_source_acl_without_dispatch_on_replay(native_scripts, native_runner, binding_target, monkeypatch, lost_receipt, http_protocol):
    """Real PG parent, Node target and MinIO; model/oracles remain specimens."""
    from dataclasses import asdict
    from apps.api.app.application.quality_loop.run_plan_observation_archives import (
        RunPlanObservationArchiveApplicationService, RunPlanObservationArchiveParent, SavedRunPlanObservationArchiveAccess,
    )
    from apps.api.app.application.quality_loop.run_plan_observations import RunPlanObservationApplicationService
    from apps.api.app.domain.system_image.source_access import SourceAccessDenied
    from apps.api.app.infrastructure.runner.http_observation_verifier import HTTPRunnerObservationVerifier
    from apps.api.app.infrastructure.storage.run_plan_observation_artifacts import RunPlanObservationArtifacts
    from apps.api.app.infrastructure.storage.object_storage import ObjectStorage

    v = native_scripts
    runner, base_url, storage = native_runner
    if http_protocol == "v2":
        select_binding_scripts(v)
        base_url, sessions, visits = binding_target
    _, _, _, selection = reviewed_plan_inputs(v)
    selected = selection.model_dump(mode="json")
    selected["environment"]["base_url"] = base_url
    if http_protocol == "v2": selected["policy_revision"] = "nasus.run-plan.v2"
    selection = type(selection).model_validate(selected)
    response = preview(v, selection)
    assert response.status_code == 200, response.text
    command = completed(submit(v, response.json()["request"]))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    prepared = read(v, ident).json()
    plan = prepared["artifact"]["plan"]
    assert plan["schema"] == "nasus.run-plan." + http_protocol
    assert prepared["artifact"]["schema"] == "nasus.run-plan-artifact." + http_protocol
    parent = RunPlanObservationArchiveParent(project_id=v["project_id"], run_plan_id=ident,
        run_plan_artifact_hash=prepared["metadata"]["artifact_hash"], plan_digest=plan["plan_digest"])
    service = RunPlanObservationArchiveApplicationService(RunPlanObservationApplicationService(HTTPRunnerObservationVerifier()),
        RunPlanObservationArtifacts(storage), SavedRunPlanObservationArchiveAccess(app.state.container.run_plans, parent))
    attempt = "explicit-native-saved-plan-" + uuid4().hex
    jobs = service.observations.commands(plan, run_id=attempt, timeout_ms=5000)
    results = []
    for index, job in enumerate(jobs):
        adapter = type(runner)(runner.endpoint, "explicit-invalid-service-token") if lost_receipt and index == 0 else runner
        results.append(adapter.execute(job))
    if http_protocol == "v2":
        assert len(sessions) == len(jobs) - int(lost_receipt)
        assert all("{{" not in path for _, path in visits)
        for job, result in zip(jobs[int(lost_receipt):], results[int(lost_receipt):]):
            assert job.http_protocol == "nasus.runner-http-execution.v2"
            receipt = result.execution_receipt
            assert receipt["schema"] == "nasus.runner-http-execution.v2"
            assert len(receipt["bindings"]) == 1 and receipt["bindings"][0]["value"] in sessions
            assert receipt["steps"][1]["kind"] == "action" and receipt["steps"][1]["status"] == "passed"
            assert receipt["requests"][1]["path"] == "/sessions/" + receipt["bindings"][0]["value"]
    entries = [{"runner_job_id": job.job_id, "result": asdict(result)} for job, result in zip(jobs, results)]
    images = app.state.container.image_revisions
    image_reads = []
    original_image_read = images.artifacts.read
    def counted_image_read(project_id, ref, digest):
        image_reads.append(digest)
        return original_image_read(project_id, ref, digest)
    monkeypatch.setattr(images.artifacts, "read", counted_image_read)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        saved = service.archive(plan, entries, run_id=attempt, timeout_ms=5000)
    assert image_reads.count(plan["source_pin"]["image_artifact_hash"]) == 1
    assert images._verified_reads.get() is None
    assert saved["artifact_ref"].startswith("s3://")
    artifacts = RunPlanObservationArtifacts(ObjectStorage())
    fresh = RunPlanObservationArchiveApplicationService(RunPlanObservationApplicationService(HTTPRunnerObservationVerifier()),
        artifacts, SavedRunPlanObservationArchiveAccess(app.state.container.run_plans, parent))
    replay_reads = []
    original_read = artifacts.read
    def counted(project_id, ref, digest):
        replay_reads.append(ref)
        return original_read(project_id, ref, digest)
    monkeypatch.setattr(artifacts, "read", counted)
    image_reads.clear()
    with actor_scope(UserProfile.model_validate(v["member"])):
        replay = fresh.read(v["project_id"], saved["artifact_ref"], saved["artifact_hash"], plan_digest=plan["plan_digest"])
    assert image_reads.count(plan["source_pin"]["image_artifact_hash"]) == 1
    assert images._verified_reads.get() is None
    assert replay["original_run_plan"] == parent.model_dump(mode="json")
    assert replay["summary"]["observed_case_count"] == len(jobs) - int(lost_receipt)
    if lost_receipt:
        assert replay["summary"]["outcome_unknown_case_count"] == 1
        assert replay["unverified_attempts"][0]["native_dispatch_verified"] is False
    assert replay["summary"]["failed_observation_count"] > 0
    assert replay["canonical_execution_committed"] is replay["execution_authorized"] is False
    assert replay["summary"]["passed_count"] == replay["summary"]["executed_on_target_count"] == 0
    from apps.api.app.application.quality_loop.run_plan_observation_records import OBSERVATION_RECORD_TOOL, OBSERVATION_RECORD_QUERY_TOOL
    from apps.api.app.infrastructure.persistence.run_plan_observation_models import RunPlanObservationRecord, RunPlanCaseObservationRecord
    recording_request = {**parent.model_dump(mode="json"), "observation_artifact_hash": saved["artifact_hash"],
        "collection_digest": replay["summary"]["collection_digest"], "run_id": attempt}
    def record_command():
        pending = invoke(v, OBSERVATION_RECORD_TOOL, recording_request)
        assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
        assert count(v, RunPlanObservationRecord) == 0
        return confirm(v, pending.json())
    original_append = EventOutboxRepository._append_in_session
    fault_hits = []
    def fail_observation_event(self, session, event):
        result = original_append(self, session, event)
        if event.event_type == "quality.run_plan.observations_recorded":
            row = session.get(RunPlanObservationRecord, event.entity_id)
            assert row is not None and row.project_id == v["project_id"] and event.patch["record_id"] == row.record_id
            command = session.get(ToolInvocationRecord, row.invocation_id)
            assert command is not None and command.tool_id == OBSERVATION_RECORD_TOOL and command.status == "running"
            members = session.scalars(select(RunPlanCaseObservationRecord).where(RunPlanCaseObservationRecord.record_id == row.record_id)).all()
            audit = session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == row.invocation_id,
                AuditEventRecord.action == "quality.run_plan.observations_recorded")).all()
            assert len(members) == len(jobs) and len(audit) == 1
            assert session.scalar(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_id == event.event_id)) is not None
            fault_hits.append((row.record_id, row.invocation_id, len(members)))
            raise RuntimeError("explicit late observation Outbox failure")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(EventOutboxRepository, "_append_in_session", fail_observation_event)
        failed_record = record_command()
    assert failed_record.status_code == 200 and failed_record.json()["status"] == "failed", failed_record.text
    assert len(fault_hits) == 1 and fault_hits[0][1] == failed_record.json()["id"]
    assert count(v, RunPlanObservationRecord) == count(v, RunPlanCaseObservationRecord) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.tool_invocation_id == failed_record.json()["id"],
            AuditEventRecord.action == "quality.run_plan.observations_recorded")).all()
        assert not session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == fault_hits[0][0],
            SSEEventOutboxRecord.event_type == "quality.run_plan.observations_recorded")).all()
    recorded = completed(record_command())
    record_id = recorded["result"]["object_refs"][0].split(":", 1)[1]
    record_url = f"/v1/projects/{v['project_id']}/quality/run-plan-observations/{record_id}"
    view = v["client"].get(record_url, headers=v["headers"])
    assert view.status_code == 200 and view.headers["cache-control"] == "private, no-store", view.text
    record_view = view.json()
    assert record_view["archive"] == replay
    assert record_view["metadata"]["case_count"] == count(v, RunPlanCaseObservationRecord) == len(jobs)
    assert record_view["metadata"]["outcome_unknown_case_count"] == int(lost_receipt)
    assert record_view["metadata"]["passed_count"] == record_view["metadata"]["executed_on_target_count"] == 0
    queried = completed(invoke(v, OBSERVATION_RECORD_QUERY_TOOL, {"project_id": v["project_id"], "record_id": record_id}))
    receipt = queried["result"]["run_plan_observations"]
    assert "members" not in receipt["metadata"] and "archive" not in receipt and "artifact_ref" not in str(receipt)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(queried["id"], v["project_id"]) == receipt
    replayed_events = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=recorded["conversation_id"],
        after_event_id=None, initial_replay_limit=1000)
    assert any(event.event_type == "quality.run_plan.observations_recorded" and event.entity_id == record_id for event in replayed_events)
    with session_scope() as session:
        rows = session.scalars(select(RunPlanCaseObservationRecord).where(RunPlanCaseObservationRecord.record_id == record_id)
            .order_by(RunPlanCaseObservationRecord.ordinal)).all()
        assert [row.payload["case_id"] for row in rows] == [case["case_id"] for case in plan["prepared"]["cases"]]
        assert all(row.payload["actions"] and row.payload["oracles"] for row in rows)
        assert len(session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == record_id,
            AuditEventRecord.action == "quality.run_plan.observations_recorded")).all()) == 1
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.entity_id == record_id,
            SSEEventOutboxRecord.event_type == "quality.run_plan.observations_recorded")).all()
        assert len(events) == 1 and "base_url" not in str(events[0].event_payload) and "raw_results" not in str(events[0].event_payload)
        with pytest.raises(Exception, match="immutable|append-only|cannot|mutation"):
            with session.begin_nested():
                session.execute(update(RunPlanObservationRecord).where(RunPlanObservationRecord.record_id == record_id).values(status="modified"))
    restrict_source(v)
    replay_reads.clear()
    with actor_scope(UserProfile.model_validate(v["member"])), pytest.raises(SourceAccessDenied):
        fresh.read(v["project_id"], saved["artifact_ref"], saved["artifact_hash"], plan_digest=plan["plan_digest"])
    assert replay_reads == []
    revoked_record = v["client"].get(record_url, headers=v["member_headers"])
    assert revoked_record.status_code == 403 and revoked_record.headers["cache-control"] == "private, no-store", revoked_record.text
    assert images._verified_reads.get() is None
    restrict_source(v, (v["member"]["id"],))
    def revoked_during_read(project_id, ref, digest):
        value = original_read(project_id, ref, digest)
        restrict_source(v)
        return value
    monkeypatch.setattr(artifacts, "read", revoked_during_read)
    with actor_scope(UserProfile.model_validate(v["member"])), pytest.raises(SourceAccessDenied):
        fresh.read(v["project_id"], saved["artifact_ref"], saved["artifact_hash"], plan_digest=plan["plan_digest"])
    assert images._verified_reads.get() is None
    assert count(v, Plan) == 1 and len(v["script_calls"]) == 1
    assert read(v, ident).json() == prepared


def test_run_plan_native_confirmation_history_withdrawal_acl_and_immutable_schema(native_scripts):
    v = native_scripts
    draft, review, reviewer, selection = reviewed_plan_inputs(v)
    response = preview(v, selection)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    initial = response.json()
    assert count(v, Plan) == 0 and len(v["script_calls"]) == 1
    observation = completed(invoke(v, RUN_PLAN_PREVIEW_TOOL, selection.model_dump(mode="json")))
    assert observation["result"]["run_plan_preview"] == initial
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(observation["id"], v["project_id"]) == initial
    changed = deepcopy(initial["request"])
    changed["environment"]["inventory_hash"] = acceptance_digest("changed-after-preview")
    rejected = submit(v, changed)
    assert rejected.status_code == 200 and rejected.json()["status"] == "failed", rejected.text
    assert count(v, Plan) == 0
    reviewer_preview = preview(reviewer, selection)
    assert reviewer_preview.status_code == 200, reviewer_preview.text
    original_request = reviewer_preview.json()["request"]
    key = uuid4().hex
    def original_command():
        # Portal recovery uses actor-scoped commands, never a conversation key.
        return v["client"].post("/v1/tool-invocations", headers=reviewer["headers"], json={
            "tool_id": RUN_PLAN_TOOL, "input": original_request, "idempotency_key": key})
    pending = original_command()
    assert pending.json()["status"] == "waiting_confirmation" and count(v, Plan) == 0
    original_lookup = {"project_id": v["project_id"], "tool_id": RUN_PLAN_TOOL, "request_key": key}
    assert v["client"].get("/v1/tool-invocations/resolve", headers=v["headers"], params=original_lookup).json() is None
    resolved = v["client"].get("/v1/tool-invocations/resolve", headers=reviewer["headers"], params=original_lookup)
    assert resolved.status_code == 200 and resolved.json()["id"] == pending.json()["id"], resolved.text
    assert resolved.json()["status"] == "waiting_confirmation" and count(v, Plan) == 0
    assert len(v["script_calls"]) == 1
    command = completed(confirm(reviewer, pending.json()))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    response = read(v, ident)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    value = response.json()
    assert value["artifact"]["plan"]["prepared"] == draft["result"]["prepared"]
    assert value["artifact"]["plan"]["proposal"] == draft["result"]["proposal"]
    assert value["artifact"]["plan"]["review_pin"]["revision_id"] == review["revision"]["revision_id"]
    assert value["artifact"]["plan"]["target_verification"] == "declared_not_native_verified"
    assert value["current_use"] == {"inputs_current": True, "target_verified": False, "execution_authorized": False}
    assert count(v, Plan) == 1 and len(v["script_calls"]) == 1
    with session_scope() as session:
        row = session.get(Plan, ident)
        assert row.artifact_ref.startswith("s3://") and app.state.container.run_plans.artifacts.storage.config.s3_enabled
        assert row.script_node_hash != row.review_node_hash and row.context_id == draft["result"]["prepared"]["context_pin"]["context_id"]
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_type == "quality.run_plan.prepared",
            SSEEventOutboxRecord.entity_id == ident)).all()
        assert len(events) == 1
        original_event = deepcopy(events[0].event_payload)
        audit = session.scalars(select(AuditEventRecord).where(AuditEventRecord.action == "quality.run_plan.prepared",
            AuditEventRecord.entity_id == ident)).all()
        assert len(audit) == 1 and audit[0].tool_invocation_id == command["id"]
        actual = inspect(session.connection())
        columns = {item["name"]: item for item in actual.get_columns(Plan.__tablename__)}
        assert set(columns) == {column.name for column in Plan.__table__.columns}
        for column in Plan.__table__.columns:
            assert columns[column.name]["nullable"] == column.nullable
            assert str(columns[column.name]["type"]).upper() == str(column.type).upper()
        actual_fks = {(tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
            for fk in actual.get_foreign_keys(Plan.__tablename__)}
        expected_fks = {(tuple(element.parent.name for element in fk.elements), fk.referred_table.name,
            tuple(element.column.name for element in fk.elements)) for fk in Plan.__table__.foreign_key_constraints}
        assert actual_fks == expected_fks
        context = MigrationContext.configure(session.connection())
        migration = importlib.import_module("apps.api.migrations.versions.0101_run_plans")
        with Operations.context(context), pytest.raises(RuntimeError, match="populated RunPlan"):
            migration.downgrade()
    for statement in (update(Plan).where(Plan.run_plan_id == ident).values(plan_digest=acceptance_digest("changed")),
            delete(Plan).where(Plan.run_plan_id == ident)):
        with pytest.raises(IntegrityError), session_scope() as session:
            session.execute(statement)
    # Isolate FK enforcement from the immutable trigger; rollback restores both.
    for fields in ({"script_node_hash": acceptance_digest("wrong-script-parent")},
            {"review_node_hash": acceptance_digest("wrong-review-parent")},
            {"context_id": "unrelated-context"}, {"manifest_id": "unrelated-manifest"}):
        with pytest.raises(IntegrityError) as rejected_fk, engine.begin() as connection:
            connection.execute(text("ALTER TABLE quality_run_plans DISABLE TRIGGER USER"))
            connection.execute(update(Plan).where(Plan.run_plan_id == ident).values(**fields))
        assert rejected_fk.value.orig.sqlstate == "23503"
    assert read(v, ident).json() == value
    withdraw = {**script_review_request(v, draft), "expected_previous_revision_id": review["revision"]["revision_id"],
        "decision": "withdraw", "actions": None, "assertions": None, "reason": "Independent withdrawal after prepared plan"}
    completed(submit_script_review(reviewer, withdraw))
    historical = read(v, ident)
    assert historical.status_code == 200 and historical.json()["artifact"] == value["artifact"], historical.text
    assert historical.json()["current_use"]["inputs_current"] is False
    assert preview(v, selection).status_code == 409
    replay = completed(original_command())
    assert replay["id"] == command["id"] and count(v, Plan) == 1
    with session_scope() as session:
        RunPlanRepository.verify_event(session, EventPayload.model_validate(original_event))
    assert read(v, ident, headers=v["member_headers"]).status_code == 200
    command_url = f"/v1/tool-invocations/{command['id']}"
    assert v["client"].get(command_url, headers=v["member_headers"]).status_code == 200
    original = v["client"].get("/v1/tool-invocations/resolve", headers=reviewer["headers"], params=original_lookup)
    assert original.status_code == 200 and original.json()["id"] == command["id"], original.text
    assert original.json()["input_payload"]["environment"] == original_request["environment"]
    # Broadcasts are shared projections, never grants to protected declarations.
    with actor_scope(UserProfile.model_validate(v["owner"])):
        public_command = app.state.container.agent._events.event_payload("tool_invocation", command["id"], {}, None)["tool_invocation"]
        assert public_command["input_payload"] == {} and public_command["result"] is None
    restrict_source(v)
    denied = read(v, ident, headers=v["member_headers"])
    assert denied.status_code == 403 and "artifact" not in denied.json()
    denied_command = v["client"].get(command_url, headers=v["member_headers"])
    assert denied_command.status_code == 403 and "input_payload" not in denied_command.json(), denied_command.text
    denied_lookup = v["client"].get("/v1/tool-invocations/resolve", headers=reviewer["headers"], params=original_lookup)
    assert denied_lookup.status_code == 403 and "input_payload" not in denied_lookup.json(), denied_lookup.text
    denied_replay = original_command()
    assert denied_replay.status_code == 403 and "input_payload" not in denied_replay.json(), denied_replay.text
    assert count(v, Plan) == 1
    assert read(v, ident).status_code == 200 and len(v["script_calls"]) == 1


def test_run_plan_real_late_outbox_failure_rolls_back_plan_and_audit_without_resending_model(native_scripts, monkeypatch):
    v = native_scripts
    draft, review, reviewer, selection = reviewed_plan_inputs(v)
    response = preview(v, selection)
    assert response.status_code == 200, response.text
    request = RunPlanRequest.model_validate(response.json()["request"])
    service = app.state.container.run_plans
    original_put = service.artifacts.put
    archived = []
    def tracked_put(*args):
        archived.append(args[0])
        return original_put(*args)
    monkeypatch.setattr(service.artifacts, "put", tracked_put)
    now = datetime.now(timezone.utc)
    for fault in ("expired", "future", "other_actor", "missing_time", "naive_time", "completed_without_plan"):
        invalid_id = uuid4().hex
        confirmed = now - timedelta(minutes=16) if fault == "expired" else now + timedelta(minutes=1) if fault == "future" else now
        actor = v["member"]["id"] if fault == "other_actor" else v["owner"]["id"]
        timestamp = "" if fault == "missing_time" else confirmed.replace(tzinfo=None).isoformat() if fault == "naive_time" else confirmed.isoformat()
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=invalid_id, tool_id=RUN_PLAN_TOOL,
                status="completed" if fault == "completed_without_plan" else "running",
                conversation_id=v["conversation"].json()["id"], summary="Internal confirmation rejection specimen",
                input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
                    "confirmed_actor_id": actor, "confirmed_at": timestamp}))
        with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(RunPlanIntegrityError):
            service.prepare(request, invocation_id=invalid_id, recorded_at=now.isoformat())
        assert count(v, Plan) == 0 and len(v["script_calls"]) == 1
        assert not archived
    monkeypatch.setattr(service.artifacts, "put", original_put)
    ident = uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id=RUN_PLAN_TOOL, status="running", conversation_id=v["conversation"].json()["id"],
            summary="Internal rollback specimen; public confirmation is tested separately",
            input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
                "confirmed_actor_id": v["owner"]["id"], "confirmed_at": datetime.now(timezone.utc).isoformat()}))
    original = EventOutboxRepository.append
    def fail_after_flush(self, event, *, session=None):
        result = original(self, event, session=session)
        if event.event_type == "quality.run_plan.prepared":
            assert session.scalar(select(Plan).where(Plan.invocation_id == ident)) is not None
            raise RuntimeError("explicit late RunPlan Outbox failure")
        return result
    monkeypatch.setattr(EventOutboxRepository, "append", fail_after_flush)
    with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(RuntimeError, match="late RunPlan"):
        service.prepare(request, invocation_id=ident, recorded_at=datetime.now(timezone.utc).isoformat())
    assert count(v, Plan) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.action == "quality.run_plan.prepared",
            AuditEventRecord.tool_invocation_id == ident)).all()
        assert not session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_type == "quality.run_plan.prepared",
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"])).all()
    monkeypatch.setattr(EventOutboxRepository, "append", original)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        metadata = service.prepare(request, invocation_id=ident, recorded_at=datetime.now(timezone.utc).isoformat())
        assert service.prepare(request, invocation_id=ident, recorded_at=datetime.now(timezone.utc).isoformat()) == metadata
    assert count(v, Plan) == 1 and len(v["script_calls"]) == 1
    artifacts = service.artifacts
    original_read = artifacts.read
    def corrupted(*args):
        value = original_read(*args)
        value["plan"]["proposal"]["scripts"][0]["assertions"][0]["oracle_digest"] = acceptance_digest("corrupted")
        return value
    monkeypatch.setattr(artifacts, "read", corrupted)
    failed = read(v, metadata["run_plan_id"])
    assert failed.status_code == 502 and "artifact" not in failed.json(), failed.text
    assert count(v, Plan) == 1 and len(v["script_calls"]) == 1
    monkeypatch.setattr(artifacts, "read", original_read)
    original_put = artifacts.put
    def withdraw_after_archive(*args):
        receipt = original_put(*args)
        withdrawal = {**script_review_request(v, draft),
            "expected_previous_revision_id": review["revision"]["revision_id"], "decision": "withdraw",
            "actions": None, "assertions": None, "reason": "Withdraw original review while new plan is archiving"}
        completed(submit_script_review(reviewer, withdrawal))
        return receipt
    monkeypatch.setattr(artifacts, "put", withdraw_after_archive)
    raced = submit(v, request.model_dump(mode="json"))
    assert raced.status_code == 200 and raced.json()["status"] == "failed", raced.text
    assert raced.json()["result"]["followup_reason"] == "run_plan_changed"
    assert count(v, Plan) == 1 and len(v["script_calls"]) == 1
    with session_scope() as session:
        assert len(session.scalars(select(AuditEventRecord).where(AuditEventRecord.action == "quality.run_plan.prepared",
            AuditEventRecord.tool_invocation_id.in_((ident, raced.json()["id"])))).all()) == 1
        assert len(session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_type == "quality.run_plan.prepared",
            SSEEventOutboxRecord.event_payload["correlation_id"].as_string() == v["project_id"])).all()) == 1
    historical = read(v, metadata["run_plan_id"])
    assert historical.status_code == 200 and historical.json()["current_use"]["inputs_current"] is False


@pytest.mark.parametrize("http_protocol", ["v1", "v2"])
def test_native_plan_locator_query_uses_private_source_bytes_and_keeps_history_readonly(native_scripts, monkeypatch, http_protocol):
    v = native_scripts
    if http_protocol == "v2": select_binding_scripts(v)
    _, _, _, selection = reviewed_plan_inputs(v)
    if http_protocol == "v2": selection = selection.model_copy(update={"policy_revision": "nasus.run-plan.v2"})
    prepared = completed(submit(v, preview(v, selection).json()["request"]))
    ident = prepared["result"]["object_refs"][0].split(":", 1)[1]
    saved = read(v, ident).json()
    plan = saved["artifact"]["plan"]
    application = app.state.container.run_plan_locators
    original_inspect, calls = application.inventory.inspect, []
    def inspected(*args, **kwargs):
        calls.append("inspect")
        return original_inspect(*args, **kwargs)
    monkeypatch.setattr(application.inventory, "inspect", inspected)
    query = {"project_id": v["project_id"], "run_plan_id": ident, "run_plan_artifact_hash": saved["metadata"]["artifact_hash"]}
    rejected = inspect_http_locators(v, ident, acceptance_digest("wrong-plan"))
    assert rejected.status_code == 502 and rejected.headers["cache-control"] == "private, no-store"
    assert not calls
    response = inspect_http_locators(v, ident, query["run_plan_artifact_hash"])
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    value = response.json()
    assert value["receipt"]["query"] == query
    assert value["report"]["source_pin"] == plan["source_pin"]
    assert value["report"]["summary"]["locator_count"] == sum(action["action"] == "request"
        for script in plan["proposal"]["scripts"] for action in script["actions"])
    assert value["receipt"]["execution_authorized"] is value["receipt"]["runtime_locators_verified"] is False
    assert value["receipt"]["passed_count"] == 0
    assert all(source["pin"]["source_revision_id"] in {pin["source_revision_id"]
        for pin in plan["selection"]["target_build"]["code_sources"]} for source in value["report"]["inventory"]["sources"])
    command = completed(invoke(v, RUN_PLAN_LOCATOR_QUERY_TOOL, query))
    assert command["result"]["run_plan_locators"] == value and len(calls) == 2
    with session_scope() as session:
        persisted = session.get(ToolInvocationRecord, command["id"])
        assert persisted.result_payload["run_plan_locators"] == value
    monkeypatch.setattr(application.inventory, "inspect", lambda *args, **kwargs: pytest.fail("history repeated static parsing"))
    historical = v["client"].get("/v1/tool-invocations/" + command["id"], headers=v["headers"])
    assert historical.status_code == 200 and historical.json()["result"]["run_plan_locators"] == value, historical.text
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(command["id"], v["project_id"]) == value["receipt"]
    assert len(v["script_calls"]) == 1 and len(calls) == 2 and count(v, Plan) == 1
    events = EventOutboxRepository().list_after(stream_kind="conversation", stream_id=command["conversation_id"],
        after_event_id=None, limit=1000)
    updates = [event for event in events if event.entity_id == command["id"]]
    assert updates and updates[-1].patch["status"] == "completed"
    for event in updates:
        assert event.payload["tool_invocation"]["input_payload"] == {} and event.payload["tool_invocation"]["result"] is None
        assert "snippet_hash" not in str(event.model_dump()) and "inventory_hash" not in str(event.model_dump())
    original_result = deepcopy(command["result"])
    damaged = deepcopy(original_result)
    damaged["run_plan_locators"]["report"]["locators"][0]["action_digest"] = acceptance_digest("rewritten-original-action")
    with session_scope() as session:
        session.get(ToolInvocationRecord, command["id"]).result_payload = damaged
    try:
        rejected = v["client"].get("/v1/tool-invocations/" + command["id"], headers=v["headers"])
        assert rejected.status_code == 502 and "snippet_hash" not in rejected.text, rejected.text
    finally:
        with session_scope() as session:
            session.get(ToolInvocationRecord, command["id"]).result_payload = original_result
    restrict_source(v)
    denied = v["client"].get("/v1/tool-invocations/" + command["id"], headers=v["member_headers"])
    assert denied.status_code == 403 and "inventory_hash" not in denied.text, denied.text
    direct = inspect_http_locators(v, ident, query["run_plan_artifact_hash"], headers=v["member_headers"])
    assert direct.status_code == 403 and direct.headers["cache-control"] == "private, no-store", direct.text


@pytest.mark.parametrize("http_protocol", ["v1", "v2"])
def test_fixed_exweb_run_plan_preserves_all_native_source_pins_and_declares_unverified_target(native_scripts, http_protocol, monkeypatch):
    v = native_scripts
    if http_protocol == "v2": select_binding_scripts(v)
    draft, review, _, selection = reviewed_plan_inputs(v)
    if http_protocol == "v2":
        selection = type(selection).model_validate({**selection.model_dump(mode="json"), "policy_revision": "nasus.run-plan.v2"})
    source_pin, member_count = verify_fixed_exweb_archive(v, draft["result"]["prepared"])
    response = preview(v, selection)
    assert response.status_code == 200, response.text
    command = completed(submit(v, response.json()["request"]))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    response = read(v, ident)
    assert response.status_code == 200, response.text
    result = response.json()
    plan = result["artifact"]["plan"]
    assert plan["schema"] == "nasus.run-plan." + http_protocol
    assert result["artifact"]["schema"] == "nasus.run-plan-artifact." + http_protocol
    assert plan["prepared"] == draft["result"]["prepared"] and plan["proposal"] == draft["result"]["proposal"]
    assert source_pin["source_revision_id"] in {item["source_revision_id"] for item in plan["selection"]["target_build"]["code_sources"]}
    assert plan["review_pin"]["authority_actor"] != draft["result"]["actor_id"]
    assert plan["executed_on_target_count"] == plan["passed_count"] == plan["automated_count"] == 0
    assert not plan["execution_authorized"] and not result["current_use"]["target_verified"]
    assert len(v["script_calls"]) == 1 and count(v, Plan) == 1
    assert read(v, ident).json() == result and len(v["script_calls"]) == 1
    locators = inspect_http_locators(v, ident, result["metadata"]["artifact_hash"])
    assert locators.status_code == 200, locators.text
    locator_value = locators.json()
    inventory = locator_value["report"]["inventory"]
    exweb = next(source for source in inventory["sources"] if source["pin"]["source_revision_id"] == source_pin["source_revision_id"])
    assert len(exweb["files"]) == 126 and {file["relative_path"] for file in exweb["files"]} == set(v["exweb_files"])
    assert all(file["source_file_hash"] == "sha256:" + hashlib.sha256(v["exweb_files"][file["relative_path"]]).hexdigest()
        for file in exweb["files"])
    observed = {(route["method"], route["route_path"]) for route in exweb["routes"] if route["status"] == "observed"}
    assert ("POST", "/api/v1/finance/chat/sessions") in observed
    assert ("GET", "/api/v1/finance/chat/sessions/{sessionId}") in observed
    assert exweb["routes"] and all(route["snippet_hash"].startswith("sha256:") for route in exweb["routes"])
    assert locator_value["report"]["source_pin"] == plan["source_pin"]
    assert locator_value["receipt"]["runtime_locators_verified"] is locator_value["receipt"]["execution_authorized"] is False
    assert not locator_value["receipt"]["business_coverage_verified"] and len(v["script_calls"]) == 1
    from apps.api.app.domain.quality_loop.http_locator_record import LOCATOR_RECORD_TOOL, LOCATOR_RECORD_QUERY_TOOL
    from apps.api.app.infrastructure.persistence.http_locator_models import HttpLocatorRecord
    locator_request = {"project_id": v["project_id"], "run_plan_id": ident,
        "run_plan_artifact_hash": result["metadata"]["artifact_hash"]}
    pending_locator = invoke(v, LOCATOR_RECORD_TOOL, locator_request, key=uuid4().hex)
    assert pending_locator.status_code == 200 and pending_locator.json()["status"] == "waiting_confirmation", pending_locator.text
    assert count(v, HttpLocatorRecord) == 0
    recorded_locator = completed(confirm(v, pending_locator.json()))
    recorded_receipt = recorded_locator["result"]["run_plan_locator_record"]
    assert recorded_receipt["metadata"]["durable_locator_evidence_verified"] is True
    assert recorded_receipt["metadata"]["report_hash"] == locator_value["report"]["report_hash"]
    assert recorded_receipt["metadata"]["summary"] == locator_value["report"]["summary"]
    assert count(v, HttpLocatorRecord) == 1 and len(v["script_calls"]) == 1
    service = app.state.container.http_locator_records
    monkeypatch.setattr(service.locators.inventory, "inspect", lambda *a, **k: pytest.fail("fixed exweb history re-parsed source"))
    historical = v["client"].get(f"/v1/projects/{v['project_id']}/quality/run-plan-locators/{recorded_receipt['metadata']['record_id']}", headers=v["headers"])
    assert historical.status_code == 200, historical.text
    assert historical.json()["archive"]["report"] == locator_value["report"]
    queried_locator = completed(invoke(v, LOCATOR_RECORD_QUERY_TOOL,
        {"project_id": v["project_id"], "record_id": recorded_receipt["metadata"]["record_id"]}))
    assert queried_locator["result"]["run_plan_locator_record"] == recorded_receipt
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(queried_locator["id"], v["project_id"]) == recorded_receipt
    assert not recorded_receipt["metadata"]["runtime_locators_verified"] and not recorded_receipt["metadata"]["business_coverage_verified"]
    report = os.getenv("EXWEB_RUN_PLAN_REPORT")
    if report:
        path = Path(report)
        if http_protocol == "v2": path = path.with_name(path.stem + "-v2" + path.suffix)
        with path.open("x") as output:
            json.dump({"schema": "nasus.exweb-run-plan-preparation-verification.v1",
                "repository": "https://github.com/kunben-duck/exweb.git", "commit": v["exweb_commit"], "tree_hash": v["exweb_tree_hash"],
                "exweb_source_pin": source_pin, "exweb_file_count": 126, "exweb_frozen_code_member_count": member_count,
                "all_126_archived_blobs_equal_fixed_git_tree": True, "postgres_private_minio": True,
                "run_plan": result["metadata"], "script_pin": plan["script_pin"], "review_pin": plan["review_pin"],
                "source_pin": plan["source_pin"], "case_count": len(plan["prepared"]["cases"]),
                "run_plan_policy": plan["schema"], "script_protocol": draft["result"]["request"].get("http_protocol", "nasus.runner-http-execution.v1"),
                "binding_action_count": sum(action["action"] == "capture_json" for script in plan["proposal"]["scripts"] for action in script["actions"]),
                "static_locator_receipt": locator_value["receipt"], "exweb_observed_route_count": len(observed),
                "independent_locator_record": recorded_receipt,
                "independent_locator_history_reverified_all_original_blobs_without_parsing": True,
                "exweb_locator_inventory_files": len(exweb["files"]),
                "exweb_all_locator_file_hashes_equal_original_git_blobs": True,
                "all_original_cases_steps_oracles_and_actions_preserved": True,
                "independent_reviewer_differs_from_generator": True,
                "target_verification": plan["target_verification"], "execution_authorized": False,
                "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0,
                "verified_scope": {"canonical_plan_preparation": True, "native_build_attestation": False,
                    "native_target_execution": False, "external_model": False, "business_gold": False,
                    "full_quality_closure": False, "unified_project_delta_dag": False}}, output, indent=2)
