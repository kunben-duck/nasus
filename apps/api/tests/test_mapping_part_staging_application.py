from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.mapping_part_inputs import MappingPartStageInput
from apps.api.app.application.quality_loop.mapping_partition_inputs import MappingPartitionPageInput
from apps.api.app.application.quality_loop.mapping_part_staging import MappingPartStagingApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.mapping_partitions import prepare_mapping_partitions
from apps.api.app.domain.quality_loop.test_design_mapping import TestDesignMappingChanged, TestDesignMappingIntegrityError, TestDesignMappingInvalid
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_mapping_partitions import generation_pin, proposal, decision_parts


@pytest.fixture
def staged():
    draft = proposal()
    pin = generation_pin(draft)
    plan, part = prepare_mapping_partitions(draft, pin, None, sequence=0)
    request = MappingPartStageInput(project_id=pin["project_id"], generation_id=pin["generation_id"],
        generation_artifact_hash=pin["artifact_hash"], plan_digest=plan["plan_digest"], sequence=0,
        part_digest=part["part_digest"], expected_previous_revision_id=None, expected_previous_part_revision_id=None,
        decisions=next(decision_parts(draft, pin))["decisions"])
    value = {"metadata": {"generation_id": pin["generation_id"], "artifact_hash": pin["artifact_hash"]},
        "result": {"proposal": draft, "context_pin": pin["context_pin"], "scope_pin": pin["scope_pin"],
            "request": {"input_digest": pin["input_digest"]}}, "current_use": {"scope_current": True}}

    class Authorization:
        role, epoch, actor_id = "qa_lead", 1, "independent-reviewer"

        def scope(self, project_id):
            assert project_id == pin["project_id"]
            return SimpleNamespace(actor_id=self.actor_id, effective_project_role=self.role, epoch=self.epoch)

        def require_current(self, scope):
            if (scope.epoch, scope.effective_project_role) != (self.epoch, self.role):
                raise SourceAccessDenied("source or reviewer changed")

    class Results:
        denied, calls = False, 0

        def read(self, project_id, generation_id):
            self.calls += 1
            if self.denied:
                raise SourceAccessDenied("original source revoked")
            return deepcopy(value)

    class Reviews:
        head = None

        def history(self, project_id, generation_id):
            return [{"revision_id": self.head}] if self.head else []

    class Repository:
        saved, records = None, 0

        def committed(self, request, *, actor_id, invocation_id, require_access):
            require_access()
            return self.saved

        def record(self, request, payload, artifact_ref, artifact_hash, *, require_current):
            require_current()
            self.records += 1
            self.saved = {"part_revision_id": "part-revision", **{key: getattr(request, key) for key in (
                "project_id", "generation_id", "generation_artifact_hash", "plan_digest", "sequence", "part_digest",
                "expected_previous_revision_id", "expected_previous_part_revision_id")},
                "revision_sequence": 1, "request_hash": acceptance_digest(request.model_dump(mode="json")),
                "artifact_hash": artifact_hash, **{key: payload[key] for key in ("authority_actor", "invocation_id", "recorded_at")},
                "assertion_mapped": False, "execution_authorized": False}
            return deepcopy(self.saved)

        def get(self, project_id, revision_id):
            assert revision_id == "part-revision"
            return deepcopy(self.saved), "private-part"

        def history(self, *args):
            return [deepcopy(self.saved)] if self.saved else []

    class Artifacts:
        body, puts, on_put = None, 0, None

        def put(self, project_id, payload):
            self.body, self.puts = deepcopy(payload), self.puts + 1
            if self.on_put:
                self.on_put()
            return "private-part", acceptance_digest(payload)

        def read(self, project_id, ref, digest):
            assert ref == "private-part"
            return deepcopy(self.body)

    access, results, reviews, repo, artifacts = Authorization(), Results(), Reviews(), Repository(), Artifacts()
    service = MappingPartStagingApplicationService(results, access, reviews, repo, artifacts)
    return SimpleNamespace(service=service, request=request, value=value, access=access, results=results,
        reviews=reviews, repository=repo, artifacts=artifacts)


def save(v):
    return v.service.stage(v.request, invocation_id="confirmed-stage-command", recorded_at="2026-10-03T00:00:00+00:00")


def test_staging_saves_exact_private_decisions_without_approval_and_recovers_original(staged):
    v = staged
    original = deepcopy(v.value)
    metadata = save(v)
    view = v.service.read(v.request.project_id, metadata["part_revision_id"])
    assert view["request"] == v.request.model_dump(mode="json")
    assert view["current_use"]["part_current"]
    assert not view["current_use"]["assertion_mapped"] and not view["current_use"]["execution_authorized"]
    v.reviews.head = "later-final-review"
    v.value["current_use"]["scope_current"] = False
    assert save(v) == metadata
    assert v.repository.records == v.artifacts.puts == 1 and v.value["result"] == original["result"]
    assert not v.service.read(v.request.project_id, metadata["part_revision_id"])["current_use"]["part_current"]


def test_staged_head_can_be_recovered_after_refresh_without_returning_decision_text(staged):
    v = staged
    query = MappingPartitionPageInput(**{key: getattr(v.request, key) for key in MappingPartitionPageInput.model_fields})
    empty = v.service.inspect(query)
    assert empty["history_count"] == 0 and empty["head"] is None
    metadata = save(v)
    value = v.service.inspect(query)
    assert value["head"] == metadata and value["history_count"] == 1
    assert "request" not in value and "decisions" not in value["head"]
    assert not value["assertion_mapped"] and not value["review_authorized"]
    v.reviews.head = "final-head-changed"
    with pytest.raises(TestDesignMappingChanged):
        v.service.inspect(query)


@pytest.mark.parametrize("change", ["source", "scope", "head", "generation", "plan", "part", "omit", "oracle", "order"])
def test_staging_invalid_source_version_or_incomplete_part_cannot_write(staged, change):
    v = staged
    fields = v.request.model_dump(mode="json")
    if change == "source":
        v.results.denied = True
    elif change == "scope":
        v.value["current_use"]["scope_current"] = False
    elif change == "head":
        v.reviews.head = "competing-review"
    elif change in {"generation", "plan", "part"}:
        fields[{"generation": "generation_artifact_hash", "plan": "plan_digest", "part": "part_digest"}[change]] = "sha256:" + "0" * 64
    elif change == "omit":
        fields["decisions"].pop()
    elif change == "oracle":
        fields["decisions"][0]["oracle_digest"] = "sha256:" + "0" * 64
    else:
        fields["decisions"].reverse()
    v.request = MappingPartStageInput.model_validate(fields)
    with pytest.raises((SourceAccessDenied, TestDesignMappingChanged, TestDesignMappingIntegrityError, TestDesignMappingInvalid)):
        save(v)
    assert v.repository.records == v.artifacts.puts == 0


@pytest.mark.parametrize("change", ["source", "head", "scope", "role", "epoch"])
def test_staging_rechecks_after_artifact_write_and_never_commits_stale_decisions(staged, change):
    v = staged

    def mutate():
        if change == "source":
            v.results.denied = True
        elif change == "head":
            v.reviews.head = "changed-head"
        elif change == "scope":
            v.value["current_use"]["scope_current"] = False
        elif change == "role":
            v.access.role = "viewer"
        else:
            v.access.epoch += 1

    v.artifacts.on_put = mutate
    with pytest.raises((SourceAccessDenied, TestDesignMappingChanged)):
        save(v)
    assert v.repository.records == 0 and v.artifacts.puts == 1


def test_staged_read_does_not_grant_another_reviewer_access_or_accept_corrupt_decisions(staged):
    v = staged
    save(v)
    v.access.actor_id = "another-reviewer"
    with pytest.raises(SourceAccessDenied):
        v.service.read(v.request.project_id, "part-revision")
    v.access.role = "project_admin"
    assert v.service.read(v.request.project_id, "part-revision")["revision"]["authority_actor"] == "independent-reviewer"
    v.artifacts.body["request"]["decisions"][0]["reason"] = "rewritten"
    with pytest.raises(TestDesignMappingIntegrityError):
        v.service.read(v.request.project_id, "part-revision")


@pytest.mark.parametrize("change", ["viewer", "tester"])
def test_non_reviewer_cannot_read_or_stage_parts(staged, change):
    staged.access.role = change
    with pytest.raises(SourceAccessDenied):
        save(staged)
    with pytest.raises(SourceAccessDenied):
        staged.service.read(staged.request.project_id, "part-revision")
    assert staged.results.calls == 0


@pytest.mark.parametrize("change", ["bool", "extra", "too_many", "no_previous"])
def test_stage_input_is_bounded_strict_and_requires_explicit_predecessors(staged, change):
    fields = staged.request.model_dump(mode="json")
    if change == "bool":
        fields["sequence"] = False
    elif change == "extra":
        fields["execution_authorized"] = True
    elif change == "too_many":
        fields["decisions"] = [fields["decisions"][0]] * 129
    else:
        del fields["expected_previous_part_revision_id"]
    with pytest.raises(ValidationError):
        MappingPartStageInput.model_validate(fields)
