"""Independently read the archived exweb inputs from the selected test store."""
import hashlib
import os

from sqlalchemy import select

from apps.api.app.infrastructure.persistence.image_revision_models import ImageRevisionRecord
from apps.api.app.infrastructure.persistence.source_snapshot_models import SourceRevisionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage


def verify_exweb_storage(project_id, image_revision_id):
    storage = ObjectStorage()
    if os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") != "minio":
        assert not storage.config.s3_enabled, "unrecognized storage must not be reported as local"
        return {"backend": "local_isolated_adapter", "independent_remote_reads": 0}
    assert storage.config.s3_enabled and storage.config.bucket.startswith("nasus-test-")
    prefix = f"s3://{storage.config.bucket}/"
    with session_scope() as session:
        pins = [(row.manifest_ref, row.manifest_hash) for row in session.scalars(
            select(SourceRevisionRecord).where(SourceRevisionRecord.project_id == project_id))]
        image = session.get(ImageRevisionRecord, image_revision_id)
        assert image is not None and image.project_id == project_id
        image_pin = (image.artifact_ref, image.artifact_hash)
    assert pins
    verified = {}
    total_bytes = 0

    def read(ref, expected_hash):
        nonlocal total_bytes
        assert ref.startswith(prefix), "archive escaped the disposable test bucket"
        if ref in verified:
            assert verified[ref] == expected_hash
            return
        body = storage.get_bytes(ref, max_bytes=64 * 1024 * 1024)
        assert "sha256:" + hashlib.sha256(body).hexdigest() == expected_hash
        verified[ref] = expected_hash
        total_bytes += len(body)

    # A fresh adapter has no ingestion/workspace caches. Each reference must
    # resolve over S3, independently of the API's successful replay response.
    file_refs = set()
    with storage.read_session():
        for ref, digest in pins:
            read(ref, digest)
            for item in storage.get_json(ref)["files"]:
                read(item["content_ref"], item["content_hash"])
                file_refs.add(item["content_ref"])
        read(*image_pin)
    return {"backend": "minio_s3", "source_manifests_verified": len(pins),
        "source_files_verified": len(file_refs), "frozen_images_verified": 1,
        "independent_remote_reads": len(verified), "verified_bytes": total_bytes,
        "bucket_scope": "disposable_private_test_bucket", "hash_integrity": "verified"}
