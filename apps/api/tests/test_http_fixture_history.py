"""Pure application/SQL transport specimens, not PG, Temporal or target evidence."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from apps.api.app.application.platform.http_fixture_job_receipts import HttpFixtureJobReceiptAccess
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.tool_handlers.http_fixture_jobs import HttpFixtureJobToolHandler
from apps.api.app.application.platform.tool_models import ToolInvocation, ToolResult
from apps.api.app.application.quality_loop.http_fixture_history import (
    HttpFixtureHistoryQuery, HttpFixtureHistoryTarget, HttpFixtureHistoryPage, HttpFixtureHistoryItem,
)
from apps.api.app.application.quality_loop.http_fixture_jobs import HttpFixtureJobApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_command import FIXTURE_COMMAND_TOOL, FIXTURE_CANCEL_TOOL, FIXTURE_JOB_TOOLS
from apps.api.app.domain.quality_loop.http_fixture_grant import GRANT_TOOL
from apps.api.app.domain.quality_loop.http_fixture_history import FIXTURE_HISTORY_LIST_TOOL, FIXTURE_HISTORY_READ_TOOL, HttpFixtureHistoryUnavailable
from apps.api.app.domain.quality_loop.http_fixtures import HttpFixtureInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence.http_fixture_history_repository import HttpFixtureHistoryRepository
from apps.api.tests.test_http_fixture_execution import selection
from apps.api.tests.test_http_fixture_native_grants import native_grant, spec


@pytest.fixture
def history_specimen(native_grant, monkeypatch):
    v = native_grant
    scope = v.service.authorization.scope(v.request.project_id)
    scope.binding_ids = frozenset({"code-source", "document-source"})
    chosen = selection(v)
    parent = {"recipe_id": v.request.recipe_id, "recipe_artifact_hash": v.request.recipe_artifact_hash}
    def command(ident, tool, payload, status="waiting_confirmation"):
        return {"id": ident, "tool_id": tool, "status": status, "input_payload": deepcopy(payload)}
    grant = command("001-grant", GRANT_TOOL, v.request.model_dump(mode="json"))
    execute = command("002-execute", FIXTURE_COMMAND_TOOL, chosen.model_dump(mode="json"), "running")
    cancel = command("003-cancel", FIXTURE_CANCEL_TOOL, {"project_id": v.request.project_id, "invocation_id": execute["id"]})
    rows = [{"command": grant, "execution": None, **parent}, {"command": execute, "execution": None, **parent},
            {"command": cancel, "execution": deepcopy(execute), **parent}]
    state = {"rows": rows, "queries": [], "workflow": []}
    def list_history(request, *, binding_ids):
        state["queries"].append((request, binding_ids))
        selected = [deepcopy(row) for row in state["rows"] if row["command"]["id"] > request.after_id]
        page = selected[:request.limit]
        return {"items": page, "lookahead": selected[request.limit:request.limit + 1], "total": len(state["rows"]),
                "next_after_id": page[-1]["command"]["id"] if len(selected) > request.limit else None}
    def read_history(project, ident, *, binding_ids):
        assert project == v.request.project_id
        state["queries"].append((ident, binding_ids))
        for row in state["rows"]:
            if row["command"]["id"] == ident: return deepcopy(row)
        raise KeyError(ident)
    repository = SimpleNamespace(list_history=list_history, read_history=read_history)
    jobs = HttpFixtureJobApplicationService(SimpleNamespace(grants=v.service), repository, SimpleNamespace())
    def no_effect(*args, **kwargs): pytest.fail("history must not renew consent, dispatch, or contact a target")
    monkeypatch.setattr(v.service.repository, "require_live", no_effect)
    monkeypatch.setattr(v.service.repository, "issue", no_effect)
    v.jobs, v.history, v.history_state, v.access = jobs, jobs.history, state, scope
    v.query = HttpFixtureHistoryQuery(project_id=v.request.project_id, limit=2)
    v.target = HttpFixtureHistoryTarget(project_id=v.request.project_id, invocation_id="002-execute")
    return v


def test_project_history_discovers_all_stages_and_waiting_confirmation_without_local_session(history_specimen):
    v = history_specimen
    original = deepcopy(v.state["issued"])
    calls = len(v.commands.calls)
    page = v.history.list(v.query)
    assert [item.stage for item in page.items] == ["grant", "execute"]
    assert page.items[0].status == "waiting_confirmation" and page.items[1].status == "running"
    assert page.total == 3 and page.next_after_id == "002-execute"
    second = v.history.list(v.query.model_copy(update={"after_id": page.next_after_id}))
    assert [item.stage for item in second.items] == ["cancel"] and second.next_after_id is None
    assert second.items[0].original_execution_id == "002-execute"
    assert all(bindings == ("code-source", "document-source") for _, bindings in v.history_state["queries"])
    wire = page.model_dump(mode="json")
    assert not any(token in str(wire) for token in ("base_url", "artifact_ref", "idempotency_key", "input_payload", "setup_steps"))
    assert v.state["issued"] == original and v.state["live"] == 0 and len(v.commands.calls) == calls
    for item in (*page.items, *second.items):
        for key in ("execution_authorized", "canonical_execution_committed", "business_coverage_verified", "baseline_restored"):
            assert getattr(item, key) is False and getattr(page, key) is False


@pytest.mark.parametrize("status", ["pending", "waiting_confirmation", "waiting_approval", "running", "completed", "failed", "cancelled"])
def test_all_original_lifecycle_statuses_remain_discoverable_without_reopening(history_specimen, status):
    v = history_specimen
    v.history_state["rows"][1]["command"]["status"] = status
    item = v.history.read(v.target)
    assert item.status == status and item.original_execution_id == v.target.invocation_id
    assert item.observation == "original_command_metadata_not_target_observation"
    assert v.history_state["rows"][1]["command"]["status"] == status


@pytest.mark.parametrize("change", ["cross_project", "recipe", "recipe_hash", "grant_digest", "extra_input", "other_tool", "cancel_target", "cancel_source", "duplicate", "out_of_order", "total_bool", "lookahead", "cursor", "revoked", "role"])
def test_history_rejects_changed_ancestry_page_or_permission_without_any_effect(history_specimen, change):
    v = history_specimen
    rows = v.history_state["rows"]
    if change == "cross_project": rows[1]["command"]["input_payload"]["project_id"] = "another-project"
    elif change == "recipe": rows[0]["recipe_id"] = "another-recipe"
    elif change == "recipe_hash": rows[0]["recipe_artifact_hash"] = acceptance_digest("other-recipe")
    elif change == "grant_digest": rows[1]["command"]["input_payload"]["grant_digest"] = acceptance_digest("other-grant")
    elif change == "extra_input": rows[0]["command"]["input_payload"]["execution_authorized"] = True
    elif change == "other_tool": rows[0]["command"]["tool_id"] = "run.start"
    elif change == "cancel_target": rows[2]["command"]["input_payload"]["invocation_id"] = "another-execution"
    elif change == "cancel_source": rows[2]["execution"]["input_payload"]["project_id"] = "another-project"
    elif change == "duplicate": rows[1] = deepcopy(rows[0])
    elif change == "out_of_order": rows[0], rows[1] = rows[1], rows[0]
    elif change in {"total_bool", "lookahead", "cursor"}:
        read = v.history.repository.list_history
        def changed(*args, **kwargs):
            value = read(*args, **kwargs)
            if change == "total_bool": value["total"] = True
            elif change == "cursor": value["next_after_id"] = "unrelated-cursor"
            else: value["lookahead"][0]["command"]["input_payload"]["project_id"] = "another-project"
            return value
        v.history.repository.list_history = changed
    elif change == "revoked": v.state["revoked"] = True
    else: v.access.effective_project_role = "qa_lead"
    with pytest.raises((ValueError, PermissionError, KeyError)):
        v.history.list(v.query)
    assert v.state["live"] == 0


def test_permission_change_after_last_archive_read_rejects_the_entire_page(history_specimen):
    v = history_specimen
    original = v.service.recipes.read
    def revoked(*args):
        value = original(*args)
        v.state["revoked"] = True
        return value
    v.service.recipes.read = revoked
    with pytest.raises(SourceAccessDenied): v.history.list(v.query)


@pytest.mark.parametrize("payload", [{"limit": True}, {"limit": 0}, {"limit": 6}, {"limit": "2"},
    {"after_id": "bad\n"}, {"after_id": "x" * 129}, {"approved": True}, {"project_id": 1}])
def test_history_query_accepts_only_bounded_read_selection(payload):
    with pytest.raises(ValueError): HttpFixtureHistoryQuery.model_validate({"project_id": "project", **payload})


@pytest.mark.parametrize("field", ["execution_authorized", "canonical_execution_committed", "business_coverage_verified", "baseline_restored"])
@pytest.mark.parametrize("value", [True, 0, 1, "false", None])
def test_receipt_never_accepts_coerced_or_new_authority(history_specimen, field, value):
    v = history_specimen
    wire = v.history.list(v.query).model_dump(mode="json")
    wire[field] = value
    with pytest.raises(ValueError): HttpFixtureHistoryPage.model_validate(wire)
    item = v.history.read(v.target).model_dump(mode="json")
    item[field] = value
    with pytest.raises(ValueError): HttpFixtureHistoryItem.model_validate(item)


def test_history_receipt_revalidates_original_ids_current_acl_and_status(history_specimen):
    v = history_specimen
    page = v.history.list(v.query).model_dump(mode="json")
    v.history.verify_receipt(v.query, page)
    item = v.history.read(v.target).model_dump(mode="json")
    v.history.verify_receipt(v.target, item)
    v.history_state["rows"][1]["command"]["status"] = "cancelled"
    with pytest.raises(HttpFixtureInvalid): v.history.verify_receipt(v.query, page)
    with pytest.raises(HttpFixtureInvalid): v.history.verify_receipt(v.target, item)
    v.state["revoked"] = True
    with pytest.raises(SourceAccessDenied): v.history.verify_receipt(v.query, page)


@pytest.mark.parametrize("tool", [FIXTURE_HISTORY_LIST_TOOL, FIXTURE_HISTORY_READ_TOOL])
def test_history_tools_use_same_service_and_original_privacy_projection(history_specimen, tool):
    v = history_specimen
    value = v.query if tool == FIXTURE_HISTORY_LIST_TOOL else v.target
    invocation = ToolInvocation(id="history-query", tool_id=tool, status="pending", summary="", input_payload=value.model_dump(mode="json"))
    events = []
    async def emit(ident, status, summary, refs, result=None): events.append((status, result))
    access = SimpleNamespace(require_invocation_project_scope=lambda _: None)
    asyncio.run(HttpFixtureJobToolHandler(v.jobs, SimpleNamespace(emit_tool_status=emit), access).handle(invocation))
    status, result = events[-1]
    assert status == "completed" and result.http_fixture_history is not None and result.http_fixture_job is None
    completed = invocation.model_copy(update={"status": status, "result": result})
    protector = HttpFixtureJobReceiptAccess(v.jobs)
    protector.require_access(completed)
    public = protector.broadcast_view(completed)
    assert public.input_payload == {} and public.result is None and public.id == invocation.id
    assert tool in FIXTURE_JOB_TOOLS
    v.state["revoked"] = True
    with pytest.raises(PlatformApplicationError) as denied: protector.require_access(completed)
    assert denied.value.status_code == 403


@pytest.mark.parametrize("receipt", [None, {}, {"execution_authorized": True}])
def test_completed_history_query_cannot_invent_or_omit_original_receipt(history_specimen, receipt):
    v = history_specimen
    invocation = ToolInvocation(id="query", tool_id=FIXTURE_HISTORY_LIST_TOOL, status="completed", summary="",
        input_payload=v.query.model_dump(mode="json"), result=ToolResult(invocation_id="query", status="completed", summary="",
            http_fixture_history=receipt))
    with pytest.raises(ValueError): v.jobs.authorize_receipts((invocation,))


@pytest.mark.parametrize("bindings", [(), ("code-source",), ("code-source", "document-source")])
def test_sql_counts_and_pages_the_full_project_after_visibility_without_lifecycle_filter(bindings):
    statement = HttpFixtureHistoryRepository._statement("project", bindings, after_id="cursor", limit=2)
    query = statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    sql = str(query)
    assert "UNION ALL" in sql and sql.count("tool_invocations.tool_id =") == 3
    assert "visible_fixture_commands AS" in sql and "NOT (EXISTS" in sql and "binding_id NOT IN" in sql
    assert sql.index("visible_fixture_commands AS") < sql.index("count(*) AS total")
    assert "original_fixture_commands.manifest_id" in sql and "invalid_total" in sql
    assert "tool_invocations.status =" not in sql and "LIMIT 3" in sql
    assert "LEFT OUTER JOIN quality_http_fixture_grants" in sql and "LEFT OUTER JOIN tool_invocations" in sql
    assert "FOR UPDATE" not in sql and "actor_id =" not in sql


def test_database_outage_has_no_partial_inventory_or_private_sql_leak(monkeypatch):
    from apps.api.app.infrastructure.persistence import http_fixture_history_repository as adapter
    @contextmanager
    def unavailable():
        raise OperationalError("private SQL", {"password": "private secret"}, RuntimeError("unavailable"))
        yield
    monkeypatch.setattr(adapter, "session_scope", unavailable)
    with pytest.raises(HttpFixtureHistoryUnavailable) as raised:
        HttpFixtureHistoryRepository().list_history(HttpFixtureHistoryQuery(project_id="project"), binding_ids=())
    assert "private" not in str(raised.value) and "password" not in str(raised.value)


def test_unresolved_ancestry_rejects_even_an_empty_page_instead_of_fabricating_zero(monkeypatch):
    from apps.api.app.infrastructure.persistence import http_fixture_history_repository as adapter
    @contextmanager
    def unresolved():
        row = SimpleNamespace(total=0, invalid_total=1, invocation_id=None)
        yield SimpleNamespace(execute=lambda _: SimpleNamespace(all=lambda: [row]))
    monkeypatch.setattr(adapter, "session_scope", unresolved)
    with pytest.raises(HttpFixtureInvalid):
        HttpFixtureHistoryRepository().list_history(HttpFixtureHistoryQuery(project_id="project"), binding_ids=())
