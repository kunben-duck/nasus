from types import SimpleNamespace

import pytest

from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.object_provenance_projection_v1 import _columns, _evidence_identity_hash_v1
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceBindingRecord


def native_values():
    return {"project_id": "project", "binding_id": "binding", "source_revision_id": "revision",
        "relative_path": "src/example.py", "start_line": 1, "end_line": 7, "precision": "exact",
        "file_hash": "sha256:" + "1" * 64, "snippet_hash": "sha256:" + "2" * 64,
        "object_ref": "s3://private/files/example", "decoder_version": "utf8-v1", "extractor_version": "v1"}


def test_frozen_binding_read_uses_only_columns_available_at_0070():
    statement = _columns(SourceBindingRecord)
    assert tuple(statement.selected_columns.keys()) == ("binding_id", "project_id", "kind")
    assert "tracked_ref" not in str(statement)


def test_frozen_evidence_identity_digest_is_independent_of_future_columns():
    values = native_values()
    item = SimpleNamespace(**values, evidence_id="opaque", identity_hash="not-an-input", captured_at="later",
        future_native_column="new-metadata", __table__=SimpleNamespace(columns=[SimpleNamespace(name="future_native_column")]))
    assert _evidence_identity_hash_v1(item) == snapshot_digest(values)
    item.future_native_column = "another-value"
    item.captured_at = "new-capture-time"
    assert _evidence_identity_hash_v1(item) == snapshot_digest(values)


@pytest.mark.parametrize("field", tuple(native_values()))
def test_every_v1_evidence_identity_field_remains_part_of_the_digest(field):
    values = native_values()
    original = _evidence_identity_hash_v1(SimpleNamespace(**values))
    changed = {**values, field: values[field] + 1 if type(values[field]) is int else "changed-value"}
    assert _evidence_identity_hash_v1(SimpleNamespace(**changed)) != original
