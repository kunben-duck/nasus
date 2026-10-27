"""Complete exweb PG/MinIO final set with explicit synthetic reviewer authority."""
from datetime import datetime, timezone
from uuid import uuid4

from apps.api.app.application.quality_loop.mapping_finalization_inputs import MappingFinalizeInput, MappingFinalizationPreviewInput
from apps.api.app.application.quality_loop.mapping_partition_inputs import MappingPartitionPageInput
from apps.api.app.application.quality_loop.mapping_part_inputs import MappingPartStageInput, STAGE_PART_TOOL
from apps.api.app.application.quality_loop.test_design_mappings import TestDesignMappingApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.mapping_part_sets import FINALIZE_TOOL
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_test_design_mapping import reviews


def finalize_exweb_mapping_parts(mappings, parts, results, authorization, query, draft):
    service = TestDesignMappingApplicationService(results, authorization, mappings.repository, mappings.artifacts, parts=parts)
    plan = service.partition_plan(query)["plan"]
    actor_id = authorization.scope(query.project_id).actor_id
    expected = {(item["case_id"], item["row_id"]): item for item in reviews(draft["result"]["proposal"])}
    staged = []

    def command(tool, request):
        ident, now = uuid4().hex, datetime.now(timezone.utc).isoformat()
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=ident, tool_id=tool, status="running",
                summary="Explicit exweb final set fixture, not public confirmation or maintainer approval",
                input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
                    "confirmed_actor_id": actor_id, "confirmed_at": now}))
        return ident, now

    for sequence in range(plan["part_count"]):
        page = service.partition_page(MappingPartitionPageInput(**query.model_dump(), plan_digest=plan["plan_digest"], sequence=sequence))["part"]
        request = MappingPartStageInput(**query.model_dump(), plan_digest=plan["plan_digest"], sequence=sequence,
            part_digest=page["part_digest"], expected_previous_revision_id=plan["expected_previous_revision_id"],
            expected_previous_part_revision_id=None, decisions=[expected[(pair["case_id"], pair["row_id"])] for pair in page["assertions"]])
        ident, now = command(STAGE_PART_TOOL, request)
        metadata = parts.stage(request, invocation_id=ident, recorded_at=now)
        assert parts.stage(request, invocation_id=ident, recorded_at="retry") == metadata
        _, ref = parts.repository.get(query.project_id, metadata["part_revision_id"])
        assert ref.startswith("s3://")
        stored = parts.artifacts.read(query.project_id, ref, metadata["artifact_hash"])
        assert stored["request"] == request.model_dump(mode="json")
        staged.append(metadata)
    preview = service.finalization_preview(MappingFinalizationPreviewInput(**query.model_dump(), plan_digest=plan["plan_digest"]))
    assert preview["ready_for_confirmation"] and preview["saved_part_count"] == preview["part_count"] == len(staged)
    assert not preview["review_authorized"] and not preview["execution_authorized"] and "members" not in preview["part_set"]
    request = MappingFinalizeInput(**query.model_dump(), plan_digest=plan["plan_digest"],
        expected_previous_revision_id=plan["expected_previous_revision_id"], part_set_digest=preview["part_set"]["part_set_digest"],
        reason="Synthetic complete-set protocol confirmation, NOT exweb maintainer acceptance")
    ident, now = command(FINALIZE_TOOL, request)
    metadata = service.finalize(request, invocation_id=ident, recorded_at=now)
    assert service.finalize(request, invocation_id=ident, recorded_at="retry") == metadata
    _, ref = service.repository.get(query.project_id, metadata["revision_id"])
    assert ref.startswith("s3://")
    body = service.artifacts.read(query.project_id, ref, metadata["artifact_hash"])
    value = service.read(query.project_id, metadata["revision_id"])
    assert metadata["mapping_schema"] == body["schema"] == "nasus.test-design-mapping-review.v2"
    assert body["plan"] == value["plan"] == plan and body["part_set"] == value["part_set"]
    assert body["request"] == value["request"] == request.model_dump(mode="json")
    assert body["assessment"] == value["assessment"] and acceptance_digest(body) == metadata["artifact_hash"]
    assert [member["part_revision_id"] for member in body["part_set"]["members"]] == [item["part_revision_id"] for item in staged]
    assert value["assessment"]["accepted_assertion_count"] == plan["assertion_count"] == len(expected)
    assert value["current_use"]["mapping_current"] and value["current_use"]["mapping_complete"]
    receipt = service.receipt(query)
    assert receipt.schema_version == "nasus.test-design-mapping-receipt.v2" and receipt.mapping_current
    assert receipt.accepted_assertion_count == len(expected) and not receipt.execution_authorized
    for item in staged:
        assert not parts.read(query.project_id, item["part_revision_id"])["current_use"]["part_current"]
    assert results.read(query.project_id, query.generation_id) == draft
    return service, value, {"revision": metadata, "plan_digest": plan["plan_digest"], "part_set_digest": request.part_set_digest,
        "part_count": len(staged), "assertion_count": len(expected), "all_private_parts_minio_verified": True,
        "final_minio_roundtrip_verified": True, "same_invocation_recovery_verified": True, "v2_receipt_verified": True,
        "original_draft_unchanged": True, "public_dispatch_verified": False, "external_model_called": False,
        "reviewer_basis": "explicit_seeded_protocol_fixture_not_exweb_maintainer", "execution_authorized": False}
