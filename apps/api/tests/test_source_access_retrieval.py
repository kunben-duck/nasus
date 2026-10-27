from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import pytest
from sqlalchemy import text

from apps.api.app.application.system_image.retrieval_port import HybridRetrievalQuery
from apps.api.app.application.system_image.retrieval_scope import AuthorizedRetrievalSubjects, RetrievalSubjectProvenance
from apps.api.app.infrastructure.persistence.db_models import EmbeddingRecord
from apps.api.app.infrastructure.persistence.system_image_repository import SystemImageRepository
from apps.api.app.infrastructure.system_image import hybrid_retrieval as module
from apps.api.tests.test_source_access_repository import access_repo, pg_repo, restrict


@pytest.mark.parametrize("with_vector", [False, True])
def test_pg_filters_denied_rows_before_lexical_and_vector_limits(access_repo, monkeypatch, with_vector):
    repo, _, sessions = access_repo
    restrict(repo)
    scope = repo.load_snapshot("project").for_actor("other", "viewer")
    allowed = AuthorizedRetrievalSubjects.compile(scope, [
        RetrievalSubjectProvenance("project", "context_object:allowed", ("public",), True),
        RetrievalSubjectProvenance("project", "context_object:denied", ("private",), True),
        RetrievalSubjectProvenance("project", "raw_asset:public", ("public",), True),
    ])
    @contextmanager
    def session_scope():
        with sessions.begin() as session:
            schema = session.scalar(text("SELECT current_schema()"))
            assert schema.startswith("snapshot_test_") and schema.replace("_", "").isalnum()
            session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            yield session
    monkeypatch.setattr(module, "session_scope", session_scope)
    with session_scope() as session:
        EmbeddingRecord.__table__.create(session.connection())
        for i, (subject, chunk, source, words, vector) in enumerate([
            ("allowed", None, "public", "payment", [0.9, 0.1]),
            ("denied", None, "public", "payment " * 20, [1.0, 0.0]),
            ("allowed", "denied-chunk", "public", "payment " * 30, [1.0, 0.0]),
        ]):
            session.add(EmbeddingRecord(
                id=str(i), project_id="project", baseline_id="baseline", object_ref=subject,
                chunk_ref=chunk, source_ref=source, content_hash="hash", embedding_model="test",
                embedding_version="v1", provider="mock", vector_ref="test", embedding_vector=vector,
                dimensions=2, search_text=words, status="ready", created_at="now", sort_order=i,
            ))
    query = HybridRetrievalQuery(
        project_id="project", baseline_id="baseline", query_text="payment", query_vector=(1.0, 0.0) if with_vector else (),
        embedding_model="test", embedding_version="v1", dimensions=2, candidate_limit=1, limit=1,
        authorized_subjects=allowed,
    )
    index = module.SQLAlchemySystemImageRetrievalIndex(SystemImageRepository())
    result = index.search(query)
    assert [item.subject_ref for item in result] == ["context_object:allowed"]
    assert result[0].search_text == "payment"
    assert index.search(replace(query, authorized_subjects=replace(allowed, subject_refs=()))) == []
    with pytest.raises(ValueError, match="project mismatch"):
        replace(query, project_id="other")
