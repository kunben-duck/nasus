"""Executable identity across actual CLI/MCP processes, not provider gold."""
from pathlib import Path
import errno
import hashlib
import itertools
import os
from types import SimpleNamespace

import pytest

from apps.api.app.domain.system_image.code_index import CodeIndexCancelled
from apps.api.app.infrastructure.system_image.codebase_memory_code_intelligence import CodebaseMemoryError
from apps.api.app.infrastructure.system_image.code_graph_executable import (
    MAX_EXECUTABLE_BYTES, code_graph_executable_digest, stage_code_graph_executable,
)
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessError
from apps.api.tests.test_code_index_session import fixture


NAMESPACE = "nasus_" + "a" * 32


def test_durable_session_executes_one_private_snapshot_for_version_protocol_and_queries(tmp_path, monkeypatch):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    original = Path(adapter.config.binary)
    expected = adapter.projection_fingerprint()
    runner = adapter._process_runner.run
    executed = []

    def run(args, **kwargs):
        executed.append(Path(args[0]))
        if args[1:] == ["--version"]:
            original.write_bytes(original.read_bytes() + b"\n# installation updated during the index session\n")
        return runner(args, **kwargs)

    monkeypatch.setattr(adapter._process_runner, "run", run)
    with adapter.open_index([unit], check_current=lambda: None, namespace=NAMESPACE,
                            provider_fingerprint=expected) as index:
        result = index.read_projection()
        assert result.entities and index.protocol_receipt() is not None
        assert len(set(executed)) == 1 and executed[0] != original
        snapshot = executed[0]
        assert snapshot.is_file() and snapshot.stat().st_mode & 0o777 == 0o500
        assert adapter.projection_fingerprint(executable=snapshot) == expected
        assert adapter.projection_fingerprint() != expected
        assert "mcp.initialize" in log.read_text() and "search_graph" in log.read_text()
    assert not snapshot.exists() and original.exists()


def test_changed_installation_before_preparation_fails_without_executing_any_native_command(tmp_path, monkeypatch):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    expected = adapter.projection_fingerprint()
    index = adapter.open_index([unit], check_current=lambda: None, namespace=NAMESPACE,
                               provider_fingerprint=expected)
    original = Path(adapter.config.binary)
    original.write_bytes(original.read_bytes() + b"\n# changed after the generation was pinned\n")
    executed = []
    runner = adapter._process_runner.run
    monkeypatch.setattr(adapter._process_runner, "run", lambda args, **kwargs: (executed.append(args), runner(args, **kwargs))[1])
    try:
        with pytest.raises(CodebaseMemoryError, match="executable.*changed"):
            index.prepare_index()
        assert index.status().state == "failed" and not executed and not log.exists()
        assert not index._root.exists() and not index._cache.exists()
    finally:
        index.close()


def test_unleased_native_session_pins_its_own_executable_before_preparation(tmp_path, monkeypatch):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    index = adapter.open_index([unit], check_current=lambda: None, namespace=NAMESPACE)
    original = Path(adapter.config.binary)
    original.write_bytes(original.read_bytes() + b"\n# changed before the first native process\n")
    try:
        with pytest.raises(CodebaseMemoryError, match="executable.*changed"):
            index.prepare_index()
        assert not log.exists()
    finally:
        index.close()


@pytest.mark.parametrize("stage", ["--version", "mcp/negotiate", "index_repository", "search_graph"])
@pytest.mark.parametrize("failure", [CodeGraphProcessError, CodeIndexCancelled, PermissionError, KeyboardInterrupt])
def test_private_executable_cleanup_at_each_failed_or_cancelled_stage(tmp_path, monkeypatch, stage, failure):
    adapter, unit, _ = fixture(tmp_path, monkeypatch)
    original = Path(adapter.config.binary)
    installed_bytes = original.read_bytes()
    runner, executed = adapter._process_runner.run, []

    def run(args, **kwargs):
        executable = Path(args[0])
        assert executable != original and executable.stat().st_mode & 0o777 == 0o500
        executed.append(executable)
        command = "mcp/negotiate" if kwargs.get("dialogue") is not None else args[2] if len(args) > 2 else "--version"
        if command == stage:
            raise failure("controlled failure")
        return runner(args, **kwargs)

    monkeypatch.setattr(adapter._process_runner, "run", run)
    index = adapter.open_index([unit], check_current=lambda: None, namespace=NAMESPACE,
                               provider_fingerprint=adapter.projection_fingerprint())
    expected = CodebaseMemoryError if failure is CodeGraphProcessError else failure
    with pytest.raises(expected):
        with index:
            index.read_projection()
    assert executed and len(set(executed)) == 1
    assert not executed[0].exists() and not executed[0].parent.exists()
    assert not index._root.exists() and not index._cache.exists()
    assert index.status().state == "closed"
    assert original.read_bytes() == installed_bytes


@pytest.mark.parametrize("fingerprint", ["", "hash", "sha256:" + "A" * 64, "sha256:" + "0" * 63])
def test_invalid_generation_fingerprint_never_runs_a_provider(tmp_path, monkeypatch, fingerprint):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        adapter.open_index([unit], check_current=lambda: None, namespace=NAMESPACE,
                           provider_fingerprint=fingerprint)
    assert not log.exists()


def test_fingerprint_cannot_be_attached_to_an_unnegotiated_legacy_session(tmp_path, monkeypatch):
    adapter, unit, log = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        adapter.open_index([unit], check_current=lambda: None, provider_fingerprint=adapter.projection_fingerprint())
    assert not log.exists()


@pytest.mark.parametrize("kind", ["empty", "oversized", "directory", "fifo", "symlink", "not_executable"])
def test_executable_file_policy_rejects_unbounded_or_nonregular_inputs(tmp_path, kind):
    source, root = tmp_path / "input", tmp_path / "private"
    root.mkdir(mode=0o700)
    if kind == "directory":
        source.mkdir()
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "symlink":
        actual = tmp_path / "actual"
        actual.write_bytes(b"source")
        actual.chmod(0o700)
        source.symlink_to(actual)
    else:
        source.write_bytes(b"" if kind == "empty" else b"source")
        if kind == "oversized":
            with source.open("wb") as handle:
                handle.truncate(MAX_EXECUTABLE_BYTES + 1)
        source.chmod(0o600 if kind == "not_executable" else 0o700)
    with pytest.raises(CodeGraphProcessError):
        stage_code_graph_executable(source, root, check_current=lambda: None)
    assert not (root / "codebase-memory-mcp").exists()


def test_executable_copy_checks_revocation_between_chunks_and_closes_files(tmp_path, monkeypatch):
    from apps.api.app.infrastructure.system_image import code_graph_executable as executable
    source, root = tmp_path / "input", tmp_path / "private"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    source.chmod(0o700)
    root.mkdir(mode=0o700)
    checks = []
    ticks = itertools.count()
    monkeypatch.setattr(executable, "time", SimpleNamespace(monotonic=lambda: next(ticks) * .05), raising=False)

    def current():
        checks.append(True)
        if len(checks) == 3:
            raise PermissionError("execution revoked")

    with pytest.raises(PermissionError):
        stage_code_graph_executable(source, root, check_current=current)
    partial = root / "codebase-memory-mcp"
    assert partial.stat().st_size == 1024 * 1024 and not partial.stat().st_mode & 0o111
    partial.unlink()
    assert source.exists()


@pytest.mark.parametrize("copy", [False, True])
def test_executable_read_coalesces_authority_checks_without_skipping_any_bytes(tmp_path, monkeypatch, copy):
    from apps.api.app.infrastructure.system_image import code_graph_executable as executable
    source, root = tmp_path / "input", tmp_path / "private"
    content = b"0123456789" * (512 * 1024)
    source.write_bytes(content)
    source.chmod(0o700)
    root.mkdir(mode=0o700)
    checks = []
    monkeypatch.setattr(executable, "time", SimpleNamespace(monotonic=lambda: 0), raising=False)
    if copy:
        result = stage_code_graph_executable(source, root, check_current=lambda: checks.append(True))
        assert result.read_bytes() == content
        assert result.stat().st_mode & 0o777 == 0o500
    else:
        assert code_graph_executable_digest(source, check_current=lambda: checks.append(True)) == hashlib.sha256(content).hexdigest()
    assert len(checks) == 2


@pytest.mark.parametrize("change", ["same_size_write", "replace"])
def test_executable_changed_before_final_check_cannot_become_a_private_snapshot(tmp_path, monkeypatch, change):
    from apps.api.app.infrastructure.system_image import code_graph_executable as executable
    source, root = tmp_path / "input", tmp_path / "private"
    source.write_bytes(b"original executable")
    source.chmod(0o700)
    root.mkdir(mode=0o700)
    checks = []
    monkeypatch.setattr(executable, "time", SimpleNamespace(monotonic=lambda: 0), raising=False)

    def current():
        checks.append(True)
        if len(checks) == 2:
            if change == "replace":
                replacement = tmp_path / "replacement"
                replacement.write_bytes(b"original executable")
                replacement.chmod(0o700)
                replacement.replace(source)
            else:
                source.write_bytes(b"modified executable")

    with pytest.raises(CodeGraphProcessError, match="changed"):
        stage_code_graph_executable(source, root, check_current=current)
    assert len(checks) == 2
    assert not (root / "codebase-memory-mcp").stat().st_mode & 0o111


def test_fast_executable_read_still_checks_revocation_before_returning(tmp_path, monkeypatch):
    from apps.api.app.infrastructure.system_image import code_graph_executable as executable
    source, root = tmp_path / "input", tmp_path / "private"
    content = b"fixed executable"
    source.write_bytes(content)
    source.chmod(0o700)
    root.mkdir(mode=0o700)
    checks = []
    monkeypatch.setattr(executable, "time", SimpleNamespace(monotonic=lambda: 0), raising=False)

    def current():
        checks.append(True)
        if len(checks) == 2:
            raise PermissionError("execution revoked before completion")

    with pytest.raises(PermissionError):
        stage_code_graph_executable(source, root, check_current=current)
    partial = root / "codebase-memory-mcp"
    assert partial.read_bytes() == content and not partial.stat().st_mode & 0o111


@pytest.mark.parametrize("failure", ["directory", "fstat", "fdopen"])
def test_executable_rejection_closes_descriptor_before_a_stream_owns_it(tmp_path, monkeypatch, failure):
    source, root = tmp_path / "input", tmp_path / "private"
    root.mkdir(mode=0o700)
    if failure == "directory":
        source.mkdir()
    else:
        source.write_bytes(b"executable bytes")
        source.chmod(0o700)
    descriptors = []
    real_open, real_fstat = os.open, os.fstat

    def record_open(*args):
        descriptor = real_open(*args)
        descriptors.append(descriptor)
        return descriptor

    def fail(*args):
        raise OSError("filesystem operation failed")

    monkeypatch.setattr(os, "open", record_open)
    if failure != "directory":
        monkeypatch.setattr(os, failure, fail)
    with pytest.raises(CodeGraphProcessError):
        stage_code_graph_executable(source, root, check_current=lambda: None)
    assert len(descriptors) == 1
    with pytest.raises(OSError) as closed:
        real_fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF
    assert not (root / "codebase-memory-mcp").exists()


def test_private_executable_is_a_byte_copy_not_a_hardlink(tmp_path):
    source, root = tmp_path / "input", tmp_path / "private"
    source.write_bytes(b"fixed executable bytes")
    source.chmod(0o700)
    root.mkdir(mode=0o700)
    expected = code_graph_executable_digest(source)
    snapshot = stage_code_graph_executable(source, root, check_current=lambda: None)
    assert snapshot.stat().st_ino != source.stat().st_ino
    source.write_bytes(b"installation was overwritten")
    assert code_graph_executable_digest(snapshot) == expected
    assert code_graph_executable_digest(source) != expected
