"""Real child-process cancellation; protocol containers are explicitly doubles."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import time

import pytest

from apps.api.app.application.quality_loop.native_build_execution import execute_native_build
from apps.api.app.infrastructure.runner.native_maven_build import bounded_command, runtime_jar_inventory, NativeBuildFailure
from apps.api.tests.test_native_build import request_value, builder, protocol_commands, protocol_jar


class LostBuildOwnership(RuntimeError):
    pass


def test_invalid_ownership_never_starts_a_child_or_build(request_value, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: calls.append(args))

    def lost():
        raise LostBuildOwnership("lost")

    with pytest.raises(LostBuildOwnership):
        bounded_command([sys.executable, "-c", "pass"], timeout=3, max_bytes=1024, require_work=lost)
    command, docker_calls = protocol_commands()
    with pytest.raises(LostBuildOwnership):
        builder(tmp_path, command).build(request_value, require_work=lost)
    assert not calls and not docker_calls


@pytest.mark.parametrize("close_stdout", [False, True])
def test_child_is_killed_promptly_when_ownership_is_lost(close_stdout, monkeypatch):
    created = []
    popen = subprocess.Popen

    def record(*args, **kwargs):
        child = popen(*args, **kwargs)
        created.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", record)
    start = time.monotonic()

    def current():
        if time.monotonic() - start > 0.3:
            raise LostBuildOwnership("lost")

    code = "import os,time;" + ("os.close(1);os.close(2);" if close_stdout else "") + "time.sleep(30)"
    with pytest.raises(LostBuildOwnership):
        bounded_command([sys.executable, "-c", code], timeout=20, max_bytes=1024, require_work=current)
    assert time.monotonic() - start < 3
    assert len(created) == 1 and created[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(created[0].pid, 0)


def test_failed_command_kills_descendant_even_after_leader_exits(tmp_path):
    marker = tmp_path / "descendant-stopped"
    # The grandchild inherits stdout after the group leader exits. A stopped
    # pipe reader must still kill that owned group, not merely the leader PID.
    child = "import time;from pathlib import Path;time.sleep(1);Path(%r).write_text('leaked')" % str(marker)
    leader = "import subprocess,sys;subprocess.Popen([sys.executable,'-c',%r])" % child
    with pytest.raises(NativeBuildFailure, match="timeout"):
        bounded_command([sys.executable, "-c", leader], timeout=0.2, max_bytes=1024)
    time.sleep(1.1)
    assert not marker.exists()


@pytest.mark.parametrize("phase", ["version", "compile", "inventory", "cleanup"])
def test_native_fence_checks_after_build_and_cleanup_is_not_cancelled(request_value, tmp_path, phase, monkeypatch):
    original, calls = protocol_commands()
    revoked = Event()

    def current():
        if revoked.is_set():
            raise LostBuildOwnership("lost")

    def command(args, **kwargs):
        result = original(args, **kwargs)
        if (phase == "version" and args[-1] == "--version") or (phase == "compile" and args[-1] == "verify"):
            revoked.set()
        if args[1:3] == ["container", "inspect"]:
            assert "require_work" not in kwargs
            if phase == "cleanup":
                revoked.set()
        return result

    if phase == "inventory":
        from apps.api.app.infrastructure.runner import native_maven_build
        inventory = native_maven_build.runtime_jar_inventory

        def fence_inventory(body, **kwargs):
            revoked.set()
            return inventory(body, **kwargs)

        monkeypatch.setattr(native_maven_build, "runtime_jar_inventory", fence_inventory)
    with pytest.raises(LostBuildOwnership):
        builder(tmp_path, command).build(request_value, require_work=current)
    cleanup = [args for args, _ in calls if args[1:3] == ["container", "inspect"]]
    assert len(cleanup) == (1 if phase == "version" else 2)
    mounts = [value for args, _ in calls for value in args if value.startswith("type=bind,src=") and value.endswith("dst=/work")]
    assert not mounts or not Path(mounts[0].split("src=", 1)[1].split(",dst=", 1)[0]).exists()


def test_inventory_remains_interruptible_between_members():
    count = 0

    def current():
        nonlocal count
        count += 1
        if count == 3:
            raise LostBuildOwnership("lost")

    with pytest.raises(LostBuildOwnership):
        runtime_jar_inventory(protocol_jar(), require_work=current)
    assert count == 3


@pytest.mark.parametrize("repeat", [False, True])
def test_async_cancellation_waits_for_owned_cleanup(request_value, repeat):
    async def scenario():
        entered, cleanup_entered, release, cleaned = (Event() for _ in range(4))

        class OwnedThreadBuilder:
            def build(self, request, *, require_work):
                try:
                    entered.set()
                    while True:
                        require_work()
                        time.sleep(0.01)
                finally:
                    cleanup_entered.set()
                    release.wait(3)
                    cleaned.set()

        task = asyncio.create_task(execute_native_build(OwnedThreadBuilder(), request_value, require_work=lambda: None))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        assert await asyncio.to_thread(cleanup_entered.wait, 3)
        if repeat:
            task.cancel()
        await asyncio.sleep(0.03)
        assert not task.done() and not cleaned.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_async_cancellation_does_not_hide_cleanup_failure(request_value):
    async def scenario():
        entered = Event()

        class UnsafeCleanupBuilder:
            def build(self, request, *, require_work):
                try:
                    entered.set()
                    while True:
                        require_work()
                        time.sleep(0.01)
                finally:
                    raise NativeBuildFailure("native_build_cleanup_unverified")

        task = asyncio.create_task(execute_native_build(UnsafeCleanupBuilder(), request_value, require_work=lambda: None))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        with pytest.raises(NativeBuildFailure, match="cleanup_unverified"):
            await task

    asyncio.run(scenario())


def test_async_native_build_returns_output_only_under_current_fence(request_value, tmp_path):
    async def scenario():
        command, _ = protocol_commands()
        checks = []
        result = await execute_native_build(builder(tmp_path, command), request_value, require_work=lambda: checks.append(1))
        assert checks and result.artifact[:2] == b"PK" and result.runtime_inventory["compiled_class_count"] == 1

    asyncio.run(scenario())
