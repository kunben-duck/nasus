"""Reference derivation reuses immutable reads, not authorization or writes."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.reference_links import (
    ReferenceLinkApplicationService, ReferenceProposalInput, StoredReferenceProposal,
)
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied


@pytest.fixture
def reference_application():
    reads, scopes, writes = [], [], []
    state = SimpleNamespace(active=False, sessions=0, failure=None, deny=False)
    request = ReferenceProposalInput(project_id="project", image_revision_id="image")
    members = tuple({"object_id": kind, "document_revision_id": f"{kind}@1",
                     "source_revision_id": f"{kind}-source@1"} for kind in ("requirement", "case"))

    @contextmanager
    def verified_read_session():
        assert not state.active
        state.sessions += 1
        state.active = True
        try:
            yield
        finally:
            state.active = False

    def document(project, image, object_id, **kwargs):
        reads.append(("document", state.active))
        is_requirement = object_id == "requirement"
        return {"fields": [] if is_requirement else [{"name": "reference", "value": "US-17",
            "start_line": 2, "end_line": 2, "snippet_hash": "reference-hash"}],
            "evidence": [{"evidence_id": f"{object_id}-whole", "start_line": 1, "end_line": 3,
                "snippet_hash": "whole-hash"}] + ([] if is_requirement else [{"evidence_id": "case-reference",
                "start_line": 2, "end_line": 2, "snippet_hash": "reference-hash"}]),
            "projection": {"kind": "requirement" if is_requirement else "test_case",
                "external_id": "US-17" if is_requirement else "TC-9", "identity_status": "explicit_id",
                "locator": {"start_line": 1, "end_line": 3}, "snippet_hash": "whole-hash"},
            "next_offset": None}

    def evidence(*args, **kwargs):
        reads.append(("evidence", state.active))
        if state.failure:
            raise state.failure
        return SimpleNamespace(content="US-17", next_start_line=None)

    def require_current(scope):
        scopes.append(state.active)
        if state.deny:
            raise SourceAccessDenied("private source scope changed")

    def record(proposal, *, require_current_scope, **kwargs):
        writes.append(state.active)
        require_current_scope()
        return StoredReferenceProposal("proposal", proposal.digest, "2026-10-08T00:00:00Z", proposal, ("assertion",))

    images = SimpleNamespace(verified_read_session=verified_read_session,
        frozen_document_members=lambda *args: (SimpleNamespace(artifact_hash="sha256:" + "a" * 64), members),
        read_document=document, read_evidence=evidence)
    application = ReferenceLinkApplicationService(images, SimpleNamespace(record=record),
        SimpleNamespace(scope=lambda *args: SimpleNamespace(actor_id="owner"), require_current=require_current))
    return SimpleNamespace(application=application, request=request, state=state, reads=reads, scopes=scopes, writes=writes)


def test_derivation_uses_one_read_session_and_closes_it_before_persistence(reference_application):
    v = reference_application
    result = v.application.propose(v.request, invocation_id="command", created_at="2026-10-08T00:00:00Z")
    assert len(result.proposal.assertions) == 1
    assert v.state.sessions == 1 and not v.state.active
    assert len(v.reads) == 4 and all(active for _, active in v.reads)
    assert v.writes == [False] and v.scopes == [False, False, False]
    v.application.propose(v.request, invocation_id="another-command", created_at="2026-10-08T00:00:00Z")
    assert v.state.sessions == 2 and not v.state.active


def test_evidence_failure_closes_session_without_persisting_partial_candidates(reference_application):
    v = reference_application
    v.state.failure = ImageRevisionIntegrityError("archive mismatch")
    with pytest.raises(ImageRevisionIntegrityError, match="archive mismatch"):
        v.application.propose(v.request, invocation_id="command", created_at="2026-10-08T00:00:00Z")
    assert v.state.sessions == 1 and not v.state.active and not v.writes


def test_permissions_are_rechecked_outside_the_immutable_read_session(reference_application):
    v = reference_application
    v.state.deny = True
    with pytest.raises(SourceAccessDenied):
        v.application.propose(v.request, invocation_id="command", created_at="2026-10-08T00:00:00Z")
    assert v.state.sessions == 1 and not v.state.active
    assert v.scopes == [False] and not v.writes
