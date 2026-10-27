from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.app.application.quality_loop.mapping_partition_inputs import MappingPartitionPageInput
from apps.api.app.application.quality_loop.test_design_mapping_inputs import MappingQueryInput
from apps.api.app.application.quality_loop.test_design_mappings import TestDesignMappingApplicationService
from apps.api.app.domain.quality_loop.test_design_mapping import TestDesignMappingChanged, TestDesignMappingIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_mapping_partitions import generation_pin, proposal


@pytest.fixture
def application():
    draft = proposal()
    pin = generation_pin(draft)
    result = {"metadata": {"generation_id": pin["generation_id"], "artifact_hash": pin["artifact_hash"]},
        "result": {"proposal": draft, "context_pin": pin["context_pin"], "scope_pin": pin["scope_pin"],
            "request": {"input_digest": pin["input_digest"]}}, "current_use": {"scope_current": True}}

    class Authorization:
        role, epoch, checks = "qa_lead", 1, 0

        def scope(self, project_id):
            assert project_id == pin["project_id"]
            return SimpleNamespace(effective_project_role=self.role, actor_id="qa-reviewer", epoch=self.epoch)

        def require_current(self, scope):
            self.checks += 1
            if scope.epoch != self.epoch or scope.effective_project_role != self.role:
                raise SourceAccessDenied("reviewer access changed")

    class Results:
        calls, denied = 0, False

        def read(self, project_id, generation_id):
            self.calls += 1
            if self.denied:
                raise SourceAccessDenied("original generation sources revoked")
            assert (project_id, generation_id) == (pin["project_id"], pin["generation_id"])
            return deepcopy(result)

    class Repository:
        calls, advance = 0, False

        def history(self, project_id, generation_id):
            self.calls += 1
            return [{"revision_id": "competing-review"}] if self.advance and self.calls > 1 else []

    class NoWrite:
        def __getattr__(self, name):
            raise AssertionError("partition inspection must not access a write/model adapter: " + name)

    authorization, results, repository = Authorization(), Results(), Repository()
    service = TestDesignMappingApplicationService(results, authorization, repository, NoWrite())
    request = MappingQueryInput(project_id=pin["project_id"], generation_id=pin["generation_id"],
        generation_artifact_hash=pin["artifact_hash"])
    return SimpleNamespace(service=service, request=request, result=result, authorization=authorization,
        results=results, repository=repository)


def test_plan_and_page_replay_exact_pins_with_no_write_or_execution_authority(application):
    v = application
    original = deepcopy(v.result)
    view = v.service.partition_plan(v.request)
    assert view["part"] is None and view["plan"]["expected_previous_revision_id"] is None
    assert not view["review_authorized"] and not view["execution_authorized"]
    page = v.service.partition_page(MappingPartitionPageInput(**v.request.model_dump(),
        plan_digest=view["plan"]["plan_digest"], sequence=0))
    assert page["plan"] == view["plan"] and page["part"]["plan_digest"] == view["plan"]["plan_digest"]
    assert page["plan"]["generation_pin"]["context_pin"] == v.result["result"]["context_pin"]
    assert page["plan"]["generation_pin"]["scope_pin"] == v.result["result"]["scope_pin"]
    assert v.results.calls == 2 and v.authorization.checks >= 4
    assert v.result == original and "oracle" not in page["part"]["assertions"][0]


@pytest.mark.parametrize("role", ["viewer", "tester"])
def test_non_reviewers_cannot_even_read_partition_metadata(application, role):
    v = application
    v.authorization.role = role
    with pytest.raises(SourceAccessDenied):
        v.service.partition_plan(v.request)
    assert v.results.calls == 0


def test_revoked_original_source_and_wrong_generation_pin_fail_closed(application):
    v = application
    v.results.denied = True
    with pytest.raises(SourceAccessDenied):
        v.service.partition_plan(v.request)
    v.results.denied = False
    with pytest.raises(TestDesignMappingIntegrityError):
        v.service.partition_plan(v.request.model_copy(update={"generation_artifact_hash": "sha256:" + "0" * 64}))


def test_reading_stale_history_does_not_grant_review_authority(application):
    v = application
    v.result["current_use"]["scope_current"] = False
    value = v.service.partition_plan(v.request)
    assert not value["scope_current"] and not value["review_authorized"]


def test_plan_digest_and_head_race_require_a_new_read(application):
    v = application
    with pytest.raises(TestDesignMappingChanged):
        v.service.partition_page(MappingPartitionPageInput(**v.request.model_dump(),
            plan_digest="sha256:" + "0" * 64, sequence=0))
    v.repository.calls, v.repository.advance = 0, True
    with pytest.raises(TestDesignMappingChanged, match="head changed"):
        v.service.partition_plan(v.request)


@pytest.mark.parametrize("change", ["role", "acl"])
def test_access_changes_during_partition_hashing_discard_the_entire_result(application, monkeypatch, change):
    from apps.api.app.application.quality_loop import test_design_mappings as module
    original = module.prepare_mapping_partitions
    v = application

    def changing(*args, **kwargs):
        value = original(*args, **kwargs)
        if change == "role":
            v.authorization.role = "viewer"
        else:
            v.authorization.epoch += 1
        return value

    monkeypatch.setattr(module, "prepare_mapping_partitions", changing)
    with pytest.raises(SourceAccessDenied):
        v.service.partition_plan(v.request)
