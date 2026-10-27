"""Finalization contract tests with explicit ports, not PG/MinIO capacity evidence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.app.application.quality_loop.mapping_finalization import MappingFinalizationApplicationService
from apps.api.app.application.quality_loop.mapping_finalization_inputs import MappingFinalizeInput, MappingFinalizationPreviewInput
from apps.api.app.application.quality_loop.test_design_mapping_inputs import MappingReceipt, PartitionedMappingReceipt
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.mapping_part_sets import part_set_commitment
from apps.api.app.domain.quality_loop.mapping_partitions import MAX_PARTS, prepare_mapping_partitions
from apps.api.app.domain.quality_loop.test_design_mapping import TestDesignMappingChanged, TestDesignMappingIntegrityError, TestDesignMappingInvalid, assess_mappings
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_mapping_partitions import proposal, generation_pin, decision_parts


def members(parts):
    return [{"sequence": item["sequence"], "part_revision_id": "saved-part-%d" % item["sequence"],
        "artifact_hash": acceptance_digest(item), "request_hash": acceptance_digest({"request": item}),
        "part_digest": item["part_digest"]} for item in parts]


@pytest.fixture
def finalization():
    draft = proposal()
    original_pin = generation_pin(draft)
    plan, _ = prepare_mapping_partitions(draft, original_pin, None)
    parts = list(decision_parts(draft, original_pin))
    selected = members(parts)
    actor, head, epoch = "independent-reviewer", None, 1
    value = {"metadata": {"generation_id": original_pin["generation_id"], "artifact_hash": original_pin["artifact_hash"]},
        "result": {"proposal": draft, "context_pin": original_pin["context_pin"], "scope_pin": original_pin["scope_pin"],
            "request": {"input_digest": original_pin["input_digest"]}}, "current_use": {"scope_current": True}}

    class Access:
        role = "qa_lead"

        def scope(self, project_id):
            return SimpleNamespace(actor_id=actor, effective_project_role=self.role, epoch=epoch)

        def require_current(self, scope):
            if scope.epoch != epoch or scope.effective_project_role != self.role:
                raise SourceAccessDenied("fixture authorization changed")

    class Results:
        denied = False

        def read(self, project_id, generation_id):
            if self.denied:
                raise SourceAccessDenied("fixture source revoked")
            return deepcopy(value)

    class Parts:
        def heads(self, requested, actor_id):
            assert requested == plan and actor_id == actor
            return deepcopy(self.selected)

        def decision_parts(self, requested, actor_id, fixed, *, final_revision=None):
            assert requested == plan and actor_id == actor
            assert fixed == selected
            yield from deepcopy(self.parts)

    class Artifacts:
        puts, body, on_put = 0, None, None

        def put(self, project_id, payload):
            self.puts += 1
            self.body = deepcopy(payload)
            if self.on_put:
                self.on_put()
            return "private-final-mapping", acceptance_digest(payload)

        def read(self, project_id, ref, digest):
            assert ref == "private-final-mapping"
            return deepcopy(self.body)

    class Repository:
        saved, records = None, 0

        def history(self, project_id, generation_id):
            return [{"revision_id": head}] if head else []

        def committed(self, request, *, actor_id, invocation_id, require_access):
            require_access()
            return deepcopy(self.saved)

        def record(self, request, payload, ref, digest, *, require_current):
            nonlocal head
            require_current()
            if head != request.expected_previous_revision_id:
                raise TestDesignMappingChanged("fixture competing final reviewer")
            self.records += 1
            head = "final-mapping-revision"
            self.saved = {"revision_id": head, "project_id": request.project_id, "generation_id": request.generation_id,
                "generation_artifact_hash": request.generation_artifact_hash, "previous_revision_id": None,
                "mapping_schema": payload["schema"], "sequence": 1, "status": "reviewed",
                "artifact_hash": digest, "request_hash": acceptance_digest(request.model_dump(mode="json")),
                **{key: payload[key] for key in ("authority_actor", "invocation_id", "recorded_at")}}
            return deepcopy(self.saved)

        def get(self, project_id, revision_id):
            assert revision_id == "final-mapping-revision"
            return deepcopy(self.saved), "private-final-mapping"

    access, results, staged, artifacts, repository = Access(), Results(), Parts(), Artifacts(), Repository()
    staged.selected, staged.parts = deepcopy(selected), deepcopy(parts)
    query = MappingFinalizationPreviewInput(project_id=original_pin["project_id"], generation_id=original_pin["generation_id"],
        generation_artifact_hash=original_pin["artifact_hash"], plan_digest=plan["plan_digest"])
    request = MappingFinalizeInput(**query.model_dump(), expected_previous_revision_id=None,
        part_set_digest=part_set_commitment(plan, actor, selected)["part_set_digest"], reason="Independent complete review fixture")
    service = MappingFinalizationApplicationService(results, access, repository, artifacts, staged)
    return SimpleNamespace(service=service, query=query, request=request, plan=plan, selected=selected, value=value,
        access=access, results=results, parts=staged, artifacts=artifacts, repository=repository)


def finalize(v):
    return v.service.finalize(v.request, invocation_id="independent-final-confirmation", recorded_at="2026-10-03T00:00:00+00:00")


def test_final_confirmation_is_exact_and_does_not_mutate_draft_or_claim_target_execution(finalization):
    v = finalization
    original = deepcopy(v.value)
    preview = v.service.inspect(v.query)
    assert preview["ready_for_confirmation"] and preview["part_set"]["part_set_digest"] == v.request.part_set_digest
    assert "members" not in preview["part_set"] and "decisions" not in str(preview)
    assert not preview["review_authorized"] and not preview["execution_authorized"]
    metadata = finalize(v)
    archive, _ = v.service.read(v.query.project_id, metadata["revision_id"])
    assert archive["assessment"] == assess_mappings(original["result"]["proposal"],
        [item for part in v.parts.parts for item in part["decisions"]])
    assert archive["current_use"]["mapping_current"] and archive["current_use"]["mapping_complete"]
    assert archive["assessment"]["coverage"]["automated_count"] == archive["assessment"]["coverage"]["passed_count"] == 0
    assert not archive["current_use"]["execution_authorized"] and v.value == original
    assert archive["part_set"]["members"] == v.selected
    assert "decisions" not in str(archive) and "saved-part-0" in str(archive)
    v.value["current_use"]["scope_current"] = False
    assert finalize(v) == metadata and v.artifacts.puts == v.repository.records == 1
    assert not v.service.read(v.query.project_id, metadata["revision_id"])[0]["current_use"]["mapping_current"]


@pytest.mark.parametrize("change", ["missing", "digest", "part", "oracle", "scope", "source", "role"])
def test_incomplete_or_changed_final_set_cannot_create_authority(finalization, change):
    v = finalization
    if change == "missing":
        v.parts.selected = []
        assert not v.service.inspect(v.query)["ready_for_confirmation"]
    elif change == "digest":
        v.request = v.request.model_copy(update={"part_set_digest": "sha256:" + "0" * 64})
    elif change == "part":
        v.parts.parts[0]["part_digest"] = "sha256:" + "0" * 64
    elif change == "oracle":
        v.parts.parts[0]["decisions"][0]["oracle_digest"] = "sha256:" + "0" * 64
    elif change == "scope":
        v.value["current_use"]["scope_current"] = False
    elif change == "source":
        v.results.denied = True
    else:
        v.access.role = "viewer"
    with pytest.raises((TestDesignMappingInvalid, TestDesignMappingChanged, TestDesignMappingIntegrityError, SourceAccessDenied)):
        finalize(v)
    assert v.artifacts.puts == v.repository.records == 0


@pytest.mark.parametrize("change", ["part_head", "source", "scope", "role", "body"])
def test_every_original_is_rechecked_after_object_write_before_atomic_final_commit(finalization, change):
    v = finalization

    def mutate():
        if change == "part_head":
            v.parts.selected[0]["part_revision_id"] = "edited-part-after-confirmation"
        elif change == "source":
            v.results.denied = True
        elif change == "scope":
            v.value["current_use"]["scope_current"] = False
        elif change == "role":
            v.access.role = "viewer"
        else:
            v.parts.parts[-1]["decisions"].pop()

    v.artifacts.on_put = mutate
    with pytest.raises((TestDesignMappingInvalid, TestDesignMappingChanged, TestDesignMappingIntegrityError, SourceAccessDenied)):
        finalize(v)
    assert v.artifacts.puts == 1 and v.repository.records == 0


@pytest.mark.parametrize("field", ["assessment", "part_set", "generation_pin", "request"])
def test_historical_final_authority_is_rederived_not_trusted_from_json(finalization, field):
    v = finalization
    metadata = finalize(v)
    v.artifacts.body[field] = {}
    with pytest.raises(TestDesignMappingIntegrityError):
        v.service.read(v.query.project_id, metadata["revision_id"])


def test_bounded_final_input_and_versioned_receipt_do_not_expand_legacy_limits(finalization):
    v = finalization
    for field in ("mappings", "members", "authority_actor", "execution_authorized"):
        with pytest.raises(ValidationError):
            MappingFinalizeInput.model_validate({**v.request.model_dump(), field: []})
    base = {**{key: getattr(v.query, key) for key in ("project_id", "generation_id", "generation_artifact_hash")},
        "head_revision_id": "reviewed", "head_artifact_hash": "sha256:" + "1" * 64, "status": "reviewed",
        "scope_current": True, "mapping_current": True, "mapping_complete": True,
        "accepted_assertion_count": 9000, "rejected_assertion_count": 0, "deferred_assertion_count": 0}
    with pytest.raises(ValidationError):
        MappingReceipt.model_validate(base)
    assert PartitionedMappingReceipt.model_validate(base).accepted_assertion_count == 9000


def test_full_maximum_part_directory_has_a_constant_size_commitment_without_truncation():
    digest = "sha256:" + "1" * 64
    plan = {"part_count": MAX_PARTS, "assertion_count": MAX_PARTS * 128, "plan_digest": digest}
    entries = [{"sequence": sequence, "part_revision_id": "explicit-fixture-part-%d" % sequence,
        "artifact_hash": digest, "request_hash": digest, "part_digest": digest} for sequence in range(MAX_PARTS)]
    value = part_set_commitment(plan, "reviewer-fixture", iter(entries))
    assert value["part_count"] == MAX_PARTS and len(str(value)) < 1024 and "members" not in value
    for bad in (entries[:-1], entries[::-1], [*entries, entries[-1]]):
        with pytest.raises(TestDesignMappingInvalid):
            part_set_commitment(plan, "reviewer-fixture", iter(bad))
    changed = deepcopy(entries[-1])
    changed["request_hash"] = "sha256:" + "2" * 64
    assert part_set_commitment(plan, "reviewer-fixture", [*entries[:-1], changed])["part_set_digest"] != value["part_set_digest"]
