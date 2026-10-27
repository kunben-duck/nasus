"""Application port scopes; these specimens do not prove PG isolation or execution."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.run_plan_inputs import RunPlanRequest
from apps.api.app.application.quality_loop.run_plans import RunPlanApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan import compile_run_plan, run_plan_artifact_schema
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_run_plans import plan_inputs


@pytest.mark.parametrize("failure", [None, "scope", "metadata", "script", "review", "source", "archive", "final"])
def test_entire_read_uses_transport_scope_but_each_authority_check_is_fresh(failure):
    draft, review, sources, selection = plan_inputs()
    plan = compile_run_plan(draft, review, selection.model_dump(mode="json"), sources)
    request = RunPlanRequest(**selection.model_dump(mode="json"), plan_digest=plan["plan_digest"],
        source_scope_digest=acceptance_digest("scope"))
    payload = {"schema": run_plan_artifact_schema(request.policy_revision), "project_id": "p", "run_plan_id": "plan",
        "request": request.model_dump(mode="json"), "plan": plan, "actor_id": "reviewer",
        "invocation_id": "prepare-command", "recorded_at": "2026-10-10T00:00:00+00:00"}
    metadata = {key: payload[key] for key in ("project_id", "run_plan_id", "actor_id", "invocation_id", "recorded_at")}
    metadata.update(artifact_hash=acceptance_digest(payload), plan_digest=plan["plan_digest"],
        request_hash=acceptance_digest(payload["request"]), context_id=plan["prepared"]["context_pin"]["context_id"],
        **{key: plan["source_pin"][key] for key in ("image_revision_id", "manifest_id")})
    active, calls, opened, closed = [False], [], [], []
    @contextmanager
    def live():
        if active[0]:
            yield
            return
        active[0] = True
        opened.append(True)
        try:
            yield
        finally:
            active[0] = False
            closed.append(True)
    @contextmanager
    def immutable():
        assert active[0]
        yield
    def checked(name, value):
        def read(*args):
            assert active[0]
            calls.append(name)
            if failure == name:
                raise SourceAccessDenied("explicit " + name + " failure")
            return deepcopy(value)
        return read
    authorization = SimpleNamespace(live_read_session=live,
        scope=checked("scope", SimpleNamespace(actor_id="reviewer")), require_current=checked("final", None))
    service = RunPlanApplicationService(SimpleNamespace(read=checked("script", draft)),
        SimpleNamespace(read=checked("review", review)),
        SimpleNamespace(run_plan_sources=checked("source", sources), verified_read_session=immutable), authorization,
        SimpleNamespace(read=checked("metadata", {"metadata": metadata, "request": payload["request"], "artifact_ref": "private"})),
        SimpleNamespace(read=checked("archive", payload)))
    if failure is None:
        result = service.read("p", "plan")
        assert result["artifact"] == payload and result["current_use"]["inputs_current"] is True
        assert calls == ["scope", "metadata", "script", "review", "source", "archive", "final"]
    else:
        with pytest.raises(SourceAccessDenied): service.read("p", "plan")
        assert calls[-1] == failure
    assert opened == closed == [True] and active == [False]


def test_read_scope_does_not_survive_an_exception_or_become_a_cross_request_cache(monkeypatch):
    active, entries = [False], []
    @contextmanager
    def live():
        assert not active[0]
        active[0] = True
        entries.append(True)
        try:
            yield
        finally:
            active[0] = False
    service = RunPlanApplicationService(None, None, SimpleNamespace(), SimpleNamespace(live_read_session=live), None, None)
    def failed(*args):
        assert active[0]
        raise RuntimeError("explicit original parent read failure")
    monkeypatch.setattr(service, "_read", failed)
    with pytest.raises(RuntimeError): service.read("p", "plan")
    assert active == [False]
    monkeypatch.setattr(service, "_read", lambda *args: active[0])
    assert service.read("p", "plan") is True
    assert active == [False] and entries == [True, True]
