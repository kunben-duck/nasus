from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.semantic_screening import (
    SemanticScreeningApplicationService, SemanticScreeningItem, SemanticScreeningSnapshot, MAX_MATCHED_REVIEW_HEADS,
)
from apps.api.app.domain.system_image.semantic_applicability import SemanticEndpointIdentity
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence import semantic_review_repository as persistence


def snapshot(items=()):
    return SemanticScreeningSnapshot("project", "image", "sha256:" + "a" * 64, "asserts",
        (SemanticEndpointIdentity("case", "tests", "test-entity", "test-revision", "test-source", "test_case", "explicit_id"),),
        SemanticEndpointIdentity("ac", "requirements", "ac-entity", "ac-revision", "ac-source", "acceptance_criterion", "explicit_id"), items)


@pytest.mark.parametrize("status", ["rejected_same_revisions", "identity_unresolved", "different_endpoints"])
def test_any_blocking_head_wins_over_another_claim_acceptance(status):
    accepted = SemanticScreeningItem("case", "new-accept", "sha256:" + "1" * 64, "other-claim", "new-image",
                                     "accept", "same_revisions_review_required", "review_before_acceptance")
    rejected = SemanticScreeningItem("case", "old-reject", "sha256:" + "2" * 64, "original-claim", "old-image",
                                     "reject", status, "exclude_from_unreviewed_candidates")
    for items in ((accepted, rejected), (rejected, accepted)):
        with pytest.raises(ValueError, match="blocks model egress"):
            snapshot(items).require_eligible()


def test_empty_history_is_pinned_and_policy_or_revision_changes_change_consent():
    original = snapshot()
    original.require_eligible()
    assert original.head_pins == ()
    changed = replace(original, target=replace(original.target, revision_id="changed"))
    assert original.digest != changed.digest
    assert original.digest != replace(original, policy_revision="new-policy").digest
    assert original.digest != replace(original, predicate="implements").digest


def test_current_heads_are_checked_without_silently_rebinding_a_consent():
    original = snapshot()
    service = SemanticScreeningApplicationService(None, SimpleNamespace(matching_heads=lambda *args: ()))
    service.require_current(original)
    service.heads.matching_heads = lambda *args: (("case", "concurrent-decision", "sha256:" + "b" * 64),)
    with pytest.raises(ImageRevisionIntegrityError, match="heads changed"):
        service.require_current(original)


def test_repository_does_not_return_a_truncated_head_set(monkeypatch):
    @contextmanager
    def session():
        def execute(query):
            assert query._limit_clause.value == MAX_MATCHED_REVIEW_HEADS + 1
            return SimpleNamespace(all=lambda: [None] * (MAX_MATCHED_REVIEW_HEADS + 1))
        yield SimpleNamespace(execute=execute)
    monkeypatch.setattr(persistence, "session_scope", session)
    selection = snapshot()
    with pytest.raises(ValueError, match="complete head budget"):
        persistence.SemanticReviewRepository().matching_heads(selection.project_id, selection.predicate, selection.subjects, selection.target)
