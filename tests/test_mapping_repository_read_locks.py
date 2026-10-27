"""Read locks are independent of whether an existing command is historical."""
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from apps.api.app.application.quality_loop.mapping_finalization_inputs import MappingFinalizeInput
from apps.api.app.application.quality_loop.mapping_part_inputs import MappingPartStageInput, STAGE_PART_TOOL
from apps.api.app.application.quality_loop.test_design_mapping_inputs import MappingReviewInput
from apps.api.app.domain.quality_loop.mapping_part_sets import FINALIZE_TOOL
from apps.api.app.domain.quality_loop.test_design_mapping import MAPPING_TOOL
from apps.api.app.infrastructure.persistence.test_design_mapping_repository import TestDesignMappingRepository
from apps.api.app.infrastructure.persistence.mapping_part_repository import MappingPartRepository
from apps.api.app.infrastructure.persistence.test_design_result_repository import TestDesignResultRepository


def mapping_request(mode):
    fields = dict(project_id="project", generation_id="generation",
        generation_artifact_hash="sha256:" + "a" * 64, expected_previous_revision_id=None,
        reason="Explicit protocol specimen")
    if mode == "final":
        return TestDesignMappingRepository, FINALIZE_TOOL, MappingFinalizeInput(**fields,
            plan_digest="sha256:" + "b" * 64, part_set_digest="sha256:" + "c" * 64)
    if mode == "part":
        fields.pop("reason")
        return MappingPartRepository, STAGE_PART_TOOL, MappingPartStageInput(**fields,
            plan_digest="sha256:" + "b" * 64, sequence=0, part_digest="sha256:" + "c" * 64,
            expected_previous_part_revision_id=None, decisions=({"case_id": "case", "row_id": "row",
                "step_index": 0, "oracle_digest": "sha256:" + "d" * 64, "decision": "defer",
                "reason": "Explicit protocol specimen"},))
    return TestDesignMappingRepository, MAPPING_TOOL, MappingReviewInput(**fields, decision="review", mappings=())


@pytest.mark.parametrize("mode", ["single", "final", "part"])
@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("lock", [False, True])
def test_mapping_lock_and_fresh_read_are_explicit_not_derived_from_historical_state(monkeypatch, mode, historical, lock):
    repository, tool, request = mapping_request(mode)
    command = SimpleNamespace(tool_id=tool,
        status="completed", input_payload={**request.model_dump(mode="json"),
            "confirmed_by_user": True, "confirmed_actor_id": "reviewer"})
    queries = []
    session = SimpleNamespace(scalar=lambda query: queries.append(query) or command)
    monkeypatch.setattr(TestDesignResultRepository, "_project_scope", lambda *_args: None)
    assert repository._canonical(session, request, "command", "reviewer",
        historical=historical, lock=lock) is command
    query = queries[0]
    assert ("FOR UPDATE" in str(query.compile(dialect=postgresql.dialect()))) is lock
    assert query.get_execution_options()["populate_existing"] is True


@pytest.mark.parametrize("mode", ["single", "final", "part"])
@pytest.mark.parametrize("historical", [False, True])
def test_mapping_writers_keep_lock_by_default_even_for_committed_replay(monkeypatch, mode, historical):
    repository, tool, request = mapping_request(mode)
    command = SimpleNamespace(tool_id=tool,
        status="completed", input_payload={**request.model_dump(mode="json"),
            "confirmed_by_user": True, "confirmed_actor_id": "reviewer"})
    queries = []
    session = SimpleNamespace(scalar=lambda query: queries.append(query) or command)
    monkeypatch.setattr(TestDesignResultRepository, "_project_scope", lambda *_args: None)
    repository._canonical(session, request, "command", "reviewer", historical=historical)
    assert "FOR UPDATE" in str(queries[0].compile(dialect=postgresql.dialect()))
