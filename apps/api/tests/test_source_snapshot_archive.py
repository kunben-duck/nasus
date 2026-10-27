from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.app.application.system_image.system_image_models import RawAssetRecord
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService


def _ingestion(tmp_path: Path) -> SourceIngestionService:
    return SourceIngestionService(
        allowed_local_roots=[tmp_path.resolve()],
        object_storage=ObjectStorage(ObjectStorageConfig(None, "snapshots", None, None, "local", tmp_path / "objects")),
        snapshot_cache_dir=tmp_path / "cache",
    )


def _capture(service: SourceIngestionService, source: RawAssetRecord) -> RawAssetRecord:
    result = service.ingest(source)
    assert result.snapshot is not None
    return source.model_copy(update={
        "content_ref": result.content_ref, "content_hash": result.content_hash,
        "evidence_refs": result.evidence_refs, "ingestion_status": "indexed",
    })


def test_local_source_snapshot_replays_after_original_is_changed_and_deleted(tmp_path: Path) -> None:
    original = tmp_path / "repo"
    original.mkdir()
    code = original / "order.py"
    code.write_text("def submit():\n    return 'old'\n")
    service = _ingestion(tmp_path)
    source = RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(original))
    old = _capture(service, source)
    code.write_text("def submit():\n    return 'new'\n")
    new = _capture(service, source)
    code.unlink()
    original.rmdir()
    # New process, no original repository, no in-memory materialization cache.
    restored = _ingestion(tmp_path)
    assert "'old'" in restored.extract_text_units(old)[0].text
    assert "'new'" in restored.extract_text_units(new)[0].text
    assert old.content_ref != new.content_ref


def test_snapshot_does_not_depend_on_decoded_document_text_for_integrity(tmp_path: Path) -> None:
    source_path = tmp_path / "requirements.txt"
    source_path.write_bytes("需求：退款必须幂等\n".encode("utf-8"))
    service = _ingestion(tmp_path)
    source = RawAssetRecord(id="doc", project_id="project", source_type="us_doc", source_uri=str(source_path))
    first = _capture(service, source)
    second = _capture(service, source)
    assert first.content_ref == second.content_ref
    source_path.unlink()
    assert restored_text(service, first) == "需求：退款必须幂等\n"


def restored_text(service: SourceIngestionService, source: RawAssetRecord) -> str:
    return service.extract_text_units(source)[0].text


@pytest.mark.parametrize("field,value", [("project_id", "other"), ("id", "other"), ("content_hash", "sha256:" + "0" * 64)])
def test_snapshot_rejects_wrong_scope(tmp_path: Path, field: str, value: str) -> None:
    path = tmp_path / "code.py"
    path.write_text("pass\n")
    service = _ingestion(tmp_path)
    source = _capture(service, RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(path)))
    with pytest.raises(ValueError, match="scope mismatch"):
        service.extract_text_units(source.model_copy(update={field: value}))


def test_snapshot_rejects_corrupt_raw_object(tmp_path: Path) -> None:
    path = tmp_path / "code.py"
    path.write_text("pass\n")
    service = _ingestion(tmp_path)
    source = _capture(service, RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(path)))
    payload = service.snapshots.storage.get_json(source.content_ref)
    ref = payload["files"][0]["content_ref"]
    service.snapshots.storage.put_bytes(ref.split("/", 3)[3], b"evil\n")
    with pytest.raises(ValueError, match="file hash mismatch"):
        service.extract_text_units(source)


def test_snapshot_rejects_mutated_checkout_instead_of_reusing_it(tmp_path: Path) -> None:
    path = tmp_path / "code.py"
    path.write_text("pass\n")
    service = _ingestion(tmp_path)
    source = _capture(service, RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(path)))
    unit = service.extract_text_units(source)[0]
    (Path(unit.source_root) / unit.relative_path).write_text("evil\n")
    with pytest.raises(ValueError, match="file hash mismatch"):
        service.extract_text_units(source)


def test_manifest_tampering_is_rejected_before_object_reads(tmp_path: Path) -> None:
    path = tmp_path / "code.py"
    path.write_text("pass\n")
    service = _ingestion(tmp_path)
    source = _capture(service, RawAssetRecord(id="source", project_id="project", source_type="code", source_uri=str(path)))
    manifest = service.snapshots.storage.get_json(source.content_ref)
    manifest["files"][0]["path"] = "../escape"
    service.snapshots.storage.put_json(source.content_ref.split("/", 3)[3], manifest)
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        service.extract_text_units(source)
