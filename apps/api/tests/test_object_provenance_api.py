import pytest
from sqlalchemy import delete, insert, select, text

from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord as Image
from apps.api.app.infrastructure.persistence.object_provenance_models import ObjectProvenanceNodeRecord as Node, ObjectProvenanceEdgeRecord as Edge
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_document_projection_api import documents
from apps.api.tests.test_source_evidence_api import evidence_api
from apps.api.tests.test_source_access_api import grant_member


def current(v):
    root = v["image_url"] + "/revisions"
    response = v["client"].get(root, headers=v["headers"])
    assert response.status_code == 200, response.text
    return next(row for row in response.json()["items"] if row["manifest_id"] == v["document_manifest_id"])


def test_multisource_native_graph_pins_document_parent_evidence_and_exact_image(documents):
    v = documents
    image = current(v)
    with session_scope() as session:
        row = session.get(Image, image["image_revision_id"])
        expected = ObjectProvenanceProjectorV1().expected(session, row)
        ObjectProvenanceProjectorV1().image(session, row, write=False)
        nodes = session.scalars(select(Node).where(Node.project_id == v["project_id"])).all()
        assert {n.kind for n in expected.values()} >= {"source", "manifest", "code", "document", "evidence", "member", "image_objects"}
        assert len(next(n for n in expected.values() if n.kind == "image_objects").source_pins) == 3
        components = [n for n in expected.values() if n.kind == "document" and any(p.startswith("document:") for p in n.parents)]
        assert len(components) == 1
        persisted = [ObjectProvenanceProjectorV1._values(n, n.content_hash) for n in expected.values()]
        assert len({n.node_key for n in nodes}) >= len(expected)
        assert "Empty input" not in str(persisted) and "s3://" not in str(persisted) and "requirements.md" not in str(persisted)
    url = v["image_url"] + "/revisions/" + image["image_revision_id"]
    response = v["client"].get(url, headers=v["headers"])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"


def test_missing_persisted_dependency_returns_sanitized_502_not_partial_image(documents):
    v = documents
    image = current(v)
    url = v["image_url"] + "/revisions/" + image["image_revision_id"]
    with session_scope() as session:
        original_edges = [{column.name: getattr(edge, column.name) for column in Edge.__table__.columns}
            for edge in session.scalars(select(Edge).where(Edge.project_id == v["project_id"],
                Edge.node_key == "image_objects:" + image["image_revision_id"]))]
        assert original_edges
        session.execute(text("ALTER TABLE image_object_provenance_edges DISABLE TRIGGER USER"))
        session.execute(delete(Edge).where(Edge.project_id == v["project_id"],
            Edge.node_key == "image_objects:" + image["image_revision_id"]))
        session.execute(text("ALTER TABLE image_object_provenance_edges ENABLE TRIGGER USER"))
    try:
        response = v["client"].get(url, headers=v["headers"])
        assert response.status_code == 502, response.text
        assert "Empty input" not in response.text and "Search" not in response.text
        assert "source_revision_id" not in response.text and "items" not in response.json()
        assert v["client"].get(url).status_code == 401
        assert v["client"].get(url, headers=v["member_headers"]).status_code == 403
    finally:
        # Other tests exercise migration backfill over the entire disposable DB.
        # Restore this deliberate corruption even if an HTTP assertion fails.
        with session_scope() as session:
            session.execute(insert(Edge), original_edges)
    assert v["client"].get(url, headers=v["headers"]).status_code == 200


@pytest.mark.parametrize("change", ["membership", "policy"])
def test_authorization_change_during_provenance_failure_takes_precedence(documents, monkeypatch, change):
    from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
    from apps.api.tests.test_source_access_api import policy
    v = documents
    image = current(v)
    grant_member(v)
    url = v["image_url"] + "/revisions/" + image["image_revision_id"]
    calls = []

    def fail_after_revocation(*args, **kwargs):
        calls.append(True)
        if change == "membership":
            result = v["client"].delete(f"/v1/projects/{v['project_id']}/members/{v['member']['id']}", headers=v["headers"])
            assert result.status_code == 200
        else:
            policy(v)
        raise ImageRevisionIntegrityError("private-diagnostic-must-not-leak")

    monkeypatch.setattr(ObjectProvenanceProjectorV1, "image", fail_after_revocation)
    response = v["client"].get(url, headers=v["member_headers"])
    assert calls == [True]
    assert response.status_code == (403 if change == "membership" else 409), response.text
    assert "private-diagnostic" not in response.text and "Search" not in response.text
    assert "source_revision_id" not in response.text
