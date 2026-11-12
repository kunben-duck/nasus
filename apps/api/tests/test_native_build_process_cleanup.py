"""Deterministic cleanup races with real children and injected signal failures."""
import errno
import os
import signal
import sys
from types import SimpleNamespace

import pytest

from apps.api.app.infrastructure.runner import native_maven_build as adapter


@pytest.fixture
def children(monkeypatch):
    created = []
    popen = adapter.subprocess.Popen

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        created.append(child)
        return child

    monkeypatch.setattr(adapter.subprocess, "Popen", spawn)
    yield created
    # Keep regression failures from leaving the test's own children behind.
    for child in created:
        if popen.poll(child) is None:
            popen.kill(child)
        popen.wait(child, timeout=3)
        child.stdout.close()


def assert_reaped(child):
    assert child.returncode is not None and child.stdout.closed
    with pytest.raises(ChildProcessError):
        os.waitpid(child.pid, os.WNOHANG)


def test_zombie_leader_is_reaped_before_group_absence_probe(monkeypatch):
    calls = []

    def wait(timeout=None):
        assert timeout is None or timeout == 0.1
        calls.append("reap" if timeout is not None else "wait")
        return 0

    def killpg(pid, sig):
        assert pid == 123
        if sig == signal.SIGKILL:
            calls.append("kill_group")
            raise PermissionError(errno.EPERM, "zombie-only group")
        assert sig == 0 and calls == ["kill_group", "reap"]
        calls.append("probe_group")
        raise ProcessLookupError(errno.ESRCH, "group gone after reaping")

    monkeypatch.setattr(adapter.os, "killpg", killpg)
    process = SimpleNamespace(pid=123, wait=wait)
    adapter._cleanup_process_group(process)
    assert calls == ["kill_group", "reap", "probe_group", "wait"]


def test_exiting_leader_gets_bounded_grace_before_group_absence_probe(monkeypatch, children):
    killpg, signals, waits = os.killpg, [], []

    def exiting_group(pid, sig):
        child = children[0]
        assert pid == child.pid
        signals.append(sig)
        if sig == signal.SIGKILL:
            wait = child.wait

            def exiting_wait(timeout=None):
                waits.append(timeout)
                assert timeout is not None or child.returncode is not None
                return wait(timeout=timeout)

            # Model the interval where a nonblocking poll has no exit status
            # yet, but a bounded wait can reap the exiting child.
            monkeypatch.setattr(child, "poll", lambda: child.returncode)
            monkeypatch.setattr(child, "wait", exiting_wait)
            raise PermissionError(errno.EPERM, "group leader still exiting")
        assert sig == 0 and child.returncode is not None
        return killpg(pid, sig)

    monkeypatch.setattr(adapter.os, "killpg", exiting_group)
    with pytest.raises(adapter.NativeBuildFailure, match="log_limit"):
        adapter.bounded_command([sys.executable, "-c", "print('x' * 101)"], timeout=3, max_bytes=100)
    assert signals == [signal.SIGKILL, 0] and waits == [0.1, None]
    assert_reaped(children[0])


@pytest.mark.parametrize("failure", ["log_limit", "timeout", "revoked"])
@pytest.mark.parametrize("signal_error", [errno.EPERM, errno.ESRCH])
def test_exited_group_preserves_original_command_failure(monkeypatch, children, failure, signal_error):
    killpg, signals = os.killpg, []
    revoked = PermissionError("original worker revoked")

    def current():
        if failure == "revoked" and children:
            raise revoked

    def exited_group(pid, sig):
        assert pid == children[0].pid
        signals.append(sig)
        if sig == signal.SIGKILL:
            # Force exit at the cleanup boundary without scheduling/sleep races.
            children[0].wait(timeout=3)
            raise OSError(signal_error, "injected exited-group race")
        assert sig == 0 and children[0].returncode is not None
        return killpg(pid, sig)

    monkeypatch.setattr(adapter.os, "killpg", exited_group)
    expected = PermissionError if failure == "revoked" else adapter.NativeBuildFailure
    with pytest.raises(expected) as caught:
        adapter.bounded_command([sys.executable, "-c", "print('x' * 101)"],
            timeout=0 if failure == "timeout" else 3, max_bytes=100, require_work=current)
    if failure == "revoked":
        assert caught.value is revoked
    else:
        assert caught.value.code == "native_build_" + failure
        assert caught.value.log == b""
    assert signals == ([signal.SIGKILL, 0] if signal_error == errno.EPERM else [signal.SIGKILL])
    assert_reaped(children[0])


@pytest.mark.parametrize("signal_error", [errno.EPERM, errno.EIO])
def test_live_group_failure_is_visible_but_direct_child_is_reaped(monkeypatch, children, signal_error):
    failure, signals = OSError(signal_error, "owned group cleanup denied"), []

    def denied(pid, sig):
        assert pid == children[0].pid and sig == signal.SIGKILL
        assert children[0].poll() is None
        signals.append(sig)
        raise failure

    monkeypatch.setattr(adapter.os, "killpg", denied)
    with pytest.raises(OSError) as caught:
        adapter.bounded_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0, max_bytes=100)
    assert caught.value is failure
    assert signals == [signal.SIGKILL]
    assert children[0].returncode == -signal.SIGKILL
    assert_reaped(children[0])


@pytest.mark.parametrize("probe_error", [None, errno.EPERM, errno.EIO])
def test_exited_leader_does_not_hide_unverified_group(monkeypatch, children, probe_error):
    failure, signals = PermissionError(errno.EPERM, "owned group cleanup denied"), []

    def denied(pid, sig):
        assert pid == children[0].pid
        signals.append(sig)
        if sig == signal.SIGKILL:
            children[0].wait(timeout=3)
            raise failure
        assert sig == 0
        # An exited leader alone says nothing about surviving descendants.
        if probe_error is not None:
            raise OSError(probe_error, "group absence unverified")

    monkeypatch.setattr(adapter.os, "killpg", denied)
    with pytest.raises(OSError) as caught:
        adapter.bounded_command([sys.executable, "-c", "print('x' * 101)"], timeout=3, max_bytes=100)
    assert caught.value.errno == (probe_error or errno.EPERM)
    assert signals == [signal.SIGKILL, 0]
    assert_reaped(children[0])


def test_failed_direct_child_cleanup_still_closes_stdout(monkeypatch, children):
    failure = PermissionError(errno.EPERM, "direct child cleanup denied")

    def denied(pid, sig):
        assert pid == children[0].pid and sig == signal.SIGKILL

        def deny_child_kill():
            raise failure

        monkeypatch.setattr(children[0], "kill", deny_child_kill)
        raise PermissionError(errno.EPERM, "owned group cleanup denied")

    monkeypatch.setattr(adapter.os, "killpg", denied)
    with pytest.raises(PermissionError) as caught:
        adapter.bounded_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0, max_bytes=100)
    assert caught.value is failure
    assert children[0].stdout.closed
