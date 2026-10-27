"""Canonical PG/MinIO binding; model and scheduler transport are explicit specimens."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import shutil
from unittest.mock import AsyncMock
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.quality_loop.run_plan_build_inputs import RunPlanBuildRequest
from apps.api.app.application.quality_loop.native_build_inputs import NativeBuildSelection
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan import RunPlanIntegrityError
from apps.api.app.domain.quality_loop.run_plan_build import RUN_PLAN_BUILD_TOOL, RUN_PLAN_BUILD_PREVIEW_TOOL, RUN_PLAN_BUILD_QUERY_TOOL
from apps.api.app.domain.shared.native_build_source import byte_digest
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import AuditEventRecord, SSEEventOutboxRecord, ToolInvocationRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.app.infrastructure.persistence.native_build_models import NativeBuildReservationRecord, NativeBuildResultRecord
from apps.api.app.infrastructure.persistence.run_plan_models import RunPlanRecord
from apps.api.app.infrastructure.persistence.run_plan_build_models import RunPlanBuildRecord as Binding, RunPlanBuildMemberRecord as Member
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.runner.configured_native_build import ConfiguredNativeBuild
from apps.api.tests.test_run_plans_api import (
    evidence_api, documents, publication, design_scope, generation_result, mapping, native_scripts,
    reviewed_plan_inputs, preview as preview_plan, submit as submit_plan, read as read_plan,
    script_review_request, submit_script_review,
)
from apps.api.tests.test_native_build_jobs_api import ProtocolBuilder
from apps.api.tests.test_semantic_evaluations_api import completed, invoke, confirm, count
from apps.api.tests.test_source_access_api import policy as restrict_source
from apps.api.tests.migration_rehearsal import foreign_key_inventory


@pytest.fixture
def base_evidence_api(tmp_path, monkeypatch, request):
    """One complete Maven code binding, rather than an unbuildable Orders-only source."""
    monkeypatch.setattr(app.state, "auth_config", replace(app.state.auth_config, mode="required", bearer_token=uuid4().hex))
    client = TestClient(app)
    def account():
        response = client.post("/v1/auth/register", json={"email": f"build-binding-{uuid4().hex}@example.com",
            "name": "Build binding reviewer", "password": "evidence-test-password-123"})
        assert response.status_code == 200, response.text
        body = response.json()
        return body["user"], {"Authorization": "Bearer " + body["access_token"]}
    owner, headers = account()
    member, member_headers = account()
    response = client.post("/v1/projects", headers=headers, json={"name": "Build binding " + uuid4().hex})
    assert response.status_code == 200, response.text
    project_id = response.json()["id"]
    conversation = client.post("/v1/conversations", headers=headers,
        json={"space_type": "project", "space_id": project_id, "title": "Original build/source binding"})
    assert conversation.status_code == 200, conversation.text
    def invoke_source(tool, payload=None):
        result = client.post("/v1/tool-invocations", headers=headers, json={"conversation_id": conversation.json()["id"],
            "tool_id": tool, "input": {"project_id": project_id, **(payload or {})}})
        assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    code_root = tmp_path / "fixed-code"
    code_root.mkdir()
    real = request.node.name in {
        "test_fixed_exweb_original_native_build_is_bound_without_target_execution",
        "test_fixed_exweb_native_environment_record_uses_original_build_and_live_inventory",
        "test_fixed_exweb_public_v3_original_setup_handoff_uses_pg_minio_and_temporal",
        "test_fixed_exweb_environment_parent_read_preserves_all_original_archives",
        "test_fixed_exweb_grant_input_reads_preserve_complete_originals_and_independent_live_checks",
        "test_fixed_exweb_journal_scope_reuses_complete_verified_environment_parent",
        "test_fixed_exweb_journal_operation_reuses_immutable_proof_without_skipping_original_reads",
    }
    exweb = {}
    if real:
        if os.environ.get("EXWEB_EXECUTE_REVIEWED_NATIVE_BUILD") != "1":
            pytest.skip("explicit reviewed offline exweb build required")
        from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
        root = os.environ["EXWEB_SOURCE_REFRESH_GIT_ROOT"]
        files, tree_hash, _ = read_git_tree(Path(root), AFTER)
        assert len(files) == 126
        for name, body in files:
            target = code_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        exweb = {"exweb_commit": AFTER, "exweb_tree_hash": tree_hash, "exweb_files": dict(files)}
    else:
        (code_root / "pom.xml").write_text("<project>Binding protocol only, not a native Maven build.</project>")
        (code_root / "orders.py").write_text("class Orders:\n    def submit(self):\n        return 'original'\n")
    code_roots = [code_root]
    if request.node.name == "test_binding_requires_every_original_code_source":
        second = tmp_path / "second-fixed-code"
        second.mkdir()
        (second / "pom.xml").write_text("<project>Second binding protocol only.</project>")
        (second / "payments.py").write_text("class Payments:\n    def settle(self):\n        return 'second-original'\n")
        code_roots.append(second)
    # Historical requirement fixtures live outside the captured code root.
    path = tmp_path / "document-fixture-anchor"
    invoke_source("system_image.sources.register", {"source_specs": [{"source_type": "code", "source_uri": str(root)} for root in code_roots]})
    invoke_source("system_image.sources.ingest")
    invoke_source("system_image.context.materialize")
    image = client.get(f"/v1/projects/{project_id}/system-image", headers=headers).json()
    obj = next(item for item in image["objects"] if item.get("code_reference"))
    revision = obj["code_reference"]["source_revision_id"]
    url = f"/v1/projects/{project_id}/system-image/evidence"
    params = {"source_revision_id": revision, "object_id": obj["id"], "entity_revision_id": obj["code_reference"]["entity_revision_id"]}
    listed = client.get(url, headers=headers, params=params)
    assert listed.status_code == 200 and listed.json(), listed.text
    return {"client": client, "headers": headers, "member_headers": member_headers, "owner": owner, "member": member,
        "project_id": project_id, "conversation": conversation, "invoke": invoke_source, "path": path, "code_root": code_root,
        "evidence": listed.json()[0], "revision": revision, "real_build": real, "code_roots": code_roots, **exweb}


def prepared_binding(v, monkeypatch, *, environment=None, fixture_recipe=None, policy_revision=None):
    draft, review, reviewer, plan_selection = reviewed_plan_inputs(v)
    if policy_revision is not None:
        plan_selection = type(plan_selection).model_validate({**plan_selection.model_dump(mode="json"),
            "policy_revision": policy_revision})
    if fixture_recipe is not None:
        declarations = [item.model_dump(mode="json") for item in plan_selection.fixtures]
        assert declarations
        manifests = [fixture_recipe(declaration) for declaration in declarations]
        for declaration, manifest in zip(declarations, manifests):
            declaration["data_manifest_hash"] = acceptance_digest(manifest)
        plan_selection = type(plan_selection).model_validate({**plan_selection.model_dump(mode="json"), "fixtures": declarations})
        v["fixture_manifests"] = manifests
        v["fixture_manifest"] = manifests[0]
    sources = plan_selection.target_build.code_sources
    assert len(sources) == len(v["code_roots"])
    service, jobs = app.state.container.native_builds, app.state.container.native_build_jobs
    if v["real_build"]:
        monkeypatch.setenv("NASUS_NATIVE_BUILD_IMAGE_ID", os.environ["EXWEB_NATIVE_MAVEN_IMAGE_ID"])
        monkeypatch.setenv("NASUS_NATIVE_BUILD_MAVEN_CACHE", os.environ["EXWEB_NATIVE_MAVEN_CACHE"])
        builder = ConfiguredNativeBuild()
    else:
        builder = ProtocolBuilder()
    monkeypatch.setattr(service, "builder", builder)
    monkeypatch.setattr(jobs, "workflow", AsyncMock())
    pin = draft["result"]["prepared"]["context_pin"]
    path = "target/FinanceEXChatService-1.0.0-RELEASE.jar" if v["real_build"] else "target/app.jar"
    # Only this test's owned exported checkout is removed; builds use MinIO bytes.
    for root in v["code_roots"]:
        shutil.rmtree(root)
    originals = []
    for source in sources:
        selection = {"project_id": v["project_id"], "image_revision_id": pin["image_revision_id"],
            "image_artifact_hash": pin["image_artifact_hash"], "binding_id": source.binding_id,
            "source_revision_id": source.source_revision_id, "artifact_path": path}
        with actor_scope(UserProfile.model_validate(v["owner"])):
            preview = service.preview(NativeBuildSelection.model_validate(selection))
        pending = invoke(v, "quality.native_build.prepare", preview["request"], key=uuid4().hex)
        assert pending.status_code == 200 and pending.json()["status"] == "waiting_confirmation", pending.text
        queued = confirm(v, pending.json())
        assert queued.status_code == 200 and queued.json()["status"] == "running", queued.text
        assert asyncio.run(jobs.run(pending.json()["id"])) == "completed"
        with actor_scope(UserProfile.model_validate(v["owner"])):
            originals.append(service.read(v["project_id"], pending.json()["id"]))
    built = originals[0]
    receipt, meta = built["receipt"], built["metadata"]
    target = plan_selection.target_build.model_dump(mode="json")
    target.update(artifact_name=Path(path).name, artifact_hash=receipt["artifact"]["content_hash"],
        build_definition_hash=next(item["content_hash"] for item in receipt["source"]["files"] if item["path"] == "pom.xml"))
    plan_selection = plan_selection.model_copy(update={"target_build": plan_selection.target_build.model_validate(target)})
    if callable(environment):
        environment = environment(built)
    if environment is not None:
        plan_selection = plan_selection.model_copy(update={"environment": plan_selection.environment.model_validate(environment)})
    planned = preview_plan(v, plan_selection)
    assert planned.status_code == 200, planned.text
    command = completed(submit_plan(v, planned.json()["request"]))
    plan_id = command["result"]["object_refs"][0].split(":", 1)[1]
    plan = read_plan(v, plan_id).json()
    request = {"project_id": v["project_id"], "run_plan_id": plan_id, "run_plan_artifact_hash": plan["metadata"]["artifact_hash"],
        "native_builds": [{key: original["metadata"][key] for key in ("invocation_id", "build_id", "artifact_hash", "receipt_digest")}
            for original in originals],
        "target_build_invocation_id": meta["invocation_id"], "reason": "Independently bind original output; no target execution"}
    preview = v["client"].post(f"/v1/projects/{v['project_id']}/quality/run-plan-build-previews", headers=v["headers"], json=request)
    assert preview.status_code == 200 and preview.headers["cache-control"] == "private, no-store", preview.text
    v.update(binding_selection=request, binding_preview=preview.json(), original_plan=plan, original_build=built, original_builds=originals,
        reviewed_draft=draft, original_review=review, reviewer=reviewer, native_builder=builder)
    return v


def submit_binding(v, request=None, *, key=None):
    pending = invoke(v, RUN_PLAN_BUILD_TOOL, request or v["binding_preview"]["request"], key=key or uuid4().hex)
    assert pending.status_code == 200, pending.text
    return confirm(v, pending.json()) if pending.json()["status"] == "waiting_confirmation" else pending


def read_binding(v, ident, *, headers=None):
    return v["client"].get(f"/v1/projects/{v['project_id']}/quality/run-plan-builds/{ident}", headers=headers or v["headers"])


def verify_populated_parent_upgrade(v):
    migration = importlib.import_module("apps.api.migrations.versions.0103_run_plan_build_bindings")
    predecessors = [importlib.import_module("apps.api.migrations.versions." + name) for name in
        ("0101_run_plans", "0102_native_builds")]
    parents = (RunPlanRecord, NativeBuildReservationRecord, NativeBuildResultRecord)
    assert engine.url.database.startswith("nasus_test_")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            foreign_keys = foreign_key_inventory(connection)
            before = [connection.execute(select(model.__table__).where(model.project_id == v["project_id"])).mappings().all()
                for model in parents]
            assert all(len(rows) == 1 for rows in before)
            namespace = "nasus_test_build_binding_" + uuid4().hex
            connection.execute(text(f'CREATE SCHEMA "{namespace}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
            with Operations.context(MigrationContext.configure(connection)):
                # Actual predecessor DDL/FKs, not reduced parent stand-ins. Existing
                # source/command ancestry stays in public and is never removed.
                for predecessor in predecessors:
                    predecessor.upgrade()
                for model in parents:
                    table = model.__tablename__
                    connection.execute(text(f'INSERT INTO "{namespace}"."{table}" '
                        f'SELECT * FROM public."{table}" WHERE project_id = :project'), {"project": v["project_id"]})
                copied = [connection.execute(select(model.__table__).where(model.project_id == v["project_id"])).mappings().all()
                    for model in parents]
                assert before == copied
                migration.upgrade()
                isolated_keys = foreign_key_inventory(connection, schema=namespace)
                migration.downgrade()
                assert not inspect(connection).has_table(Binding.__tablename__, schema=namespace)
                assert not inspect(connection).has_table(Member.__tablename__, schema=namespace)
                migration.upgrade()
                assert foreign_key_inventory(connection, schema=namespace) == isolated_keys
            after = [connection.execute(select(model.__table__).where(model.project_id == v["project_id"])).mappings().all()
                for model in parents]
            assert before == after
            for model, name in ((RunPlanRecord, "uq_run_plan_build_parent"),
                    (NativeBuildReservationRecord, "uq_native_build_binding_source"),
                    (NativeBuildResultRecord, "uq_native_build_binding_parent")):
                assert name in {item["name"] for item in inspect(connection).get_unique_constraints(model.__tablename__, schema=namespace)}
        finally:
            transaction.rollback()
        assert foreign_key_inventory(connection) == foreign_keys
        assert namespace not in inspect(connection).get_schema_names()
    assert read_plan(v, v["original_plan"]["metadata"]["run_plan_id"]).json() == v["original_plan"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.native_builds.read(v["project_id"], v["original_build"]["invocation_id"]) == v["original_build"]


def test_canonical_binding_exact_fk_archive_history_withdrawal_and_acl(native_scripts, monkeypatch):
    v = prepared_binding(native_scripts, monkeypatch)
    build_url = f"/v1/projects/{v['project_id']}/quality/native-builds/{v['original_build']['invocation_id']}"
    native = v["client"].get(build_url, headers=v["headers"])
    assert native.status_code == 200 and native.headers["cache-control"] == "private, no-store", native.text
    assert native.json() == v["original_build"]
    assert "s3://" not in native.text
    assert count(v, Binding) == count(v, Member) == 0 and len(v["native_builder"].calls) == 1
    verify_populated_parent_upgrade(v)
    observation = completed(invoke(v, RUN_PLAN_BUILD_PREVIEW_TOOL, v["binding_selection"]))
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(observation["id"], v["project_id"]) == v["binding_preview"]
    changed = deepcopy(v["binding_preview"]["request"])
    changed["reason"] = "Changed after the independently previewed binding"
    rejected = submit_binding(v, changed)
    assert rejected.json()["status"] == "failed" and count(v, Binding) == 0
    key = uuid4().hex
    command = completed(submit_binding(v, key=key))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    response = read_binding(v, ident)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store", response.text
    original = response.json()
    # Populated public history must not make an empty-schema rehearsal destructive
    # or test-order-dependent, including history from this very same project.
    verify_populated_parent_upgrade(v)
    assert read_binding(v, ident).json() == original
    assert original["current_use"]["native_build_source_attested"] is True
    assert original["current_use"]["environment_verified"] is original["current_use"]["fixtures_verified"] is False
    assert original["artifact"]["binding"]["passed_count"] == original["artifact"]["binding"]["executed_on_target_count"] == 0
    assert read_plan(v, v["original_plan"]["metadata"]["run_plan_id"]).json() == v["original_plan"]
    assert count(v, Binding) == count(v, Member) == 1 and len(v["native_builder"].calls) == 1
    query = completed(invoke(v, RUN_PLAN_BUILD_QUERY_TOOL, {"project_id": v["project_id"], "binding_id": ident}))
    assert "s3://" not in json.dumps(query) and "pom.xml" not in json.dumps(query) and "receipt" not in query["result"]["run_plan_build"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert app.state.container.tool_evidence.describe(query["id"], v["project_id"]) == query["result"]["run_plan_build"]
    with session_scope() as session:
        row = session.get(Binding, ident)
        assert row.artifact_ref.startswith("s3://")
        assert len(session.scalars(select(AuditEventRecord).where(AuditEventRecord.entity_id == ident)).all()) == 1
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_type == "quality.run_plan.build_bound", SSEEventOutboxRecord.entity_id == ident)).all()
        assert len(events) == 1
        for model in (Binding, Member):
            actual = inspect(session.connection())
            assert {item["name"] for item in actual.get_columns(model.__tablename__)} == {column.name for column in model.__table__.columns}
            actual_fks = {(tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"])) for fk in actual.get_foreign_keys(model.__tablename__)}
            expected_fks = {(tuple(e.parent.name for e in fk.elements), fk.referred_table.name, tuple(e.column.name for e in fk.elements)) for fk in model.__table__.foreign_key_constraints}
            assert actual_fks == expected_fks
        context = MigrationContext.configure(session.connection())
        migration = importlib.import_module("apps.api.migrations.versions.0103_run_plan_build_bindings")
        with Operations.context(context), pytest.raises(RuntimeError, match="populated RunPlan build binding"):
            migration.downgrade()
    for statement in (update(Binding).where(Binding.binding_id == ident).values(target_artifact_hash=byte_digest(b"wrong")),
            delete(Binding).where(Binding.binding_id == ident), delete(Member).where(Member.binding_id == ident)):
        with pytest.raises(IntegrityError), session_scope() as session: session.execute(statement)
    for model, fields in ((Binding, {"run_plan_artifact_hash": byte_digest(b"wrong plan")}),
            (Member, {"archive_hash": byte_digest(b"wrong archive")}), (Member, {"source_revision_id": "wrong-source"})):
        with pytest.raises(IntegrityError) as rejected_fk, engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {model.__tablename__} DISABLE TRIGGER USER"))
            connection.execute(update(model).where(model.binding_id == ident).values(**fields))
        assert rejected_fk.value.orig.sqlstate == "23503"
    withdraw = {**script_review_request(v, v["reviewed_draft"]), "expected_previous_revision_id": v["original_review"]["revision"]["revision_id"],
        "decision": "withdraw", "actions": None, "assertions": None, "reason": "Independent withdrawal after original build attestation"}
    completed(submit_script_review(v["reviewer"], withdraw))
    historical = read_binding(v, ident)
    assert historical.status_code == 200 and historical.json()["artifact"] == original["artifact"], historical.text
    assert historical.json()["current_use"]["inputs_current"] is False
    assert v["client"].post(f"/v1/projects/{v['project_id']}/quality/run-plan-build-previews", headers=v["headers"], json=v["binding_selection"]).status_code == 409
    assert completed(submit_binding(v, key=key))["id"] == command["id"] and count(v, Binding) == 1
    assert read_binding(v, ident, headers=v["member_headers"]).status_code == 200
    restrict_source(v)
    denied = read_binding(v, ident, headers=v["member_headers"])
    assert denied.status_code == 403 and "artifact" not in denied.json()
    native_denied = v["client"].get(build_url, headers=v["member_headers"])
    assert native_denied.status_code == 403 and "receipt" not in native_denied.json()
    for receipt_id in (command["id"], observation["id"], query["id"]):
        receipt_denied = v["client"].get(f"/v1/tool-invocations/{receipt_id}", headers=v["member_headers"])
        assert receipt_denied.status_code == 403 and "input_payload" not in receipt_denied.json()
    assert read_binding(v, ident).status_code == 200 and len(v["native_builder"].calls) == 1


def test_binding_expired_confirmation_and_outbox_failure_leave_no_fact(native_scripts, monkeypatch):
    v = prepared_binding(native_scripts, monkeypatch)
    service = app.state.container.run_plan_builds
    request = RunPlanBuildRequest.model_validate(v["binding_preview"]["request"])
    original_put = service.artifacts.put
    archived = []
    def tracked_put(*args): archived.append(1); return original_put(*args)
    monkeypatch.setattr(service.artifacts, "put", tracked_put)
    for fault in ("expired", "future", "missing_time", "naive_time", "wrong_actor", "already_terminal"):
        ident = uuid4().hex
        now = datetime.now(timezone.utc)
        confirmed = now + timedelta(seconds=-901 if fault == "expired" else 60 if fault == "future" else 0)
        timestamp = "" if fault == "missing_time" else confirmed.replace(tzinfo=None).isoformat() if fault == "naive_time" else confirmed.isoformat()
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=ident, tool_id=RUN_PLAN_BUILD_TOOL, status="completed" if fault == "already_terminal" else "running",
                conversation_id=v["conversation"].json()["id"], summary="Expired binding confirmation specimen",
                input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
                    "confirmed_actor_id": v["member"]["id"] if fault == "wrong_actor" else v["owner"]["id"], "confirmed_at": timestamp}))
        with actor_scope(UserProfile.model_validate(v["owner"])), pytest.raises(RunPlanIntegrityError):
            service.bind(request, invocation_id=ident, recorded_at=datetime.now(timezone.utc).isoformat())
    assert not archived and count(v, Binding) == 0
    original_append = EventOutboxRepository.append
    def fail(self, event, **kwargs):
        if event.event_type == "quality.run_plan.build_bound": raise RuntimeError("Late outbox protocol fault")
        return original_append(self, event, **kwargs)
    monkeypatch.setattr(EventOutboxRepository, "append", fail)
    failed = submit_binding(v)
    assert failed.status_code == 200 and failed.json()["status"] == "failed", failed.text
    assert count(v, Binding) == count(v, Member) == 0 and archived == [1]
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.action == "quality.run_plan.build_bound",
            AuditEventRecord.conversation_id == v["conversation"].json()["id"])).all()
    monkeypatch.setattr(EventOutboxRepository, "append", original_append)
    completed(submit_binding(v))
    assert count(v, Binding) == count(v, Member) == 1 and len(v["native_builder"].calls) == 1


def test_binding_late_review_withdrawal_rolls_back_without_rebuilding(native_scripts, monkeypatch):
    v = prepared_binding(native_scripts, monkeypatch)
    artifacts = app.state.container.run_plan_builds.artifacts
    original_put = artifacts.put
    archived = []
    def withdraw_after_archive(*args):
        result = original_put(*args)
        archived.append(result)
        withdrawal = {**script_review_request(v, v["reviewed_draft"]),
            "expected_previous_revision_id": v["original_review"]["revision"]["revision_id"],
            "decision": "withdraw", "actions": None, "assertions": None, "reason": "Withdraw while independent binding is archived"}
        completed(submit_script_review(v["reviewer"], withdrawal))
        return result
    monkeypatch.setattr(artifacts, "put", withdraw_after_archive)
    response = submit_binding(v)
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    assert len(archived) == 1 and count(v, Binding) == count(v, Member) == 0
    with session_scope() as session:
        assert not session.scalars(select(AuditEventRecord).where(AuditEventRecord.action == "quality.run_plan.build_bound",
            AuditEventRecord.conversation_id == v["conversation"].json()["id"])).all()
    original = read_plan(v, v["original_plan"]["metadata"]["run_plan_id"]).json()
    assert original["artifact"] == v["original_plan"]["artifact"] and original["current_use"]["inputs_current"] is False
    assert len(v["native_builder"].calls) == len(v["script_calls"]) == 1


def test_binding_corrupt_original_build_blocks_private_binding_read_and_observation(native_scripts, monkeypatch):
    v = prepared_binding(native_scripts, monkeypatch)
    command = completed(submit_binding(v))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    query = completed(invoke(v, RUN_PLAN_BUILD_QUERY_TOOL, {"project_id": v["project_id"], "binding_id": ident}))
    artifacts = app.state.container.native_builds.artifacts
    original_read = artifacts.read
    def corrupted(*args, **kwargs):
        value = original_read(*args, **kwargs)
        value["receipt"]["artifact"]["content_hash"] = byte_digest(b"corrupt original jar")
        return value
    monkeypatch.setattr(artifacts, "read", corrupted)
    reads = []
    binding_artifacts = app.state.container.run_plan_builds.artifacts
    original_binding_read = binding_artifacts.read
    def tracked(*args): reads.append(1); return original_binding_read(*args)
    monkeypatch.setattr(binding_artifacts, "read", tracked)
    response = read_binding(v, ident)
    assert response.status_code == 502 and "artifact" not in response.json() and "s3://" not in response.text, response.text
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(RunPlanIntegrityError):
            app.state.container.run_plan_builds.read(v["project_id"], ident)
        with pytest.raises(PlatformApplicationError) as rejected_receipt:
            app.state.container.tool_evidence.describe(query["id"], v["project_id"])
        assert rejected_receipt.value.code == "run_plan_receipt_integrity_failed"
        assert rejected_receipt.value.status_code == 502
    assert not reads and count(v, Binding) == count(v, Member) == 1
    assert len(v["native_builder"].calls) == 1


def test_binding_requires_every_original_code_source(native_scripts, monkeypatch):
    v = prepared_binding(native_scripts, monkeypatch)
    assert v["binding_preview"]["code_source_count"] == len(v["native_builder"].calls) == 2
    assert all(not root.exists() for root in v["code_roots"])
    missing = deepcopy(v["binding_selection"])
    missing["native_builds"] = missing["native_builds"][:1]
    url = f"/v1/projects/{v['project_id']}/quality/run-plan-build-previews"
    response = v["client"].post(url, headers=v["headers"], json=missing)
    assert response.status_code == 409, response.text
    forged = {**missing, **{key: v["binding_preview"]["request"][key] for key in ("binding_digest", "source_scope_digest")}}
    writes, put = [], app.state.container.run_plan_builds.artifacts.put
    def tracked(*args): writes.append(1); return put(*args)
    monkeypatch.setattr(app.state.container.run_plan_builds.artifacts, "put", tracked)
    rejected = submit_binding(v, forged)
    assert rejected.status_code == 502, rejected.text
    error = rejected.json()
    assert error["error"]["code"] == "run_plan_receipt_integrity_failed", error
    assert isinstance(error["request_id"], str) and error["request_id"]
    assert "result" not in error and "input_payload" not in error and "s3://" not in rejected.text
    assert not writes and count(v, Binding) == count(v, Member) == 0
    command = completed(submit_binding(v))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    result = read_binding(v, ident)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["metadata"]["code_source_count"] == len(value["artifact"]["binding"]["builds"]) == 2
    expected = {item["receipt"]["source"]["pin"]["binding_id"]: item["metadata"]["invocation_id"] for item in v["original_builds"]}
    with session_scope() as session:
        rows = session.scalars(select(Member).where(Member.binding_id == ident)).all()
        assert {row.source_binding_id: row.native_invocation_id for row in rows} == expected
    assert writes == [1] and len(v["native_builder"].calls) == 2
    assert value["current_use"]["execution_authorized"] is False
    assert read_plan(v, v["original_plan"]["metadata"]["run_plan_id"]).json() == v["original_plan"]


def test_fixed_exweb_original_native_build_is_bound_without_target_execution(native_scripts, monkeypatch):
    v = prepared_binding(native_scripts, monkeypatch)
    completed_command = completed(submit_binding(v))
    ident = completed_command["result"]["object_refs"][0].split(":", 1)[1]
    view = read_binding(v, ident)
    assert view.status_code == 200, view.text
    value, receipt = view.json(), v["original_build"]["receipt"]
    assert len(receipt["source"]["files"]) == len(v["exweb_files"]) == 126
    for item in receipt["source"]["files"]:
        assert item["content_hash"] == byte_digest(v["exweb_files"][item["path"]])
    assert value["artifact"]["binding"]["target_artifact_hash"] == receipt["artifact"]["content_hash"]
    assert value["artifact"]["binding"]["native_build_source_attested"] is True
    assert value["current_use"]["execution_authorized"] is False and value["current_use"]["environment_verified"] is False
    assert not v["code_root"].exists()
    report = {"commit": v["exweb_commit"], "git_tree_hash": v["exweb_tree_hash"], "source_file_count": 126,
        "native_build_invocation_id": v["original_build"]["invocation_id"], "binding_id": ident,
        "run_plan_id": value["metadata"]["run_plan_id"], "binding_digest": value["metadata"]["binding_digest"],
        "target_artifact": receipt["artifact"], "toolchain": receipt["toolchain"], "canonical_confirmation_verified": True,
        "postgres_binding_and_members_verified": count(v, Binding) == count(v, Member) == 1,
        "original_minio_build_revalidated": True, "original_plan_unchanged": read_plan(v, v["original_plan"]["metadata"]["run_plan_id"]).json() == v["original_plan"],
        "model_transport_specimen": True, "scheduler_transport_specimen": True, "business_oracles_are_protocol_specimens": True,
        "external_model_called": False, "target_execution_verified": False, "execution_authorized": False,
        "environment_verified": False, "fixtures_verified": False, "reproducible_build_verified": False, "full_quality_closure_verified": False}
    destination = os.environ.get("EXWEB_RUN_PLAN_BUILD_REPORT")
    if destination:
        with Path(destination).open("x") as stream: json.dump(report, stream, indent=2)
