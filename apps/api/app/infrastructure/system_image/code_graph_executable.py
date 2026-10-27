"""Bounded, worker-private executable snapshots; not an OS sandbox."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import stat
import time

from .code_graph_process import CodeGraphProcessError


MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
AUTHORITY_CHECK_INTERVAL = .05


def _file_io(operation, *args):
    try:
        return operation(*args)
    except OSError as error:
        raise CodeGraphProcessError("code graph executable snapshot is unavailable") from error


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_executable(source, *, destination=None, check_current=None):
    check_after = 0.0

    def check(*, force=False):
        nonlocal check_after
        if check_current is not None and (force or time.monotonic() >= check_after):
            check_current()
            check_after = time.monotonic() + AUTHORITY_CHECK_INTERVAL

    with ExitStack() as resources:
        check(force=True)
        descriptor = _file_io(os.open, source, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            info = _file_io(os.fstat, descriptor)
            if (not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111
                    or not 0 < info.st_size <= MAX_EXECUTABLE_BYTES):
                raise CodeGraphProcessError("code graph executable exceeds its file policy")
            handle = _file_io(os.fdopen, descriptor, "rb")
        except BaseException:
            os.close(descriptor)
            raise
        resources.enter_context(handle)
        output = resources.enter_context(_file_io(Path(destination).open, "xb")) if destination is not None else None
        digest, consumed = hashlib.sha256(), 0
        for chunk in iter(lambda: _file_io(handle.read, 1024 * 1024), b""):
            # Recheck authority on elapsed time, not once per MiB of a large
            # executable. Every read still hashes all bytes, with forced fences.
            check()
            consumed += len(chunk)
            if consumed > MAX_EXECUTABLE_BYTES:
                raise CodeGraphProcessError("code graph executable exceeds its file policy")
            digest.update(chunk)
            if output is not None:
                _file_io(output.write, chunk)
        check(force=True)
        after = _file_io(os.fstat, handle.fileno())
        current = _file_io(Path(source).lstat)
        if consumed != info.st_size or _signature(info) != _signature(after) or _signature(after) != _signature(current):
            raise CodeGraphProcessError("code graph executable changed while taking its snapshot")
        return digest.hexdigest()


def code_graph_executable_digest(source, *, check_current=None):
    return _read_executable(source, check_current=check_current)


def stage_code_graph_executable(source, root, *, check_current):
    destination = Path(root) / "codebase-memory-mcp"
    _read_executable(source, destination=destination, check_current=check_current)
    _file_io(destination.chmod, 0o500)
    return destination
