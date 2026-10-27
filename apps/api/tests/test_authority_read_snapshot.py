"""Actual PG authority reads; immutable ancestry is not current approval or ACL."""
import pytest
from sqlalchemy import delete, insert, select, text, update

from apps.api.app.domain.quality_loop.acceptance_specification import AcceptanceIntegrityError
from apps.api.app.infrastructure.persistence.authority_provenance_models import AuthorityProvenanceRecord as Anchor
from apps.api.app.infrastructure.persistence.authority_provenance_projection_v1 import AuthorityProvenanceProjectorV1 as Projector
from apps.api.app.infrastructure.persistence.image_read_snapshot import current_image_read_snapshot
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import ObjectProvenanceProjectorV1
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_authority_provenance_api import (
    authority, acceptance, rule, documents, evidence_api, completed, withdraw,
)


def approved(authority):
    v = authority
    completed(v["authority_submit"](v))
    head = v["authority_inspect"](v)["head"]
    service = v["ac_service"] if v["authority_kind"] == "acceptance" else v["rule_service"]
    return v, head, service.repository, service.sources.images.repository


def observed_audits(monkeypatch):
    original, sessions = ObjectProvenanceProjectorV1.image, []

    def counted(self, session, *args, **kwargs):
        sessions.append(session)
        return original(self, session, *args, **kwargs)

    monkeypatch.setattr(ObjectProvenanceProjectorV1, "image", counted)
    return sessions


def test_pure_authority_reads_reuse_complete_image_proof_but_reverify_native_history(authority, monkeypatch):
    v, head, repo, images = approved(authority)
    audits = observed_audits(monkeypatch)
    original, authority_sessions = Projector.facts, []

    def checked(self, session, *args, **kwargs):
        authority_sessions.append(session)
        return original(self, session, *args, **kwargs)

    monkeypatch.setattr(Projector, "facts", checked)
    with images.verified_read_session():
        images.get(v["project_id"], head["image_revision_id"])
        snapshot = current_image_read_snapshot()[0]
        for _ in range(2):
            history = repo.history(v["project_id"], head[repo.id_field])
            value, ref = repo.get(v["project_id"], head["revision_id"])
            assert history[-1] == value and value.digest and ref
        assert len(authority_sessions) == len({id(session) for session in authority_sessions}) == 4
        assert all(session is not snapshot for session in authority_sessions)
        assert audits == [snapshot]
    repo.get(v["project_id"], head["revision_id"])
    assert len(audits) == 2


def test_cached_image_never_hides_new_authority_withdrawal(authority):
    v, head, repo, images = approved(authority)
    with images.verified_read_session():
        frozen = images.get(v["project_id"], head["image_revision_id"])
        assert repo.history(v["project_id"], head[repo.id_field])[-1].status == "approved"
        completed(withdraw(v, head))
        current = repo.history(v["project_id"], head[repo.id_field])
        assert [value.status for value in current] == ["approved", "withdrawn"]
        assert current[-1].previous_revision_id == head["revision_id"]
        assert repo.get(v["project_id"], head["revision_id"])[0].status == "approved"
        assert images.get(v["project_id"], head["image_revision_id"]) == frozen


@pytest.mark.parametrize("damage", ["missing", "metadata_hash"])
def test_cached_image_never_hides_fresh_authority_registration_damage(authority, damage):
    v, head, repo, images = approved(authority)
    key = v["project_id"], v["authority_kind"], head["revision_id"]
    with session_scope() as session:
        saved = dict(session.execute(select(*Anchor.__table__.columns).where(
            Anchor.project_id == key[0], Anchor.kind == key[1], Anchor.revision_id == key[2])).mappings().one())
    with images.verified_read_session():
        images.get(v["project_id"], head["image_revision_id"])
        try:
            with session_scope() as session:
                session.execute(text("ALTER TABLE requirement_authority_provenance DISABLE TRIGGER USER"))
                query = (Anchor.project_id == key[0], Anchor.kind == key[1], Anchor.revision_id == key[2])
                if damage == "missing":
                    session.execute(delete(Anchor).where(*query))
                else:
                    session.execute(update(Anchor).where(*query).values(metadata_hash="sha256:" + "0" * 64))
                session.execute(text("ALTER TABLE requirement_authority_provenance ENABLE TRIGGER USER"))
            for _ in range(2):
                with pytest.raises(AcceptanceIntegrityError):
                    repo.history(v["project_id"], head[repo.id_field])
        finally:
            with session_scope() as session:
                session.execute(text("ALTER TABLE requirement_authority_provenance DISABLE TRIGGER USER"))
                if damage == "missing":
                    session.execute(insert(Anchor), [saved])
                else:
                    session.execute(update(Anchor).where(*query).values(metadata_hash=saved["metadata_hash"]))
                session.execute(text("ALTER TABLE requirement_authority_provenance ENABLE TRIGGER USER"))
        assert repo.history(v["project_id"], head[repo.id_field])[-1].revision_id == head["revision_id"]


def test_write_side_history_does_not_opt_into_outer_image_proof(authority, monkeypatch):
    v, head, repo, images = approved(authority)
    audits = observed_audits(monkeypatch)
    with images.verified_read_session():
        images.get(v["project_id"], head["image_revision_id"])
        snapshot = current_image_read_snapshot()[0]
        with session_scope() as fresh:
            values = repo._history(fresh, v["project_id"], head[repo.id_field])
            assert values[-1].revision_id == head["revision_id"]
            assert audits == [snapshot, fresh]


def test_authority_registration_ignores_read_only_reuse_option(authority, monkeypatch):
    v, head, repo, images = approved(authority)
    audits = observed_audits(monkeypatch)
    with images.verified_read_session():
        images.get(v["project_id"], head["image_revision_id"])
        snapshot = current_image_read_snapshot()[0]
        with session_scope() as fresh:
            row = fresh.get(v["authority_model"], head["revision_id"])
            assert Projector().facts(fresh, v["authority_kind"], (row,), write=True, reuse_snapshot=True) == 0
            assert audits == [snapshot, fresh]


def test_unverified_snapshot_and_separate_operations_do_not_cache_authority_ancestry(authority, monkeypatch):
    v, head, repo, images = approved(authority)
    audits = observed_audits(monkeypatch)
    with images.verified_read_session():
        # Opening a read scope alone is not proof of any image.
        for _ in range(2):
            repo.get(v["project_id"], head["revision_id"])
        assert len(audits) == 2
    with images.verified_read_session():
        repo.get(v["project_id"], head["revision_id"])
    assert len(audits) == 3
