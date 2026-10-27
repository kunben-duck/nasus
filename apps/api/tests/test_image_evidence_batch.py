from types import SimpleNamespace

import pytest

from apps.api.app.application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from apps.api.app.domain.system_image.image_revision import build_image_artifact, ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_access import SourceAccessDenied, SourceAccessScope
from apps.api.tests.test_image_revision import candidate, header


def service():
    payload, _ = build_image_artifact(candidate()[0], "baseline", *candidate()[1:])
    payload["members"][0]["evidence_ids"] = ["one", "two"]
    calls, evidence_calls = [], []
    authorization = SimpleNamespace(allowed=True)

    def current(_):
        if not authorization.allowed:
            raise SourceAccessDenied("revoked")

    authorization.scope = lambda _: SourceAccessScope("project", "actor", "tester", 0,
        frozenset({"binding"}), frozenset({"source"}), "sha256:" + "a" * 64, False)
    authorization.require_current = current

    def artifact(*args):
        calls.append(args)
        return payload

    def evidence(_, ident, **kwargs):
        evidence_calls.append(ident)
        return SimpleNamespace(integrity="verified", evidence=SimpleNamespace(evidence_id=ident,
            source_revision_id="source-revision", binding_id="binding"))

    application = ImageRevisionQueryApplicationService(
        SimpleNamespace(get=lambda *_: (header(payload), "archive", frozenset({"binding"}))),
        SimpleNamespace(read=artifact), authorization, SimpleNamespace(read=evidence))
    return application, calls, evidence_calls


def test_batch_reuses_only_query_local_verified_image_not_source_authorization():
    application, calls, evidence_calls = service()
    application.verify_evidence_selection("project", "image", (("code", "one"), ("code", "two")))
    assert len(calls) == 1 and evidence_calls == ["one", "two"]
    application.verify_evidence_selection("project", "image", (("code", "one"),))
    assert len(calls) == 2


@pytest.mark.parametrize("selection", [(), (("code", "one"),) * 2, tuple(("code", str(i)) for i in range(513))])
def test_invalid_batches_are_rejected_before_storage(selection):
    application, calls, evidence_calls = service()
    with pytest.raises(ValueError):
        application.verify_evidence_selection("project", "image", selection)
    assert not calls and not evidence_calls


@pytest.mark.parametrize("selection", [(("core", "one"),), (("code", "unfrozen"),), (("unknown", "one"),)])
def test_batch_evidence_cannot_escape_frozen_membership(selection):
    application, _, evidence_calls = service()
    with pytest.raises(KeyError):
        application.verify_evidence_selection("project", "image", selection)
    assert not evidence_calls


def test_batch_rejects_revocation_before_reading_the_next_source():
    application, _, evidence_calls = service()
    original = application.evidence.read

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        application.authorization.allowed = False
        return result

    application.evidence.read = revoke
    with pytest.raises(SourceAccessDenied):
        application.verify_evidence_selection("project", "image", (("code", "one"), ("code", "two")))
    assert evidence_calls == ["one"]


def test_batch_rejects_wrong_adapter_scope():
    application, _, _ = service()
    application.evidence.read = lambda *args, **kwargs: SimpleNamespace(integrity="verified",
        evidence=SimpleNamespace(evidence_id="one", source_revision_id="wrong", binding_id="binding"))
    with pytest.raises(ImageRevisionIntegrityError):
        application.verify_evidence_selection("project", "image", (("code", "one"),))
