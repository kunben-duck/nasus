from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.link_candidates import LinkCandidateQueryApplicationService
from apps.api.app.application.system_image.screened_link_candidates import ScreenedLinkCandidateQueryApplicationService
from apps.api.app.application.system_image.semantic_screening import SemanticScreeningItem, SemanticScreeningSnapshot
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_link_candidate_queries import Images, DIGEST


class RegisteredImages(Images):
    def __init__(self):
        super().__init__()
        code = self.members.pop("code")
        self.objects = [o for o in self.objects if o["id"] != "code"]
        for i in range(40):
            ident = f"code-{i:02d}"
            self.members[ident] = {**code, "object_id": ident, "entity_id": ident, "entity_revision_id": ident + "-rev"}
            self.objects.append({"id": ident, "name": "SearchController.emptyInput"})
        self.header.code_member_count = 40
        for ident, doc in self.docs.items():
            member = self.members[ident]
            doc["document"].update(binding_id=ident + "-binding", entity_id=ident,
                document_revision_id=member["document_revision_id"], source_revision_id=member["source_revision_id"])
            doc["projection"]["identity_status"] = "explicit_id"

    def frozen_snapshot(self, *args):
        header, payload = super().frozen_snapshot(*args)
        payload["source_members"] = [{"source_revision_id": ident + "-source", "binding_id": ident + "-binding"}
                                     for ident in ("code", "parent", "ac", "test")]
        return header, payload


def service(images, make_items):
    def screen(project, image, digest, relation, subjects, target, **kwargs):
        assert len(subjects) == 40  # Model selection's 30-item cap does not truncate recall screening.
        return SemanticScreeningSnapshot(project, image, digest, relation, subjects, target, make_items(subjects))
    return ScreenedLinkCandidateQueryApplicationService(images,
        SimpleNamespace(screen_endpoints=screen, require_current=lambda snapshot: None))


def review(ident, status, decision="reject", suffix=""):
    return SemanticScreeningItem(ident, ident + suffix, DIGEST, "claim" + suffix, "old-image", decision, status, "fixture")


def test_full_matched_corpus_is_screened_before_limit_not_only_raw_top_n():
    images = RegisteredImages()
    raw = LinkCandidateQueryApplicationService(images).read("p", "i", "ac", relation="implements", limit=40)
    excluded = {item.endpoint.object_id for item in raw.items[:-1]}
    query = service(images, lambda subjects: tuple(review(s.object_id, "rejected_same_revisions") for s in subjects if s.object_id in excluded))
    page = query.read("p", "i", "ac", relation="implements", limit=1)
    assert page.items[0].endpoint == raw.items[-1].endpoint
    assert page.pre_review_matched_count == 40 and page.matched_count == 1 and not page.truncated
    assert page.excluded["historical_review"] == 39
    assert page.items[0].review_status == "unreviewed"
    assert LinkCandidateQueryApplicationService(images).read("p", "i", "ac", relation="implements", limit=40) == raw


def test_stale_wins_over_reviewed_but_rejection_wins_over_both():
    images = RegisteredImages()
    def items(subjects):
        return (review(subjects[0].object_id, "same_revisions_review_required", "accept"),
            review(subjects[0].object_id, "stale_requires_review", suffix="old"),
            review(subjects[1].object_id, "same_revisions_review_required", "accept"),
            review(subjects[1].object_id, "rejected_same_revisions", suffix="old"))
    page = service(images, items).read("p", "i", "ac", relation="implements", limit=1)
    assert page.items[0].review_status == "requires_revalidation"
    assert page.matched_count == 39 and page.excluded["historical_review"] == 1 and page.truncated


def test_last_authorization_check_cannot_return_a_stale_screened_page():
    images = RegisteredImages()
    query = service(images, lambda subjects: ())
    query.screening.require_current = lambda snapshot: setattr(images, "allowed", False)
    with pytest.raises(SourceAccessDenied):
        query.read("p", "i", "ac", relation="implements")
