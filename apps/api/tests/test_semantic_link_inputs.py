from dataclasses import replace

import pytest

from apps.api.app.application.system_image.evidence_queries import EvidencePage, EvidenceSummary
from apps.api.app.application.system_image.semantic_link_inputs import SemanticLinkInputApplicationService
from apps.api.app.domain.system_image.evidence import DECODER_VERSION, EvidenceLocator, text_digest
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from apps.api.app.domain.system_image.source_access import SourceAccessDenied
from apps.api.tests.test_link_candidate_queries import Images, DIGEST


class GroundedImages(Images):
    def __init__(self):
        super().__init__()
        self.spans = {}
        for ident, doc in self.docs.items():
            member = self.members[ident]
            doc["document"].update(document_revision_id=member["document_revision_id"], source_revision_id=member["source_revision_id"])
            for index, field in enumerate(doc["fields"]):
                raw = f'{field["name"]}: {field["value"]}\n'
                evidence_id = doc["evidence"][index]["evidence_id"]
                field["snippet_hash"] = doc["evidence"][index]["snippet_hash"] = text_digest(raw)
                self.spans[evidence_id] = (raw, EvidenceSummary(evidence_id, member["source_revision_id"], ident + "-binding",
                    EvidenceLocator(ident + ".md", index + 1, index + 1, "exact"), DIGEST, text_digest(raw), DECODER_VERSION, "now"))
        raw = 'if (input.isEmpty()) return http400();\n'
        self.spans["code-evidence"] = (raw, EvidenceSummary("code-evidence", "code-source", "code-binding",
            EvidenceLocator("Controller.java", 1, 1, "exact"), DIGEST, text_digest(raw), DECODER_VERSION, "now"))

    def read_document(self, *args, **kwargs):
        return {**super().read_document(*args, **kwargs), "total_fields": len(self.docs[args[2]]["fields"])}

    def read_evidence(self, project, image, object_id, evidence_id, *, start_line=None, max_lines=100):
        self.current(None)
        self.reads.append((object_id, evidence_id))
        raw, evidence = self.spans[evidence_id]
        start = evidence.locator.start_line if start_line is None else start_line
        end = min(evidence.locator.end_line, start + max_lines - 1)
        content = "".join(raw.splitlines(keepends=True)[start - evidence.locator.start_line:end - evidence.locator.start_line + 1])
        return EvidencePage(evidence, content, start, end, end + 1 if end < evidence.locator.end_line else None, text_digest(content))


def prepare(images, **kwargs):
    return SemanticLinkInputApplicationService(images).prepare("p", "i", "ac", **{
        "relation": "asserts", "subject_object_ids": ("test",), "expected_image_hash": DIGEST, **kwargs})


def test_prepare_reads_pinned_complete_source_and_only_expected_fields():
    images = GroundedImages()
    result = prepare(images)
    assert result.target.revision_id == "ac-rev"
    assert result.subjects[0].revision_id == "test-rev"
    assert result.excerpts[1].role == "expected_result" and result.excerpts[1].field_index == 1
    assert result.excerpts[1].text == "HTTP 400" and result.excerpts[1].raw_text == "expected_result: HTTP 400\n"
    assert result.excerpts[1].text_hash != result.excerpts[1].snippet_hash
    assert prepare(images) == result
    images.docs["test"]["fields"][1]["value"] = "different result"
    assert prepare(images).digest != result.digest


def test_preparation_reuses_operation_snapshot_and_releases_it_before_returning_model_input():
    images = GroundedImages()
    original = images.read_evidence
    depths, authorization_depths = [], []
    current = images.authorization.require_current

    def require_current(scope):
        authorization_depths.append(images.snapshot_depth)
        return current(scope)

    def evidence(*args, **kwargs):
        depths.append((kwargs.get("max_lines"), images.snapshot_depth))
        return original(*args, **kwargs)

    images.read_evidence = evidence
    images.authorization.require_current = require_current
    result = prepare(images)
    assert result.excerpts
    assert images.snapshot_entries == [1] and images.snapshot_depth == 0
    assert {depth for lines, depth in depths if lines == 200} == {1}
    assert {depth for lines, depth in depths if lines is None} == {1}
    checks = len(authorization_depths)
    assert checks >= len(result.excerpts) + 1 and set(authorization_depths) == {1}
    prepare(images)
    assert images.snapshot_entries == [1, 1] and images.snapshot_depth == 0
    assert len(authorization_depths) == 2 * checks and set(authorization_depths) == {1}


def test_preparation_releases_shared_snapshot_on_denial_and_reverifies_next_input():
    images = GroundedImages()
    original = images.read_evidence

    def revoke(*args, **kwargs):
        page = original(*args, **kwargs)
        images.allowed = False
        return page

    images.read_evidence = revoke
    with pytest.raises(SourceAccessDenied):
        prepare(images)
    assert images.snapshot_depth == 0
    images.read_evidence, images.allowed = original, True
    result = prepare(images)
    assert result.subjects[0].object_id == "test" and images.snapshot_depth == 0
    assert images.snapshot_entries == [1, 1]


def test_code_span_is_complete_across_multiple_pages_not_a_silent_first_page():
    images = GroundedImages()
    raw = "".join(f"// line {i}\n" for i in range(405))
    _, old = images.spans["code-evidence"]
    images.spans["code-evidence"] = (raw, replace(old, locator=EvidenceLocator("Controller.java", 12, 416, "exact"), snippet_hash=text_digest(raw)))
    result = prepare(images, relation="implements", subject_object_ids=("code",))
    assert result.excerpts[1].raw_text == raw and result.excerpts[1].text == raw
    assert result.excerpts[1].field_index is None
    assert result.excerpts[1].end_line == 416
    assert images.reads.count(("code", "code-evidence")) == 4  # one recall verification + three full pages


@pytest.mark.parametrize("kwargs", [
    {"subject_object_ids": ()}, {"subject_object_ids": ["test"]}, {"subject_object_ids": ("test", "test")},
    {"subject_object_ids": ("foreign",)}, {"subject_object_ids": ("ac",)},
    {"subject_object_ids": tuple(str(i) for i in range(31))}, {"expected_image_hash": "head"},
    {"expected_image_hash": text_digest("different image")}, {"recall_limit": True},
])
def test_client_cannot_select_unrecalled_or_unpinned_inputs(kwargs):
    with pytest.raises((ValueError, ImageRevisionIntegrityError)):
        prepare(GroundedImages(), **kwargs)


def test_revoked_scope_after_source_read_discards_entire_input():
    images = GroundedImages()
    original = images.read_evidence
    def read(*args, **kwargs):
        page = original(*args, **kwargs)
        if kwargs.get("max_lines") == 200:
            images.allowed = False
        return page
    images.read_evidence = read
    with pytest.raises(SourceAccessDenied):
        prepare(images)


@pytest.mark.parametrize("change", [
    lambda page: replace(page, excerpt_hash=DIGEST),
    lambda page: replace(page, content="injected source"),
    lambda page: replace(page, integrity="unchecked"),
    lambda page: replace(page, next_start_line=page.start_line),
    lambda page: replace(page, start_line=page.start_line + 1),
    lambda page: replace(page, evidence=replace(page.evidence, source_revision_id="wrong-source")),
])
def test_evidence_page_tampering_is_rejected(change):
    images = GroundedImages()
    original = images.read_evidence
    images.read_evidence = lambda *args, **kwargs: change(original(*args, **kwargs)) if kwargs.get("max_lines") == 200 else original(*args, **kwargs)
    with pytest.raises(ImageRevisionIntegrityError):
        prepare(images)


def test_missing_expected_result_cannot_be_promoted_from_references_or_steps():
    images = GroundedImages()
    images.docs["test"]["fields"][1]["name"] = "reference"
    with pytest.raises(ValueError, match="recalled selection"):
        prepare(images)


def test_document_revision_change_between_recall_and_preparation_is_rejected():
    images = GroundedImages()
    service = SemanticLinkInputApplicationService(images)
    original = service.recall.read
    def recall(*args, **kwargs):
        result = original(*args, **kwargs)
        images.docs["test"]["document"]["document_revision_id"] = "replacement"
        return result
    service.recall.read = recall
    with pytest.raises(ImageRevisionIntegrityError, match="endpoint mismatch"):
        service.prepare("p", "i", "ac", relation="asserts", subject_object_ids=("test",), expected_image_hash=DIGEST)


def test_large_selected_source_span_is_rejected_not_sent_partially():
    images = GroundedImages()
    raw = "x" * 65536 + "\n"
    _, old = images.spans["code-evidence"]
    images.spans["code-evidence"] = (raw, replace(old, snippet_hash=text_digest(raw)))
    with pytest.raises(ImageRevisionPageTooLarge, match="no partial"):
        prepare(images, relation="implements", subject_object_ids=("code",))


def test_source_pages_cannot_omit_the_rest_of_a_span():
    images = GroundedImages()
    raw = "line\n" * 250
    _, old = images.spans["code-evidence"]
    images.spans["code-evidence"] = (raw, replace(old, locator=EvidenceLocator("Controller.java", 1, 250, "exact"), snippet_hash=text_digest(raw)))
    original = images.read_evidence
    def read(*args, **kwargs):
        page = original(*args, **kwargs)
        return replace(page, next_start_line=None) if kwargs.get("max_lines") == 200 else page
    images.read_evidence = read
    with pytest.raises(ImageRevisionIntegrityError, match="truncated"):
        prepare(images, relation="implements", subject_object_ids=("code",))


@pytest.mark.parametrize("change", [lambda p: {**p, "next_offset": None},
    lambda p: {**p, "total_fields": 0}, lambda p: {**p, "next_offset": p["next_offset"] + 1}])
def test_document_field_pages_cannot_silently_skip_expected_fields(change):
    images = GroundedImages()
    service = SemanticLinkInputApplicationService(images)
    original_recall, original_doc = service.recall.read, images.read_document
    def recall(*args, **kwargs):
        result = original_recall(*args, **kwargs)
        images.read_document = lambda *a, **kw: change(original_doc(*a, **kw)) if a[2] == "test" and kw["offset"] == 0 else original_doc(*a, **kw)
        return result
    service.recall.read = recall
    with pytest.raises(ImageRevisionIntegrityError):
        service.prepare("p", "i", "ac", relation="asserts", subject_object_ids=("test",), expected_image_hash=DIGEST)


def test_fields_on_the_same_raw_row_keep_distinct_field_identity():
    images = GroundedImages()
    field = images.docs["test"]["fields"][1]
    images.docs["test"]["fields"].append({**field, "value": "Body includes the validation error"})
    result = prepare(images)
    spans = [item for item in result.excerpts if item.object_id == "test"]
    assert len(spans) == 2 and spans[0].evidence_id == spans[1].evidence_id
    assert spans[0].field_index != spans[1].field_index
    assert spans[0].span_id != spans[1].span_id
