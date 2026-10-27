"""Actual PG reauthorization races; source and target inputs remain protocol specimens."""
import pytest
from sqlalchemy import func, select

from apps.api.app.domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_run_plan_case_command_fence_postgres import original_pg_command, case_inputs, spec


@pytest.mark.parametrize("change", ["clock", "cancel", "remove", "change_project"])
def test_reader_returns_pg_clock_and_command_after_its_last_current_check(case_inputs, change):
    v = case_inputs
    ident = original_pg_command(v)
    checks = []

    def current():
        with session_scope() as session:
            if len(checks) == 1:
                command = session.get(ToolInvocationRecord, ident)
                if change == "cancel":
                    command.status = "cancelled"
                elif change == "remove":
                    # The journal's FK prohibits deletion of a prepared command.
                    # Inject disappearance in the lookup identity, not receipt repair.
                    command.id = "replacement-" + ident
                elif change == "change_project":
                    command.input_payload = {**command.input_payload, "project_id": "another-project"}
            checks.append(session.scalar(select(func.clock_timestamp())))

    if change == "remove":
        # A preparation protects its command with an FK, so use the unmarked
        # legacy read protocol explicitly rather than disabling database guards.
        with session_scope() as session:
            legacy = ToolInvocationRecord(id="legacy-" + ident, tool_id="quality.run_plan.execute_http",
                status="running", summary="Explicit legacy read race specimen",
                input_payload={**v.selection.model_dump(mode="json"), "confirmed_by_user": True,
                    "confirmed_actor_id": "admin", "confirmed_at":
                    session.scalar(select(func.clock_timestamp())).isoformat()}, revision=0)
            session.add(legacy)
            ident = legacy.id
    if change in {"remove", "change_project"}:
        with pytest.raises(RunPlanCaseExecutionInvalid):
            v.service.commands.original_command(v.selection.project_id, ident, actor_id="admin", require_current=current)
    else:
        original = v.service.commands.original_command(v.selection.project_id, ident, actor_id="admin", require_current=current)
        assert original["now"] >= checks[-1]
        assert original["command"]["status"] == ("cancelled" if change == "cancel" else "running")
    assert len(checks) == 2
