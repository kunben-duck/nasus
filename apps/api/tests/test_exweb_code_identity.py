"""Opt-in real MinIO/exweb graph replay against an isolated PostgreSQL schema."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.source_ports import (
    CodeEntityCandidate, CodeIntelligenceResult, CodeRelationshipCandidate,
)
from apps.api.app.application.system_image.system_image_models import KnowledgeCodeReference, KnowledgeObject, RawAssetRecord
from apps.api.app.application.system_image.memory_context import SystemImageMemoryContextApplicationService
from apps.api.app.application.system_image.code_entity_registry import legacy_code_object_id
from apps.api.app.application.system_image.evidence_queries import EvidenceQueryApplicationService
from apps.api.app.application.system_image.evidence_tools import EvidenceToolApplicationService
from apps.api.app.application.system_image.evidence_tool_models import EvidenceListInput, EvidenceReadInput, EvidenceReadReceipt
from apps.api.app.application.system_image.source_access import SourceAccessApplicationService
from apps.api.app.application.system_image.code_analysis_queries import CodeAnalysisQueryApplicationService
from apps.api.app.application.system_image.context_extraction import ContextExtractionService
from apps.api.app.application.system_image.image_candidates import ImageCandidateApplicationService
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.application.system_image.build_plan_queries import BuildPlanQueryApplicationService, BuildPlanReadInput
from apps.api.app.application.system_image.image_query_models import ImageListInput, ImagePageInput, ImageEvidenceInput, ImageEvidenceReceipt
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.application.platform.project_models import ProjectCard
from apps.api.app.application.system_image.snapshots import SystemImageSnapshotQueryApplicationService
from apps.api.app.application.system_image.knowledge_queries import SystemImageKnowledgeQueryApplicationService
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, SourceAccessRule, StaleSourceAccessScope
from apps.api.app.domain.system_image.source_snapshots import SourceSnapshotArtifact
from apps.api.app.domain.system_image.source_inventory import SourceInventory, SourceInventoryArtifact
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.domain.system_image.evidence import source_lines, text_digest
from apps.api.app.infrastructure.persistence.source_evidence_repository import SourceEvidenceRepository
from apps.api.app.infrastructure.persistence import source_access_repository
from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageProjectSnapshot
from apps.api.app.infrastructure.system_image.code_identity_normalization import attach_symbol_keys
from apps.api.app.infrastructure.system_image.composite_code_intelligence import CompositeCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.evidence_source_reader import ArchivedEvidenceSourceReader
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.app.infrastructure.system_image import source_read_projection
from apps.api.app.infrastructure.system_image.source_context_reader import SQLAlchemySystemImageContextReader
from apps.api.app.infrastructure.system_image.source_snapshot_reader import SQLAlchemySystemImageSnapshotReader
from apps.api.app.infrastructure.system_image.tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter
from apps.api.app.infrastructure.system_image.archived_code_analysis import ArchivedCodeAnalysisRecorder
from apps.api.app.infrastructure.system_image.image_artifacts import ArchivedImageArtifacts
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.tests.test_code_entity_registry import registry, pg_repo, register
from apps.api.tests.test_source_evidence import Authorization
from apps.api.tests.test_source_access_repository import access_repo
from apps.api.tests.test_source_inventory_repository import inventory_repo
from apps.api.tests.test_code_analysis_repository import analysis_repo
from apps.api.tests.test_image_revision_repository import image_repo
from apps.api.tests.test_build_plan_repository import build_repo, invocation
from apps.api.app.application.system_image.build_plans import BuildPlanApplicationService, BuildPlanInput
from apps.api.app.application.system_image.structure_builds import StructureBuildApplicationService, StructureBuildInput
from apps.api.app.application.system_image.image_candidate_preparation import ImageCandidatePreparation
from apps.api.app.infrastructure.persistence import structure_build_repository
from apps.api.app.infrastructure.persistence.db_models import ProjectRecord, ProjectRoleBindingRecord, BaselineRecord, ToolInvocationRecord


def test_real_exweb_provider_identity_replay(registry, access_repo, inventory_repo, analysis_repo, image_repo, build_repo, tmp_path, monkeypatch):
    report_path = os.environ.get("EXWEB_PROBE_REPORT") or os.environ.get("NASUS_EXWEB_PROBE_REPORT")
    if not report_path:
        pytest.skip("run verify-system-image-repository.py then set NASUS_EXWEB_PROBE_REPORT")
    path = Path(report_path)
    report = json.loads(path.read_text())
    assert report["repository"] == "https://github.com/kunben-duck/exweb.git"
    assert report["revision"] == "fe5827f6b76f77ef34918d8b452ee823142332dc"
    assert report["status"] == "passed"
    snapshot = SourceSnapshotArtifact(**report["source_snapshot"])
    source = RawAssetRecord(
        id=report["source_id"], project_id=report["project_id"], source_type="code",
        source_uri=report["repository"], ingestion_status="indexed",
        content_ref=snapshot.manifest_ref, content_hash=snapshot.content_hash,
        evidence_refs=[f"git:revision:{report['revision']}"],
    )
    sessions = access_repo[2]
    with sessions.kw["bind"].begin() as conn:
        ProjectRecord.__table__.create(conn)
        ProjectRoleBindingRecord.__table__.create(conn)
    with sessions.begin() as session:
        session.add(ProjectRecord(id=source.project_id, name="exweb", code="EXW", summary="Static validation"))
        for actor_id in ("reviewer", "outsider"):
            session.add(ProjectRoleBindingRecord(binding_id=f"exweb-{actor_id}", project_id=source.project_id,
                user_id=actor_id, role="viewer", scope_key=f"project:{source.project_id}", scope_ref=f"project:{source.project_id}",
                status="active", created_at=report["verified_at"], updated_at=report["verified_at"], created_by="fixture-admin"))
    # Restore/verify original bytes from MinIO, not from the mutable checkout.
    storage = None
    if os.environ.get("EXWEB_MINIO_ENDPOINT"):
        storage = ObjectStorage(ObjectStorageConfig(os.environ["EXWEB_MINIO_ENDPOINT"], os.environ["EXWEB_MINIO_BUCKET"],
            os.environ["EXWEB_MINIO_ACCESS_KEY"], os.environ["EXWEB_MINIO_SECRET_KEY"], "us-east-1", tmp_path))
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "restored")
    units = reader.extract_text_units(source)
    primary = TreeSitterCodeIntelligenceAdapter().analyze(units)
    graph = json.loads((path.parent / "normalized-graph.json").read_text())
    provider = CodeIntelligenceResult(
        provider=graph["provider"], provider_version=graph["provider_version"],
        entities=tuple(CodeEntityCandidate(**{**item, "evidence_refs": tuple(item["evidence_refs"])}) for item in graph["entities"]),
        relationships=tuple(CodeRelationshipCandidate(**{**item, "evidence_refs": tuple(item["evidence_refs"])}) for item in graph["relationships"]),
        evidence_refs=tuple(graph["evidence_refs"]),
    )
    normalized = attach_symbol_keys(provider, primary)
    service, snapshots, _ = registry
    inventory_checks = {"status": "legacy_inventory_unavailable"}
    if "source_inventory" in report:
        artifact = SourceInventoryArtifact(**report["source_inventory"])
        raw_inventory = reader.snapshots.storage.get_json(artifact.report_ref)
        assert snapshot_digest(raw_inventory) == artifact.report_hash
        inventory = SourceInventory.from_payload(raw_inventory["inventory"])
        assert inventory.complete and raw_inventory["external_revision"] == report["revision"]
        manifest = reader.snapshots.storage.get_json(snapshot.manifest_ref)
        assert manifest["inventory_hash"] == artifact.report_hash
        assert inventory.file_count == snapshot.file_count
        assert {unit.relative_path for unit in units} <= {
            item.path for item in inventory.entries if item.status == "included"
        }
        inventory_id = snapshots.record_inventory(source, artifact, recorded_at=report["verified_at"])
        assert snapshots.record_inventory(source, artifact, recorded_at=report["verified_at"]) == inventory_id
        inventory_checks = {"status": "complete", "inventory_id": inventory_id,
                            "report_hash": artifact.report_hash, "entry_count": artifact.entry_count,
                            "file_count": artifact.file_count, "minio_and_pg_verified": True}
    snapshots.record_capture(source, snapshot, captured_at=report["verified_at"])
    analysis_checks, analysis_queries = verify_structural_inventory(source, units, primary, reader,
                                                                   analysis_repo[0], access_repo[0], report, path)
    first = register(service, source, units, primary)
    second = register(service, source, units, normalized)
    merged = CompositeCodeIntelligenceAdapter._merge(primary, normalized)
    merged_registered = register(service, source, units, merged)
    assert len({item.provider_node_id for item in merged.entities}) == len(merged.entities)
    assert {value.entity_id for value in merged_registered.values()} == {value.entity_id for value in first.values()}
    assert register(service, source, units, normalized) == second
    first_by_key = {item.symbol_key: first[item.provider_node_id] for item in primary.entities if item.provider_node_id in first}
    for item in normalized.entities:
        if item.provider_node_id in second:
            assert second[item.provider_node_id].entity_id == first_by_key[item.symbol_key].entity_id
    symbols = {}
    for symbol in ("ChatController", "DocumentUploadController", "ToolGatewayApplicationService"):
        entity = next(item for item in normalized.entities if item.name == symbol and item.entity_kind == "class")
        assert entity.provider_node_id in second
        symbols[symbol] = asdict(second[entity.provider_node_id])
    assert len(second) >= 100, "probe must exercise repository-wide matching, not only three classes"
    evidence_checks = verify_archived_evidence(source, units, primary, first, reader)
    candidate_checks, candidate_queries = verify_image_candidate(source, reader, registry, image_repo[0], access_repo[0], first)
    plan_repository, plan_snapshots, plan_sessions = build_repo
    pinned_manifest = plan_snapshots.latest_manifest(source.project_id)
    planner = BuildPlanApplicationService(plan_snapshots, plan_repository, candidate_queries.authorization)
    invocation(plan_sessions, "exweb-plan", source.project_id)
    investigation = planner.create(BuildPlanInput(project_id=source.project_id, source_manifest_id=pinned_manifest.manifest_id,
        objective="Investigate exweb chat, document upload and tool gateway structure"), invocation_id="exweb-plan", created_at=report["verified_at"])
    assert planner.read(source.project_id, investigation.plan_id) == investigation
    assert investigation.proposal.intent.sources == pinned_manifest.members
    assert investigation.proposal.execution_ready is False
    assert not any(gap.code == "captured_code_required" for gap in investigation.proposal.gaps)
    plan_queries = BuildPlanQueryApplicationService(planner)
    plan_receipt = plan_queries.execute(BuildPlanReadInput(project_id=source.project_id, plan_id=investigation.plan_id))
    plan_observation = plan_queries.describe(plan_queries.expand(plan_receipt), plan_receipt)
    assert plan_observation["sources"][0]["source_revision_id"] == pinned_manifest.members[0].source_revision_id
    assert plan_observation["work_items"][0]["proposed_tool_id"] == "system_image.build.structure"
    assert "Investigate exweb chat" not in json.dumps(plan_observation)
    structure_checks = verify_structural_work(source, reader, registry, image_repo[0], planner,
        investigation, plan_sessions, monkeypatch)
    assert plan_queries.describe(plan_queries.expand(plan_receipt), plan_receipt) == plan_observation
    access_checks = verify_source_access(source, reader, access_repo[0], evidence_checks["evidence_tool_receipts"])
    monkeypatch.setattr(source_read_projection, "session_scope", source_access_repository.session_scope)
    context_checks, image_checks = verify_source_context(source, primary, first, access_repo[0])
    with pytest.raises(PlatformApplicationError) as denied:
        analysis_queries.read(source.project_id, analysis_checks["source_revision_id"], analysis_checks["analysis_id"])
    assert denied.value.status_code == 403
    analysis_checks["read_denied_after_revocation"] = True
    assert candidate_queries.list(source.project_id).items == ()
    with pytest.raises(SourceAccessDenied):
        candidate_queries.read(source.project_id, candidate_checks["image_revision_id"])
    for pin in candidate_checks["expanded_evidence"].values():
        with pytest.raises(SourceAccessDenied):
            candidate_queries.read_evidence(source.project_id, candidate_checks["image_revision_id"], pin["object_id"], pin["evidence_id"])
        with pytest.raises(SourceAccessDenied):
            ImageQueryToolApplicationService(candidate_queries).expand(ImageEvidenceReceipt.model_validate(pin["tool_receipt"]))
    candidate_checks["denied_after_revocation"] = True
    assert planner.list(source.project_id).items == ()
    with pytest.raises(SourceAccessDenied):
        planner.read(source.project_id, investigation.plan_id)
    with pytest.raises(SourceAccessDenied):
        plan_queries.expand(plan_receipt)
    output = {
        "scope": "isolated_postgresql_identity_registry_not_business_acceptance",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": report["revision"], "raw_manifest_hash": snapshot.manifest_hash,
        "acquisition_inventory": inventory_checks,
        "code_analysis": analysis_checks,
        "primary_registered": len(first), "cbm_registered": len(second),
        "merged_entities": len(merged.entities), "merged_registered": len(merged_registered),
        "provider_identity_equal": True, "retry_idempotent": True,
        "cbm_exact_locations_after_syntax_check": sum(item.location_precision == "exact" for item in normalized.entities),
        "cbm_disputed_locations": sum("code-graph-location:syntax-mismatch" in item.evidence_refs for item in normalized.entities),
        "evidence_checks": evidence_checks,
        "source_access_checks": access_checks,
        "source_context_checks": context_checks,
        "source_image_query_checks": image_checks,
        "frozen_image_candidate": candidate_checks,
        "investigation_draft": {"plan_id": investigation.plan_id, "plan_digest": investigation.plan_digest,
            "source_manifest_id": pinned_manifest.manifest_id, "fixed_input_replay": True,
            "execution_authorized": False, "read_denied_after_revocation": True},
        "confirmed_structural_work": structure_checks,
        "investigation_plan_query": {"receipt": plan_receipt.model_dump(mode="json"),
            "replay_after_candidate_commit": True, "body_free_agent_observation": True, "denied_after_revocation": True},
        "symbols": symbols, "note": "UUIDs belong to an isolated test schema removed after verification.",
    }
    (path.parent / "identity-registry.json").write_text(json.dumps(output, indent=2) + "\n")


def verify_structural_work(source, reader, registry, images, planner, plan, sessions, monkeypatch):
    from contextlib import contextmanager
    from apps.api.app.application.system_image.build_authorizations import BuildAuthorizationApplicationService, BuildAuthorizationInput
    from apps.api.app.application.platform.tool_models import ToolInvocation
    from apps.api.app.infrastructure.persistence import build_authorization_repository
    from apps.api.app.infrastructure.persistence.db_models import AgentGoalRecord, ConversationRecord
    target = "exweb-confirmed-target"
    confirmed_at = datetime.now(timezone.utc).isoformat()
    request = StructureBuildInput(project_id=source.project_id, plan_id=plan.plan_id,
        plan_digest=plan.plan_digest, target_baseline_id=target)
    # This adapter test seeds canonical goal/command rows. HTTP confirmation
    # and RBAC path is separately exercised by API tests and exweb Playwright.
    consent = BuildAuthorizationInput(**request.model_dump(), budget={
        "max_tool_calls": 1, "max_model_calls": 0, "max_active_seconds": 1200, "max_cost_microusd": 0})
    goal_id, conversation_id = "exweb-build-goal", "exweb-build-conversation"
    steps = [dict(id="authorize", phase="acting", status="blocked", selected_tool_id="system_image.build.authorize",
                  tool_input_payload=consent.model_dump(), tool_invocation_id="exweb-authorize"),
             dict(id="structure", phase="acting", status="pending", selected_tool_id="system_image.build.structure",
                  tool_input_payload=request.model_dump())]
    with sessions.kw["bind"].begin() as conn:
        BaselineRecord.__table__.create(conn)
        ConversationRecord.__table__.create(conn)
    with sessions.begin() as session:
        session.add(BaselineRecord(id=target, project_id=source.project_id, kind="official", updated_at=confirmed_at))
        session.add(ConversationRecord(id=conversation_id, session_id="exweb-session", project_id=source.project_id, title="Static exweb investigation",
            space_type="project", space_id=source.project_id))
        session.add(AgentGoalRecord(id=goal_id, project_id=source.project_id, conversation_id=conversation_id,
            title="Build exweb image", summary="Authorized structure", goal_template="system_image_build",
            status="running", steps=steps, target_refs=[f"build_plan:{plan.plan_id}"]))
        session.add(ToolInvocationRecord(id="exweb-authorize", tool_id="system_image.build.authorize", status="running",
            summary="Confirmed fixed-plan consent", conversation_id=conversation_id, initiator_surface="agent_loop", initiator_actor="agent",
            input_payload={**consent.model_dump(), "agent_goal_id": goal_id, "confirmed_by_user": True, "confirmed_at": confirmed_at}))
        session.add(ToolInvocationRecord(id="exweb-structure", tool_id="system_image.build.structure", status="running",
            summary="Reserved static validation", conversation_id=conversation_id, initiator_surface="agent_loop", initiator_actor="agent",
            input_payload={**request.model_dump(), "agent_goal_id": goal_id}))

    @contextmanager
    def scope():
        with sessions.begin() as session:
            yield session

    monkeypatch.setattr(structure_build_repository, "session_scope", scope)
    monkeypatch.setattr(build_authorization_repository, "session_scope", scope)
    authorizations = BuildAuthorizationApplicationService(planner, build_authorization_repository.BuildAuthorizationRepository())
    grant = authorizations.authorize(consent, invocation_id="exweb-authorize")
    with sessions.begin() as session:
        session.get(ToolInvocationRecord, "exweb-authorize").status = "completed"
        session.get(AgentGoalRecord, goal_id).steps = [{**steps[0], "status": "completed"}, steps[1]]
    assert authorizations.reserve_execution(ToolInvocation(id="exweb-structure", tool_id="system_image.build.structure",
        summary="Static work", status="running", input_payload={**request.model_dump(), "agent_goal_id": goal_id}))
    artifacts = ArchivedImageArtifacts(reader.snapshots.storage)
    preparation = ImageCandidatePreparation(registry[1], ContextExtractionService(reader,
        TreeSitterCodeIntelligenceAdapter(), code_entity_registry=registry[0].repository),
        ImageCandidateApplicationService(artifacts, images))
    executor = StructureBuildApplicationService(planner, preparation, structure_build_repository.StructureBuildRepository())
    revision = executor.execute(request, invocation_id="exweb-structure")
    assert revision.code_member_count == 725 and revision.status == "candidate"
    assert revision.manifest_id == plan.proposal.intent.source_manifest_id
    header, ref, _ = images.get(source.project_id, revision.image_revision_id)
    assert ref.startswith("s3://")
    payload = artifacts.read(source.project_id, ref, header.artifact_hash)
    assert len(payload["objects"]) == revision.object_count

    def no_repeat(*args, **kwargs):
        raise AssertionError("committed work must replay without parsing again")

    monkeypatch.setattr(preparation, "prepare", no_repeat)
    assert executor.execute(request, invocation_id="exweb-structure") == revision
    assert planner.read(source.project_id, plan.plan_id).structural_artifacts[0].image_revision_id == revision.image_revision_id
    return {"image_revision_id": revision.image_revision_id, "manifest_id": revision.manifest_id,
        "artifact_hash": revision.artifact_hash, "minio_verified": True, "code_member_count": revision.code_member_count,
        "retry_without_reextraction": True, "publication": revision.publication,
        "authorization": {"authorization_id": grant.authorization_id, "digest": grant.digest, "goal_id": goal_id,
            "target_baseline_id": grant.target_baseline_id, "budget": asdict(grant.budget), "reserved_work_items": ["structure"]},
        "scope": "goal_bound_structural_consent_not_semantic_or_publication_authority"}


def verify_image_candidate(source, reader, registry, repository, policies, registered):
    # Use the production extraction and archive adapters, not a hand-built graph.
    extracted = ContextExtractionService(reader, TreeSitterCodeIntelligenceAdapter(),
        code_entity_registry=registry[0].repository).extract(project_id=source.project_id, project_name="exweb",
        baseline_id="exweb-candidate-baseline", sources=[source], version_id=None, captured_at="2026-09-10T00:00:00Z")
    manifest = registry[1].freeze_manifest(source.project_id, [source], captured_at="2026-09-10T00:00:00Z")
    artifacts = ArchivedImageArtifacts(reader.snapshots.storage)
    writer = ImageCandidateApplicationService(artifacts, repository)
    arguments = dict(objects=extracted.objects, relationships=extracted.relationships,
                     invocation_id="exweb-static-validation", recorded_at="2026-09-10T00:00:00Z")
    first = writer.freeze(manifest, "exweb-candidate-baseline", **arguments)
    assert writer.freeze(manifest, "exweb-candidate-baseline", **arguments) == first
    header, ref, _ = repository.get(source.project_id, first.image_revision_id)
    assert ref.startswith("s3://"), "exweb acceptance must archive in real MinIO"
    payload = artifacts.read(source.project_id, ref, header.artifact_hash)
    code_members = [item for item in payload["members"] if item["kind"] == "code_entity"]
    assert len(code_members) == len(registered) == 725
    assert {item["entity_revision_id"] for item in code_members} == {item.entity_revision_id for item in registered.values()}
    assert all(item["evidence_ids"] for item in code_members)
    evidence_repo = SourceEvidenceRepository()
    for member in code_members:
        for evidence_id in member["evidence_ids"]:
            evidence = evidence_repo.get(source.project_id, evidence_id).evidence
            assert evidence.source_revision_id == member["source_revision_id"]
            assert evidence.object_ref.startswith("s3://") and evidence.snippet_hash
    authorization = SourceAccessApplicationService(policies, SimpleNamespace(
        current_actor=lambda: SimpleNamespace(id="reviewer", role="viewer"),
        effective_user_for_project=lambda *args, **kwargs: SimpleNamespace(id="reviewer", role="viewer")))
    evidence_reader = EvidenceQueryApplicationService(evidence_repo, ArchivedEvidenceSourceReader(reader.snapshots.storage),
                                                      Authorization(), authorization)
    queries = ImageRevisionQueryApplicationService(repository, artifacts, authorization, evidence_reader)
    tools = ImageQueryToolApplicationService(queries)
    assert queries.list(source.project_id).items == (header,)
    listed = tools.execute(ImageListInput(project_id=source.project_id))
    assert tools.expand(listed).items == (header,)
    tool_pages = 0
    for section in ("members", "objects", "relationships", "source_members"):
        offset, items = 0, []
        while True:
            receipt = tools.execute(ImagePageInput(project_id=source.project_id, image_revision_id=first.image_revision_id,
                                                   section=section, offset=offset, limit=25))
            page = tools.expand(receipt)
            assert receipt.artifact_hash == first.artifact_hash
            tool_pages += 1
            items.extend(page.items)
            if page.next_offset is None:
                break
            offset = page.next_offset
        assert items == payload[section]
    expanded = {}
    for name in ("ChatController", "DocumentUploadController", "ToolGatewayApplicationService"):
        obj = next(item for item in payload["objects"] if item["name"].startswith(name + " (")
                   and item["type"] == "CodeClass" and item.get("code_reference"))
        member = next(item for item in code_members if item["object_id"] == obj["id"])
        evidence_id = member["evidence_ids"][0]
        page = queries.read_evidence(source.project_id, first.image_revision_id, obj["id"], evidence_id)
        receipt = tools.execute(ImageEvidenceInput(project_id=source.project_id, image_revision_id=first.image_revision_id,
                                                   object_id=obj["id"], evidence_id=evidence_id))
        assert tools.expand(receipt) == page
        assert name not in receipt.model_dump_json() and "s3://" not in receipt.model_dump_json()
        assert page.integrity == "verified" and name in page.content
        assert page.evidence.source_revision_id == member["source_revision_id"]
        expanded[name] = {"object_id": obj["id"], "evidence_id": evidence_id,
                          "source_revision_id": member["source_revision_id"], "snippet_hash": page.evidence.snippet_hash,
                          "path": page.evidence.locator.relative_path, "start_line": page.start_line, "end_line": page.end_line,
                          "tool_receipt": receipt.model_dump(mode="json")}
    return {"image_revision_id": first.image_revision_id, "manifest_id": manifest.manifest_id,
            "artifact_hash": first.artifact_hash, "membership_hash": first.membership_hash,
            "code_member_count": len(code_members), "object_count": first.object_count,
            "relationship_count": first.relationship_count, "real_minio_archive": True,
            "idempotent": True, "all_pages_replayed": True, "expanded_evidence": expanded,
            "canonical_query_pages_verified": tool_pages, "canonical_evidence_receipts_verified": len(expanded),
            "publication": first.publication, "scope": "frozen_static_candidate_not_approved_semantics"}, queries


def verify_structural_inventory(source, units, result, reader, repository, policies, report, report_path):
    recorder = ArchivedCodeAnalysisRecorder(reader.snapshots, repository, max_files=5000,
                                            max_bytes=100 * 1024 * 1024, max_file_bytes=10 * 1024 * 1024)
    analysis_id = recorder.record(source, result, units, captured_at=report["verified_at"])
    assert recorder.record(source, result, units, captured_at=report["verified_at"]) == analysis_id
    target = next(item for item in policies.load_snapshot(source.project_id).bindings if item.source_id == source.id)
    from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceRevisionRecord
    from sqlalchemy import select
    with source_access_repository.session_scope() as session:
        revision = session.scalar(select(SourceRevisionRecord).where(
            SourceRevisionRecord.project_id == source.project_id, SourceRevisionRecord.binding_id == target.binding_id,
            SourceRevisionRecord.manifest_ref == source.content_ref,
        )).source_revision_id
    authorization = SourceAccessApplicationService(policies, SimpleNamespace(
        current_actor=lambda: SimpleNamespace(id="reviewer", role="viewer"),
        effective_user_for_project=lambda *args, **kwargs: SimpleNamespace(id="reviewer", role="viewer"),
    ))
    queries = CodeAnalysisQueryApplicationService(repository, authorization)
    listed = queries.list_for_revision(source.project_id, revision)
    assert listed.next_after_id is None and len(listed.items) == 1
    summary = listed.items[0]
    assert summary.analysis_id == analysis_id and summary.summary["failed"] == 0
    sections = {}
    for section in ("files", "facts"):
        offset, items = 0, []
        while True:
            page = queries.read(source.project_id, revision, analysis_id, section=section, offset=offset, limit=25)
            assert page.analysis == summary and len(page.items) <= 25
            items.extend(page.items)
            if page.next_offset is None:
                assert len(items) == page.total
                break
            assert page.next_offset > offset
            offset = page.next_offset
        sections[section] = items
    if "code_analysis" in report:
        assert summary.report_hash == report["code_analysis"]["report_hash"]
        saved = json.loads((report_path.parent / "code-analysis.json").read_text())
        assert all(saved[section] == sections[section] for section in sections)
    assert len(sections["files"]) == report["source_snapshot"]["file_count"]
    texts = {item.relative_path: item for item in units}
    for fact in sections["facts"]:
        if fact["status"] == "path_hint":
            assert "snippet_hash" not in fact
            continue
        unit = texts[fact["relative_path"]]
        assert fact["source_file_hash"] == unit.content_hash
        lines = source_lines(unit.text)
        for span in [fact, *fact["supporting_spans"]]:
            assert text_digest("".join(lines[span["start_line"] - 1:span["end_line"]])) == span["snippet_hash"]
    gold = json.loads((Path(__file__).resolve().parents[3] / "tests/fixtures/system-image/exweb-controller-routes.json").read_text())
    for controller in gold["controllers"]:
        expected = {(item["method"], item["path"], item["line"]) for item in controller["routes"]}
        observed = [item for item in sections["facts"] if item["relative_path"] == gold["source_root"] + controller["file"]
                    and item["kind"] == "route" and item["status"] == "observed"]
        assert {(item["method"], item["route_path"], item["start_line"]) for item in observed} == expected
        for item in observed:
            assert {(span["role"], span["start_line"]) for span in item["supporting_spans"]} == {
                ("controller", controller["controller_line"]), ("class_mapping", controller["class_mapping_line"]),
            }
    return {"analysis_id": analysis_id, "source_revision_id": revision, "report_hash": summary.report_hash,
            "summary": summary.summary, "annotated_routes_gold_count": sum(len(item["routes"]) for item in gold["controllers"]),
            "scope": gold["scope"], "all_fact_snippets_verified": True, "all_pages_replayed": True}, queries


def verify_archived_evidence(source, units, graph, registered, ingestion):
    repo = SourceEvidenceRepository()
    app = EvidenceQueryApplicationService(repo, ArchivedEvidenceSourceReader(ingestion.snapshots.storage), Authorization(), Authorization())
    tools = EvidenceToolApplicationService(app)
    texts = {unit.relative_path: unit.text for unit in units}
    verified, examples, tool_receipts = 0, {}, {}
    for entity in graph.entities:
        if entity.provider_node_id not in registered or entity.location_precision != "exact":
            continue
        reference = registered[entity.provider_node_id]
        evidence = app.list_for_alias(source.project_id, reference.source_revision_id,
                                      legacy_code_object_id(source.project_id, source.id, entity.provider_node_id))
        assert len(evidence) == 1
        item = evidence[0]
        assert item.locator.precision == "exact"
        start, content = None, ""
        while True:
            page = app.read(source.project_id, item.evidence_id, start_line=start, max_lines=200)
            assert page.integrity == "verified"
            content += page.content
            start = page.next_start_line
            if start is None:
                break
        expected = "".join(source_lines(texts[entity.relative_path])[entity.start_line - 1:entity.end_line])
        assert content == expected
        assert text_digest(content) == item.snippet_hash
        verified += 1
        if entity.name in {"ChatController", "DocumentUploadController", "ToolGatewayApplicationService"} and entity.entity_kind == "class":
            assert f"public class {entity.name}" in content
            examples[entity.name] = asdict(item)
            listed = tools.list(EvidenceListInput(
                project_id=source.project_id, source_revision_id=reference.source_revision_id,
                object_id=legacy_code_object_id(source.project_id, source.id, entity.provider_node_id),
                entity_revision_id=reference.entity_revision_id,
            ))
            assert [entry.evidence_id for entry in listed.items] == [item.evidence_id]
            receipt = tools.read(EvidenceReadInput(
                project_id=source.project_id, source_revision_id=reference.source_revision_id,
                evidence_id=item.evidence_id,
            ))
            assert tools.expand(receipt).content == content
            assert "content" not in receipt.model_dump()
            tool_receipts[entity.name] = receipt.model_dump(mode="json")
    assert verified >= 500
    assert len(examples) == 3
    return {"exact_excerpts_verified": verified, "examples": examples,
            "evidence_tool_receipts": tool_receipts,
            "scope": "real_minio_postgresql_hash_and_locator_replay_not_semantic_gold_or_auth_acceptance"}


def verify_source_access(source, ingestion, repository, receipts):
    actor = ["outsider"]
    def effective_user(project_id, *, require_existing_project):
        assert project_id == source.project_id and require_existing_project
        return SimpleNamespace(id=actor[0], role="viewer")
    authorization = SourceAccessApplicationService(repository, SimpleNamespace(effective_user_for_project=effective_user,
        current_actor=lambda: effective_user(source.project_id, require_existing_project=True)))
    scope = authorization.scope(source.project_id)
    target = next(item for item in repository.load_snapshot(source.project_id).bindings if item.source_id == source.id)
    repository.set_policy(source.project_id, target.binding_id, SourceAccessRule("restricted", ("reviewer",)),
                          expected_epoch=0, changed_by="fixture-admin", invocation_id="exweb-acl-fixture-1")
    with pytest.raises(StaleSourceAccessScope):
        authorization.require_current(scope)
    storage = ArchivedEvidenceSourceReader(ingestion.snapshots.storage)
    calls = []
    def read(target):
        calls.append(target.evidence.evidence_id)
        return storage.read(target)
    queries = EvidenceQueryApplicationService(SourceEvidenceRepository(), SimpleNamespace(read=read), Authorization(), authorization)
    tools = EvidenceToolApplicationService(queries)
    values = {name: EvidenceReadReceipt.model_validate(value) for name, value in receipts.items()}
    for receipt in values.values():
        with pytest.raises(PlatformApplicationError) as error:
            tools.expand(receipt)
        assert error.value.status_code == 403
        with pytest.raises(PlatformApplicationError):
            tools.authorize_receipt(receipt)
    assert not calls
    actor[0] = "reviewer"
    for name, receipt in values.items():
        assert f"public class {name}" in tools.expand(receipt).content
    repository.set_policy(source.project_id, target.binding_id, SourceAccessRule("restricted"),
                          expected_epoch=1, changed_by="fixture-admin", invocation_id="exweb-acl-fixture-2")
    for receipt in values.values():
        with pytest.raises(PlatformApplicationError):
            tools.expand(receipt)
    assert len(calls) == 3
    return {"denied_before_storage": 3, "authorized_minio_reads": 3, "old_receipts_revoked": 3,
            "scope_invalidated": True, "scope": "real_source_policy_and_archive_with_project_actor_test_double"}


def verify_source_context(source, graph, registered, policies):
    # The DTO is deliberately poisoned; only immutable PG symbol facts are safe.
    objects = []
    for entity in graph.entities:
        reference = registered.get(entity.provider_node_id)
        if reference is None:
            continue
        objects.append(KnowledgeObject(
            id=legacy_code_object_id(source.project_id, source.id, entity.provider_node_id),
            name="UNPROVEN_DERIVED_LABEL", type="code", branch="main", confidence="high", freshness="fresh",
            relations=["UNPROVEN_DERIVED_LABEL"], evidence=["UNPROVEN_DERIVED_LABEL"],
            code_reference=KnowledgeCodeReference(
                entity_id=reference.entity_id, entity_revision_id=reference.entity_revision_id,
                source_revision_id=reference.source_revision_id,
            ),
        ))
    snapshot = SystemImageProjectSnapshot(
        knowledge_objects=objects, raw_assets=[source], raw_asset_chunks=[], baselines=[], relationships=[],
        overlays=[], metric_snapshots=[], embedding_records=[], retrieval_runs=[], rerank_records=[],
        task_contexts=[], quality_profiles=[],
    )
    before = asdict(snapshot)
    def effective_user(project_id, *, require_existing_project):
        assert project_id == source.project_id and require_existing_project
        return SimpleNamespace(id="reviewer", role="viewer")
    access = SourceAccessApplicationService(policies, SimpleNamespace(effective_user_for_project=effective_user,
        current_actor=lambda: effective_user(source.project_id, require_existing_project=True)))
    reader = SQLAlchemySystemImageContextReader(
        SimpleNamespace(load_project_snapshot=lambda project: snapshot), access, lambda _: "UNPROVEN_DERIVED_LABEL",
    )
    context = SystemImageMemoryContextApplicationService(reader)
    denied = reader.read(source.project_id)
    assert not denied.objects and not denied.sources
    assert context.context_sections(source.project_id) == []
    denied_scope = denied.scope
    target = next(item for item in policies.load_snapshot(source.project_id).bindings if item.source_id == source.id)
    policies.set_policy(source.project_id, target.binding_id, SourceAccessRule("restricted", ("reviewer",)),
                        expected_epoch=2, changed_by="fixture-admin", invocation_id="exweb-context-fixture")
    with pytest.raises(StaleSourceAccessScope):
        reader.require_current(denied_scope)
    allowed = reader.read(source.project_id)
    assert len(allowed.objects) == len(registered) >= 500
    assert {item.code_reference.entity_id for item in allowed.objects} == {item.entity_id for item in registered.values()}
    for symbol in ("ChatController", "DocumentUploadController", "ToolGatewayApplicationService"):
        assert any(item.name.startswith(symbol + " (") for item in allowed.objects)
    rendered = "\n".join(context.context_sections(source.project_id))
    assert "code_evidence_query=" in rendered
    assert "UNPROVEN_DERIVED_LABEL" not in str(asdict(allowed)) + rendered
    assert allowed.system_image_status is None and asdict(snapshot) == before
    context_checks = {"authorized_code_objects": len(allowed.objects), "denied_code_objects": len(denied.objects),
            "mutable_derived_labels_excluded": True, "pinned_references_preserved": True,
            "scope": "real_pg_identity_and_source_policy_with_dto_and_project_actor_test_doubles"}
    image_checks = verify_image_queries(source, snapshot, access, policies, target.binding_id, registered)
    assert asdict(snapshot) == before
    return context_checks, image_checks


def verify_image_queries(source, snapshot, access, policies, binding_id, registered):
    project = ProjectCard(
        id=source.project_id, name="exweb", code="EXWEB", summary="UNPROVEN_DERIVED_LABEL",
        status="UNPROVEN_DERIVED_LABEL", risk="UNPROVEN_DERIVED_LABEL", progress=99,
        active_version="UNPROVEN_DERIVED_LABEL", blocked_items=5, pending_approvals=8,
        system_image_status="UNPROVEN_DERIVED_LABEL",
    )
    def legacy_snapshot(project_id):
        pytest.fail("restricted queries must not read the legacy aggregate")
    reader = SQLAlchemySystemImageSnapshotReader(
        SimpleNamespace(load_project_snapshot=lambda project_id: snapshot), access,
        lambda project_id: project, legacy_snapshot,
    )
    images = SystemImageSnapshotQueryApplicationService(reader)
    knowledge = SystemImageKnowledgeQueryApplicationService(images)
    allowed = images.get_system_image(source.project_id)
    assert allowed.visibility.mode == "source_filtered"
    assert allowed.build_state.status == "visibility_limited"
    assert allowed.build_state.stage_index is None
    assert allowed.project.progress is None and allowed.project.blocked_items is None
    assert allowed.project.pending_approvals is None and allowed.project.system_image_status is None
    assert len(allowed.objects) == len(registered) >= 500
    assert allowed.objects == knowledge.list_knowledge_objects(source.project_id)
    assert {item.code_reference.entity_revision_id for item in allowed.objects} == {
        item.entity_revision_id for item in registered.values()
    }
    serialized = allowed.model_dump_json()
    assert "UNPROVEN_DERIVED_LABEL" not in serialized
    assert "s3://" not in serialized and source.content_ref not in serialized
    assert not allowed.relationships and not allowed.baselines and not allowed.metric_snapshots
    selected = next(item for item in allowed.objects if item.name.startswith("ChatController ("))
    assert knowledge.get_knowledge_object(source.project_id, selected.id) == selected
    policies.set_policy(source.project_id, binding_id, SourceAccessRule("restricted"),
                        expected_epoch=3, changed_by="fixture-admin", invocation_id="exweb-image-fixture")
    denied = images.get_system_image(source.project_id)
    assert not denied.objects and not denied.sources and not knowledge.list_knowledge_objects(source.project_id)
    with pytest.raises(StopIteration):
        knowledge.get_knowledge_object(source.project_id, selected.id)
    return {"authorized_code_objects": len(allowed.objects), "denied_code_objects": len(denied.objects),
            "list_and_detail_agree": True, "unproven_metrics_withheld": True, "archive_urls_withheld": True,
            "scope": "real_pg_identity_and_policy_through_application_queries_with_dto_and_project_actor_test_doubles"}
