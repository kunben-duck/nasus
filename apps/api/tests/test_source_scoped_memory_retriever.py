from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.app.main import app
from apps.api.app.application.agent.agent_models import AgentMemoryItem, ConversationSession
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.errors import PlatformApplicationError
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope, SourceAccessRule
from apps.api.app.infrastructure.persistence.conversation_repository import ConversationRepository
from apps.api.app.infrastructure.persistence.code_alias_models import CodeObjectAliasRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository
from apps.api.app.infrastructure.system_image.hybrid_retrieval import SQLAlchemySystemImageRetrievalIndex
from apps.api.app.infrastructure.system_image.sqlalchemy_memory_retriever import SQLAlchemySystemImageRetriever
from apps.api.app.infrastructure.system_image.source_read_projection import SQLAlchemySourceReadProjection
from apps.api.tests.test_source_evidence_api import evidence_api


class RecordingModels:
    def __init__(self, profile, on_embed=None, on_rerank=None):
        self.profile = profile
        self.on_embed = on_embed
        self.on_rerank = on_rerank
        self.rerank_inputs = []
        self.embedding_inputs = []
        self.refreshes = []

    async def embed_texts(self, texts, *, call_context=None):
        self.embedding_inputs.append(texts)
        if self.on_embed:
            self.on_embed()
        return SimpleNamespace(vectors=[[1.0] * self.profile.dimensions], model_name=self.profile.model_name, mode="live")

    async def rerank_candidates(self, *, query, candidates, call_context=None):
        self.rerank_inputs.append(candidates)
        if self.on_rerank:
            self.on_rerank()
        return SimpleNamespace(ranked_indices=list(range(len(candidates))), mode="live", model_name="test",
                               reason="test", latency_ms=1)

    def refresh_project_read_model(self, project_id):
        self.refreshes.append(project_id)


@pytest.fixture
def scoped_project(evidence_api, tmp_path):
    v = evidence_api
    # The optional document is deliberately restricted; public code stays usable.
    hidden = tmp_path / "HiddenPaymentRequirement.md"
    hidden.write_text("# US-99 RestrictedPaymentSecret\nAs a payer I require a secret payment policy.\n")
    v["invoke"]("system_image.sources.register", {"source_specs": [{"source_type": "us_doc", "source_uri": str(hidden)}]})
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    membership_url = f"/v1/projects/{v['project_id']}/members/{v['member']['id']}"
    assert v["client"].put(membership_url, headers=v["headers"], json={"role": "viewer"}).status_code == 200
    repository = SystemImageRepository()
    snapshot = repository.load_project_snapshot(v["project_id"])
    source = next(item for item in snapshot.raw_assets if item.source_type == "us_doc")
    policies = SourceAccessRepository()
    binding = next(item for item in policies.load_snapshot(v["project_id"]).bindings if item.source_id == source.id)
    policies.set_policy(v["project_id"], binding.binding_id, SourceAccessRule("restricted"), expected_epoch=0,
                        changed_by=v["owner"]["id"], invocation_id="test-scope-policy")
    conversations = ConversationRepository()
    memory = AgentMemoryItem(id="memory-" + uuid4().hex, memory_scope="project_long_term",
                             owner_ref=f"project:{v['project_id']}", summary="Orders RestrictedPaymentSecret stale aggregate",
                             status="active", created_at="2026-09-09")
    conversations.upsert_agent_memory_item(memory)
    actor = UserProfile.model_validate(v["member"])
    conversation = ConversationSession.model_validate(v["conversation"].json())
    access = app.state.container.evidence.source_authorization
    return SimpleNamespace(**v, repository=repository, snapshot=snapshot, hidden_source=source,
                           policies=policies, binding=binding, actor=actor, session=conversation,
                           access=access, conversations=conversations, membership_url=membership_url)


def retrieval(v, *, on_embed=None, on_rerank=None, index=None):
    with actor_scope(v.actor):
        projection = SQLAlchemySourceReadProjection().project(v.snapshot, v.access.scope(v.project_id))
    profile = SQLAlchemySystemImageRetriever._embedding_profile(projection.snapshot, v.session)
    assert profile is not None, "authorized source chunks must retain semantic retrieval"
    workspace = RecordingModels(profile, on_embed, on_rerank)
    retriever = SQLAlchemySystemImageRetriever(
        system_images=v.repository, conversations=v.conversations,
        retrieval_index=index or SQLAlchemySystemImageRetrievalIndex(v.repository), workspace=workspace,
        source_access=v.access,
    )
    return retriever, workspace


def test_restricted_projection_is_detached_and_rebuilds_safe_source_local_objects(scoped_project):
    v = scoped_project
    code = next(item for item in v.snapshot.knowledge_objects if item.code_reference)
    code.name = "RestrictedPaymentSecret injected into mutable projection"
    code.relations = ["RestrictedPaymentSecret"]
    code.evidence = ["RestrictedPaymentSecret"]
    before = asdict(v.snapshot)
    with actor_scope(v.actor):
        projection = SQLAlchemySourceReadProjection().project(v.snapshot, v.access.scope(v.project_id))
    assert asdict(v.snapshot) == before
    assert projection.snapshot.knowledge_objects
    assert "RestrictedPaymentSecret" not in str(asdict(projection.snapshot))
    assert all(item.id != v.hidden_source.id for item in projection.snapshot.raw_assets)
    assert not projection.snapshot.relationships and not projection.snapshot.metric_snapshots
    assert projection.snapshot.baselines[0].object_count == 0
    assert all(not ref.startswith("context_object:") for ref in projection.index_subjects.subject_refs)
    assert projection.include_unproven_memory is False
    projection.snapshot.raw_assets[0].source_label = "read-copy"
    assert asdict(v.snapshot) == before


def test_restricted_projection_preserves_both_canonical_and_historical_object_ids(scoped_project):
    v = scoped_project
    snapshot = deepcopy(v.snapshot)
    original = next(item for item in snapshot.knowledge_objects if item.code_reference)
    with session_scope() as session:
        alias = session.scalars(select(CodeObjectAliasRecord).where(
            CodeObjectAliasRecord.project_id == v.project_id,
            CodeObjectAliasRecord.entity_revision_id == original.code_reference.entity_revision_id)).first()
        legacy_id = alias.legacy_object_id
    historical = original.model_copy(deep=True, update={"id": legacy_id})
    snapshot.knowledge_objects.append(historical)
    with actor_scope(v.actor):
        projected = SQLAlchemySourceReadProjection().project(snapshot, v.access.scope(v.project_id)).snapshot
    objects = {item.id: item for item in projected.knowledge_objects}
    assert original.id == "CODE-" + original.code_reference.entity_id
    assert objects[original.id].code_reference == objects[legacy_id].code_reference == original.code_reference
    assert "RestrictedPaymentSecret" not in str(asdict(projected))
    assert historical.id == legacy_id and original.id in {item.id for item in v.snapshot.knowledge_objects}


def test_actual_pg_retrieval_filters_before_rerank_and_does_not_publish_legacy_shared_trace(scoped_project):
    v = scoped_project
    retriever, workspace = retrieval(v)
    before = v.repository.load_project_snapshot(v.project_id)
    with actor_scope(v.actor):
        result = asyncio.run(retriever.search_project_memory(v.session, "Orders payment", limit=12, trace=True))
    assert result.hits and workspace.rerank_inputs
    assert any("Orders" in item.summary for item in result.hits)
    assert any(item.kind == "raw_asset_chunk" for item in result.hits)
    assert all("RestrictedPaymentSecret" not in text for text in workspace.rerank_inputs[0])
    assert all(v.hidden_source.id not in text for text in workspace.rerank_inputs[0])
    assert all(item.kind != "agent_memory" for item in result.hits)
    assert result.retrieval_run_refs == () and workspace.refreshes == []
    after = v.repository.load_project_snapshot(v.project_id)
    assert after.retrieval_runs == before.retrieval_runs
    assert after.knowledge_objects == before.knowledge_objects
    assert after.raw_assets == before.raw_assets


@pytest.mark.parametrize("phase", ["embed", "rerank"])
def test_policy_change_across_provider_await_rejects_old_scope(scoped_project, phase):
    v = scoped_project
    def revoke():
        # Granting or revoking any source changes the exact context scope.
        v.policies.set_policy(v.project_id, v.binding.binding_id, SourceAccessRule("restricted", (v.actor.id,)),
                              expected_epoch=1, changed_by=v.owner["id"], invocation_id="test-new-scope")
    retriever, workspace = retrieval(v, on_embed=revoke if phase == "embed" else None,
                                     on_rerank=revoke if phase == "rerank" else None)
    with actor_scope(v.actor), pytest.raises(StaleSourceAccessScope):
        asyncio.run(retriever.search_project_memory(v.session, "Orders payment", trace=True))
    assert len(workspace.rerank_inputs) == (0 if phase == "embed" else 1)
    assert workspace.refreshes == []


def test_project_membership_denial_prevents_all_provider_calls(scoped_project):
    v = scoped_project
    retriever, workspace = retrieval(v)
    assert v.client.delete(v.membership_url, headers=v.headers).status_code == 200
    with actor_scope(v.actor), pytest.raises(PlatformApplicationError):
        asyncio.run(retriever.search_project_memory(v.session, "Orders"))
    assert workspace.embedding_inputs == [] and workspace.rerank_inputs == []


def test_misbehaving_index_cannot_bypass_pre_rerank_scope(scoped_project):
    v = scoped_project
    class WrongIndex:
        def search(self, query):
            assert query.authorized_subjects is not None
            return [SimpleNamespace(subject_ref=f"raw_asset:{v.hidden_source.id}", search_text="RestrictedPaymentSecret")]
    retriever, workspace = retrieval(v, index=WrongIndex())
    with actor_scope(v.actor), pytest.raises(ValueError, match="outside the authorized scope"):
        asyncio.run(retriever.search_project_memory(v.session, "Orders"))
    assert workspace.rerank_inputs == []
