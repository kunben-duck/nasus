from types import SimpleNamespace

import pytest

from apps.api.app.domain.system_image.image_revision import ImageRevisionIntegrityError
from apps.api.app.infrastructure.persistence.code_alias_projection_v1 import CodeAliasProjectorV1


class RecordingSession:
    def __init__(self, rows=()):
        self.rows = rows
        self.statement = None
        self.flushed = False

    def execute(self, statement):
        self.statement = statement
        return self.rows

    def flush(self):
        self.flushed = True


def test_alias_backfill_selects_frozen_binding_fields_instead_of_current_orm():
    session = RecordingSession()
    assert CodeAliasProjectorV1().backfill(session) == 0
    sql = str(session.statement)
    assert "source_bindings.tracked_ref" not in sql
    assert "source_bindings.external_identity" not in sql
    for field in ("project_id", "binding_id", "kind", "legacy_source_id"):
        assert "source_bindings." + field in sql
    assert session.flushed


def test_alias_backfill_preserves_binding_identity_for_the_original_audit(monkeypatch):
    objects = tuple(SimpleNamespace(kind=kind) for kind in ("mapping", "revision", "identity"))
    session = RecordingSession([(*objects, "project", "binding", "code", "legacy")])
    observed = []

    def append(actual_session, mapping, revision, identity, binding):
        assert actual_session is session
        assert (mapping, revision, identity) == objects
        observed.append((binding.project_id, binding.binding_id, binding.kind, binding.legacy_source_id))
        return True

    monkeypatch.setattr(CodeAliasProjectorV1, "append", staticmethod(append))
    assert CodeAliasProjectorV1().backfill(session) == 1
    assert observed == [("project", "binding", "code", "legacy")]


@pytest.mark.parametrize("missing", range(1, 7))
def test_alias_backfill_still_rejects_missing_endpoint_or_binding_provenance(missing):
    row = [SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), "project", "binding", "code", "legacy"]
    row[missing] = None
    session = RecordingSession([tuple(row)])
    with pytest.raises(ImageRevisionIntegrityError, match="missing provenance"):
        CodeAliasProjectorV1().backfill(session)
    assert not session.flushed
