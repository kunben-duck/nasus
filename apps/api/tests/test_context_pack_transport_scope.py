"""One context read reuses transport, never original bytes or authorization."""
from contextlib import nullcontext

import pytest

from apps.api.app.domain.system_image.context_pack import CONTEXT_SCHEMA, ContextPackIntegrityError, canonical_bytes
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.system_image.context_pack_artifacts import ContextPackArtifacts
from apps.api.tests.test_context_pack_read_scope import reader
from apps.api.tests.test_object_storage_read_session import storage


@pytest.fixture
def transport_reader(reader, storage, monkeypatch):
    service, authorization, calls, _ = reader
    value, clients, bodies, content = storage
    artifacts = ContextPackArtifacts(value)
    service.artifacts = artifacts
    payload = {"schema": CONTEXT_SCHEMA, "project_id": "project", "original": "immutable"}
    content["body"] = canonical_bytes(payload)
    digest = snapshot_digest(payload)
    ref = "s3://test/" + artifacts._key("project", digest)

    def original():
        assert artifacts.read("project", ref, digest) == payload

    verify, prepare = service._verify_stored, service._prepare

    def replay(*args):
        original()
        return verify(*args)

    def live(*args):
        # Inner image readers already open their own storage read sessions.
        with value.read_session():
            original()
        return prepare(*args)

    monkeypatch.setattr(service, "_verify_stored", replay)
    monkeypatch.setattr(service, "_prepare", live)
    return service, authorization, calls, clients, bodies, content


def test_single_read_reuses_transport_without_skipping_bytes_or_acl(transport_reader, monkeypatch):
    service, authorization, calls, clients, bodies, _ = transport_reader
    with monkeypatch.context() as baseline:
        baseline.setattr(service.artifacts, "read_session", nullcontext)
        expected = service.read("project", "context")
    original_calls = calls[:]
    assert len(clients) == 2 and sum(client.reads for client in clients) == 2
    calls.clear()

    assert service.read("project", "context") == expected
    assert len(clients) == 3 and clients[-1].reads == 2
    assert calls == original_calls
    assert service.read("project", "context") == expected
    assert len(clients) == 4 and clients[-1].reads == 2
    assert calls == original_calls * 2
    assert all(client.closed == 1 for client in clients)
    assert all(body.closed for body in bodies) and authorization.depth == 0


def test_replay_does_not_cache_bytes_for_live_verification(transport_reader, monkeypatch):
    service, authorization, _, clients, bodies, content = transport_reader
    prepare = service._prepare

    def corrupt(*args):
        content["body"] = b"changed after historical replay"
        return prepare(*args)

    with monkeypatch.context() as changed:
        changed.setattr(service, "_prepare", corrupt)
        with pytest.raises(ContextPackIntegrityError, match="digest mismatch"):
            service.read("project", "context")
    assert len(clients) == 1 and clients[0].reads == 2 and clients[0].closed == 1
    assert all(body.closed for body in bodies) and authorization.depth == 0


@pytest.mark.parametrize("stage", ["_verify_stored", "_prepare"])
def test_failed_parent_verification_closes_transport_and_next_read_is_fresh(transport_reader, monkeypatch, stage):
    service, authorization, _, clients, _, _ = transport_reader
    operation = getattr(service, stage)

    def fail(*args):
        operation(*args)
        raise ContextPackIntegrityError("invalid ancestor")

    with monkeypatch.context() as failed:
        failed.setattr(service, stage, fail)
        with pytest.raises(ContextPackIntegrityError, match="invalid ancestor"):
            service.read("project", "context")
    assert len(clients) == 1 and clients[0].closed == 1 and authorization.depth == 0
    assert service.read("project", "context")["current_use"]["stale"] is False
    assert len(clients) == 2 and clients[1].reads == 2 and clients[1].closed == 1


def test_final_acl_check_still_rejects_revocation_and_closes_transport(transport_reader, monkeypatch):
    service, authorization, calls, clients, _, _ = transport_reader
    replay = service._verify_stored

    def revoke(*args):
        result = replay(*args)
        authorization.epoch += 1
        return result

    with monkeypatch.context() as revoked:
        revoked.setattr(service, "_verify_stored", revoke)
        with pytest.raises(StaleSourceAccessScope, match="source access changed"):
            service.read("project", "context")
    assert calls[-2:] == ["current", "close"] and authorization.depth == 0
    assert len(clients) == 1 and clients[0].reads == 2 and clients[0].closed == 1
    assert service.read("project", "context")["current_use"]["stale"] is False
    assert len(clients) == 2 and clients[1].closed == 1
