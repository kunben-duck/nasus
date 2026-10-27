"""Bounded regular-file reads for an operation-local dependency inventory."""
import hashlib
import os
from pathlib import Path
import stat
import time

from .code_graph_process import CodeGraphProcessError


MAX_DEPENDENCY_FILE_BYTES = 64 * 1024 * 1024
MAX_DEPENDENCY_BYTES = 512 * 1024 * 1024
MAX_DEPENDENCY_FILES = 65536


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _io(operation, *args):
    try:
        return operation(*args)
    except OSError as error:
        raise CodeGraphProcessError("code projection dependency is unavailable") from error


class DependencyFiles:
    def __init__(self, *, check_current=None):
        self._check_current = check_current or (lambda: None)
        self._check_after = 0.0
        self.bytes_read = 0
        self.records = {}

    def check_current(self, *, force=False):
        now = time.monotonic()
        if force or now >= self._check_after:
            self._check_current()
            self._check_after = time.monotonic() + .05

    def read(self, path, *, capture=False, limit=MAX_DEPENDENCY_FILE_BYTES):
        self.check_current()
        path = Path(path)
        # Ancestor links cannot redirect an approved package/source directory.
        if any(parent.is_symlink() for parent in path.parents):
            raise CodeGraphProcessError("code projection dependency contains a symbolic link")
        descriptor = _io(os.open, path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = _io(os.fstat, descriptor)
            if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= limit:
                raise CodeGraphProcessError("code projection dependency exceeds its file policy")
            if (len(self.records) >= MAX_DEPENDENCY_FILES
                    or self.bytes_read + before.st_size > MAX_DEPENDENCY_BYTES):
                raise CodeGraphProcessError("code projection dependency inventory exceeds its budget")
            digest, data, consumed = hashlib.sha256(), bytearray() if capture else None, 0
            while True:
                self.check_current()
                chunk = _io(os.read, descriptor, 1024 * 1024)
                if not chunk:
                    break
                consumed += len(chunk)
                self.bytes_read += len(chunk)
                if consumed > limit or self.bytes_read > MAX_DEPENDENCY_BYTES:
                    raise CodeGraphProcessError("code projection dependency exceeds its byte budget")
                digest.update(chunk)
                if data is not None:
                    data.extend(chunk)
            after = _io(os.fstat, descriptor)
            if consumed != before.st_size or _signature(before) != _signature(after):
                raise CodeGraphProcessError("code projection dependency changed during its read")
            previous = self.records.get(path)
            if previous is not None and previous != _signature(after):
                raise CodeGraphProcessError("code projection dependency changed during its inventory")
            self.records[path] = _signature(after)
            return digest.hexdigest(), bytes(data) if data is not None else None
        finally:
            os.close(descriptor)

    def finish(self):
        for path, signature in self.records.items():
            self.check_current()
            if _signature(_io(path.lstat)) != signature or any(parent.is_symlink() for parent in path.parents):
                raise CodeGraphProcessError("code projection dependency changed during its inventory")
        self.check_current(force=True)
