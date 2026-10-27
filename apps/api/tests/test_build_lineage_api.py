import importlib
import json
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.main import app
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.system_image.structure_builds import StructureBuildInput
from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.build_lineage_repository import StructureBuildLineageRepository
from apps.api.app.infrastructure.persistence.build_lineage_models import StructureBuildLineageRecord
from apps.api.app.infrastructure.persistence.code_analysis_models import CodeAnalysisRecord
from apps.api.app.infrastructure.persistence.database import engine
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.structure_build_models import StructureBuildArtifactRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_investigation_api import investigation
from apps.api.tests.test_build_completion_api import completion, submit, report
from apps.api.tests.test_source_access_api import grant_member, policy
from apps.api.tests.test_structure_build_api import request as structure_request, submit as structure_submit, confirm
from apps.api.tests.test_code_index_lifecycle_api import install_native, generation
from apps.api.tests.test_code_graph_enrichment import _FixtureProcessRunner


def attested(v, **changes):
    return {**v["completion_input"], "analyses": [], "analysis_policy": "committed_build", **changes}


def original_lineage(v):
    with session_scope() as session:
        return session.scalars(select(StructureBuildLineageRecord).where(
            StructureBuildLineageRecord.project_id == v["project_id"],
            StructureBuildLineageRecord.image_revision_id == v["investigation_input"]["image_revision_id"])).one()


def corrupt(v, mutate):
    with session_scope() as session:
        session.execute(text("ALTER TABLE image_structure_build_lineages DISABLE TRIGGER USER"))
        try:
            row = session.get(StructureBuildLineageRecord, original_lineage(v).invocation_id)
            mutate(session, row)
            session.flush()
        finally:
            session.execute(text("ALTER TABLE image_structure_build_lineages ENABLE TRIGGER USER"))


def test_actual_build_output_is_discovered_not_selected_and_replay_is_private(completion):
    v = completion
    response = submit(v, attested(v), key="actual-code-build-lineage")
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    item = response.json()
    observed = report(v, item["id"])
    assert observed.status_code == 200, observed.text
    body = observed.json()
    assert body["schema"] == "nasus.image-build-completion.v2" and len(body["build_lineages"]) == 1
    lineage = original_lineage(v)
    assert body["build_lineages"][0] == {"lineage_hash": lineage.lineage_hash, **lineage.payload}
    assert all(analysis["build_lineage_verified"] for analysis in body["code_analyses"])
    assert "analysis_build_lineage_unverified" not in body["blockers"]
    assert not body["goal_completed"] and not body["publication_authorized"] and not body["execution_authorized"]
    assert submit(v, attested(v), key="actual-code-build-lineage").json()["id"] == item["id"]
    assert report(v, item["id"]).json() == body
    assert "build_lineages" not in json.dumps(item)
    for statement in (update(StructureBuildLineageRecord).values(lineage_hash="changed"), delete(StructureBuildLineageRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with session_scope() as session:
                session.execute(statement.where(StructureBuildLineageRecord.invocation_id == lineage.invocation_id))


def test_other_report_for_the_same_source_cannot_attest_this_build(completion):
    v = completion
    actual = original_lineage(v).payload["analyses"][0]
    with session_scope() as session:
        row = session.get(CodeAnalysisRecord, actual["analysis_id"])
        payload = {**row.payload, "algorithm": "independent-analysis.v1"}
        extra = CodeAnalysisRecord(analysis_id=str(uuid4()), project_id=row.project_id, binding_id=row.binding_id,
            source_revision_id=row.source_revision_id, report_hash=snapshot_digest(payload), payload=payload, recorded_at=row.recorded_at)
        session.add(extra)
        selected = {key: getattr(extra, key) for key in ("source_revision_id", "analysis_id", "report_hash")}
    item = submit(v, attested(v, analyses=[selected])).json()
    assert item["status"] == "failed" and item["result"].get("build_completion") is None
    # Discovery still returns the original output, not the additional report.
    item = submit(v, attested(v)).json()
    assert item["status"] == "completed", item
    assert report(v, item["id"]).json()["code_analyses"][0]["analysis_id"] == actual["analysis_id"]


@pytest.mark.parametrize("damage", ["missing", "hash", "scope", "projection", "analysis", "schema", "digest"])
def test_corrupt_build_lineage_is_rejected_without_repair(completion, damage):
    v = completion
    item = submit(v, attested(v)).json()
    assert item["status"] == "completed", item
    def mutate(session, row):
        if damage == "missing":
            session.delete(row)
            return
        payload = json.loads(json.dumps(row.payload))
        if damage == "scope":
            payload["plan_id"] = "foreign"
        elif damage == "projection":
            payload["analyses"][0]["merged_projection_hash"] = snapshot_digest("different projection")
        elif damage == "analysis":
            payload["analyses"][0]["analysis_id"] = "missing"
        elif damage == "schema":
            payload["analyses"][0]["private"] = "not-a-contract-field"
        elif damage == "digest":
            payload["analyses"][0]["observation_archive_hash"] = "malformed"
        row.payload = payload
        row.lineage_hash = "sha256:" + "0" * 64 if damage == "hash" else snapshot_digest(payload)
    corrupt(v, mutate)
    response = report(v, item["id"])
    assert response.status_code == 502 and "build_lineages" not in response.text, response.text
    assert submit(v, attested(v)).json()["result"].get("build_completion") is None


def test_missing_receipt_blocks_completed_structure_replay_without_provider_restart(completion, monkeypatch):
    v = completion
    lineage = original_lineage(v)
    payload = lineage.payload
    corrupt(v, lambda session, row: session.delete(row))
    def forbidden(*args, **kwargs):
        raise AssertionError("Completed replay must not repeat extraction or replace its lineage")
    monkeypatch.setattr(app.state.container.structure_builds.preparation, "prepare", forbidden)
    request = StructureBuildInput(**{key: payload[key] for key in StructureBuildInput.model_fields})
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(BuildPlanIntegrityError, match="lineage is missing"):
            app.state.container.structure_builds.read_completed(request, invocation_id=lineage.invocation_id)
    with session_scope() as session:
        assert session.get(StructureBuildLineageRecord, lineage.invocation_id) is None


def test_lineage_cannot_be_present_on_an_unmarked_legacy_structural_artifact(completion):
    v = completion
    item = submit(v, attested(v)).json()
    assert item["status"] == "completed", item
    lineage = original_lineage(v)
    with session_scope() as session:
        session.execute(text("ALTER TABLE image_structure_build_artifacts DISABLE TRIGGER USER"))
        try:
            session.get(StructureBuildArtifactRecord, lineage.invocation_id).lineage_required = False
            session.flush()
        finally:
            session.execute(text("ALTER TABLE image_structure_build_artifacts ENABLE TRIGGER USER"))
    response = report(v, item["id"])
    assert response.status_code == 502 and "build_lineages" not in response.text, response.text
    assert submit(v, attested(v)).json()["result"].get("build_completion") is None


def test_lineage_and_candidate_roll_back_with_the_structural_completion_event(evidence_api, monkeypatch):
    v = evidence_api
    invocation = structure_submit(v, structure_request(v))
    with session_scope() as session:
        before = session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(
            ImageRevisionRecord.project_id == v["project_id"]))
    original = StructureBuildLineageRepository.attach
    def abort_after_receipt(session, commit, candidate):
        original(session, commit, candidate)
        assert session.get(StructureBuildLineageRecord, invocation) is not None
        raise BuildPlanIntegrityError("private-lineage-transaction-failure")
    monkeypatch.setattr(StructureBuildLineageRepository, "attach", abort_after_receipt)
    result = confirm(v, invocation)
    assert result["status"] == "failed" and "private-lineage" not in str(result), result
    with session_scope() as session:
        assert session.get(StructureBuildLineageRecord, invocation) is None
        assert session.get(StructureBuildArtifactRecord, invocation) is None
        assert session.scalar(select(func.count()).select_from(ImageRevisionRecord).where(
            ImageRevisionRecord.project_id == v["project_id"])) == before
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.build.structure.completed",
            SSEEventOutboxRecord.event_payload["patch"]["invocation_id"].as_string() == invocation)) == 0


def test_lineage_discards_the_verified_archive_when_source_access_changes(completion, monkeypatch):
    v = completion
    item = submit(v, attested(v)).json()
    assert item["status"] == "completed", item
    grant_member(v)
    policy(v, (v["member"]["id"],))
    analysis = app.state.container.code_analysis
    original = analysis.verify_projection
    def revoke(*args, **kwargs):
        verified = original(*args, **kwargs)
        policy(v)
        return verified
    monkeypatch.setattr(analysis, "verify_projection", revoke)
    response = report(v, item["id"], v["member_headers"])
    assert response.status_code == 409 and "build_lineages" not in response.text, response.text


@pytest.mark.parametrize("outcome", ["consumed", "unused"])
def test_native_build_receipt_distinguishes_consumed_output_from_optional_failed_attempt(evidence_api, monkeypatch, tmp_path, outcome):
    from dataclasses import asdict
    from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryError
    v = evidence_api
    class OptionalUnavailable(_FixtureProcessRunner):
        def run(self, args, **kwargs):
            if len(args) > 2 and args[2] == "index_repository":
                raise CodebaseMemoryError("private-native-attempt-failed")
            return super().run(args, **kwargs)
    _, log = install_native(v, monkeypatch, tmp_path, OptionalUnavailable() if outcome == "unused" else None)
    if outcome == "unused":
        app.state.container.structure_builds.preparation.extraction._source_code_intelligence.composite.mode = "optional"
    request = structure_request(v)
    invocation = structure_submit(v, request)
    result = confirm(v, invocation)
    assert result["status"] == "completed", result
    pin = generation(invocation)
    with session_scope() as session:
        receipt = session.get(StructureBuildLineageRecord, invocation)
        analysis = receipt.payload["analyses"][0]
        image_id = receipt.image_revision_id
        assert len(receipt.payload["analyses"]) == 1
        if outcome == "consumed":
            assert analysis["native"]["generation"] == asdict(pin)
            assert analysis["unused_native_generations"] == []
        else:
            assert analysis["native"] is None
            assert analysis["unused_native_generations"] == [asdict(pin)]
    calls = log.read_text() if log.exists() else ""
    with actor_scope(UserProfile.model_validate(v["owner"])):
        completed = app.state.container.structure_builds.read_completed(
            StructureBuildInput(**request), invocation_id=invocation)
    assert completed.image_revision_id == image_id
    assert (log.read_text() if log.exists() else "") == calls


def test_actual_build_lineage_reads_the_complete_private_observation_archive(completion, monkeypatch):
    v = completion
    item = submit(v, attested(v)).json()
    assert item["status"] == "completed", item
    monkeypatch.setattr(app.state.container.code_analysis.observations, "read",
        lambda payload: (_ for _ in ()).throw(ValueError("private-observation-body-and-storage-credentials")))
    response = report(v, item["id"])
    assert response.status_code == 502 and "credentials" not in response.text and "build_lineages" not in response.text


@pytest.mark.parametrize("populated", [False, True])
def test_lineage_migration_never_invents_legacy_execution_and_protects_new_receipts(completion, monkeypatch, populated):
    v = completion
    actual = original_lineage(v)
    migration = importlib.import_module("apps.api.migrations.versions.0090_structure_build_lineage")
    assert engine.dialect.name == "postgresql" and engine.url.database.startswith("nasus_test_")
    schema = "lineage_migration_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            connection.execute(text("CREATE TABLE image_structure_build_artifacts (LIKE public.image_structure_build_artifacts INCLUDING ALL)"))
            connection.execute(text("ALTER TABLE image_structure_build_artifacts DROP COLUMN lineage_required"))
            columns = ", ".join(column.name for column in StructureBuildArtifactRecord.__table__.columns if column.name != "lineage_required")
            connection.execute(text(f"INSERT INTO image_structure_build_artifacts ({columns}) SELECT {columns} FROM public.image_structure_build_artifacts WHERE invocation_id = :id"), {"id": actual.invocation_id})
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert not connection.scalar(text("SELECT lineage_required FROM image_structure_build_artifacts"))
            assert connection.scalar(text("SELECT count(*) FROM image_structure_build_lineages")) == 0
            columns = {item["name"]: item for item in inspect(connection).get_columns("image_structure_build_lineages", schema=schema)}
            assert columns.keys() == set(StructureBuildLineageRecord.__table__.columns.keys())
            if populated:
                connection.execute(text("UPDATE image_structure_build_artifacts SET lineage_required = true"))
                connection.execute(text("INSERT INTO image_structure_build_lineages SELECT * FROM public.image_structure_build_lineages WHERE invocation_id = :id"), {"id": actual.invocation_id})
                with pytest.raises(RuntimeError, match="Cannot discard actual"):
                    migration.downgrade()
                assert connection.scalar(text("SELECT count(*) FROM image_structure_build_lineages")) == 1
            else:
                migration.downgrade()
                assert "lineage_required" not in {item["name"] for item in inspect(connection).get_columns("image_structure_build_artifacts", schema=schema)}
                migration.upgrade()
                assert connection.scalar(text("SELECT count(*) FROM image_structure_build_lineages")) == 0
        finally:
            transaction.rollback()
