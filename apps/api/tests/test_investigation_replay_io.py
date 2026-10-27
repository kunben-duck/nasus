"""Replay shares immutable verification, never raw bytes or live authority."""
from time import perf_counter

import pytest

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.domain.system_image.evidence import EvidenceIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.app.main import app
from apps.api.tests.test_investigation_api import investigate, investigation
from apps.api.tests.test_source_evidence_api import evidence_api


@pytest.mark.parametrize("depth", [1, 3])
def test_replay_and_parent_history_use_one_scoped_transport_and_fresh_evidence(
        investigation, monkeypatch, depth):
    v = investigation
    service = app.state.container.investigations
    previous = None
    for _ in range(depth):
        payload = {**v["investigation_input"], **({"parent_revision_id": previous.revision_id,
            "parent_revision_hash": previous.revision_hash} if previous else {})}
        command = investigate(v, payload=payload)
        assert command["status"] == "completed", command
        previous = service.repository.read(v["project_id"], command["result"]["investigation"]["revision_id"])

    images = service.images
    reader = images.evidence.reader
    storage = reader.storage
    snapshots, raw_reads, clients, closed, plan_reads = [], [], [], [], []
    frozen, raw, create = images.frozen_snapshot, reader.read, storage._create_s3_client
    plan_read = service.plans.read

    def verified_plan(*args, **kwargs):
        plan_reads.append(args)
        return plan_read(*args, **kwargs)

    def snapshot(*args, **kwargs):
        snapshots.append(images._verified_reads.get() is not None)
        return frozen(*args, **kwargs)

    def source(target):
        raw_reads.append(images._verified_reads.get() is not None)
        return raw(target)

    def client(config):
        value = create(config)
        clients.append(value)
        close = value.close

        def close_once():
            closed.append(value)
            close()

        monkeypatch.setattr(value, "close", close_once)
        return value

    monkeypatch.setattr(images, "frozen_snapshot", snapshot)
    monkeypatch.setattr(reader, "read", source)
    monkeypatch.setattr(storage, "_create_s3_client", client)
    monkeypatch.setattr(service.plans, "read", verified_plan)
    pins = sum(len(service.repository.read(v["project_id"], ident).review.verified_evidence)
               for ident in _history_ids(service, v["project_id"], previous))
    started = perf_counter()
    with actor_scope(UserProfile.model_validate(v["owner"])):
        assert service.read(v["project_id"], previous.revision_id) == previous
        assert images._verified_reads.get() is None
        assert storage._read_clients.get() is None
        assert len(snapshots) == depth and all(snapshots)
        assert len(raw_reads) == pins and all(raw_reads)
        assert len(plan_reads) == depth
        if storage.config.s3_enabled:
            assert len(clients) == len(closed) == 1
        assert service.read(v["project_id"], previous.revision_id) == previous
    assert len(raw_reads) == 2 * pins
    assert len(plan_reads) == 2 * depth
    if storage.config.s3_enabled:
        assert len(clients) == len(closed) == 2
    print(f"Investigation replay: depth={depth}, raw_reads={len(raw_reads)}, "
          f"s3_clients={len(clients)}, seconds={perf_counter() - started:.3f}")


def _history_ids(service, project_id, value):
    result = []
    while value is not None:
        result.append(value.revision_id)
        value = service.repository.read(project_id, value.request.parent_revision_id) if value.request.parent_revision_id else None
    return result


def test_replay_batch_rechecks_live_permission_and_releases_scope_on_failure(investigation, monkeypatch):
    v = investigation
    service = app.state.container.investigations
    command = investigate(v)
    assert command["status"] == "completed", command
    ident = command["result"]["investigation"]["revision_id"]
    record = service.repository.read(v["project_id"], ident)
    assert len(record.review.verified_evidence) > 1
    evidence = service.images.evidence
    original, calls = evidence.require_binding_access, []

    def require(*args, **kwargs):
        calls.append(service.images._verified_reads.get() is not None)
        if len(calls) == 3:
            raise SourceAccessDenied("source was revoked during replay")
        return original(*args, **kwargs)

    monkeypatch.setattr(evidence, "require_binding_access", require)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(SourceAccessDenied, match="revoked"):
            service.read(v["project_id"], ident)
        assert all(calls)
        assert service.images._verified_reads.get() is None
        assert evidence.reader._manifests.get() is None
        assert evidence.reader.storage._read_clients.get() is None
        monkeypatch.setattr(evidence, "require_binding_access", original)
        assert service.read(v["project_id"], ident) == record


def test_replay_batch_does_not_cache_source_bytes_between_evidence_reads(investigation, monkeypatch):
    v = investigation
    service = app.state.container.investigations
    command = investigate(v)
    assert command["status"] == "completed", command
    ident = command["result"]["investigation"]["revision_id"]
    record = service.repository.read(v["project_id"], ident)
    evidence = service.images.evidence
    targets = [evidence.repository.get(v["project_id"], pin.evidence_id) for pin in record.review.verified_evidence]
    assert len(targets) > 1 and len({target.evidence.object_ref for target in targets}) == 1
    storage = evidence.reader.storage
    original, reads = storage.get_bytes, []

    def changed(ref, **kwargs):
        body = original(ref, **kwargs)
        if ref == targets[0].evidence.object_ref:
            reads.append(ref)
            if len(reads) == 2:
                return body + b"# tampered between evidence reads\n"
        return body

    monkeypatch.setattr(storage, "get_bytes", changed)
    with actor_scope(UserProfile.model_validate(v["owner"])):
        with pytest.raises(EvidenceIntegrityError, match="digest mismatch"):
            service.read(v["project_id"], ident)
        assert len(reads) == 2
        assert service.images._verified_reads.get() is None
        assert evidence.reader._manifests.get() is None
        assert storage._read_clients.get() is None
        monkeypatch.setattr(storage, "get_bytes", original)
        assert service.read(v["project_id"], ident) == record
