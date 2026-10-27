"""Real PG command/time fences with explicit source and target protocol specimens."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from apps.api.app.domain.quality_loop.run_plan_case_execution import CASE_EXECUTE_TOOL, RunPlanCaseExecutionInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, UserIdentityRecord
from apps.api.app.infrastructure.persistence.run_plan_case_execution_repository import PostgresRunPlanCaseExecutionRepository
from apps.api.app.infrastructure.persistence.run_plan_case_preparation_models import RunPlanCasePreparationRecord as Preparation
from apps.api.app.infrastructure.persistence.tool_claim_journal import ToolClaimJournal
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_run_plan_case_inputs import case_inputs, spec
from apps.api.tests.test_run_plan_fixture_handoff import fixture_inputs


def original_pg_command(v, *, age=0):
    ident = "pg-case-fence-" + uuid4().hex
    v.selection = v.selection.model_copy(update={"run_id": "pg-case-fence-run-" + uuid4().hex})
    request = v.selection.model_dump(mode="json")
    with session_scope() as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert session.scalar(text("SELECT current_database()")).startswith("nasus_test_")
        now = session.scalar(select(func.clock_timestamp())).isoformat()
        confirmed = session.scalar(text("SELECT clock_timestamp() - (:age * interval '1 second')"),
            {"age": age}).isoformat()
        if session.get(UserIdentityRecord, "admin") is None:
            session.add(UserIdentityRecord(user_id="admin", email="pg-case-fence-admin@example.invalid",
                display_name="Isolated case fence actor", role="platform_admin", status="active",
                password_hash="unusable-test-password", created_at=now, updated_at=now))
        session.add(ToolInvocationRecord(id=ident, tool_id=CASE_EXECUTE_TOOL, status="waiting_confirmation",
            summary="Original command fence protocol specimen", input_payload=deepcopy(request), revision=0))
    command = ConversationRepository(tool_claim_journal=ToolClaimJournal()).claim_tool_invocation_for_execution(
        ident, expected_statuses=("waiting_confirmation",), input_updates={"confirmed_by_user": True,
            "confirmed_actor_id": "admin", "confirmed_at": confirmed})
    assert command is not None and command.status == "running"
    v.service.commands = PostgresRunPlanCaseExecutionRepository()
    return ident


@pytest.mark.parametrize("fixture", ["case_inputs", "fixture_inputs"])
@pytest.mark.parametrize("fault", ["unchanged", "expired", "cancelled", "actor_revoked"])
def test_original_pg_command_is_rechecked_after_complete_input_verification(request, monkeypatch, fixture, fault):
    v = request.getfixturevalue(fixture)
    ident = original_pg_command(v, age=895 if fault == "expired" else 0)
    original_health = v.service.health.inspect

    def health(*args, **kwargs):
        value = original_health(*args, **kwargs)
        with session_scope() as session:
            if fault == "expired":
                # The actual server clock crosses the unchanged 15-minute limit.
                session.execute(text("SELECT pg_sleep(6)"))
            elif fault == "cancelled":
                session.get(ToolInvocationRecord, ident).status = "cancelled"
            elif fault == "actor_revoked":
                session.get(UserIdentityRecord, "admin").status = "disabled"
        return value

    monkeypatch.setattr(v.service.health, "inspect", health)
    try:
        if fault == "unchanged":
            prepared = v.service.prepare(v.selection, invocation_id=ident)
            assert prepared.scope.invocation_id == ident and prepared.scope.actor_id == "admin"
        else:
            with pytest.raises((RunPlanCaseExecutionInvalid, SourceAccessDenied, PermissionError)):
                v.service.prepare(v.selection, invocation_id=ident)
        assert v.state["health_reads"] == 1
        assert len(v.runner.commands) == v.state["initial_request_count"]
        with session_scope() as session:
            assert session.get(Preparation, ident) is not None
            assert session.scalar(text("SELECT count(*) FROM quality_run_plan_case_work WHERE invocation_id = :id"),
                {"id": ident}) == 0
            assert session.scalar(text("SELECT count(*) FROM quality_run_plan_case_claims WHERE work_id IN "
                "(SELECT work_id FROM quality_run_plan_case_work WHERE invocation_id = :id)"), {"id": ident}) == 0
    finally:
        if fault == "actor_revoked":
            with session_scope() as session:
                session.get(UserIdentityRecord, "admin").status = "active"
