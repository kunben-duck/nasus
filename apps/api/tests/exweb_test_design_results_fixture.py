"""Real PG/MinIO result persistence using an explicitly synthetic model receipt."""
from apps.api.app.application.quality_loop.test_design_results import TestDesignResultApplicationService
from apps.api.app.infrastructure.persistence.test_design_result_repository import TestDesignResultRepository
from apps.api.app.infrastructure.storage.test_design_result_artifacts import TestDesignResultArtifacts
from apps.api.app.infrastructure.storage.generation_batch_reply_artifacts import GenerationBatchReplyArtifacts
from apps.api.tests.test_design_result_fixture import seed_generation_execution


def archive_exweb_generation_fixture(generation, selection, authorization, profiles, model_config, storage):
    service = TestDesignResultApplicationService(generation, authorization, profiles,
        TestDesignResultRepository(), TestDesignResultArtifacts(storage), batch_replies=GenerationBatchReplyArtifacts(storage))
    execution = seed_generation_execution(service, selection, authorization.scope(selection.project_id).actor_id, config=model_config)
    args = {k: execution[k] for k in ("request", "invocation_id", "call_id", "content")}
    metadata = service.commit(**args)
    view = service.read(selection.project_id, metadata["generation_id"])
    assert view["metadata"] == metadata and view["current_use"]["scope_current"]
    assert service.commit(**args) == metadata
    stored = service.repository.get(selection.project_id, metadata["generation_id"])
    assert stored["artifact_ref"].startswith("s3://")
    coverage = view["result"]["proposal"]["coverage"]
    assert coverage["constraint_denominator"] == coverage["planned_constraint_count"] == 2
    assert coverage["obligation_denominator"] == coverage["planned_obligation_count"] == 8
    assert coverage["passed_count"] == coverage["executed_on_target_count"] == coverage["assertion_mapped_count"] == 0
    return service, view, {"metadata": metadata, "minio_roundtrip_verified": True,
        "proposal_source": "explicit_protocol_fixture_not_model_generation", "native_provider_invoked": False,
        "synthetic_usage_not_actual_tokens": True, "persisted_case_count": len(stored["cases"]),
        "coverage": coverage, "idempotent_recovery_verified": True, "target_executed": False}
