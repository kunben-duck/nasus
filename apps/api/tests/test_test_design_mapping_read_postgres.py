"""Real isolated PG read transactions; generation and review data are specimens."""
from contextlib import contextmanager
from copy import deepcopy

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError

from apps.api.app.domain.quality_loop.test_design_mapping import TestDesignMappingIntegrityError
from apps.api.app.infrastructure.persistence import test_design_mapping_repository as mapping_module
from apps.api.app.infrastructure.persistence import mapping_part_repository as part_module
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_mapping_part_staging_api import staging, mapping, generation_result, design_scope, publication, documents, evidence_api
from apps.api.tests.test_mapping_part_staging_api import submit as stage_submit
from apps.api.tests.test_mapping_finalization_api import request as final_request, submit as final_submit
from apps.api.tests.test_test_design_mapping_api import completed, inspect, submit as review_submit


@pytest.fixture
def original_mapping(staging, request):
    value = staging
    if request.param == "partitioned":
        completed(stage_submit(value))
        completed(final_submit(value, final_request(value)))
    else:
        completed(review_submit(value))
    response = inspect(value)
    assert response.status_code == 200, response.text
    value["original_head"] = response.json()["head"]
    return value


@contextmanager
def read_only_session():
    with session_scope() as session:
        if session.bind.dialect.name != "postgresql":
            pytest.skip("an isolated PostgreSQL database is required")
        session.execute(text("SET TRANSACTION READ ONLY"))
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        yield session


@pytest.mark.parametrize("original_mapping", ["single", "partitioned"], indirect=True)
def test_mapping_history_get_works_in_actual_read_only_transaction(original_mapping, monkeypatch):
    value = original_mapping
    repository = value["mapping_service"].repository
    revision = value["original_head"]["revision"]
    before = deepcopy(repository.get(value["project_id"], revision["revision_id"]))
    monkeypatch.setattr(mapping_module, "session_scope", read_only_session)
    assert repository.get(value["project_id"], revision["revision_id"]) == before
    assert revision["status"] == "reviewed"
    assert not value["original_head"]["current_use"]["execution_authorized"]


@pytest.mark.parametrize("original_mapping", ["single", "partitioned"], indirect=True)
def test_mapping_command_verification_refreshes_identity_map_and_writes_remain_locked(original_mapping):
    value = original_mapping
    repository = value["mapping_service"].repository
    revision = value["original_head"]["revision"]
    assert_fresh_canonical_and_writer_lock(repository, revision)


def assert_fresh_canonical_and_writer_lock(repository, revision):
    with read_only_session() as session:
        cached = session.get(ToolInvocationRecord, revision["invocation_id"])
        parsed = repository._request(cached)
        # A historical command can change independently of this session's identity map.
        with session_scope() as writer:
            command = writer.get(ToolInvocationRecord, cached.id)
            command.input_payload = {**command.input_payload, "confirmed_actor_id": "another-reviewer"}
        with pytest.raises(TestDesignMappingIntegrityError):
            repository._canonical(session, parsed, cached.id, revision["authority_actor"], historical=True, lock=False)
        assert cached.input_payload["confirmed_actor_id"] == "another-reviewer"
    with read_only_session() as session:
        with pytest.raises(InternalError) as error:
            repository._canonical(session, parsed, cached.id, revision["authority_actor"], historical=True)
        assert error.value.orig.sqlstate == "25006"


def test_staged_mapping_part_get_is_read_only_and_does_not_grant_final_authority(staging, monkeypatch):
    command = completed(stage_submit(staging))
    revision_id = command["result"]["object_refs"][0].split(":", 1)[1]
    repository = staging["stage_service"].repository
    before = deepcopy(repository.get(staging["project_id"], revision_id))
    monkeypatch.setattr(part_module, "session_scope", read_only_session)
    assert repository.get(staging["project_id"], revision_id) == before
    assert inspect(staging).json()["head"] is None


def test_staged_mapping_part_rechecks_cached_command_and_retains_writer_lock(staging):
    command = completed(stage_submit(staging))
    revision_id = command["result"]["object_refs"][0].split(":", 1)[1]
    repository = staging["stage_service"].repository
    revision, _ref = repository.get(staging["project_id"], revision_id)
    assert_fresh_canonical_and_writer_lock(repository, revision)
