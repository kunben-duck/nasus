"""Read-only diagnostic boundaries, not a provider performance measurement."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


path = Path(__file__).resolve().parents[1] / "scripts" / "profile-fixed-fixture-read.py"
spec = importlib.util.spec_from_file_location("fixed_fixture_profile", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("connection,database", [
    ("postgresql+psycopg://user:secret@db.example.invalid/nasus", "nasus_test_" + "a" * 32),
    ("sqlite+pysqlite:///nasus.db", "nasus_test_" + "a" * 32),
    ("postgresql+psycopg://user:secret@localhost/nasus", "nasus"),
    ("postgresql+psycopg://user:secret@localhost/nasus", "nasus_test_not_owned"),
])
def test_profile_rejects_shared_or_nonlocal_database(connection, database):
    with pytest.raises(ValueError):
        module.isolated_read_url(connection, database)


def test_profile_forces_server_readonly_even_when_original_options_allow_writes():
    url = module.isolated_read_url("postgresql+psycopg://user:secret@localhost/nasus?options=unsafe&application_name=probe",
        "nasus_test_" + "a" * 32)
    assert url.query["options"] == "-c default_transaction_read_only=on"
    assert url.query["application_name"] == "probe" and url.database == "nasus_test_" + "a" * 32


@pytest.mark.parametrize("operation", ["GetObject", "HeadObject", "HeadBucket", "GetBucketLocation", "ListObjectsV2"])
def test_profile_permits_only_declared_s3_reads(operation):
    module.read_only_s3(SimpleNamespace(name=operation))


@pytest.mark.parametrize("operation", ["PutObject", "DeleteObject", "DeleteObjects", "CreateBucket", "PutObjectAcl",
    "CopyObject", "UploadPart", "CompleteMultipartUpload", "Unknown"])
def test_profile_blocks_s3_mutation_or_unknown_operation(operation):
    with pytest.raises(RuntimeError):
        module.read_only_s3(SimpleNamespace(name=operation))
