"""Independent review protocol fixture on fixed exweb, never maintainer approval."""
from datetime import datetime, timezone
from uuid import uuid4

from apps.api.app.application.quality_loop.test_design_mapping_inputs import MappingReviewInput, MappingQueryInput
from apps.api.app.application.quality_loop.test_design_mappings import TestDesignMappingApplicationService
from apps.api.app.application.quality_loop.test_design_review_queries import ReviewDraftListInput, ReviewDraftListReceipt
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.test_design_mapping import MAPPING_TOOL
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.test_design_mapping_repository import TestDesignMappingRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.test_design_mapping_artifacts import TestDesignMappingArtifacts
from apps.api.tests.test_test_design_mapping import reviews
from apps.api.tests.exweb_mapping_part_staging_fixture import stage_exweb_mapping_part
from apps.api.tests.exweb_mapping_finalization_fixture import finalize_exweb_mapping_parts


def find_exweb_review_draft(results, metadata):
    """Follow bounded pages instead of assuming random generation IDs sort first."""
    request = ReviewDraftListInput(project_id=metadata["project_id"])
    seen = set()
    for page_number in range(1, 9):
        page = results.list_for_review(request)
        assert page["request"] == request.model_dump(mode="json")
        assert page["can_review"] and not page["generation_authorized"] and not page["execution_authorized"]
        assert len(page["items"]) <= request.limit
        previous = request.after_id
        for item in page["items"]:
            assert set(item) == {"metadata", "context_pin", "scope_pin"}
            ident = item["metadata"]["generation_id"]
            assert item["metadata"]["project_id"] == request.project_id and ident > previous and ident not in seen
            seen.add(ident)
            previous = ident
        if any(item["metadata"] == metadata for item in page["items"]):
            return page, request, page_number, len(seen)
        cursor = page["next_after_id"]
        assert cursor is not None and cursor == previous and cursor > request.after_id, "fixture draft was not discovered"
        request = request.model_copy(update={"after_id": cursor})
    raise AssertionError("exweb fixture draft discovery exceeded eight bounded pages")


def review_exweb_test_design_mapping(results, authorization, storage, draft):
    service = TestDesignMappingApplicationService(results, authorization, TestDesignMappingRepository(), TestDesignMappingArtifacts(storage))
    metadata = draft["metadata"]
    discovery, discovery_request, discovery_pages, discovered_count = find_exweb_review_draft(results, metadata)
    item = next(value for value in discovery["items"] if value["metadata"] == metadata)
    assert item == {"metadata": metadata, "context_pin": draft["result"]["context_pin"],
                    "scope_pin": draft["result"]["scope_pin"]}
    assert discovery["can_review"] and not discovery["generation_authorized"] and not discovery["execution_authorized"]
    assert all(set(value) == {"metadata", "context_pin", "scope_pin"} for value in discovery["items"])
    receipt = results.review_receipt(discovery_request)
    assert receipt.page_digest == acceptance_digest(discovery)
    assert receipt.generation_ids == tuple(value["metadata"]["generation_id"] for value in discovery["items"])
    results.verify_review_receipt(ReviewDraftListReceipt.model_validate_json(receipt.model_dump_json()))
    assert not receipt.generation_authorized and not receipt.execution_authorized
    assert "raw_output" not in receipt.model_dump_json() and "artifact_ref" not in receipt.model_dump_json()
    query = MappingQueryInput(project_id=metadata["project_id"], generation_id=metadata["generation_id"],
        generation_artifact_hash=metadata["artifact_hash"])
    assert service.inspect(query)["head"] is None
    staged_service, staged_metadata, staged_report = stage_exweb_mapping_part(service, results, authorization, storage, query, draft)
    decisions = reviews(draft["result"]["proposal"])
    decisions[0]["decision"], decisions[1]["decision"] = "reject", "defer"
    actor_id = authorization.scope(query.project_id).actor_id

    def review(previous, mappings):
        request = MappingReviewInput(**query.model_dump(), expected_previous_revision_id=previous, decision="review",
            mappings=mappings, reason="Synthetic reviewer protocol, NOT exweb product-owner validation")
        ident = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=ident, tool_id=MAPPING_TOOL, status="running",
                summary="Explicit independent mapping fixture, not target test evidence",
                input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
                    "confirmed_actor_id": actor_id, "confirmed_at": now}))
        value = service.review(request, invocation_id=ident, recorded_at=now)
        assert service.review(request, invocation_id=ident, recorded_at="retry") == value
        _, ref = service.repository.get(query.project_id, value["revision_id"])
        assert ref.startswith("s3://")
        return service.read(query.project_id, value["revision_id"])

    partial = review(None, decisions)
    assert partial["assessment"]["accepted_assertion_count"] == 6
    assert partial["assessment"]["rejected_assertion_count"] == partial["assessment"]["deferred_assertion_count"] == 1
    assert partial["current_use"]["mapping_current"] and not partial["current_use"]["mapping_complete"]
    accepted = review(partial["revision"]["revision_id"], reviews(draft["result"]["proposal"]))
    assert accepted["current_use"]["mapping_current"] and accepted["current_use"]["mapping_complete"]
    assessment = accepted["assessment"]
    assert assessment["accepted_assertion_count"] == assessment["coverage"]["assertion_mapped_count"] == 8
    assert assessment["coverage"]["constraint_denominator"] == 2
    assert assessment["coverage"]["automated_count"] == assessment["coverage"]["executed_on_target_count"] == assessment["coverage"]["passed_count"] == 0
    assert not accepted["current_use"]["execution_authorized"]
    assert results.read(query.project_id, query.generation_id) == draft
    assert service.read(query.project_id, partial["revision"]["revision_id"])["assessment"] == partial["assessment"]
    results.verify_review_receipt(receipt)
    assert not staged_service.read(query.project_id, staged_metadata["part_revision_id"])["current_use"]["part_current"]
    v1_accepted = accepted
    service, accepted, final_report = finalize_exweb_mapping_parts(service, staged_service, results, authorization, query, draft)
    assert service.read(query.project_id, v1_accepted["revision"]["revision_id"])["assessment"] == v1_accepted["assessment"]
    assert not service.read(query.project_id, v1_accepted["revision"]["revision_id"])["current_use"]["mapping_current"]
    return service, accepted, {"revision": accepted["revision"], "partial_revision": partial["revision"],
        "legacy_accepted_revision": v1_accepted["revision"], "partitioned_finalization": final_report,
        "legacy_assessment_unchanged_after_v2_verified": True,
        "private_part_staging": staged_report, "staged_part_stale_after_final_review_verified": True,
        "review_draft_discovery_verified": True, "review_discovery_count": len(discovery["items"]),
        "review_discovery_page_count": discovery_pages, "review_discovery_inspected_count": discovered_count,
        "review_draft_receipt_roundtrip_verified": True, "mapping_did_not_grant_discovery_execution_authority": True,
        "minio_roundtrip_verified": True, "immutable_draft_preserved": True, "idempotent_review_verified": True,
        "reject_defer_preserved": True, "accepted_assertion_count": 8, "constraint_denominator": 2, "obligation_denominator": 8,
        "reviewer_basis": "explicit_protocol_fixture_not_exweb_maintainer", "external_model_called": False,
        "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0, "execution_authorized": False}
