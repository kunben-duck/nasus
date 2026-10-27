"""Operation-local image reuse must not become a cross-request authority cache."""
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.acceptance_sources import FrozenRequirementSourceApplicationService
from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.application.quality_loop.acceptance_specifications import AcceptanceSpecificationApplicationService
from apps.api.app.domain.quality_loop.acceptance_specification import (
    AcceptanceIntegrityError, AcceptanceRevision, acceptance_digest, acceptance_identity,
)


class ReadPort:
    def __init__(self):
        self.entered = 0
        self.exited = 0

    @contextmanager
    def verified_read_session(self):
        self.entered += 1
        try:
            yield
        finally:
            self.exited += 1


def query():
    repository, evidence = ReadPort(), ReadPort()
    return ImageRevisionQueryApplicationService(repository, None, None, evidence=evidence), repository, evidence


def test_reuse_joins_only_an_existing_operation_and_next_operation_is_fresh():
    images, repository, evidence = query()
    with images.verified_read_session():
        outer = images._verified_reads.get()
        outer["fixed-image"] = {"digest": "original"}
        with images.verified_read_session(reuse=True):
            assert images._verified_reads.get() is outer
            assert (repository.entered, evidence.entered) == (1, 1)
        assert images._verified_reads.get() is outer
    assert images._verified_reads.get() is None
    with images.verified_read_session(reuse=True):
        assert images._verified_reads.get() == {}
        assert images._verified_reads.get() is not outer
    assert (repository.entered, repository.exited, evidence.entered, evidence.exited) == (2, 2, 2, 2)


def test_default_nested_operations_still_have_independent_snapshots():
    images, repository, evidence = query()
    with images.verified_read_session():
        outer = images._verified_reads.get()
        with images.verified_read_session():
            assert images._verified_reads.get() is not outer
        assert images._verified_reads.get() is outer
    assert images._verified_reads.get() is None
    assert (repository.entered, repository.exited, evidence.entered, evidence.exited) == (2, 2, 2, 2)


def test_reused_scope_does_not_swallow_failure_or_close_its_outer_snapshot():
    images, repository, evidence = query()
    with images.verified_read_session():
        outer = images._verified_reads.get()
        with pytest.raises(ValueError, match="corrupt input"):
            with images.verified_read_session(reuse=True):
                raise ValueError("corrupt input")
        assert images._verified_reads.get() is outer
        assert (repository.exited, evidence.exited) == (0, 0)
    assert images._verified_reads.get() is None
    assert (repository.exited, evidence.exited) == (1, 1)


@pytest.mark.parametrize("kind", ["acceptance_criterion", "business_rule"])
def test_authority_source_inspection_scopes_its_fixed_reads_and_reuses_enclosing_compiler(kind, monkeypatch):
    images, repository, evidence = query()
    source = FrozenRequirementSourceApplicationService(images, kind=kind)
    scopes = []

    def inspect(*args):
        scopes.append(images._verified_reads.get())
        assert scopes[-1] is not None
        return args

    monkeypatch.setattr(source, "_inspect", inspect)
    args = ("project", "image", "digest", "object")
    assert source.inspect(*args) == args
    assert images._verified_reads.get() is None
    with images.verified_read_session():
        outer = images._verified_reads.get()
        assert source.inspect(*args) == args
        assert source.inspect(*args) == args
        assert scopes[-2] is outer and scopes[-1] is outer
    assert scopes[0] is not outer
    assert images._verified_reads.get() is None
    assert (repository.entered, repository.exited, evidence.entered, evidence.exited) == (2, 2, 2, 2)


def test_failed_authority_source_inspection_resets_its_local_read_scope(monkeypatch):
    images, repository, evidence = query()
    source = FrozenRequirementSourceApplicationService(images, kind="acceptance_criterion")

    def fail(*args):
        assert images._verified_reads.get() is not None
        raise ValueError("invalid source")

    monkeypatch.setattr(source, "_inspect", fail)
    with pytest.raises(ValueError, match="invalid source"):
        source.inspect("project", "image", "digest", "object")
    assert images._verified_reads.get() is None
    assert (repository.entered, repository.exited, evidence.entered, evidence.exited) == (1, 1, 1, 1)


def test_inspection_rejects_a_substituted_head_before_reading_its_private_artifact():
    basis = {"project_id": "project", "image_revision_id": "image", "object_id": "object"}
    head = AcceptanceRevision("revision", acceptance_identity("project", "image", "object"), "project", "image",
        "sha256:" + "a" * 64, "object", "binding", "source", "document", acceptance_digest(basis),
        "approved", None, 1, "reviewer", "command", "now", "sha256:" + "b" * 64)
    reads = []
    service = AcceptanceSpecificationApplicationService(
        SimpleNamespace(inspect=lambda *args: basis),
        SimpleNamespace(scope=lambda project: SimpleNamespace(effective_project_role="qa_lead")),
        SimpleNamespace(history=lambda *args: (head,), get=lambda *args: (replace(head, authority_actor="other"), "private")),
        SimpleNamespace(read=lambda *args: reads.append(args)),
    )
    with pytest.raises(AcceptanceIntegrityError, match="inspection head mismatch"):
        service.inspect("project", "image", head.image_artifact_hash, "object")
    assert reads == []
