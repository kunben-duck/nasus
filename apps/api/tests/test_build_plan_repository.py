from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from apps.api.app.domain.system_image.build_plan import BuildPlanIntegrityError, BuildBudgetProposal, propose_build_plan
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.app.infrastructure.persistence import build_plan_repository as module
from apps.api.app.infrastructure.persistence.build_plan_models import BuildPlanRecord, BuildPlanInvocationRecord
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord, ToolInvocationRecord, AgentGoalRecord
from apps.api.tests.test_image_revision_repository import image_repo, inputs
from apps.api.tests.test_code_entity_registry import registry, pg_repo


@pytest.fixture
def build_repo(image_repo, monkeypatch):
    _, snapshots, sessions = image_repo
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0039_image_build_plans.py"
    spec = importlib.util.spec_from_file_location("build_plan_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    work_spec = importlib.util.spec_from_file_location("structure_build_migration", path.with_name("0040_structure_build_artifacts.py"))
    work_migration = importlib.util.module_from_spec(work_spec)
    work_spec.loader.exec_module(work_migration)
    consent_spec = importlib.util.spec_from_file_location("build_authorization_migration", path.with_name("0041_build_authorizations.py"))
    consent_migration = importlib.util.module_from_spec(consent_spec)
    consent_spec.loader.exec_module(consent_migration)
    lineage_spec = importlib.util.spec_from_file_location("build_lineage_migration", path.with_name("0090_structure_build_lineage.py"))
    lineage_migration = importlib.util.module_from_spec(lineage_spec)
    lineage_spec.loader.exec_module(lineage_migration)
    with sessions.kw["bind"].begin() as conn:
        AgentGoalRecord.__table__.create(conn)
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        work_migration.op = Operations(MigrationContext.configure(conn))
        work_migration.upgrade()
        lineage_migration.op = Operations(MigrationContext.configure(conn))
        lineage_migration.upgrade()
        consent_migration.op = Operations(MigrationContext.configure(conn))
        consent_migration.upgrade()

    @contextmanager
    def scope():
        with sessions.begin() as session:
            yield session

    monkeypatch.setattr(module, "session_scope", scope)
    yield module.BuildPlanRepository(), snapshots, sessions
    with sessions.kw["bind"].begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        work_migration.op = Operations(MigrationContext.configure(conn))
        consent_migration.op = Operations(MigrationContext.configure(conn))
        lineage_migration.op = Operations(MigrationContext.configure(conn))
        consent_migration.downgrade()
        lineage_migration.downgrade()
        work_migration.downgrade()
        migration.downgrade()
        migration.upgrade()
        work_migration.upgrade()
        lineage_migration.upgrade()
        consent_migration.upgrade()
        assert conn.scalar(select(func.count()).select_from(BuildPlanRecord)) == 0
        consent_migration.downgrade()
        lineage_migration.downgrade()
        work_migration.downgrade()
        migration.downgrade()
        AgentGoalRecord.__table__.drop(conn)


def invocation(sessions, ident="inv", project="project", **changes):
    with sessions.begin() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id="system_image.build.plan", status="running", summary="plan",
            input_payload={"project_id": project, **changes}))


def proposal(registry):
    pinned, _ = inputs(registry)
    return propose_build_plan(pinned, objective="Private investigation goal", mode="initialize", purpose="structure",
                              budget=BuildBudgetProposal())


def save(repo, planned, ident="inv", guard=lambda: None):
    return repo.record(planned, actor_id="owner", invocation_id=ident, created_at="now", require_current_scope=guard)


def test_append_only_idempotent_plan_and_invocation_links_survive_source_changes(build_repo, registry):
    repo, snapshots, sessions = build_repo
    planned = proposal(registry)
    invocation(sessions)
    first = save(repo, planned)
    assert save(repo, planned) == first
    invocation(sessions, "retry")
    assert save(repo, planned, "retry") == first
    inputs(registry, seed="b")
    assert snapshots.latest_manifest("project").manifest_id != planned.intent.source_manifest_id
    assert repo.get("project", first.plan_id) == first
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord)) == 1
        assert session.scalar(select(func.count()).select_from(BuildPlanInvocationRecord)) == 2
        events = session.scalars(select(SSEEventOutboxRecord).where(SSEEventOutboxRecord.event_type == "system_image.build.plan.proposed")).all()
        assert len(events) == 2
        assert "Private investigation" not in str([e.event_payload for e in events])
    for statement in (update(BuildPlanRecord).values(state="draft"), delete(BuildPlanRecord), delete(BuildPlanInvocationRecord)):
        with pytest.raises(IntegrityError, match="append-only"):
            with sessions.begin() as session:
                session.execute(statement)
    with pytest.raises(KeyError):
        repo.get("other", first.plan_id)
    assert repo.list("project", binding_ids=frozenset(), after_id="", limit=1) == []


def test_authorization_change_rolls_back_plan_link_and_outbox(build_repo, registry):
    repo, _, sessions = build_repo
    planned = proposal(registry)
    invocation(sessions)

    def revoked():
        raise StaleSourceAccessScope("revoked")

    with pytest.raises(StaleSourceAccessScope):
        save(repo, planned, guard=revoked)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord)) == 0
        assert session.scalar(select(func.count()).select_from(BuildPlanInvocationRecord)) == 0
        assert session.scalar(select(func.count()).select_from(SSEEventOutboxRecord).where(
            SSEEventOutboxRecord.event_type == "system_image.build.plan.proposed")) == 0


def test_missing_foreign_invocation_or_reused_invocation_cannot_store_plan(build_repo, registry):
    repo, _, sessions = build_repo
    planned = proposal(registry)
    with pytest.raises(BuildPlanIntegrityError):
        save(repo, planned)
    invocation(sessions, "foreign", "other")
    with pytest.raises(BuildPlanIntegrityError):
        save(repo, planned, "foreign")
    invocation(sessions)
    save(repo, planned)
    with pytest.raises(BuildPlanIntegrityError):
        save(repo, replace(planned, intent=replace(planned.intent, objective="Changed")))


def test_concurrent_proposals_share_artifact_but_keep_both_invocations(build_repo, registry):
    repo, _, sessions = build_repo
    planned = proposal(registry)
    for ident in ("first", "second"):
        invocation(sessions, ident)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda ident: save(repo, planned, ident), ("first", "second")))
    assert results[0] == results[1]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord)) == 1
        assert session.scalar(select(func.count()).select_from(BuildPlanInvocationRecord)) == 2


def test_corrupt_record_fails_read_and_outbox_failure_rolls_back(build_repo, registry, monkeypatch):
    repo, _, sessions = build_repo
    planned = proposal(registry)
    invocation(sessions)
    first = save(repo, planned)
    with sessions.begin() as session:
        row = session.get(BuildPlanRecord, first.plan_id)
        session.add(BuildPlanRecord(plan_id="corrupt", project_id=row.project_id, manifest_id=row.manifest_id,
            plan_digest="wrong", payload=row.payload, created_at=row.created_at, created_by=row.created_by, state=row.state))
    with pytest.raises(BuildPlanIntegrityError):
        repo.get("project", "corrupt")

    def unavailable(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(module.EventOutboxRepository, "append", unavailable)
    invocation(sessions, "next")
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        save(repo, replace(planned, intent=replace(planned.intent, objective="Other")), "next")
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(BuildPlanRecord)) == 2
        assert session.get(BuildPlanInvocationRecord, "next") is None
