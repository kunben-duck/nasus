from copy import deepcopy
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.link_candidates import LinkCandidateQueryApplicationService
from apps.api.app.application.system_image.image_query_models import ImageLinkCandidatesInput
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from apps.api.app.domain.system_image.source_access import SourceAccessDenied


DIGEST = "sha256:" + "a" * 64


class Images:
    def __init__(self):
        self.allowed = True
        self.snapshot_depth = 0
        self.snapshot_entries = []
        self.header = SimpleNamespace(artifact_hash=DIGEST, code_member_count=1)
        self.authorization = SimpleNamespace(scope=lambda _: "scope", require_current=self.current)
        self.members, self.docs, self.objects, self.reads = {}, {}, [], []
        for ident, kind, fields in (("parent", "requirement", [("description", "Search empty input"), ("description", "HTTP service")]),
            ("ac", "acceptance_criterion", [("acceptance_criterion", "Empty input returns HTTP 400")]),
            ("test", "test_case", [("step", "Empty input"), ("expected_result", "HTTP 400")])):
            values = [{"name": name, "value": value, "start_line": i + 1, "end_line": i + 1, "snippet_hash": DIGEST} for i, (name, value) in enumerate(fields)]
            evidence = [{"evidence_id": f"{ident}-{i}", **{k: f[k] for k in ("start_line", "end_line", "snippet_hash")}} for i, f in enumerate(values)]
            self.members[ident] = {"object_id": ident, "document_revision_id": ident + "-rev", "kind": "source_document",
                                  "source_revision_id": ident + "-source", "object_hash": DIGEST, "evidence_ids": [e["evidence_id"] for e in evidence]}
            self.docs[ident] = {"document": {"parent_document_revision_id": "parent-rev"} if ident == "ac" else {},
                "projection": {"kind": kind, "title": ident, "external_id": "US-17" if ident == "parent" else None},
                "payload_hash": DIGEST, "fields": values, "evidence": evidence}
            self.objects.append({"id": ident, "name": ident})
        self.members["code"] = {"object_id": "code", "kind": "code_entity", "entity_revision_id": "code-rev",
            "source_revision_id": "code-source", "object_hash": DIGEST, "evidence_ids": ["code-evidence"]}
        self.objects.append({"id": "code", "name": "SearchController.emptyInput"})

    def current(self, _):
        if not self.allowed:
            raise SourceAccessDenied("revoked")

    @contextmanager
    def verified_read_session(self, *, reuse=False):
        if reuse and self.snapshot_depth:
            yield
            return
        self.snapshot_depth += 1
        self.snapshot_entries.append(self.snapshot_depth)
        try:
            yield
        finally:
            self.snapshot_depth -= 1

    def frozen_snapshot(self, *_):
        return self.header, {"members": list(self.members.values()), "objects": self.objects}

    def read_document(self, project, revision, object_id, *, offset, limit):
        doc = deepcopy(self.docs[object_id])
        fields = doc["fields"]
        return {**doc, "fields": fields[offset:offset + 1], "next_offset": offset + 1 if offset + 1 < len(fields) else None}

    def read_evidence(self, project, revision, object_id, evidence_id, **kwargs):
        self.reads.append((object_id, evidence_id))

    def verify_evidence_selection(self, project, revision, selection):
        for object_id, evidence_id in selection:
            self.read_evidence(project, revision, object_id, evidence_id)


def test_full_document_pagination_keeps_expected_field_not_just_case_title():
    images = Images()
    page = LinkCandidateQueryApplicationService(images).read("p", "i", "ac", relation="asserts")
    assert page.items[0].endpoint.evidence_ids == ("test-1",)
    assert images.reads == [("ac", "ac-0"), ("test", "test-1")]
    assert page.target.revision_id == "ac-rev"
    assert page.items[0].calibrated_probability is None


def test_recall_snapshot_covers_documents_and_selected_evidence_but_not_later_pages():
    images = Images()
    original_document, original_verify = images.read_document, images.verify_evidence_selection
    depths = []

    def document(*args, **kwargs):
        depths.append(images.snapshot_depth)
        return original_document(*args, **kwargs)

    def verify(*args, **kwargs):
        depths.append(images.snapshot_depth)
        return original_verify(*args, **kwargs)

    images.read_document, images.verify_evidence_selection = document, verify
    query = LinkCandidateQueryApplicationService(images)
    query.read("p", "i", "ac", relation="asserts")
    assert depths and set(depths) == {1}
    assert images.snapshot_entries == [1] and images.snapshot_depth == 0
    corpus = query.collect("p", "i", "ac", relation="asserts")
    assert images.snapshot_entries == [1, 1] and images.snapshot_depth == 0
    query.page(corpus, limit=30)
    assert depths[-1] == 0 and images.snapshot_depth == 0


def test_failed_recall_releases_snapshot_and_next_call_rechecks_access():
    images = Images()
    query = LinkCandidateQueryApplicationService(images)
    original = images.read_document

    def damaged(*args, **kwargs):
        raise ImageRevisionIntegrityError("damaged")

    images.read_document = damaged
    with pytest.raises(ImageRevisionIntegrityError, match="damaged"):
        query.read("p", "i", "ac", relation="asserts")
    assert images.snapshot_depth == 0
    images.read_document = original
    query.read("p", "i", "ac", relation="asserts")
    images.allowed = False
    with pytest.raises(SourceAccessDenied):
        query.read("p", "i", "ac", relation="asserts")
    assert images.snapshot_entries == [1, 1, 1] and images.snapshot_depth == 0


def test_nested_recall_reuses_immutable_scope_without_reusing_access_decisions():
    images = Images()
    query = LinkCandidateQueryApplicationService(images)
    with images.verified_read_session():
        query.read("p", "i", "ac", relation="asserts")
        query.collect("p", "i", "ac", relation="asserts")
        images.allowed = False
        with pytest.raises(SourceAccessDenied):
            query.read("p", "i", "ac", relation="asserts")
        assert images.snapshot_depth == 1 and images.snapshot_entries == [1]
    assert images.snapshot_depth == 0
    images.allowed = True
    query.collect("p", "i", "ac", relation="asserts")
    assert images.snapshot_depth == 0 and images.snapshot_entries == [1, 1]


def test_recall_receipt_is_version_pinned_and_digest_mismatch_fails():
    images = Images()
    tools = ImageQueryToolApplicationService(images)
    request = ImageLinkCandidatesInput(project_id="p", image_revision_id="i", target_object_id="ac", relation="implements")
    receipt = tools.execute(request)
    assert receipt.candidates[0].revision_id == "code-rev" and receipt.target.revision_id == "ac-rev"
    assert "SearchController" not in receipt.model_dump_json()
    assert tools.expand(receipt).items[0].endpoint.title == "SearchController.emptyInput"
    with pytest.raises(ImageRevisionIntegrityError, match="receipt"):
        tools.expand(receipt.model_copy(update={"result_hash": "sha256:" + "b" * 64}))
    images.objects[-1]["name"] = "ChangedSearchController.emptyInput"
    with pytest.raises(ImageRevisionIntegrityError, match="receipt"):
        tools.expand(receipt)


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101}, {"limit": True}, {"limit": "30"},
    {"method_version": "latest"}, {"relation": "covers"}])
def test_application_does_not_depend_only_on_http_validation(kwargs):
    with pytest.raises(ValueError):
        LinkCandidateQueryApplicationService(Images()).read("p", "i", "ac", **{"relation": "asserts", **kwargs})


def test_source_permission_is_rechecked_after_last_evidence_read():
    images = Images()
    images.read_evidence = lambda *args, **kwargs: setattr(images, "allowed", False)
    with pytest.raises(SourceAccessDenied):
        LinkCandidateQueryApplicationService(images).read("p", "i", "ac", relation="asserts")


def test_parent_closure_field_evidence_and_cursor_fail_closed():
    images = Images()
    query = LinkCandidateQueryApplicationService(images)
    images.members.pop("parent")
    with pytest.raises(ImageRevisionIntegrityError, match="parent"):
        query.read("p", "i", "ac", relation="asserts")
    images = Images()
    images.docs["ac"]["evidence"] = []
    with pytest.raises(ImageRevisionIntegrityError, match="evidence"):
        LinkCandidateQueryApplicationService(images).read("p", "i", "ac", relation="asserts")
    images = Images()
    original = images.read_document
    images.read_document = lambda *args, **kwargs: {**original(*args, **kwargs), "next_offset": 0}
    with pytest.raises(ImageRevisionIntegrityError, match="cursor"):
        LinkCandidateQueryApplicationService(images).read("p", "i", "ac", relation="asserts")


def test_corpus_budget_and_explicit_evidence_budget_are_not_silent_sampling():
    images = Images()
    images.header.code_member_count = 10001
    with pytest.raises(ImageRevisionPageTooLarge):
        LinkCandidateQueryApplicationService(images).read("p", "i", "ac", relation="implements")
    images = Images()
    for i in range(6):
        images.members[str(i)] = {**images.members["code"], "object_id": str(i), "entity_revision_id": str(i) + "-rev",
            "evidence_ids": [f"ev-{i}-{j}" for j in range(100)]}
        images.objects.append({"id": str(i), "name": "SearchController.emptyInput"})
    with pytest.raises(ImageRevisionPageTooLarge, match="512 spans"):
        LinkCandidateQueryApplicationService(images).read("p", "i", "ac", relation="implements")
    assert images.reads == []


def test_rule_supports_implementation_investigation_not_test_coverage_claim():
    images = Images()
    images.docs["ac"]["projection"]["kind"] = "business_rule"
    images.docs["ac"]["fields"][0]["name"] = "business_rule"
    service = LinkCandidateQueryApplicationService(images)
    assert service.read("p", "i", "ac", relation="implements").target.kind == "business_rule"
    with pytest.raises(ValueError):
        service.read("p", "i", "ac", relation="asserts")
