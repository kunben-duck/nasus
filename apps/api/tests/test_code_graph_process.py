import os
from pathlib import Path
import sys
import time

import pytest

from apps.api.app.infrastructure.system_image.code_graph_process import (
    CodeGraphProcessError, CodeGraphProcessRunner,
)


def run_python(source, *, runner=None, **kwargs):
    return (runner or CodeGraphProcessRunner()).run(
        [sys.executable, "-c", source], env={"PATH": os.defpath},
        timeout_seconds=kwargs.pop("timeout_seconds", 2), **kwargs,
    )


def process_is_running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_process_output_handles_unicode_split_across_writes():
    output = run_python(
        "import os,time; value='中🦆'.encode(); "
        "[(os.write(1,bytes([byte])),time.sleep(.001)) for byte in value]; os.write(2,b'diagnostic')"
    )
    assert output.stdout == "中🦆"
    assert output.stderr == "diagnostic"
    assert output.returncode == 0


@pytest.mark.parametrize("fd,limit_name", [(1, "max_stdout_bytes"), (2, "max_stderr_bytes")])
def test_continuous_output_is_bounded_without_leaking_provider_text(fd, limit_name):
    started = time.monotonic()
    with pytest.raises(CodeGraphProcessError, match="output limit") as caught:
        run_python(f"import os\nwhile True: os.write({fd}, b'PRIVATE-SOURCE'*1024)", **{limit_name: 4096})
    assert "PRIVATE-SOURCE" not in str(caught.value)
    assert time.monotonic() - started < 3


def test_process_timeout_terminates_and_reaps_main_process(tmp_path):
    pid_path = tmp_path / "pid"
    with pytest.raises(CodeGraphProcessError, match="time limit"):
        run_python(f"import os,time,pathlib; pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid())); time.sleep(30)",
                   timeout_seconds=.3)
    assert not process_is_running(int(pid_path.read_text()))


def test_execution_guard_failure_terminates_process_group_and_preserves_error(tmp_path):
    pid_path, child_path = tmp_path / "pid", tmp_path / "child"
    error = PermissionError("source access revoked")

    def check_current():
        if child_path.exists():
            raise error

    source = (
        "import os,pathlib,subprocess,sys,time; "
        f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid())); "
        f"child=subprocess.Popen([sys.executable,'-c',\"import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)\"]); "
        f"pathlib.Path({str(child_path)!r}).write_text(str(child.pid)); time.sleep(30)"
    )
    started = time.monotonic()
    with pytest.raises(PermissionError) as caught:
        run_python(source, check_current=check_current)
    assert caught.value is error
    assert time.monotonic() - started < 3
    assert not process_is_running(int(pid_path.read_text()))
    # On Unix an orphan can remain a zombie briefly; it must not still execute.
    child_pid = int(child_path.read_text())
    import subprocess
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(child_pid)], capture_output=True, text=True).stdout.strip()
    assert not state or state.startswith("Z")


def test_guard_is_checked_before_launch_and_after_success(tmp_path):
    marker = tmp_path / "launched"
    calls = []

    def check_current():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        run_python(f"from pathlib import Path; Path({str(marker)!r}).touch()", check_current=check_current)
    assert not marker.exists()

    calls.clear()

    def check_after():
        calls.append(True)
        if marker.exists():
            raise RuntimeError("cancelled after output")

    with pytest.raises(RuntimeError, match="cancelled after output"):
        run_python(f"from pathlib import Path; Path({str(marker)!r}).touch(); print('ok')", check_current=check_after)
    assert len(calls) >= 2


def test_environment_is_explicit_not_inherited(monkeypatch):
    monkeypatch.setenv("NASUS_PRIVATE_CREDENTIAL", "must-not-inherit")
    output = run_python("import os,json; print(json.dumps(dict(os.environ)))")
    assert "NASUS_PRIVATE_CREDENTIAL" not in output.stdout
    assert "must-not-inherit" not in output.stdout


def test_invalid_utf8_stdout_fails_closed():
    with pytest.raises(CodeGraphProcessError, match="UTF-8"):
        run_python("import os; os.write(1,b'\\xff')")


def test_process_that_closes_pipes_still_checks_control_and_is_reaped(tmp_path):
    marker = tmp_path / "closed-pipes-pid"
    error = RuntimeError("cancel after pipes close")

    def check_current():
        if marker.exists():
            raise error

    with pytest.raises(RuntimeError) as caught:
        run_python(f"import os,pathlib,time; pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
                   "os.close(1); os.close(2); time.sleep(30)", check_current=check_current)
    assert caught.value is error
    assert not process_is_running(int(marker.read_text()))


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("inf"), float("nan"), True])
def test_invalid_timeout_never_starts_process(timeout_seconds):
    with pytest.raises(ValueError, match="time limit"):
        run_python("raise SystemExit(99)", timeout_seconds=timeout_seconds)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_output_limit_never_starts_process(limit):
    with pytest.raises(ValueError, match="output limit"):
        run_python("raise SystemExit(99)", max_stdout_bytes=limit)
