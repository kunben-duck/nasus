"""Real exweb PG/MinIO staging with an explicit synthetic canonical reviewer."""
from datetime import datetime, timezone
from uuid import uuid4

from apps.api.app.application.quality_loop.mapping_part_inputs import MappingPartStageInput, STAGE_PART_TOOL
from apps.api.app.application.quality_loop.mapping_partition_inputs import MappingPartitionPageInput
from apps.api.app.application.quality_loop.mapping_part_staging import MappingPartStagingApplicationService
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.mapping_part_repository import MappingPartRepository
from apps.api.app.infrastructure.persistence.test_design_mapping_repository import TestDesignMappingRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.mapping_part_artifacts import MappingPartArtifacts
from apps.api.tests.test_test_design_mapping import reviews


def stage_exweb_mapping_part(mappings, results, authorization, storage, query, draft):
    view = mappings.partition_plan(query)
    plan = view["plan"]
    assert plan["part_count"] == 1 and plan["assertion_count"] == 8
    page_request = MappingPartitionPageInput(**query.model_dump(), sequence=0, plan_digest=plan["plan_digest"])
    part = mappings.partition_page(page_request)["part"]
    decisions = {(item["case_id"], item["row_id"]): item for item in reviews(draft["result"]["proposal"])}
    selected = [decisions[(pair["case_id"], pair["row_id"])] for pair in part["assertions"]]
    selected[0]["decision"], selected[1]["decision"] = "reject", "defer"
    request = MappingPartStageInput(**query.model_dump(), plan_digest=plan["plan_digest"], sequence=0,
        part_digest=part["part_digest"], expected_previous_revision_id=plan["expected_previous_revision_id"],
        expected_previous_part_revision_id=None, decisions=selected)
    service = MappingPartStagingApplicationService(results, authorization, TestDesignMappingRepository(),
        MappingPartRepository(), MappingPartArtifacts(storage))
    actor_id = authorization.scope(query.project_id).actor_id
    ident, now = uuid4().hex, datetime.now(timezone.utc).isoformat()
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=ident, tool_id=STAGE_PART_TOOL, status="running",
            summary="Explicit exweb staging protocol fixture, not public confirmation or maintainer approval",
            input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True,
                "confirmed_actor_id": actor_id, "confirmed_at": now}))
    metadata = service.stage(request, invocation_id=ident, recorded_at=now)
    assert service.stage(request, invocation_id=ident, recorded_at="retry") == metadata
    _, ref = service.repository.get(query.project_id, metadata["part_revision_id"])
    assert ref.startswith("s3://")
    stored = service.artifacts.read(query.project_id, ref, metadata["artifact_hash"])
    value = service.read(query.project_id, metadata["part_revision_id"])
    assert stored["request"] == value["request"] == request.model_dump(mode="json")
    assert stored["plan"] == value["plan"] == plan
    assert service.inspect(page_request)["head"] == metadata
    assert value["current_use"]["part_current"] and not value["current_use"]["assertion_mapped"]
    assert not value["current_use"]["execution_authorized"] and mappings.inspect(query)["head"] is None
    assert results.read(query.project_id, query.generation_id) == draft
    return service, metadata, {"part_revision_id": metadata["part_revision_id"], "plan_digest": plan["plan_digest"],
        "assertion_count": 8, "part_count": 1, "minio_roundtrip_verified": True,
        "same_invocation_recovery_verified": True, "head_discovery_verified": True,
        "immutable_draft_preserved": True, "assertion_mapped": False, "execution_authorized": False,
        "canonical_basis": "explicit_seeded_protocol_fixture_not_public_dispatch_or_maintainer_approval"}
