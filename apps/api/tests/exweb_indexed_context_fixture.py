"""Exweb context compilation consumes saved trace pins, never another provider request."""
from uuid import uuid4

from apps.api.app.application.system_image.context_pack_inputs import ContextPreviewInput, ContextCompileInput
from apps.api.app.application.system_image.indexed_context_recall import IndexedContextRecall
from apps.api.app.domain.system_image.context_pack import COMPILE_CONTEXT_TOOL, canonical_bytes
from apps.api.app.domain.system_image.context_partition import INDEXED_CONTEXT_POLICY
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope


def compile_exweb_indexed_context(packs, index, published_preview, bindings, recorded_at):
    packs.sources.indexed_recall = IndexedContextRecall(index, packs.sources.image_queries.screened_candidates)
    assert set(bindings) == {item["object_id"] for item in published_preview["context"]["required_constraints"]
        if item["kind"] == "acceptance_criterion"}
    request = ContextPreviewInput.model_validate({**published_preview["request"],
        "policy_revision": INDEXED_CONTEXT_POLICY, "retrieval_bindings": bindings})
    provider = index.provider
    class NoProvider:
        async def embed(self, *args, **kwargs):
            raise AssertionError("Context derivation must replay, not issue an embedding request")
    index.provider = NoProvider()
    try:
        view = packs.preview(request)
        assert view["context"]["required_constraints"] == published_preview["context"]["required_constraints"]
        assert view["context"]["retrieval"]["method"] == "nasus.link-recall.indexed-reviewed.v3"
        assert view["context"]["retrieval"]["fallback_used"] is False
        command = ContextCompileInput.model_validate({**view["request"], "expected_input_digest": view["input_digest"]})
        invocation_id = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=invocation_id, tool_id=COMPILE_CONTEXT_TOOL, status="running",
                summary="Explicit exweb indexed context fixture; not business approval",
                input_payload={**command.model_dump(mode="json"), "confirmed_by_user": True}))
        metadata = packs.compile(command, invocation_id=invocation_id, recorded_at=recorded_at)
        history = packs.read(request.project_id, metadata["context_id"])
        assert history["current_use"] == {"stale": False, "generation_authorized": False, "reason": "draft_investigation_only"}
        assert canonical_bytes(history["context"]) == canonical_bytes(view["context"])
        for part in history["context"]["parts"]:
            assert len(canonical_bytes(part["context"])) == part["context"]["budget"]["used_upper_bound"] <= request.max_tokens
        _, ref = packs.repository.get(request.project_id, metadata["context_id"])
        assert ref.startswith("s3://")
        artifact = packs.artifacts.read(request.project_id, ref, metadata["artifact_hash"])
        assert len(artifact["provenance"]["retrieval_runs"]) == 2 * len(bindings)
        assert {item["trace_pin"]["retrieval_id"] for item in artifact["provenance"]["retrieval_runs"]} == set(bindings.values())
        assert packs.compile(command, invocation_id=invocation_id, recorded_at="retry") == metadata
        report = {"metadata": metadata, "retrieval_bindings": bindings, "minio_roundtrip_verified": True,
            "all_mandatory_constraints_preserved": True, "compile_and_replay_without_model_egress": True,
            "fixed_trace_derivation_verified": True, "lost_completion_no_duplicate_archive": True,
            "complete_source_ac_queries_automatically_bound": True,
            "quality_generation_authorized": False}
        return request, command, history, report
    finally:
        index.provider = provider
