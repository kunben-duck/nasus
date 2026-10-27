from uuid import uuid4

import pytest

from scripts.isolated_test_storage import isolated_test_storage


SETTINGS = {"NASUS_TEST_S3_ENDPOINT": "http://127.0.0.1:9000",
    "NASUS_TEST_S3_ACCESS_KEY": "test-access", "NASUS_TEST_S3_SECRET_KEY": "test-secret",
    "NASUS_S3_BUCKET": "developer-artifacts"}


class FakeS3:
    def __init__(self, *, create_error=False, delete_error=False):
        self.calls = []
        self.objects = ["key-" + uuid4().hex for _ in range(1001)]
        self.create_error = create_error
        self.delete_error = delete_error

    def create_bucket(self, **kwargs):
        self.calls.append(("create", kwargs))
        if self.create_error:
            raise RuntimeError("bucket already exists")

    def list_objects_v2(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"Contents": [{"Key": key} for key in self.objects[:kwargs["MaxKeys"]]]}

    def delete_objects(self, **kwargs):
        self.calls.append(("delete_objects", kwargs))
        if self.delete_error:
            return {"Errors": [{"Code": "AccessDenied"}]}
        for item in kwargs["Delete"]["Objects"]:
            self.objects.remove(item["Key"])
        return {}

    def delete_bucket(self, **kwargs):
        self.calls.append(("delete_bucket", kwargs))
        assert not self.objects

    def close(self):
        self.calls.append(("close", {}))


@pytest.mark.parametrize("fails", [False, True])
def test_private_random_bucket_is_cleaned_without_touching_developer_bucket(fails):
    client = FakeS3()
    observed = []
    def run():
        with isolated_test_storage(SETTINGS, client_factory=lambda settings: client) as env:
            observed.append(env)
            assert env["NASUS_S3_BUCKET"].startswith("nasus-test-")
            assert env["NASUS_TEST_OBJECT_STORAGE_MODE"] == "minio"
            assert env["NASUS_S3_SECRET_KEY"] == SETTINGS["NASUS_TEST_S3_SECRET_KEY"]
            if fails:
                raise ValueError("original test failure")
    if fails:
        with pytest.raises(ValueError, match="original test failure"):
            run()
    else:
        run()
    bucket = observed[0]["NASUS_S3_BUCKET"]
    assert client.calls[0] == ("create", {"Bucket": bucket, "ACL": "private"})
    assert all(args["Bucket"] == bucket for name, args in client.calls if name != "close")
    assert [name for name, _ in client.calls].count("delete_objects") == 2
    assert client.calls[-2:] == [("delete_bucket", {"Bucket": bucket}), ("close", {})]


def test_failed_bucket_creation_never_deletes_an_unowned_bucket():
    client = FakeS3(create_error=True)
    with pytest.raises(RuntimeError, match="already exists"):
        with isolated_test_storage(SETTINGS, client_factory=lambda settings: client):
            pytest.fail("must not enter test")
    assert [name for name, _ in client.calls] == ["create", "close"]


def test_cleanup_failure_is_reported_and_client_is_closed():
    client = FakeS3(delete_error=True)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        with isolated_test_storage(SETTINGS, client_factory=lambda settings: client):
            pass
    assert not any(name == "delete_bucket" for name, _ in client.calls)
    assert client.calls[-1] == ("close", {})


@pytest.mark.parametrize("endpoint", ["", "https://example.com", "http://127.0.0.1:bad",
    "http://user:secret@localhost:9000", "http://localhost:9000/bucket", "http://localhost:9000/?key=secret",
    "file:///tmp/objects", "http://localhost:9000/#bucket"])
def test_nonlocal_or_ambiguous_endpoint_is_rejected_before_client_creation(endpoint):
    def unexpected(settings):
        pytest.fail("invalid endpoint must not create client")
    with pytest.raises(ValueError):
        with isolated_test_storage({**SETTINGS, "NASUS_TEST_S3_ENDPOINT": endpoint}, client_factory=unexpected):
            pytest.fail("invalid endpoint must not enter test")


@pytest.mark.parametrize("field", ["NASUS_TEST_S3_ACCESS_KEY", "NASUS_TEST_S3_SECRET_KEY"])
def test_developer_credentials_are_not_implicitly_reused(field):
    environment = {**SETTINGS, "NASUS_S3_ACCESS_KEY": "developer", "NASUS_S3_SECRET_KEY": "developer-secret"}
    environment.pop(field)
    with pytest.raises(ValueError, match="explicit"):
        with isolated_test_storage(environment, client_factory=lambda settings: pytest.fail("must not create client")):
            pytest.fail("missing test credentials must not enter test")
