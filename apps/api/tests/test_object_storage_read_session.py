"""Transport reuse must not cache raw evidence or cross read lifetimes."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from io import BytesIO
from threading import Barrier, Event, Lock

import pytest

from apps.api.app.infrastructure.storage.object_storage import ObjectStorage, ObjectStorageConfig


@pytest.fixture
def storage(tmp_path, monkeypatch):
    value = ObjectStorage(ObjectStorageConfig("http://127.0.0.1:1", "test", "test-key", "test-secret", "test", tmp_path))
    clients, bodies, content = [], [], {"body": b"first", "length": None}
    lock = Lock()

    class Client:
        def __init__(self):
            self.closed, self.reads = 0, 0

        def get_object(self, **kwargs):
            self.reads += 1
            body = BytesIO(content["body"])
            bodies.append(body)
            return {"Body": body, "ContentLength": len(content["body"]) if content["length"] is None else content["length"]}

        def close(self):
            self.closed += 1

    def create(config):
        with lock:
            client = Client()
            clients.append(client)
            return client

    monkeypatch.setattr(value, "_create_s3_client", create, raising=False)
    return value, clients, bodies, content


def read(value, **kwargs):
    return value.get_bytes("s3://test/file", **kwargs)


def test_nested_sessions_reuse_one_transport_but_every_read_fetches_fresh_bytes(storage):
    value, clients, bodies, content = storage
    with value.read_session():
        assert read(value) == b"first"
        with value.read_session():
            content["body"] = b"changed"
            assert read(value) == b"changed"
        assert read(value) == b"changed"
        assert len(clients) == 1 and clients[0].reads == 3 and clients[0].closed == 0
    assert clients[0].closed == 1 and all(body.closed for body in bodies)
    with value.read_session():
        assert read(value) == b"changed"
    assert len(clients) == 2 and clients[1].closed == 1


def test_unused_and_local_read_sessions_do_not_construct_an_s3_client(storage):
    value, clients, _, _ = storage
    with value.read_session():
        pass
    value.config = replace(value.config, endpoint=None, access_key=None, secret_key=None)
    ref = value.put_bytes("local", b"local").storage_ref
    with value.read_session():
        assert value.get_bytes(ref) == b"local"
    assert clients == []


@pytest.mark.parametrize("length", [None, 0])
def test_bounded_reads_close_the_body_and_transport_for_known_and_unknown_lengths(storage, length):
    value, clients, bodies, content = storage
    content.update(body=b"too large", length=length)
    with pytest.raises(ValueError, match="exceeds max bytes"):
        with value.read_session():
            read(value, max_bytes=3)
    assert clients[0].closed == 1 and all(body.closed for body in bodies)
    content["body"] = b"ok"
    with value.read_session():
        assert read(value, max_bytes=3) == b"ok"
    assert clients[1].closed == 1


def test_exception_restores_the_outer_context_and_closes_only_the_owned_transport(storage):
    value, clients, _, _ = storage
    with pytest.raises(LookupError, match="caller failed"):
        with value.read_session():
            read(value)
            raise LookupError("caller failed")
    assert clients[0].closed == 1
    with value.read_session():
        assert read(value) == b"first"
    assert len(clients) == 2 and clients[1].closed == 1


def test_configuration_changes_cannot_silently_reuse_the_previous_credentials(storage):
    value, clients, _, _ = storage
    original = value.config
    with value.read_session():
        read(value)
        value.config = replace(original, access_key="other-key")
        with pytest.raises(RuntimeError, match="configuration changed"):
            read(value)
        with value.read_session():
            read(value)
        assert len(clients) == 2 and clients[1].closed == 1
        value.config = original
        read(value)
        assert clients[0].closed == 0
    assert clients[0].closed == 1


def test_independent_threads_do_not_inherit_another_read_session(storage):
    value, clients, _, _ = storage
    barrier = Barrier(2)
    def worker():
        with value.read_session():
            barrier.wait(timeout=5)
            return read(value)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(worker), executor.submit(worker)
        assert first.result(timeout=5) == second.result(timeout=5) == b"first"
    assert len(clients) == 2 and all(client.closed == 1 for client in clients)


def test_copied_context_cannot_read_through_a_closed_scope_but_can_start_a_new_one(storage):
    value, clients, _, _ = storage
    with value.read_session():
        read(value)
        copied = copy_context()
    with pytest.raises(RuntimeError, match="closed"):
        copied.run(read, value)
    def fresh():
        with value.read_session():
            return read(value)
    assert copied.run(fresh) == b"first"
    assert len(clients) == 2 and all(client.closed == 1 for client in clients)


def test_inherited_process_scope_is_rejected_before_using_its_lock_or_client(storage):
    value, clients, _, _ = storage
    with value.read_session():
        read(value)
        scope = value._read_clients.get()
        original_pid = scope.pid
        scope.pid = -1
        try:
            with scope._lock:
                with pytest.raises(RuntimeError, match="process"):
                    read(value)
                with value.read_session():
                    assert read(value) == b"first"
        finally:
            scope.pid = original_pid
    assert len(clients) == 2 and all(client.reads == client.closed == 1 for client in clients)


def test_scope_exit_does_not_close_a_transport_used_by_an_inherited_active_read(storage):
    value, clients, _, _ = storage
    started, release = Event(), Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with value.read_session():
            read(value)
            copied = copy_context()
            original_get = clients[0].get_object
            def blocked(**kwargs):
                started.set()
                assert release.wait(timeout=5)
                return original_get(**kwargs)
            clients[0].get_object = blocked
            pending = executor.submit(copied.run, read, value)
            assert started.wait(timeout=5)
        try:
            assert clients[0].closed == 0
        finally:
            release.set()
        assert pending.result(timeout=5) == b"first"
    assert clients[0].closed == 1 and clients[0].reads == 2


def test_standalone_reads_release_each_transport_and_do_not_leave_a_scope(storage):
    value, clients, _, _ = storage
    for _ in range(2):
        assert read(value) == b"first"
        assert value._read_clients.get() is None
    assert len(clients) == 2 and all(client.closed == 1 for client in clients)


def test_client_factory_failure_restores_context_and_allows_a_fresh_scope(storage, monkeypatch):
    value, clients, _, _ = storage
    original = value._create_s3_client
    def fail(_config):
        raise LookupError("factory failed")
    monkeypatch.setattr(value, "_create_s3_client", fail)
    with pytest.raises(LookupError, match="factory failed"):
        with value.read_session():
            read(value)
    assert value._read_clients.get() is None and not clients
    monkeypatch.setattr(value, "_create_s3_client", original)
    assert read(value) == b"first" and clients[0].closed == 1


@pytest.mark.parametrize("caller_fails", [False, True])
def test_close_failure_restores_scope_and_preserves_a_prior_caller_error(storage, caller_fails):
    value, clients, _, _ = storage
    def close():
        clients[0].closed += 1
        raise OSError("close failed")
    expected, message = (LookupError, "caller failed") if caller_fails else (OSError, "close failed")
    with pytest.raises(expected, match=message):
        with value.read_session():
            read(value)
            clients[0].close = close
            if caller_fails:
                raise LookupError("caller failed")
    assert value._read_clients.get() is None and clients[0].closed == 1
    assert read(value) == b"first" and clients[1].closed == 1


def test_invalid_content_length_still_closes_the_response_body(storage):
    value, clients, bodies, content = storage
    content["length"] = "invalid"
    with pytest.raises(ValueError):
        read(value)
    assert clients[0].closed == 1 and bodies[0].closed
    assert value._read_clients.get() is None


def test_cancellation_releases_transport_and_restores_scope(storage):
    value, clients, _, _ = storage
    with pytest.raises(KeyboardInterrupt):
        with value.read_session():
            read(value)
            raise KeyboardInterrupt()
    assert clients[0].closed == 1 and value._read_clients.get() is None


def test_copied_live_contexts_initialize_only_one_client(storage):
    value, clients, _, _ = storage
    barrier = Barrier(2)
    def worker():
        barrier.wait(timeout=5)
        return read(value)
    with value.read_session():
        contexts = (copy_context(), copy_context())
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(contexts[0].run, worker)
            second = executor.submit(contexts[1].run, worker)
            assert first.result(timeout=5) == second.result(timeout=5) == b"first"
        assert len(clients) == 1 and clients[0].reads == 2
    assert clients[0].closed == 1


def test_writes_use_an_independent_transport_not_the_read_lifetime(storage):
    value, clients, _, _ = storage
    calls = []
    original = value._create_s3_client
    def create(config):
        client = original(config)
        client.put_object = lambda **kwargs: calls.append(kwargs)
        return client
    value._create_s3_client = create
    with value.read_session():
        read(value)
        result = value.put_bytes("written", b"write")
        assert clients[0].closed == 0 and clients[1].closed == 1
        assert read(value) == b"first"
    assert len(clients) == 2 and clients[0].closed == 1
    assert result.backend == "s3" and len(calls) == 1 and calls[0]["Body"] == b"write"


def test_sdk_factory_uses_an_explicit_session_not_the_default_shared_session(storage, monkeypatch):
    import boto3
    value, _, _, _ = storage
    sessions, calls, client = [], [], object()
    class Session:
        def __init__(self):
            sessions.append(self)

        def client(self, service, **kwargs):
            calls.append((service, kwargs))
            return client
    def forbidden_default(*args, **kwargs):
        raise AssertionError("Do not initialize through the shared default session")
    monkeypatch.setattr(boto3, "client", forbidden_default)
    monkeypatch.setattr(boto3.session, "Session", Session)
    assert ObjectStorage._create_s3_client(value.config) is client
    assert len(sessions) == 1
    assert calls == [("s3", {"endpoint_url": value.config.endpoint,
        "aws_access_key_id": value.config.access_key, "aws_secret_access_key": value.config.secret_key,
        "region_name": value.config.region})]
