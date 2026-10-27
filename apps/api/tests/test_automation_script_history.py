"""History checks fixed source pins; it never reserves or repeats model work."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from apps.api.app.application.quality_loop.automation_script_inputs import SCRIPT_TOOL, ScriptExecutionRequest, ScriptHistoryQuery
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultIntegrityError
from apps.api.app.domain.quality_loop.automation_input import AutomationInputInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.infrastructure.persistence.automation_script_repository import AutomationScriptRepository
from apps.api.app.infrastructure.persistence.test_design_mapping_models import TestDesignMappingRecord
from apps.api.tests.test_automation_input import automation_inputs
from apps.api.tests.test_automation_scripts import script_executor


@pytest.mark.parametrize("running", [False, True])
def test_script_history_reads_do_not_lock_commands_but_generation_still_does(running):
    service, selection, _, _ = script_executor()
    request = ScriptExecutionRequest.model_validate(service.preview(selection)["request"])
    actor_id = "original-author"
    command = SimpleNamespace(tool_id=SCRIPT_TOOL, status="running" if running else "completed", conversation_id=None,
        input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True, "confirmed_actor_id": actor_id})
    class Session:
        def scalar(self, query):
            assert ("FOR UPDATE" in str(query.compile(dialect=postgresql.dialect()))) is running
            return command
        def get(self, model, ident):
            assert model is TestDesignMappingRecord and ident == request.mapping_revision_id
            return SimpleNamespace(project_id=request.project_id, payload={"artifact_hash": request.mapping_artifact_hash})
    assert AutomationScriptRepository._canonical(Session(), request, "command", actor_id, running=running) is command
    command.input_payload["confirmed_actor_id"] = "different-author"
    with pytest.raises(TestDesignResultIntegrityError):
        AutomationScriptRepository._canonical(Session(), request, "command", actor_id, running=running)


@pytest.mark.parametrize("changes", [{"limit": 0}, {"limit": 21}, {"limit": True}, {"limit": "10"}, {"after_id": True},
    {"after_id": "a" * 129}, {"mapping_artifact_hash": "latest"}, {"execution_authorized": True}])
def test_history_query_refuses_unbounded_or_implicit_authority(changes):
    mapping = automation_inputs()[2]
    with pytest.raises(ValidationError):
        ScriptHistoryQuery.model_validate({"project_id": "p", "mapping_revision_id": "m",
            "mapping_artifact_hash": mapping["revision"]["artifact_hash"], **changes})


@pytest.mark.parametrize("fault", [None, "mapping_hash", "withdrawn", "no_assessment", "source_revoked", "final_access", "completed_without_draft"])
def test_even_empty_history_replays_original_sources_and_checks_current_access(fault):
    service, _, deps, prepared = script_executor()
    mapping = deepcopy(automation_inputs()[2])
    query = ScriptHistoryQuery(project_id="p", mapping_revision_id="m", mapping_artifact_hash=mapping["revision"]["artifact_hash"])
    seen = []
    if fault == "mapping_hash": mapping["revision"]["artifact_hash"] = "sha256:" + "0" * 64
    if fault == "withdrawn": mapping["revision"]["status"] = "withdrawn"
    if fault == "no_assessment": mapping["assessment"] = None
    def replay(selection):
        seen.append("replay")
        assert selection.case_ids == tuple(mapping["assessment"]["accepted_case_ids"])
        if fault == "source_revoked": raise SourceAccessDenied("revoked source specimen")
        return deepcopy(prepared)
    def history(selection):
        seen.append("history")
        assert selection == query
        return [{"invocation_id": "completed", "status": "completed"}] if fault == "completed_without_draft" else []
    def require_current(access):
        seen.append("access")
        if fault == "final_access": raise SourceAccessDenied("revoked before metadata return")
    deps["inputs"].mappings = SimpleNamespace(read=lambda *args: deepcopy(mapping))
    deps["inputs"].replay = replay
    deps["repository"].history = history
    deps["authorization"].require_current = require_current
    if fault:
        with pytest.raises((AutomationInputInvalid, TestDesignResultIntegrityError, SourceAccessDenied)):
            service.history(query)
    else:
        assert service.history(query) == {"request": query.model_dump(mode="json"), "items": [], "next_after_id": None,
            "generation_authorized": False, "execution_authorized": False}
        assert seen == ["replay", "history", "access"]
    assert deps["provider"].calls == 0 and deps["repository"].stored is None
