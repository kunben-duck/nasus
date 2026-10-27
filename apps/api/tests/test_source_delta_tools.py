from types import SimpleNamespace

import pytest

from apps.api.app.application.platform.tool_models import ToolResult
from apps.api.app.application.system_image.image_query_models import ImageSourceDeltaInput, ImageSourceDeltaReceipt
from apps.api.app.application.system_image.image_query_tools import ImageQueryToolApplicationService
from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.domain.system_image.source_access import StaleSourceAccessScope
from apps.api.tests.test_source_delta import snapshot
from apps.api.tests.test_source_delta_application import delta_app


def request(**kwargs):
    return ImageSourceDeltaInput(project_id="project", before_revision_id="one", after_revision_id="two", **kwargs)


def test_source_delta_receipt_replays_explicit_pins_and_never_persists_file_paths(delta_app):
    app, _, calls = delta_app
    tools = ImageQueryToolApplicationService(SimpleNamespace(), source_deltas=app)
    receipt = tools.execute(request(limit=1))
    assert isinstance(receipt, ImageSourceDeltaReceipt) and receipt.operation == "source_delta"
    assert receipt.total == 3 and receipt.next_offset == 1
    assert receipt.counts["unchanged"] == receipt.counts["added"] == receipt.counts["deleted"] == 1
    assert all(forbidden not in receipt.model_dump_json() for forbidden in ("old.py", "new.py", "private-ref", "items"))
    page = tools.expand(receipt)
    assert page.content_hash == receipt.delta_hash and len(calls) == 4
    durable = ToolResult(invocation_id="invocation", status="completed", summary="Compared manifests", image_query=receipt)
    assert ToolResult.model_validate_json(durable.model_dump_json()).image_query == receipt
    filtered = tools.execute(request(kind="deleted"))
    rename = tools.execute(request(section="rename_candidates"))
    assert filtered.delta_hash == rename.delta_hash == receipt.delta_hash
    assert filtered.result_hash != rename.result_hash != receipt.result_hash
    assert not tools.expand(rename).items[0].identity_preserved


@pytest.mark.parametrize("fields", [
    {"delta_hash": "sha256:" + "0" * 64}, {"result_hash": "sha256:" + "0" * 64},
    {"before_manifest_hash": "sha256:" + "0" * 64}, {"next_offset": None}, {"complete": False},
])
def test_delta_receipt_tampering_is_detected_by_full_recomputation(delta_app, fields):
    app, _, _ = delta_app
    tools = ImageQueryToolApplicationService(SimpleNamespace(), source_deltas=app)
    receipt = tools.execute(request(limit=1))
    with pytest.raises(ImageRevisionIntegrityError, match="receipt"):
        tools.expand(receipt.model_copy(update=fields))


def test_delta_receipt_replay_rechecks_acl_and_both_archived_manifests(delta_app):
    app, snapshots, calls = delta_app
    tools = ImageQueryToolApplicationService(SimpleNamespace(), source_deltas=app)
    receipt = tools.execute(request())
    snapshots["two"] = snapshot("two", {"new.py": "different", "stay.py": "same"})
    with pytest.raises(ImageRevisionIntegrityError):
        tools.expand(receipt)
    before_reads = len(calls)
    def revoked(scope):
        raise StaleSourceAccessScope("revoked")
    app.authorization.require_current = revoked
    with pytest.raises(StaleSourceAccessScope):
        tools.expand(receipt)
    assert len(calls) == before_reads


@pytest.mark.parametrize("fields", [
    {"limit": True}, {"limit": "1"}, {"offset": -1}, {"before_revision_id": 7},
    {"section": "rename_candidates", "kind": "added"}, {"kind": "accepted"},
    {"source_uri": "/private"}, {"publication_authorized": True},
])
def test_delta_tool_requires_strict_pins_and_rejects_authority_fields(fields):
    with pytest.raises(ValueError):
        ImageSourceDeltaInput.model_validate({"project_id": "project", "before_revision_id": "one",
            "after_revision_id": "two", **fields})


def test_unconfigured_delta_port_does_not_fall_back_to_mutable_image_queries():
    with pytest.raises(ValueError, match="Unsupported image query"):
        ImageQueryToolApplicationService(SimpleNamespace()).execute(request())


def test_source_delta_receipt_cannot_claim_missing_categories_or_authority(delta_app):
    app, _, _ = delta_app
    receipt = ImageQueryToolApplicationService(SimpleNamespace(), source_deltas=app).execute(request())
    for changed in ({"counts": {"added": 1}}, {"impact_complete": True}, {"publication_authorized": True},
                    {"file_bodies_verified": True}, {"counts": {**receipt.counts, "added": True}}):
        with pytest.raises(ValueError):
            ImageSourceDeltaReceipt.model_validate({**receipt.model_dump(), **changed})
