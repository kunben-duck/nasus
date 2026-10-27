from __future__ import annotations

from dataclasses import asdict, replace
import hashlib

import pytest

from apps.api.app.application.system_image.evidence_queries import EvidenceQueryApplicationService, EvidenceReadTarget
from apps.api.app.domain.system_image.evidence import (
    DECODER_VERSION, EvidenceIntegrityError, EvidenceLocationUnavailable, EvidenceLocator,
    EvidencePageTooLarge, SourceEvidence, source_lines, text_digest,
)


def target(text="def run():\n    return 'ok'\n"):
    return EvidenceReadTarget(
        SourceEvidence("evidence", "project", "binding", "revision", EvidenceLocator("code.py", 1, 2, "exact"),
                       "sha256:" + hashlib.sha256(text.encode()).hexdigest(), text_digest(text),
                       "s3://private/raw", DECODER_VERSION, "extractor-v2", "2026-09-09"),
        "source", "s3://private/manifest", "sha256:" + "a" * 64, "sha256:" + "b" * 64,
    )


class Authorization:
    allowed = True

    def require_project_access(self, project_id):
        if not self.allowed:
            raise PermissionError("membership revoked")

    def require_binding_access(self, project_id, binding_id):
        self.require_project_access(project_id)

    def require_revision_access(self, project_id, source_revision_id):
        self.require_project_access(project_id)


class Repository:
    def __init__(self, value):
        self.value = value

    def get(self, project_id, evidence_id):
        return self.value

    def get_many(self, project_id, evidence_ids):
        return [self.value]

    def list_for_alias(self, *args, **kwargs):
        return [self.value.evidence]


class Reader:
    calls = 0

    def __init__(self, body):
        self.body = body

    def read(self, value):
        self.calls += 1
        return self.body


def service(value=None, text="def run():\n    return 'ok'\n"):
    reader = Reader(text.encode())
    authorization = Authorization()
    return EvidenceQueryApplicationService(Repository(value or target(text)), reader, authorization, authorization), reader, authorization


def test_page_preserves_source_lines_and_exposes_no_object_references():
    app, _, _ = service()
    first = app.read("project", "evidence", max_lines=1)
    second = app.read("project", "evidence", start_line=first.next_start_line, max_lines=1)
    assert first.content == "def run():\n"
    assert second.content == "    return 'ok'\n"
    assert second.next_start_line is None
    assert first.excerpt_hash == text_digest(first.content)
    assert first.integrity == "verified"
    assert "s3://" not in str(asdict(first))
    assert "object_ref" not in asdict(first)["evidence"]
    assert "s3://" not in str(app.list_for_alias("project", "revision", "object"))


def test_unauthorized_read_does_not_fetch_storage():
    app, reader, authorization = service()
    authorization.allowed = False
    with pytest.raises(PermissionError):
        app.read("project", "evidence")
    assert reader.calls == 0


def test_membership_revoked_during_object_read_prevents_response():
    app, reader, authorization = service()
    original = reader.read

    def revoke(value):
        authorization.allowed = False
        return original(value)

    reader.read = revoke
    with pytest.raises(PermissionError):
        app.read("project", "evidence")


def test_project_scope_is_checked_even_if_repository_is_faulty():
    app, reader, _ = service()
    with pytest.raises(KeyError):
        app.read("foreign", "evidence")
    assert reader.calls == 0


@pytest.mark.parametrize("project,revision", [("foreign", "revision"), ("project", "foreign")])
def test_evidence_list_does_not_leak_a_faulty_repository_result(project, revision):
    app, reader, _ = service()
    with pytest.raises(KeyError):
        app.list_for_alias(project, revision, "object")
    assert reader.calls == 0


def test_wrong_evidence_id_cannot_return_an_unrelated_excerpt():
    app, reader, _ = service()
    with pytest.raises(KeyError):
        app.read("project", "unrelated")
    assert reader.calls == 0


def test_approximate_location_never_returns_a_misleading_excerpt():
    value = target()
    value = replace(value, evidence=replace(value.evidence, locator=replace(value.evidence.locator, precision="approximate"), snippet_hash=None))
    app, reader, _ = service(value)
    with pytest.raises(EvidenceLocationUnavailable):
        app.read("project", "evidence")
    assert reader.calls == 0


@pytest.mark.parametrize("kind", ["file", "snippet", "decoder", "range"])
def test_integrity_mismatch_is_not_presented_as_verified(kind):
    value = target()
    if kind == "file":
        value = replace(value, evidence=replace(value.evidence, file_hash="sha256:" + "0" * 64))
    elif kind == "snippet":
        value = replace(value, evidence=replace(value.evidence, snippet_hash="sha256:" + "0" * 64))
    elif kind == "decoder":
        value = replace(value, evidence=replace(value.evidence, decoder_version="unknown"))
    else:
        value = replace(value, evidence=replace(value.evidence, locator=replace(value.evidence.locator, end_line=20)))
    app, _, _ = service(value)
    with pytest.raises(EvidenceIntegrityError):
        app.read("project", "evidence")


def test_lf_coordinates_do_not_treat_unicode_separators_as_extra_rows():
    text = 'first = "a\u2028b\vcontinued"\r\nsecond = "value"\n'
    assert source_lines(text) == ['first = "a\u2028b\vcontinued"\r\n', 'second = "value"\n', ""]
    app, _, _ = service(text=text)
    assert app.read("project", "evidence", start_line=2).content == 'second = "value"\n'


@pytest.mark.parametrize("kwargs", [{"start_line": 0}, {"start_line": 3}, {"max_lines": 0}, {"max_lines": 201}])
def test_invalid_or_unbounded_page_request_is_rejected(kwargs):
    app, reader, _ = service()
    with pytest.raises(ValueError):
        app.read("project", "evidence", **kwargs)
    assert reader.calls == 0


def test_large_line_is_rejected_not_silently_cut():
    text = "x" * 65537 + "\nsecond\n"
    app, _, _ = service(text=text)
    with pytest.raises(EvidencePageTooLarge):
        app.read("project", "evidence")


def test_batch_verifies_complete_bytes_but_returns_only_metadata():
    app, reader, _ = service()
    values = app.verify_many("project", (("revision", "evidence"),))
    assert len(values) == 1 and values[0].evidence_id == "evidence" and reader.calls == 1
    assert "return" not in str(asdict(values[0])) and "s3://" not in str(asdict(values[0]))
    reader.body = b"corrupt\n"
    with pytest.raises(EvidenceIntegrityError):
        app.verify_many("project", (("revision", "evidence"),))


@pytest.mark.parametrize("project,selection", [("foreign", (("revision", "evidence"),)),
    ("project", (("wrong-revision", "evidence"),)), ("project", (("revision", "other"),))])
def test_batch_rejects_wrong_repository_scope_before_storage(project, selection):
    app, reader, _ = service()
    with pytest.raises(KeyError):
        app.verify_many(project, selection)
    assert reader.calls == 0


@pytest.mark.parametrize("selection", [(), (("revision", "evidence"),) * 2,
    tuple(("revision", str(i)) for i in range(513))])
def test_batch_is_bounded_and_deduplicated(selection):
    app, reader, _ = service()
    with pytest.raises(ValueError):
        app.verify_many("project", selection)
    assert reader.calls == 0


@pytest.mark.parametrize("revoke_after", [1, 2, 16, 17, 20])
def test_batch_revocation_stops_at_the_current_file_and_never_returns_partial_metadata(revoke_after):
    app, reader, authorization = service()
    values = [replace(target(), evidence=replace(target().evidence, evidence_id=str(i),
        locator=EvidenceLocator(f"code-{i}.py", 1, 2, "exact"), object_ref=f"s3://private/raw-{i}"))
        for i in range(20)]
    app.repository.get_many = lambda *args: values
    original = reader.read
    def revoke(value):
        body = original(value)
        if reader.calls == revoke_after:
            authorization.allowed = False
        return body
    reader.read = revoke
    with pytest.raises(PermissionError):
        app.verify_many("project", tuple(("revision", str(i)) for i in range(20)))
    assert reader.calls == revoke_after


def batch_service(values, text="def run():\n    return 'ok'\n"):
    app, reader, authorization = service(text=text)
    app.repository.get_many = lambda *args: values
    return app, reader, authorization


def selection_for(values):
    return tuple((value.evidence.source_revision_id, value.evidence.evidence_id) for value in values)


def file_spans():
    value = target()
    return [replace(value, evidence=replace(value.evidence, evidence_id=f"span-{index}",
        locator=EvidenceLocator("code.py", index, index, "exact"), snippet_hash=text_digest(line)))
        for index, line in enumerate(("def run():\n", "    return 'ok'\n"), 1)]


def test_batch_reads_a_pinned_file_once_verifies_all_spans_and_does_not_cache_next_request():
    values = file_spans()
    app, reader, authorization = batch_service(values)
    checks = []
    original = authorization.require_binding_access
    def check(project_id, binding_id):
        checks.append((project_id, binding_id))
        original(project_id, binding_id)
    authorization.require_binding_access = check
    assert [item.evidence_id for item in app.verify_many("project", selection_for(values))] == ["span-1", "span-2"]
    assert reader.calls == 1 and len(checks) == 4
    reader.body = b"corrupt\n"
    with pytest.raises(EvidenceIntegrityError):
        app.verify_many("project", selection_for(values))
    assert reader.calls == 2


def test_batch_preserves_repository_order_for_interleaved_file_spans():
    first, second = file_spans()
    other = replace(first, evidence=replace(first.evidence, evidence_id="other-file",
        locator=EvidenceLocator("other.py", 1, 1, "exact"), object_ref="s3://private/other"))
    values = [first, other, second]
    app, reader, _ = batch_service(values)
    result = app.verify_many("project", selection_for(values))
    assert [item.evidence_id for item in result] == ["span-1", "other-file", "span-2"]
    assert reader.calls == 2


@pytest.mark.parametrize("field", ["binding_id", "source_revision_id", "relative_path", "object_ref",
    "source_id", "manifest_ref", "manifest_hash", "source_content_hash", "file_hash"])
def test_batch_never_shares_bytes_across_distinct_file_or_manifest_pins(field):
    first, second = file_spans()
    if field == "relative_path":
        second = replace(second, evidence=replace(second.evidence,
            locator=replace(second.evidence.locator, relative_path="other.py")))
    elif field in {"binding_id", "source_revision_id", "object_ref", "file_hash"}:
        value = "sha256:" + "c" * 64 if field == "file_hash" else "other-" + getattr(second.evidence, field)
        second = replace(second, evidence=replace(second.evidence, **{field: value}))
    else:
        value = "sha256:" + "c" * 64 if field.endswith("hash") else "other-" + getattr(second, field)
        second = replace(second, **{field: value})
    values = [first, second]
    app, reader, _ = batch_service(values)
    if field == "file_hash":
        with pytest.raises(EvidenceIntegrityError):
            app.verify_many("project", selection_for(values))
    else:
        assert len(app.verify_many("project", selection_for(values))) == 2
    assert reader.calls == 2


@pytest.mark.parametrize("field", ["snippet", "range", "decoder", "precision"])
def test_batch_checks_every_span_even_when_raw_file_is_shared(field):
    first, second = file_spans()
    if field == "snippet":
        second = replace(second, evidence=replace(second.evidence, snippet_hash="sha256:" + "0" * 64))
    elif field == "range":
        second = replace(second, evidence=replace(second.evidence,
            locator=replace(second.evidence.locator, end_line=20)))
    elif field == "decoder":
        second = replace(second, evidence=replace(second.evidence, decoder_version="unknown"))
    else:
        second = replace(second, evidence=replace(second.evidence, snippet_hash=None,
            locator=replace(second.evidence.locator, precision="approximate")))
    app, _, _ = batch_service([first, second])
    with pytest.raises(EvidenceLocationUnavailable if field == "precision" else EvidenceIntegrityError):
        app.verify_many("project", selection_for([first, second]))


def test_batch_revocation_during_shared_file_read_stops_before_next_file():
    first, second = file_spans()
    other = replace(first, evidence=replace(first.evidence, evidence_id="other-file",
        locator=EvidenceLocator("other.py", 1, 1, "exact"), object_ref="s3://private/other"))
    values = [first, other, second]
    app, reader, authorization = batch_service(values)
    original = reader.read
    def revoke(value):
        body = original(value)
        authorization.allowed = False
        return body
    reader.read = revoke
    with pytest.raises(PermissionError):
        app.verify_many("project", selection_for(values))
    assert reader.calls == 1


@pytest.mark.parametrize("path", [".", "../file.py", "/etc/passwd", "a\\b", "a//b", "a\x00b"])
def test_invalid_source_locator(path):
    with pytest.raises(ValueError):
        EvidenceLocator(path, 1, 2, "exact")
