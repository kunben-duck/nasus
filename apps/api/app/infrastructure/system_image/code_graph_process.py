from __future__ import annotations

from dataclasses import dataclass
import math
import os
import selectors
import signal
import subprocess
import time
from typing import Callable, Mapping, Optional, Protocol, Sequence


class CodeGraphProcessError(RuntimeError):
    """Transport failures contain no provider output or source text."""


@dataclass(frozen=True)
class CodeGraphProcessOutput:
    stdout: str
    stderr: str
    returncode: int


class CodeGraphStdioDialogue(Protocol):
    completed: bool
    def initial_input(self) -> bytes: ...
    def receive(self, line: bytes) -> bytes: ...


class CodeGraphProcessRunner:
    """Bounded CLI transport; the caller retains lifecycle and authorization authority."""

    def run(self, args: Sequence[str], *, env: Mapping[str, str], timeout_seconds: float,
            max_stdout_bytes: int = 4 * 1024 * 1024, max_stderr_bytes: int = 64 * 1024,
            check_current: Optional[Callable[[], None]] = None,
            dialogue: Optional[CodeGraphStdioDialogue] = None, cwd: Optional[str] = None) -> CodeGraphProcessOutput:
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("code graph requires a finite positive time limit")
        if any(type(limit) is not int or limit <= 0 for limit in (max_stdout_bytes, max_stderr_bytes)):
            raise ValueError("code graph requires positive integer output limits")
        if check_current is not None:
            check_current()
        deadline = time.monotonic() + timeout_seconds
        next_check = time.monotonic() + .25
        process = None
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        limits = {"stdout": max_stdout_bytes, "stderr": max_stderr_bytes}
        outgoing, line_buffer, input_bytes = bytearray(), bytearray(), 0
        if dialogue is not None:
            initial = dialogue.initial_input()
            if type(initial) is not bytes or not 1 <= len(initial) <= 128 * 1024:
                raise ValueError("code graph protocol input exceeds its bound")
            outgoing.extend(initial)
            input_bytes = len(initial)
        try:
            try:
                process = subprocess.Popen(list(args), stdin=subprocess.PIPE if dialogue else subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(env), cwd=cwd,
                    close_fds=True, start_new_session=True)
            except OSError as exc:
                raise CodeGraphProcessError("code graph process transport failed") from exc
            with selectors.DefaultSelector() as selector:
                for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                if dialogue is not None:
                    os.set_blocking(process.stdin.fileno(), False)
                    selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                while selector.get_map():
                    now = time.monotonic()
                    if now >= deadline:
                        raise CodeGraphProcessError("code graph process exceeded its time limit")
                    if check_current is not None and now >= next_check:
                        check_current()
                        next_check = time.monotonic() + .25
                    for key, _ in selector.select(min(.1, max(0, deadline - now))):
                        if key.data == "stdin":
                            try:
                                sent = os.write(key.fileobj.fileno(), outgoing)
                            except BrokenPipeError as error:
                                raise CodeGraphProcessError("code graph protocol input closed early") from error
                            del outgoing[:sent]
                            if not outgoing:
                                selector.unregister(key.fileobj)
                            continue
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        buffer = buffers[key.data]
                        if len(buffer) + len(data) > limits[key.data]:
                            raise CodeGraphProcessError("code graph process exceeded its output limit")
                        buffer.extend(data)
                        if dialogue is not None and key.data == "stdout":
                            line_buffer.extend(data)
                            while b"\n" in line_buffer:
                                line, _, rest = line_buffer.partition(b"\n")
                                line_buffer[:] = rest
                                next_input = dialogue.receive(bytes(line))
                                if type(next_input) is not bytes or input_bytes + len(next_input) > 128 * 1024:
                                    raise CodeGraphProcessError("code graph protocol input exceeded its bound")
                                input_bytes += len(next_input)
                                if next_input:
                                    outgoing.extend(next_input)
                                    if process.stdin.fileno() not in selector.get_map():
                                        selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                            if dialogue.completed and line_buffer:
                                raise CodeGraphProcessError("code graph protocol has trailing output")
                    if dialogue is not None and dialogue.completed:
                        if outgoing:
                            raise CodeGraphProcessError("code graph responded before receiving its request")
                        break
                if dialogue is not None and not dialogue.completed:
                    raise CodeGraphProcessError("code graph protocol closed before negotiation completed")
                # A provider can close both pipes and keep running.
                while dialogue is None and process.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CodeGraphProcessError("code graph process exceeded its time limit")
                    if check_current is not None:
                        check_current()
                    try:
                        process.wait(timeout=min(.25, remaining))
                    except subprocess.TimeoutExpired:
                        pass
            if check_current is not None:
                check_current()
            try:
                stdout = buffers["stdout"].decode("utf-8")
            except UnicodeDecodeError:
                raise CodeGraphProcessError("code graph process returned invalid UTF-8") from None
            code = process.poll()
            return CodeGraphProcessOutput(stdout, buffers["stderr"].decode("utf-8", errors="replace"),
                0 if dialogue is not None and code is None else code)
        finally:
            if process is not None:
                # Kill the owned session, including children that inherited pipes.
                # This also runs for guard exceptions, KeyboardInterrupt and success.
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        # macOS may reject signalling an already exited group.
                        # Never ignore denied cleanup of a still-live child.
                        if process.poll() is None:
                            raise
                process.wait()
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
