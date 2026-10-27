"""Opt-in real MinIO roundtrip; use test-api-postgres.py for disposable PostgreSQL."""
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from apps.api.app.application.system_image.context_extraction import ContextExtractionService
from apps.api.app.application.system_image.document_projections import DocumentProjectionApplicationService
from apps.api.app.application.system_image.image_candidates import ImageCandidateApplicationService
from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.domain.system_image.source_snapshots import SourceSnapshotArtifact
from apps.api.app.infrastructure.persistence.code_entity_repository import CodeEntityRepository
from apps.api.app.infrastructure.persistence.document_projection_repository import DocumentProjectionRepository
from apps.api.app.infrastructure.persistence.image_revision_repository import ImageRevisionRepository
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.archived_document_projection import ArchivedDocumentProjection
from apps.api.app.infrastructure.system_image.document_artifacts import DocumentArtifacts
from apps.api.app.infrastructure.system_image.explicit_document_extractor import ExplicitDocumentExtractor
from apps.api.app.infrastructure.system_image.image_artifacts import ArchivedImageArtifacts
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.tests.exweb_frozen_index_fixture import build_exweb_index
from apps.api.tests.exweb_indexed_context_fixture import compile_exweb_indexed_context
from apps.api.tests.exweb_test_design_scope_fixture import review_exweb_test_design_scope
from apps.api.tests.exweb_test_design_generation_fixture import verify_exweb_generation_contract
from apps.api.tests.exweb_test_design_results_fixture import archive_exweb_generation_fixture
from apps.api.tests.exweb_native_generation_fixture import verify_exweb_native_generation
from apps.api.tests.exweb_test_design_mapping_fixture import review_exweb_test_design_mapping, find_exweb_review_draft


def test_exweb_code_and_companion_documents_survive_minio_roundtrip(tmp_path):
    report_file = os.getenv("EXWEB_PROBE_REPORT")
    if not report_file or not os.getenv("EXWEB_MINIO_ENDPOINT"):
        pytest.skip("explicit exweb report and MinIO opt-in required")
    url = make_url(os.environ["NASUS_DATABASE_URL"])
    assert url.get_backend_name() == "postgresql" and url.database.startswith("nasus_test_")
    report = json.loads(Path(report_file).read_text())
    assert report["repository"] == "https://github.com/kunben-duck/exweb.git"
    assert report["revision"] == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    written = set()

    class RecordingStorage(ObjectStorage):
        def put_bytes(self, *args, **kwargs):
            result = super().put_bytes(*args, **kwargs)
            written.add(result.key)
            return result

    config = ObjectStorageConfig(os.environ["EXWEB_MINIO_ENDPOINT"], os.environ["EXWEB_MINIO_BUCKET"],
        os.environ["EXWEB_MINIO_ACCESS_KEY"], os.environ["EXWEB_MINIO_SECRET_KEY"], "us-east-1", tmp_path)
    storage = RecordingStorage(config)
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "snapshots")
    snapshots = SourceSnapshotRepository()
    snapshot = SourceSnapshotArtifact(**report["source_snapshot"])
    code = RawAssetRecord(id=report["source_id"], project_id=report["project_id"], source_type="code",
        source_uri=report["repository"], ingestion_status="indexed", content_ref=snapshot.manifest_ref, content_hash=snapshot.content_hash)
    now = datetime.now(timezone.utc).isoformat()
    snapshots.record_capture(code, snapshot, captured_at=now)
    sources = [code]
    try:
        for kind, filename in (("us_doc", "exweb-requirements.md"), ("test_asset", "exweb-test-cases.csv")):
            local_document = tmp_path / filename
            local_document.write_text(Path("tests/fixtures/system-image", filename).read_text())
            source = RawAssetRecord(id=f"verification-{uuid4().hex}", project_id=code.project_id, source_type=kind,
                source_uri=str(local_document))
            captured = reader.ingest(source)
            assert captured.snapshot and captured.content_ref.startswith("s3://")
            snapshots.record_capture(source, captured.snapshot, captured_at=now)
            sources.append(source.model_copy(update={"content_ref": captured.content_ref, "content_hash": captured.content_hash,
                                                    "ingestion_status": "indexed"}))
        manifest = snapshots.freeze_manifest(code.project_id, sources, captured_at=now)
        doc_artifacts = DocumentArtifacts(storage)
        docs = DocumentProjectionRepository()
        context = ContextExtractionService(reader, TreeSitterCodeIntelligenceAdapter(), code_entity_registry=CodeEntityRepository(),
            document_projections=DocumentProjectionApplicationService(ExplicitDocumentExtractor(),
                ArchivedDocumentProjection(reader.snapshots, doc_artifacts, docs)))
        extracted = context.extract(project_id=code.project_id, project_name="exweb verification", baseline_id="exweb-documents",
            sources=snapshots.materialization_sources(manifest), version_id=None, captured_at=now)
        registry = ImageRevisionRepository()
        images = ArchivedImageArtifacts(storage)
        header = ImageCandidateApplicationService(images, registry).freeze(manifest, "exweb-documents", objects=extracted.objects,
            relationships=extracted.relationships, invocation_id="minio-verification", recorded_at=now)
        assert header.code_member_count == 725
        _, ref, _ = registry.get(code.project_id, header.image_revision_id)
        assert ref.startswith("s3://")
        frozen = images.read(code.project_id, ref, header.artifact_hash)
        members = [item for item in frozen["members"] if item["kind"] == "source_document"]
        assert len(members) == 4 and len(frozen["source_members"]) == 3
        from apps.api.app.infrastructure.persistence.source_evidence_repository import SourceEvidenceRepository
        from apps.api.app.infrastructure.system_image.evidence_source_reader import ArchivedEvidenceSourceReader
        from apps.api.app.domain.system_image.evidence import source_lines, text_digest
        evidence_reader = ArchivedEvidenceSourceReader(storage, max_files=5000, max_bytes=100 * 1024 * 1024, max_file_bytes=10 * 1024 * 1024)
        reviewed = []
        bindings = frozenset(item.binding_id for item in manifest.members)
        for member in members:
            summary, document_ref, digest, _ = docs.get(code.project_id, member["document_revision_id"], binding_ids=bindings)
            payload = DocumentArtifacts(storage).read(code.project_id, document_ref, digest)
            assert document_ref.startswith("s3://") and payload["semantic_status"] == "source_projection_not_approved_specification"
            for evidence_id in member["evidence_ids"]:
                target = SourceEvidenceRepository().get(code.project_id, evidence_id)
                raw = evidence_reader.read(target)
                lines = source_lines(raw.decode("utf-8"))
                locator = target.evidence.locator
                assert text_digest("".join(lines[locator.start_line - 1:locator.end_line])) == target.evidence.snippet_hash
            if payload.get("parent"):
                assert payload["authority_status"] == "pending_confirmation"
                parent_id = summary["parent_document_revision_id"]
                assert any(item["document_revision_id"] == parent_id for item in members)
                _, parent_ref, parent_hash, _ = docs.get(code.project_id, parent_id, binding_ids=bindings)
                assert parent_hash == payload["parent"]["payload_hash"]
                parent = DocumentArtifacts(storage).read(code.project_id, parent_ref, parent_hash)
                assert payload["fields"] == [parent["fields"][i] for i in payload["parent"]["field_indices"]]
            reviewed.append({"kind": summary["kind"], "payload_hash": digest, "evidence_count": len(member["evidence_ids"]),
                "parent_document_revision_id": summary.get("parent_document_revision_id"),
                "parent_payload_hash": payload.get("parent", {}).get("payload_hash")})
        from apps.api.app.application.system_image.document_queries import DocumentQueryApplicationService
        from apps.api.app.application.system_image.evidence_queries import EvidenceQueryApplicationService
        from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
        from apps.api.app.application.system_image.reference_links import ReferenceLinkApplicationService, ReferenceProposalInput
        from apps.api.app.application.system_image.source_access import SourceAccessApplicationService
        from apps.api.app.infrastructure.persistence.reference_link_repository import ReferenceLinkRepository
        from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
        from apps.api.app.infrastructure.persistence.db_models import ProjectRecord, ToolInvocationRecord
        from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
        with session_scope() as session:
            session.add(ProjectRecord(id=code.project_id, name="exweb", code="EXW", summary="Static fixture validation"))
        # This adapter test uses an explicit actor double; real RBAC, ToolRuntime
        # and invocation authorization are exercised by HTTP and browser tests.
        actor = SimpleNamespace(
            current_actor=lambda: SimpleNamespace(id="exweb-reference-reviewer", role="platform_admin"),
            effective_user_for_project=lambda *a, **kw: SimpleNamespace(id="exweb-reference-reviewer", role="platform_admin"),
            require_project_access=lambda *a, **kw: None)
        authorization = SourceAccessApplicationService(SourceAccessRepository(), actor)
        evidence = EvidenceQueryApplicationService(SourceEvidenceRepository(), evidence_reader, actor, authorization)
        document_queries = DocumentQueryApplicationService(docs, doc_artifacts, authorization)
        image_queries = ImageRevisionQueryApplicationService(registry, images, authorization, evidence, document_queries)
        for member in members:
            projected = document_queries.read(code.project_id, member["document_revision_id"])
            assert projected["document"]["document_revision_id"] == member["document_revision_id"]
        from apps.api.app.application.system_image.image_query_models import ImageLinkCandidatesInput
        from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
        query_tools = ImageQueryToolApplicationService(image_queries)
        ac_member = next(item for item in members if document_queries.read(code.project_id,
            item["document_revision_id"])["projection"]["kind"] == "acceptance_criterion")
        recalled = {}
        for relation in ("implements", "asserts"):
            request = ImageLinkCandidatesInput(project_id=code.project_id, image_revision_id=header.image_revision_id,
                                               target_object_id=ac_member["object_id"], relation=relation)
            receipt = query_tools.execute(request)
            recalled[relation] = query_tools.expand(receipt)
            assert recalled[relation].target.revision_id == ac_member["document_revision_id"]
            assert recalled[relation].authority_status == "pending_confirmation"
            assert all(item.status == "retrieved_not_asserted" and item.calibrated_probability is None for item in recalled[relation].items)
            assert "Chat" not in receipt.model_dump_json() and "US-EXWEB" not in receipt.model_dump_json()
        assert any("ChatController" in item.endpoint.title for item in recalled["implements"].items)
        assert recalled["implements"].eligible_count == 725
        assert len(recalled["asserts"].items) == 1 and recalled["asserts"].items[0].endpoint.kind == "test_case"
        from apps.api.app.application.system_image.semantic_link_inputs import SemanticLinkInputApplicationService
        from apps.api.app.application.system_image.semantic_link_output import validate_semantic_output
        from apps.api.app.application.system_image.semantic_evaluations import SemanticEvaluationApplicationService, SemanticSelection
        from apps.api.app.application.platform.model_execution_profiles import ModelExecutionProfileApplicationService
        from apps.api.app.infrastructure.llm.semantic_link_model import HTTPSemanticLinkModel
        from apps.api.app.infrastructure.persistence.settings_repository import SettingsRepository
        from apps.api.app.infrastructure.persistence.semantic_evaluation_repository import SemanticEvaluationRepository
        from apps.api.app.infrastructure.persistence.llm_call_repository import SQLAlchemyLLMCallRepository
        from apps.api.app.infrastructure.system_image.semantic_evaluation_artifacts import SemanticEvaluationArtifacts
        from apps.api.app.application.system_image.semantic_review import SemanticReviewApplicationService, SemanticReviewInput
        from apps.api.app.domain.system_image.semantic_review import SEMANTIC_REVIEW_TOOL
        from apps.api.app.infrastructure.persistence.semantic_review_repository import SemanticReviewRepository
        from apps.api.tests.test_semantic_link_model import saved_config, native_reply
        import asyncio
        import httpx
        semantic_inputs = {}
        semantic_evaluations = {}
        semantic_decisions = {}
        semantic_review_requests = {}
        semantic_history_receipts = {}
        settings = SettingsRepository()
        model_config = saved_config(config_id=str(uuid4()))
        settings.save_model_config(model_config, "test-only-encrypted-key")
        # No external provider credentials or network: exercise the real native
        # HTTP adapter with an explicit synthetic response at the transport seam.
        model_profiles = ModelExecutionProfileApplicationService(settings,
            SimpleNamespace(decrypt_api_key=lambda value: "test-only-provider-key"))
        preparation = SemanticLinkInputApplicationService(image_queries)
        for relation in ("implements", "asserts"):
            subject = (next(item.endpoint for item in recalled[relation].items
                            if item.endpoint.title.startswith("chatStream (") and "ChatController.java" in item.endpoint.title)
                       if relation == "implements" else recalled[relation].items[0].endpoint)
            prepared = preparation.prepare(code.project_id, header.image_revision_id, ac_member["object_id"],
                relation=relation, subject_object_ids=(subject.object_id,), expected_image_hash=header.artifact_hash)
            assert prepared.target.revision_id == ac_member["document_revision_id"]
            assert prepared.subjects[0].revision_id == subject.revision_id
            target_span = next(item for item in prepared.excerpts if item.object_id == prepared.target.object_id)
            subject_span = next(item for item in prepared.excerpts if item.object_id == subject.object_id)
            assert subject_span.role == ("implementation" if relation == "implements" else "expected_result")
            assert subject_span.basis == ("source_excerpt" if relation == "implements" else "projected_field")
            # Synthetic output exercises the contract, not an LLM or a business judgment.
            quotes = [{"span_id": item.span_id, "start": 0, "end": min(256, len(item.text)), "quote": item.text[:256]}
                      for item in (target_span, subject_span)]
            output = {"schema_version": "nasus.semantic-link-output.v1", "input_digest": prepared.digest, "judgments": [{
                "subject_object_id": subject.object_id, "subject_revision_id": subject.revision_id,
                "target_object_id": prepared.target.object_id, "target_revision_id": prepared.target.revision_id,
                "relation": relation, "assessment": "unknown", "reason_summary": "Synthetic contract fixture, requires actual semantic review.",
                "evidence": quotes, "counterevidence": [], "unknowns": ["An independently approved expected content type is not supplied."],
                "oracle": None}]}
            evaluated = validate_semantic_output(prepared, json.dumps(output))
            assert evaluated.status == "proposed" and evaluated.calibrated_probability is None
            assert evaluated.authority_status == "pending_confirmation"
            native_calls = []
            wire_output = json.dumps(output)
            def native_response(request):
                native_calls.append(request)
                payload = json.loads(json.loads(request.content)["messages"][1]["content"])
                assert payload["input_digest"] == prepared.digest
                return httpx.Response(200, json=native_reply("openai_compatible", wire_output))
            semantic = SemanticEvaluationApplicationService(image_queries, model_profiles,
                HTTPSemanticLinkModel(transport=httpx.MockTransport(native_response)), SemanticEvaluationRepository(),
                SemanticEvaluationArtifacts(storage), SQLAlchemyLLMCallRepository())
            from apps.api.app.application.system_image.semantic_applicability import SemanticApplicabilityApplicationService
            from apps.api.app.application.system_image.semantic_screening import SemanticScreeningApplicationService
            semantic_reviews = SemanticReviewApplicationService(semantic, authorization, SemanticReviewRepository())
            semantic.decision_guard = SemanticScreeningApplicationService(
                SemanticApplicabilityApplicationService(image_queries, semantic_reviews), semantic_reviews.repository)
            selection = SemanticSelection(project_id=code.project_id, image_revision_id=header.image_revision_id,
                expected_image_hash=header.artifact_hash, target_object_id=prepared.target.object_id,
                relation=relation, subject_object_ids=[subject.object_id], model_config_id=model_config.config_id)
            preview = semantic.preview(selection)
            assert preview.request.input_digest == prepared.digest and not native_calls
            semantic_invocation = str(uuid4())
            with session_scope() as session:
                session.add(ToolInvocationRecord(id=semantic_invocation, tool_id="system_image.links.evaluate", status="running",
                    summary="Synthetic transport verification with fixed exweb evidence",
                    input_payload={**preview.request.model_dump(), "confirmed_by_user": True,
                                   "confirmed_at": datetime.now(timezone.utc).isoformat()}))
            saved_evaluation = asyncio.run(semantic.evaluate(preview.request, invocation_id=semantic_invocation))
            assert len(native_calls) == 1
            assert saved_evaluation["evaluation"] == asdict(evaluated)
            saved_row = semantic.repository.get(code.project_id, semantic_invocation)
            assert saved_row["artifact_ref"].startswith("s3://")
            assert semantic.read(code.project_id, semantic_invocation) == saved_evaluation
            assert asyncio.run(semantic.evaluate(preview.request, invocation_id=semantic_invocation)) == saved_evaluation
            assert len(native_calls) == 1
            audited, = semantic.audit.list_llm_calls(tool_invocation_id=semantic_invocation)
            assert audited.outcome == "success" and audited.model_calls == 1
            review_page = semantic_reviews.read(code.project_id, semantic_invocation, subject.object_id)
            from apps.api.app.application.system_image.image_query_models import ImageSemanticDecisionInput
            semantic_query = ImageQueryToolApplicationService(image_queries, semantic_reviews=semantic_reviews)
            history_selection = ImageSemanticDecisionInput(project_id=code.project_id, evaluation_id=semantic_invocation,
                subject_object_id=subject.object_id)
            empty_history = semantic_query.execute(history_selection)
            assert semantic_query.expand(empty_history).head is None
            pinned_assertion = review_page["assertion"]
            assert not pinned_assertion["can_accept"] and review_page["total"] == 0
            review_request = SemanticReviewInput(**{key: pinned_assertion[key] for key in (
                "project_id", "evaluation_id", "subject_object_id", "assertion_id", "assertion_digest", "evidence_digest")},
                expected_previous_decision_id=None, policy_revision=review_page["policy_revision"], decision="defer",
                reason="Fixture has no independently approved business oracle; retain the unknown relation.")
            review_id = str(uuid4())
            with session_scope() as session:
                session.add(ToolInvocationRecord(id=review_id, tool_id=SEMANTIC_REVIEW_TOOL, status="running",
                    summary="Fixed exweb semantic review verification", input_payload={**review_request.model_dump(), "confirmed_by_user": True}))
            semantic_decision = semantic_reviews.review(review_request, invocation_id=review_id, recorded_at=now)
            semantic_decisions[relation] = semantic_decision
            semantic_review_requests[relation] = review_request
            assert semantic_reviews.review(review_request, invocation_id=review_id, recorded_at=now) == semantic_decision
            read_review = semantic_reviews.read(code.project_id, semantic_invocation, subject.object_id)
            assert read_review["items"] == [asdict(semantic_decision)] and read_review["head_decision_id"] == semantic_decision.decision_id
            assert read_review["assertion"] == pinned_assertion and read_review["publication"] == "not_in_image_membership"
            history_receipt = semantic_query.execute(history_selection)
            semantic_history_receipts[relation] = history_receipt
            assert semantic_query.expand(history_receipt).items == (asdict(semantic_decision),)
            assert semantic_query.expand(empty_history).items == ()
            assert review_request.reason not in history_receipt.model_dump_json()
            assert "Chat" not in history_receipt.model_dump_json() and "s3://" not in history_receipt.model_dump_json()
            with pytest.raises(ValueError, match="supported, grounded"):
                semantic_reviews.review(review_request.model_copy(update={"decision": "accept"}), invocation_id=str(uuid4()), recorded_at=now)
            assert len(native_calls) == 1
            semantic_evaluations[relation] = {"artifact_hash": saved_evaluation["artifact_hash"],
                "evaluation_digest": evaluated.digest, "native_transport_calls": len(native_calls),
                "reservation_persisted": True, "private_minio_roundtrip": True, "replay_did_not_call_model": True,
                "external_model_called": False, "response_origin": "synthetic_native_transport_not_semantic_acceptance",
                "review": {"assertion_id": pinned_assertion["assertion_id"], "claim_id": pinned_assertion["claim_id"],
                    "assertion_digest": pinned_assertion["assertion_digest"], "decision_id": semantic_decision.decision_id,
                    "decision_digest": semantic_decision.digest, "decision": semantic_decision.decision,
                    "durable_roundtrip": True, "idempotent_replay": True, "unknown_acceptance_rejected": True,
                    "publication": read_review["publication"]}}
            output["judgments"][0]["evidence"][1]["quote"] += "invented"
            with pytest.raises(ValueError, match="exact verified text"):
                validate_semantic_output(prepared, json.dumps(output))
            semantic_inputs[relation] = {"input_digest": prepared.digest, "evaluation_digest": evaluated.digest,
                "subject_revision_id": subject.revision_id, "target_revision_id": prepared.target.revision_id,
                "excerpt_count": len(prepared.excerpts), "verified_span_ids": [item.span_id for item in prepared.excerpts],
                "authority_status": evaluated.authority_status, "status": evaluated.status,
                "assessment": evaluated.judgments[0].assessment,
                "external_model_called": False, "response_origin": "synthetic_contract_fixture_not_semantic_acceptance"}
        references = ReferenceLinkApplicationService(image_queries, ReferenceLinkRepository(), authorization)
        request = ReferenceProposalInput(project_id=code.project_id, image_revision_id=header.image_revision_id)
        invocation_id = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=invocation_id, tool_id="system_image.links.propose_references", status="running",
                summary="Static reference verification", input_payload=request.model_dump()))
        proposal = references.propose(request, invocation_id=invocation_id, created_at=now)
        page = references.read(code.project_id, proposal.proposal_id)
        assert page.assertion_count == 1 and page.gap_count == 0
        assert page.items[0]["reference_id"] == "US-EXWEB-CHAT" and page.items[0]["predicate"] == "references"
        assert page.items[0]["status"] == "proposed" and page.publication == "not_in_image_membership"
        assert references.propose(request, invocation_id=invocation_id, created_at=now) == proposal
        from apps.api.app.application.system_image.link_decisions import LinkDecisionApplicationService, LinkReviewInput
        from apps.api.app.infrastructure.persistence.link_decision_repository import LinkDecisionRepository
        reviews = LinkDecisionApplicationService(references, LinkDecisionRepository())
        history = reviews.read(code.project_id, proposal.proposal_id, page.items[0]["assertion_id"])
        review_input = LinkReviewInput(**{key: getattr(history, key) for key in (
            "project_id", "proposal_id", "assertion_id", "proposal_digest", "evidence_digest", "policy_revision")},
            expected_previous_decision_id=None, decision="defer", reason="Verification fixture, not an approved business oracle")
        review_invocation = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=review_invocation, tool_id="system_image.links.review", status="running",
                summary="Reference review verification", input_payload={**review_input.model_dump(), "confirmed_by_user": True}))
        decision = reviews.review(review_input, invocation_id=review_invocation, recorded_at=now)
        assert decision.decision == "defer" and decision.sequence == 1
        assert reviews.review(review_input, invocation_id=review_invocation, recorded_at=now) == decision
        assert references.propose(request, invocation_id=invocation_id, created_at=now) == proposal
        assert reviews.read(code.project_id, proposal.proposal_id, decision.assertion_id).items == (decision,)
        from apps.api.app.application.system_image.image_membership import ImageMembershipApplicationService, ImageReviewFreezeInput
        freeze_request = ImageReviewFreezeInput(project_id=code.project_id, parent_revision_id=header.image_revision_id,
            parent_artifact_hash=header.artifact_hash, proposal_id=proposal.proposal_id,
            proposal_digest=proposal.digest, decision_ids=(decision.decision_id,))
        freeze_invocation = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=freeze_invocation, tool_id="system_image.revisions.freeze_links", status="running",
                summary="Freeze reviewed references verification", input_payload={**freeze_request.model_dump(mode="json"), "confirmed_by_user": True}))
        membership = ImageMembershipApplicationService(image_queries, reviews)
        child = membership.freeze(freeze_request, invocation_id=freeze_invocation, recorded_at=now)
        assert child.parent_revision_id == header.image_revision_id and child.assertion_count == 1
        assert child.code_member_count == 725 and child.artifact_hash != header.artifact_hash
        frozen_reviews = image_queries.read(code.project_id, child.image_revision_id, section="assertion_members")
        assert frozen_reviews.items[0]["decision_id"] == decision.decision_id and frozen_reviews.items[0]["decision"] == "defer"
        assert membership.freeze(freeze_request, invocation_id=freeze_invocation, recorded_at=now) == child
        assert image_queries.read(code.project_id, header.image_revision_id, section="assertion_members").total == 0
        revised_input = review_input.model_copy(update={"expected_previous_decision_id": decision.decision_id,
            "decision": "reject", "reason": "Later fixture-only review; do not rewrite historical candidate"})
        later_invocation = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=later_invocation, tool_id="system_image.links.review", status="running",
                summary="Later reference review verification", input_payload={**revised_input.model_dump(), "confirmed_by_user": True}))
        later = reviews.review(revised_input, invocation_id=later_invocation, recorded_at=now)
        assert later.decision == "reject"
        # Retry after commit/status loss reuses the committed output, even after a later review.
        assert membership.freeze(freeze_request, invocation_id=freeze_invocation, recorded_at=now) == child
        assert image_queries.read(code.project_id, child.image_revision_id, section="assertion_members") == frozen_reviews
        from apps.api.app.application.system_image.semantic_membership import SemanticMembershipApplicationService, SemanticFreezeInput
        from apps.api.app.domain.system_image.semantic_membership import FREEZE_SEMANTIC_TOOL
        semantic_freezes = SemanticMembershipApplicationService(image_queries, semantic_reviews)
        semantic_freeze = SemanticFreezeInput(project_id=code.project_id, parent_revision_id=child.image_revision_id,
            parent_artifact_hash=child.artifact_hash, decision_ids=tuple(d.decision_id for d in semantic_decisions.values()))
        semantic_freeze_id = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=semantic_freeze_id, tool_id=FREEZE_SEMANTIC_TOOL, status="running",
                summary="Freeze exweb implements/asserts reviews with inherited references",
                input_payload={**semantic_freeze.model_dump(mode="json"), "confirmed_by_user": True}))
        semantic_child = semantic_freezes.freeze(semantic_freeze, invocation_id=semantic_freeze_id, recorded_at=now)
        assert semantic_child.policy_version == "nasus.image-candidate.v3" and semantic_child.assertion_count == 3
        semantic_page = image_queries.read(code.project_id, semantic_child.image_revision_id, section="semantic_assertion_members")
        assert {item["assertion"]["predicate"] for item in semantic_page.items} == {"implements", "asserts"}
        assert {item["decision"]["decision"] for item in semantic_page.items} == {"defer"}
        assert image_queries.read(code.project_id, semantic_child.image_revision_id, section="assertion_members").items == frozen_reviews.items
        revised_semantic = semantic_review_requests["asserts"].model_copy(update={"decision": "reject",
            "expected_previous_decision_id": semantic_decisions["asserts"].decision_id,
            "reason": "Later fixture review must not rewrite frozen semantic membership."})
        revised_semantic_id = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=revised_semantic_id, tool_id=SEMANTIC_REVIEW_TOOL, status="running",
                summary="Recheck frozen semantic history", input_payload={**revised_semantic.model_dump(), "confirmed_by_user": True}))
        semantic_reviews.review(revised_semantic, invocation_id=revised_semantic_id, recorded_at=now)
        for relation, history_receipt in semantic_history_receipts.items():
            assert semantic_query.expand(history_receipt).items == (asdict(semantic_decisions[relation]),)
        assert semantic_freezes.freeze(semantic_freeze, invocation_id=semantic_freeze_id, recorded_at=now) == semantic_child
        assert image_queries.read(code.project_id, semantic_child.image_revision_id, section="semantic_assertion_members") == semantic_page
        # Reference admission on a v3 parent must retain exact semantic snapshots,
        # including a decision no longer at the mutable semantic review head.
        mixed_request = freeze_request.model_copy(update={"parent_revision_id": semantic_child.image_revision_id,
            "parent_artifact_hash": semantic_child.artifact_hash, "decision_ids": (later.decision_id,)})
        mixed_id = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=mixed_id, tool_id="system_image.revisions.freeze_links", status="running",
                summary="Preserve semantic members while updating references", input_payload={**mixed_request.model_dump(mode="json"), "confirmed_by_user": True}))
        mixed = membership.freeze(mixed_request, invocation_id=mixed_id, recorded_at=now)
        assert mixed.policy_version == "nasus.image-candidate.v3" and mixed.assertion_count == 3
        assert image_queries.read(code.project_id, mixed.image_revision_id, section="semantic_assertion_members").items == semantic_page.items
        assert image_queries.read(code.project_id, mixed.image_revision_id, section="assertion_members").items[0]["decision"] == "reject"
        from apps.api.app.application.system_image.image_query_models import ImageSemanticApplicabilityInput, ImageScreenedCandidatesInput
        applicability_receipts, applicability, screening_results = {}, {}, {}
        screened_recalls, screened_receipts = {}, {}
        for relation, old_decision in semantic_decisions.items():
            request = semantic_review_requests[relation]
            assertion = semantic_reviews.assertion(code.project_id, request.evaluation_id, request.subject_object_id)
            receipt = semantic_query.execute(ImageSemanticApplicabilityInput(project_id=code.project_id,
                image_revision_id=mixed.image_revision_id, expected_image_hash=mixed.artifact_hash,
                source_decision_id=old_decision.decision_id, subject_object_id=assertion.subject_object_id,
                target_object_id=assertion.object_id))
            comparison = semantic_query.expand(receipt)
            assert comparison.source_image_revision_id != comparison.image_revision_id
            assert comparison.original_subject.entity_id == comparison.subject.entity_id
            assert comparison.original_target.entity_id == comparison.target.entity_id
            assert comparison.assessment.status == ("rejected_same_revisions" if relation == "asserts" else "same_revisions_review_required")
            assert not comparison.assessment.approval_transferred
            assert "reason" not in str(receipt.model_dump()) and "s3://" not in str(receipt.model_dump())
            applicability_receipts[relation] = receipt.model_dump(mode="json")
            applicability[relation] = asdict(comparison)
            screened = semantic.preview(SemanticSelection(project_id=code.project_id, image_revision_id=mixed.image_revision_id,
                expected_image_hash=mixed.artifact_hash, target_object_id=assertion.object_id, relation=relation,
                subject_object_ids=[assertion.subject_object_id], model_config_id=model_config.config_id))
            hit, = screened.review_screening
            assert hit.head_decision_id == comparison.head_decision_id and hit.status == comparison.assessment.status
            screening_results[relation] = screened.model_dump(mode="json")
            recall_receipt = semantic_query.execute(ImageScreenedCandidatesInput(project_id=code.project_id,
                image_revision_id=mixed.image_revision_id, target_object_id=assertion.object_id, relation=relation, limit=30))
            recall_page = semantic_query.expand(recall_receipt)
            assert recall_page.review_scope == "pinned_query_heads_not_live"
            assert recall_page.excluded["historical_review"] == (1 if relation == "asserts" else 0)
            matching = [item for item in recall_page.items if item.endpoint.object_id == assertion.subject_object_id]
            if relation == "asserts":
                assert not matching
            else:
                assert matching and matching[0].review_status == "reviewed_not_approved"
            screened_recalls[relation] = asdict(recall_page)
            screened_receipts[relation] = recall_receipt
            if relation == "asserts":
                # A new image and fresh consent cannot bypass an unchanged reject.
                with pytest.raises(ValueError, match="blocks model egress"):
                    asyncio.run(semantic.evaluate(screened.request, invocation_id=str(uuid4())))
                assert len(native_calls) == 1
        from apps.api.app.application.quality_loop.acceptance_specifications import AcceptanceSpecificationApplicationService, AcceptanceReviewInput
        from apps.api.app.application.system_image.acceptance_sources import FrozenAcceptanceSourceApplicationService
        from apps.api.app.domain.quality_loop.acceptance_specification import AC_TOOL, AC_POLICY, StaleAcceptanceSpecification
        from apps.api.app.infrastructure.persistence.acceptance_specification_repository import AcceptanceSpecificationRepository
        from apps.api.app.infrastructure.storage.acceptance_artifacts import AcceptanceSpecificationArtifacts
        authority = AcceptanceSpecificationApplicationService(FrozenAcceptanceSourceApplicationService(image_queries), authorization,
            AcceptanceSpecificationRepository(), AcceptanceSpecificationArtifacts(storage))
        authority_preview = authority.inspect(code.project_id, header.image_revision_id, header.artifact_hash, ac_member["object_id"])
        assert authority_preview["head"] is None
        # A fixture reviewer confirms a companion requirement. This exercises authority
        # provenance, not independent approval of exweb's real business requirements.
        approval = AcceptanceReviewInput(project_id=code.project_id, image_revision_id=header.image_revision_id,
            image_artifact_hash=header.artifact_hash, object_id=ac_member["object_id"], basis_digest=authority_preview["basis_digest"],
            expected_previous_revision_id=None, decision="approve", authority_basis="user_confirmed_requirement", policy_revision=AC_POLICY,
            oracle={"preconditions": "Authorized isolated test environment", "action": "POST the documented finance chat request",
                    "observation": "HTTP response content type", "expected_result": "The documented event-stream content type"},
            reason="Companion test fixture only; not exweb maintainer approval or observed execution")
        def record_authority(request):
            ident = str(uuid4())
            with session_scope() as session:
                session.add(ToolInvocationRecord(id=ident, tool_id=AC_TOOL, status="running", summary="Verify AC authority storage",
                    input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True}))
            return authority.review(request, invocation_id=ident, recorded_at=now)
        approved_ac = record_authority(approval)
        approved_ac_body = authority.read(code.project_id, approved_ac.revision_id)
        assert authority.repository.get(code.project_id, approved_ac.revision_id)[1].startswith("s3://")
        assert authority.resolve_oracle(code.project_id, header.image_revision_id, ac_member["object_id"], approved_ac.revision_id,
                                        approved_ac.artifact_hash) == approved_ac_body
        before_replay = set(written)
        assert authority.review(approval, invocation_id=approved_ac.invocation_id, recorded_at="recovery") == approved_ac
        assert written == before_replay
        assert authority_preview["basis"]["source_authority"] == "unapproved_source_projection"
        from apps.api.app.application.quality_loop.business_rules import BusinessRuleApplicationService, BusinessRuleReviewInput
        from apps.api.app.application.system_image.acceptance_sources import FrozenBusinessRuleSourceApplicationService
        from apps.api.app.domain.quality_loop.business_rule import RULE_TOOL, RULE_POLICY
        from apps.api.app.infrastructure.persistence.business_rule_repository import BusinessRuleRepository
        from apps.api.app.infrastructure.storage.business_rule_artifacts import BusinessRuleArtifacts
        rules = BusinessRuleApplicationService(FrozenBusinessRuleSourceApplicationService(image_queries), authorization,
            BusinessRuleRepository(), BusinessRuleArtifacts(storage))
        rule_object = next(obj for obj in extracted.objects if obj.type == "SourceBusinessRule")
        rule_preview = rules.inspect(code.project_id, header.image_revision_id, header.artifact_hash, rule_object.id)
        rule_request = BusinessRuleReviewInput(project_id=code.project_id, image_revision_id=header.image_revision_id,
            image_artifact_hash=header.artifact_hash, object_id=rule_object.id, basis_digest=rule_preview["basis_digest"],
            expected_previous_revision_id=None, decision="approve", authority_basis="user_confirmed_business_rule", policy_revision=RULE_POLICY,
            oracle={"preconditions": "Unauthenticated caller in isolated fixture environment", "action": "POST the documented finance chat request",
                    "observation": "HTTP response status and body", "expected_result": "HTTP 401; no chat content disclosed"},
            reason="Independent companion fixture review; not exweb maintainer approval or observed execution")
        def record_rule(request):
            ident = str(uuid4())
            with session_scope() as session:
                session.add(ToolInvocationRecord(id=ident, tool_id=RULE_TOOL, status="running", summary="Verify business rule storage",
                    input_payload={**request.model_dump(mode="json"), "confirmed_by_user": True}))
            return rules.review(request, invocation_id=ident, recorded_at=now)
        approved_rule = record_rule(rule_request)
        approved_rule_body = rules.read(code.project_id, approved_rule.revision_id)
        assert rules.repository.get(code.project_id, approved_rule.revision_id)[1].startswith("s3://")
        assert rules.resolve_oracle(code.project_id, header.image_revision_id, rule_object.id,
            approved_rule.revision_id, approved_rule.artifact_hash) == approved_rule_body
        from apps.api.app.application.system_image.context_pack_inputs import ContextPreviewInput, ContextCompileInput, ContextListInput
        from apps.api.app.application.system_image.context_pack_sources import TestDesignContextSources
        from apps.api.app.application.system_image.context_packs import ContextPackApplicationService
        from apps.api.app.domain.system_image.context_pack import COMPILE_CONTEXT_TOOL
        from apps.api.app.infrastructure.persistence.context_pack_repository import ContextPackRepository
        from apps.api.app.infrastructure.system_image.context_pack_artifacts import ContextPackArtifacts
        packs = ContextPackApplicationService(TestDesignContextSources(image_queries, authority, semantic_query, rules=rules), authorization,
            ContextPackRepository(), ContextPackArtifacts(storage))
        context_preview = packs.preview(ContextPreviewInput(project_id=code.project_id, image_revision_id=header.image_revision_id,
            image_artifact_hash=header.artifact_hash))
        context_request = ContextCompileInput.model_validate({**context_preview["request"], "expected_input_digest": context_preview["input_digest"]})
        context_invocation = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=context_invocation, tool_id=COMPILE_CONTEXT_TOOL, status="running",
                summary="Archive fixture context", input_payload={**context_request.model_dump(mode="json"), "confirmed_by_user": True}))
        context_pack = packs.compile(context_request, invocation_id=context_invocation, recorded_at=now)
        assert packs.repository.get(code.project_id, context_pack["context_id"])[1].startswith("s3://")
        context_body = packs.read(code.project_id, context_pack["context_id"])
        assert context_body["context"] == json.loads(json.dumps(context_preview["context"]))
        required = context_body["context"]["required_constraints"]
        assert {item["object_id"] for item in required} == {obj.id for obj in extracted.objects if obj.type in {"SourceAcceptanceCriterion", "SourceBusinessRule"}}
        assert next(c for c in required if c["object_id"] == ac_member["object_id"])["oracle"] == approval.oracle.model_dump(mode="json")
        assert context_body["context"]["facts"]
        assert all(f["relation"] != "asserts" and f["semantic_class"] == "retrieval_candidate_not_coverage" for f in context_body["context"]["facts"])
        assert context_body["current_use"] == {"stale": False, "generation_authorized": False, "reason": "draft_investigation_only"}
        assert packs.list(ContextListInput(project_id=code.project_id, image_revision_id=header.image_revision_id,
            image_artifact_hash=header.artifact_hash))["items"] == [context_pack]
        from apps.api.app.domain.system_image.context_partition import PARTITION_POLICY
        from apps.api.app.domain.system_image.context_pack import canonical_bytes
        partition_preview = packs.preview(ContextPreviewInput(project_id=code.project_id, image_revision_id=header.image_revision_id,
            image_artifact_hash=header.artifact_hash, policy_revision=PARTITION_POLICY))
        partition_request = ContextCompileInput.model_validate({**partition_preview["request"], "expected_input_digest": partition_preview["input_digest"]})
        partition_invocation = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=partition_invocation, tool_id=COMPILE_CONTEXT_TOOL, status="running",
                summary="Archive partitioned fixture context", input_payload={**partition_request.model_dump(mode="json"), "confirmed_by_user": True}))
        partition_metadata = packs.compile(partition_request, invocation_id=partition_invocation, recorded_at=now)
        partition_body = packs.read(code.project_id, partition_metadata["context_id"])
        assert packs.repository.get(code.project_id, partition_metadata["context_id"])[1].startswith("s3://")
        assert partition_body["context"]["schema_version"] == "nasus.context-bundle.v1"
        assert len(partition_body["context"]["parts"]) == 1  # This companion has one AC; multi-AC splitting is a separate fixture.
        for part in partition_body["context"]["parts"]:
            assert len(canonical_bytes(part["context"])) == part["context"]["budget"]["used_upper_bound"] <= 12000
            assert len(part["context"]["partition"]["global_constraint_ids"]) == 1
            assert next(c for c in part["context"]["required_constraints"] if c["object_id"] == ac_member["object_id"])["oracle"] == approval.oracle.model_dump(mode="json")
        from apps.api.app.domain.system_image.context_partition import RULE_AUTHORITY_POLICY
        rule_context_preview = packs.preview(ContextPreviewInput(project_id=code.project_id, image_revision_id=header.image_revision_id,
            image_artifact_hash=header.artifact_hash, policy_revision=RULE_AUTHORITY_POLICY))
        assert rule_context_preview["context"]["readiness"]["status"] == "partial"
        rule_context_request = ContextCompileInput.model_validate({**rule_context_preview["request"], "expected_input_digest": rule_context_preview["input_digest"]})
        rule_context_invocation = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=rule_context_invocation, tool_id=COMPILE_CONTEXT_TOOL, status="running",
                summary="Archive rule-authorized fixture context", input_payload={**rule_context_request.model_dump(mode="json"), "confirmed_by_user": True}))
        rule_context_metadata = packs.compile(rule_context_request, invocation_id=rule_context_invocation, recorded_at=now)
        rule_context_body = packs.read(code.project_id, rule_context_metadata["context_id"])
        assert packs.repository.get(code.project_id, rule_context_metadata["context_id"])[1].startswith("s3://")
        for part in rule_context_body["context"]["parts"]:
            obligation = next(c for c in part["context"]["required_constraints"] if c["kind"] == "business_rule")
            assert obligation["oracle"] == rule_request.oracle.model_dump(mode="json")
            assert obligation["authority"]["revision_id"] == approved_rule.revision_id
        withdrawn_rule = record_rule(rule_request.model_copy(update={"decision": "withdraw", "oracle": None, "authority_basis": None,
            "expected_previous_revision_id": approved_rule.revision_id, "reason": "Withdraw fixture rule without rewriting historical contexts"}))
        assert rules.read(code.project_id, approved_rule.revision_id) == approved_rule_body
        with pytest.raises(StaleAcceptanceSpecification):
            rules.resolve_oracle(code.project_id, header.image_revision_id, rule_object.id, approved_rule.revision_id, approved_rule.artifact_hash)
        stale_rule_context = packs.read(code.project_id, rule_context_metadata["context_id"])
        assert stale_rule_context["context"] == rule_context_body["context"] and stale_rule_context["current_use"]["stale"]
        assert stale_rule_context["current_use"]["generation_authorized"] is False
        assert packs.read(code.project_id, partition_metadata["context_id"])["current_use"]["stale"] is False
        # The later reviewed scope requires current independent rule authority.
        # Append a new explicit fixture decision; never revive the withdrawn pin.
        restored_rule = record_rule(rule_request.model_copy(update={
            "expected_previous_revision_id": withdrawn_rule.revision_id,
            "reason": "Explicit new fixture approval for test-design review; not exweb maintainer acceptance"}))
        assert restored_rule.revision_id != approved_rule.revision_id and restored_rule.sequence == withdrawn_rule.sequence + 1
        with pytest.raises(StaleAcceptanceSpecification):
            rules.resolve_oracle(code.project_id, header.image_revision_id, rule_object.id, approved_rule.revision_id, approved_rule.artifact_hash)
        from apps.api.tests.exweb_publication_fixture import publish_exweb_fixture, advance_exweb_publication
        from apps.api.app.domain.system_image.publication import PublicationChanged
        publication_service, publication_target, published_head = publish_exweb_fixture(image_queries, snapshots, authorization, header)
        from apps.api.app.application.system_image.published_reads import PublishedImageReadApplicationService
        published_reader = PublishedImageReadApplicationService(image_queries, snapshots, authorization, publication_service.repository)
        published_view = published_reader.read(code.project_id)
        assert published_view.state.pin.image_revision_id == header.image_revision_id
        assert len(published_view.objects) == header.object_count
        assert sum(item.code_reference is not None for item in published_view.objects) == 725
        assert all(item.content_ref is None for item in published_view.sources)
        frozen_index_service, frozen_index_metadata, frozen_index_report = build_exweb_index(
            image_queries, publication_service, published_reader, model_profiles, storage, published_head)
        from apps.api.app.domain.system_image.context_partition import PUBLISHED_CONTEXT_POLICY
        from apps.api.app.domain.system_image.context_pack import ContextPublicationChanged
        packs.sources.publications = publication_service
        published_context_input = ContextPreviewInput(project_id=code.project_id, image_revision_id=header.image_revision_id,
            image_artifact_hash=header.artifact_hash, policy_revision=PUBLISHED_CONTEXT_POLICY, publication_id=published_head["publication_id"])
        published_context_preview = packs.preview(published_context_input)
        assert published_context_preview["context"]["publication_pin"] == published_view.state.pin.model_dump(mode="json")
        assert "image_not_published" not in published_context_preview["context"]["readiness"]["reason_codes"]
        published_context_request = ContextCompileInput.model_validate({**published_context_preview["request"],
            "expected_input_digest": published_context_preview["input_digest"]})
        published_context_invocation = str(uuid4())
        with session_scope() as session:
            session.add(ToolInvocationRecord(id=published_context_invocation, tool_id=COMPILE_CONTEXT_TOOL, status="running",
                summary="Archive published fixture context", input_payload={**published_context_request.model_dump(mode="json"), "confirmed_by_user": True}))
        published_context_metadata = packs.compile(published_context_request, invocation_id=published_context_invocation, recorded_at=now)
        published_context_body = packs.read(code.project_id, published_context_metadata["context_id"])
        assert packs.repository.get(code.project_id, published_context_metadata["context_id"])[1].startswith("s3://")
        assert published_context_body["context"] == json.loads(json.dumps(published_context_preview["context"]))
        assert {c["object_id"] for c in published_context_body["context"]["required_constraints"]} == {c["object_id"] for c in required}
        for part in published_context_body["context"]["parts"]:
            assert part["context"]["publication_pin"] == published_context_body["context"]["publication_pin"]
            assert len(canonical_bytes(part["context"])) == part["context"]["budget"]["used_upper_bound"] <= 12000
        indexed_input, indexed_command, indexed_body, indexed_report = compile_exweb_indexed_context(
            packs, frozen_index_service, published_context_preview,
            frozen_index_report["context_retrieval"]["result"]["retrieval_bindings"], now)
        scope_service, scope_before, scope_report = review_exweb_test_design_scope(packs, authorization, storage, indexed_body, now)
        design_generation, design_selection, design_report = verify_exweb_generation_contract(scope_service, scope_before, authorization, now)
        result_service, design_result, design_result_report = archive_exweb_generation_fixture(
            design_generation, design_selection, authorization, model_profiles, model_config, storage)
        native_design, native_generation_report = verify_exweb_native_generation(
            result_service, design_selection, authorization, model_profiles, model_config, image_queries, storage)
        mapping_service, mapping_before, mapping_report = review_exweb_test_design_mapping(
            result_service, authorization, storage, native_design)
        recovery_metadata = native_generation_report["batch_recovery"]["metadata"]
        recovered_design = result_service.read(code.project_id, recovery_metadata["generation_id"])
        recovered_mapping_service, recovered_mapping_before, recovered_mapping_report = review_exweb_test_design_mapping(
            result_service, authorization, storage, recovered_design)
        native_generation_report["batch_recovery"]["mapping_review"] = recovered_mapping_report
        # Reingest a changed companion requirement, not exweb's target code.
        # Stable registry identities must survive, while the decision becomes
        # stale for the new AC revision and never mutates its original review.
        requirement_source = next(source for source in sources if source.source_type == "us_doc")
        requirement_path = Path(requirement_source.source_uri)
        requirement_path.write_text(requirement_path.read_text().replace("response content type", "response content type and response status"))
        capture = reader.ingest(requirement_source)
        assert capture.snapshot and capture.content_ref.startswith("s3://")
        snapshots.record_capture(requirement_source, capture.snapshot, captured_at=now)
        next_sources = [source.model_copy(update={"content_ref": capture.content_ref, "content_hash": capture.content_hash})
                        if source.id == requirement_source.id else source for source in sources]
        next_manifest = snapshots.freeze_manifest(code.project_id, next_sources, captured_at=now)
        next_extracted = context.extract(project_id=code.project_id, project_name="exweb verification", baseline_id="exweb-documents-updated",
            sources=snapshots.materialization_sources(next_manifest), version_id=None, captured_at=now)
        next_image = ImageCandidateApplicationService(images, registry).freeze(next_manifest, "exweb-documents-updated",
            objects=next_extracted.objects, relationships=next_extracted.relationships,
            invocation_id="minio-verification-reingestion", recorded_at=now)
        _, next_payload = image_queries.frozen_snapshot(code.project_id, next_image.image_revision_id)
        identities = {}
        for member in next_payload["members"]:
            if member["kind"] == "code_entity":
                identities[member["entity_id"]] = member["object_id"]
            elif member["kind"] == "source_document":
                document = document_queries.read(code.project_id, member["document_revision_id"])["document"]
                identities[document["entity_id"]] = member["object_id"]
        changed_applicability, changed_screening, changed_recalls = {}, {}, {}
        for relation, receipt_payload in applicability_receipts.items():
            comparison = applicability[relation]
            request = ImageSemanticApplicabilityInput.model_validate(receipt_payload["request"]).model_copy(update={
                "image_revision_id": next_image.image_revision_id, "expected_image_hash": next_image.artifact_hash,
                "subject_object_id": identities[comparison["subject"]["entity_id"]],
                "target_object_id": identities[comparison["target"]["entity_id"]]})
            checked = semantic_query.expand(semantic_query.execute(request))
            assert checked.target.entity_id == checked.original_target.entity_id
            assert checked.target.revision_id != checked.original_target.revision_id
            assert checked.assessment.status == "stale_requires_review" and not checked.assessment.approval_transferred
            changed_applicability[relation] = asdict(checked)
            screened = semantic.preview(SemanticSelection(project_id=code.project_id, image_revision_id=next_image.image_revision_id,
                expected_image_hash=next_image.artifact_hash, target_object_id=request.target_object_id, relation=relation,
                subject_object_ids=[request.subject_object_id], model_config_id=model_config.config_id))
            hit, = screened.review_screening
            assert hit.status == "stale_requires_review" and hit.head_decision_id == checked.head_decision_id
            changed_screening[relation] = screened.model_dump(mode="json")
            recall_receipt = semantic_query.execute(ImageScreenedCandidatesInput(project_id=code.project_id,
                image_revision_id=next_image.image_revision_id, target_object_id=request.target_object_id, relation=relation, limit=30))
            recall_page = semantic_query.expand(recall_receipt)
            matching = next(item for item in recall_page.items if item.endpoint.object_id == request.subject_object_id)
            assert matching.review_status == "requires_revalidation" and recall_page.excluded["historical_review"] == 0
            assert asdict(semantic_query.expand(screened_receipts[relation])) == screened_recalls[relation]
            changed_recalls[relation] = asdict(recall_page)
        assert image_queries.read(code.project_id, semantic_child.image_revision_id, section="semantic_assertion_members") == semantic_page
        changed_ac = authority.inspect(code.project_id, next_image.image_revision_id, next_image.artifact_hash,
                                       identities[authority_preview["basis"]["entity_id"]])
        assert changed_ac["head"] is None and changed_ac["ac_id"] != approved_ac.ac_id
        assert changed_ac["basis_digest"] != approved_ac.basis_digest
        changed_rule = rules.inspect(code.project_id, next_image.image_revision_id, next_image.artifact_hash,
            identities[rule_preview["basis"]["entity_id"]])
        assert changed_rule["head"] is None and changed_rule["rule_id"] != approved_rule.rule_id
        withdrawn_ac = record_authority(approval.model_copy(update={"decision": "withdraw", "oracle": None, "authority_basis": None,
            "expected_previous_revision_id": approved_ac.revision_id, "reason": "Withdraw fixture oracle without rewriting its history"}))
        before_replay = set(written)
        assert authority.review(approval, invocation_id=approved_ac.invocation_id, recorded_at="late-recovery") == approved_ac
        assert authority.inspect(code.project_id, header.image_revision_id, header.artifact_hash, ac_member["object_id"])["head"]["revision_id"] == withdrawn_ac.revision_id
        assert written == before_replay
        with pytest.raises(StaleAcceptanceSpecification):
            authority.resolve_oracle(code.project_id, header.image_revision_id, ac_member["object_id"], approved_ac.revision_id, approved_ac.artifact_hash)
        assert authority.read(code.project_id, approved_ac.revision_id) == approved_ac_body
        stale_context = packs.read(code.project_id, context_pack["context_id"])
        assert stale_context["context"] == context_body["context"] and stale_context["current_use"]["stale"]
        stale_partition = packs.read(code.project_id, partition_metadata["context_id"])
        assert stale_partition["context"] == partition_body["context"] and stale_partition["current_use"]["stale"]
        before_replay = set(written)
        assert packs.compile(context_request, invocation_id=context_invocation, recorded_at="late-recovery") == context_pack
        assert packs.compile(partition_request, invocation_id=partition_invocation, recorded_at="late-recovery") == partition_metadata
        assert written == before_replay
        with pytest.raises(PublicationChanged, match="Source manifest changed"):
            publication_service.preview(publication_target.model_copy(update={"expected_head_id": published_head["publication_id"]}))
        assert publication_service.history(code.project_id, header.baseline_id)["head"] == published_head
        published_after = published_reader.read(code.project_id)
        assert published_after.state == published_view.state
        assert published_after.objects == published_view.objects and published_after.sources == published_view.sources
        assert images.read(code.project_id, ref, header.artifact_hash) == frozen
        next_publication = advance_exweb_publication(publication_service, publication_target, next_image)
        assert next_publication["sequence"] == 2 and next_publication["previous_publication_id"] == published_head["publication_id"]
        assert frozen_index_service.describe(code.project_id, frozen_index_metadata["generation_id"]) == frozen_index_metadata
        assert asyncio.run(frozen_index_service.search(published_reader.read(code.project_id), "ChatController")) is None
        frozen_index_report.update(new_publication_does_not_reuse_old_vectors=True, historical_index_unchanged=True)
        with pytest.raises(ContextPublicationChanged):
            packs.preview(published_context_input)
        historical_published_context = packs.read(code.project_id, published_context_metadata["context_id"])
        assert historical_published_context["context"] == published_context_body["context"]
        assert historical_published_context["current_use"] == {"stale": True, "generation_authorized": False, "reason": "published_image_head_changed"}
        assert packs.compile(published_context_request, invocation_id=published_context_invocation, recorded_at="after-new-head") == published_context_metadata
        with pytest.raises(ContextPublicationChanged):
            packs.preview(indexed_input)
        historical_indexed = packs.read(code.project_id, indexed_body["metadata"]["context_id"])
        assert historical_indexed["context"] == indexed_body["context"]
        assert historical_indexed["current_use"] == historical_published_context["current_use"]
        assert packs.compile(indexed_command, invocation_id=indexed_body["metadata"]["invocation_id"], recorded_at="after-new-head") == indexed_body["metadata"]
        indexed_report.update(historical_bytes_unchanged_after_new_head=True, current_use=historical_indexed["current_use"])
        from apps.api.app.domain.quality_loop.test_design_scope import TestDesignScopeChanged
        scope_revision = scope_before["revision"]
        scope_after = scope_service.read(code.project_id, scope_revision["revision_id"])
        assert scope_after["request"] == scope_before["request"] and scope_after["assessment"] == scope_before["assessment"]
        assert not scope_after["current_use"]["scope_current"]
        with pytest.raises(TestDesignScopeChanged):
            scope_service.resolve(code.project_id, scope_revision["revision_id"], scope_revision["artifact_hash"])
        scope_report.update(history_unchanged_after_authority_and_head_change=True, stale_scope_rejected_for_use=True)
        with pytest.raises(TestDesignScopeChanged):
            design_generation.prepare(design_selection)
        design_report["stale_generation_input_rejected"] = True
        historical_design = result_service.read(code.project_id, design_result["metadata"]["generation_id"])
        assert historical_design["result"] == design_result["result"] and not historical_design["current_use"]["scope_current"]
        design_result_report["historical_bytes_unchanged_after_new_head"] = True
        design_result_report["current_use"] = historical_design["current_use"]
        native_history = result_service.read(code.project_id, native_design["metadata"]["generation_id"])
        assert native_history["result"] == native_design["result"] and not native_history["current_use"]["scope_current"]
        native_generation_report.update(historical_result_unchanged_after_new_head=True, current_use=native_history["current_use"])
        batch_metadata = native_generation_report["batch_ledger"]["metadata"]
        batch_history = result_service.read(code.project_id, batch_metadata["generation_id"])
        assert batch_history["metadata"] == batch_metadata and not batch_history["current_use"]["scope_current"]
        native_generation_report["batch_ledger"].update(historical_aggregate_unchanged_after_new_head=True,
            current_use=batch_history["current_use"])
        recovery_metadata = native_generation_report["batch_recovery"]["metadata"]
        recovery_history = result_service.read(code.project_id, recovery_metadata["generation_id"])
        assert recovery_history["metadata"] == recovery_metadata and recovery_history["result"] == recovered_design["result"]
        assert not recovery_history["current_use"]["scope_current"]
        native_generation_report["batch_recovery"].update(historical_recovery_unchanged_after_new_head=True,
            current_use=recovery_history["current_use"])
        from apps.api.app.domain.quality_loop.test_design_mapping import TestDesignMappingChanged
        mapping_revision = mapping_before["revision"]
        mapping_after = mapping_service.read(code.project_id, mapping_revision["revision_id"])
        assert mapping_after["request"] == mapping_before["request"] and mapping_after["assessment"] == mapping_before["assessment"]
        assert not mapping_after["current_use"]["mapping_current"]
        with pytest.raises(TestDesignMappingChanged):
            mapping_service.resolve(code.project_id, mapping_revision["revision_id"], mapping_revision["artifact_hash"])
        mapping_report.update(historical_bytes_unchanged_after_new_head=True, stale_mapping_rejected_for_use=True,
            current_use=mapping_after["current_use"])
        recovered_mapping_revision = recovered_mapping_before["revision"]
        recovered_mapping_after = recovered_mapping_service.read(code.project_id, recovered_mapping_revision["revision_id"])
        assert recovered_mapping_after["request"] == recovered_mapping_before["request"]
        assert recovered_mapping_after["assessment"] == recovered_mapping_before["assessment"]
        assert not recovered_mapping_after["current_use"]["mapping_current"]
        with pytest.raises(TestDesignMappingChanged):
            recovered_mapping_service.resolve(code.project_id, recovered_mapping_revision["revision_id"], recovered_mapping_revision["artifact_hash"])
        recovered_mapping_report.update(historical_bytes_unchanged_after_new_head=True, stale_mapping_rejected_for_use=True,
            current_use=recovered_mapping_after["current_use"])
        historical_discovery, _, _, _ = find_exweb_review_draft(result_service, native_design["metadata"])
        assert any(item["metadata"] == native_design["metadata"] for item in historical_discovery["items"])
        assert not historical_discovery["generation_authorized"] and not historical_discovery["execution_authorized"]
        mapping_report["stale_draft_still_discoverable_without_execution_authority"] = True
        result = {"repository": report["repository"], "revision": report["revision"], "verified_at": now,
                  "frozen_retrieval_index": frozen_index_report,
                  "indexed_context": indexed_report,
                  "reviewed_test_design_scope": scope_report,
                  "test_design_generation_contract": design_report,
                  "test_design_result_persistence": design_result_report,
                  "native_test_design_generation": native_generation_report,
                  "independent_test_design_mapping": mapping_report,
                  "published_context": {"metadata": published_context_metadata, "publication_id": published_head["publication_id"],
                      "next_publication_id": next_publication["publication_id"], "minio_roundtrip_verified": True,
                      "mandatory_constraints_preserved": True, "all_subpacks_pin_publication": True,
                      "new_head_rejects_old_preview": True, "historical_bytes_unchanged": True, "lost_completion_replays_original": True,
                      "current_use": historical_published_context["current_use"]},
                  "knowledge_publication": {"head": published_head, "minio_candidate_unchanged": True,
                      "published_reader_unchanged_after_source_update": True, "published_code_members": 725,
                      "reingestion_did_not_move_head": True, "stale_candidate_republication_blocked": True,
                      "lost_completion_replays_original": True, "quality_generation_authorized": False,
                      "release_authorized": False, "reviewer_basis": "explicit_fixture_not_exweb_maintainer"},
                  "test_design_context": {"metadata": context_pack, "mandatory_count": len(required),
                      "partition_policy": {"metadata": partition_metadata, "subpack_count": len(partition_body["context"]["parts"]),
                          "global_rules_inherited": True, "per_part_bytes_verified": True, "minio_roundtrip_verified": True,
                          "historical_replay_unchanged_after_withdrawal": True},
                      "mandatory_source_constraints_preserved": True, "approved_oracle_pinned": True,
                      "rejected_test_candidate_excluded": True, "minio_roundtrip_verified": True,
                      "withdrawal_marks_stale_without_rewriting_history": True, "lost_completion_replays_original": True,
                      "generation_authorized": False, "scope": "draft_investigation_only_not_complete_P5"},
                  "acceptance_authority": {"approved": asdict(approved_ac), "withdrawn": asdict(withdrawn_ac),
                      "changed_image_unapproved": changed_ac["head"] is None, "historical_revision_unchanged": True,
                      "lost_completion_replayed_original": True, "replay_did_not_reactivate_or_write_artifacts": True,
                      "withdrawal_blocks_new_oracle_use": True, "authority_basis": "fixture_reviewer_not_exweb_maintainer"},
                  "business_rule_authority": {"approved": asdict(approved_rule), "withdrawn": asdict(withdrawn_rule),
                      "new_approval_for_reviewed_scope": asdict(restored_rule),
                      "changed_image_unapproved": changed_rule["head"] is None, "historical_revision_unchanged": True,
                      "minio_roundtrip_verified": True, "withdrawal_blocks_new_oracle_use": True,
                      "context_policy": rule_context_metadata, "global_rule_oracle_pinned": True,
                      "withdrawal_marks_context_stale_without_rewriting_history": True, "legacy_v2_replay_unchanged": True,
                      "authority_basis": "fixture_reviewer_not_exweb_maintainer"},
                  "candidate": asdict(header), "documents": reviewed,
                  "link_candidate_recall": {key: asdict(value) for key, value in recalled.items()},
                  "semantic_link_inputs": semantic_inputs,
                  "semantic_evaluations": semantic_evaluations,
                  "semantic_history_receipts": {key: value.model_dump(mode="json") for key, value in semantic_history_receipts.items()},
                  "semantic_applicability_receipts": applicability_receipts,
                  "semantic_applicability": applicability,
                  "semantic_automatic_screening": screening_results,
                  "review_screened_recall": screened_recalls,
                  "review_screened_receipts": {key: value.model_dump(mode="json") for key, value in screened_receipts.items()},
                  "reingested_screened_recall": changed_recalls,
                  "reingested_semantic_screening": changed_screening,
                  "reingested_candidate": asdict(next_image), "reingested_semantic_applicability": changed_applicability,
                  "explicit_reference_proposal": asdict(page),
                  "reference_review_decision": asdict(decision), "reference_review_digest": decision.digest,
                  "reviewed_candidate": asdict(child), "frozen_review_membership": asdict(frozen_reviews),
                  "semantic_candidate": asdict(semantic_child), "frozen_semantic_membership": asdict(semantic_page),
                  "mixed_review_candidate": asdict(mixed), "semantic_history_survived_redecision": True,
                  "scope": "real_pg_minio_static_projection_with_companion_verification_fixtures_not_business_acceptance",
                  "target_executed": False, "minio_verified": True, "fixture_objects_cleaned_after_test": True}
        Path(".nasus/validation/exweb-source-documents-report.json").write_text(json.dumps(result, indent=2) + "\n")
    finally:
        # Only remove keys written by this isolated run; never delete the archived exweb input.
        import boto3
        client = boto3.client("s3", endpoint_url=config.endpoint, aws_access_key_id=config.access_key,
                              aws_secret_access_key=config.secret_key)
        if written:
            cleanup = client.delete_objects(Bucket=config.bucket, Delete={"Objects": [{"Key": key} for key in written]})
            assert not cleanup.get("Errors")
