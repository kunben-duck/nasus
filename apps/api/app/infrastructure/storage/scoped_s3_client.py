from __future__ import annotations

import os
from contextlib import contextmanager
from threading import Lock
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .object_storage import ObjectStorageConfig


class ScopedS3Client:
    """One lazy transport lifetime, with no object or authorization cache."""

    def __init__(self, config: ObjectStorageConfig, factory: Callable[[], Any]) -> None:
        self.config, self.factory, self.pid = config, factory, os.getpid()
        self._lock = Lock()
        self._client = None
        self._active = 0
        self._closed = False

    @property
    def is_open(self) -> bool:
        # A fork must not acquire an inherited lock or reuse an inherited client.
        if self.pid != os.getpid():
            return False
        with self._lock:
            return not self._closed

    @contextmanager
    def lease(self):
        if self.pid != os.getpid():
            raise RuntimeError("S3 transport session belongs to another process")
        with self._lock:
            if self._closed:
                raise RuntimeError("S3 transport session is closed")
            if self._client is None:
                self._client = self.factory()
            client = self._client
            self._active += 1
        failed = False
        try:
            yield client
        except BaseException:
            failed = True
            raise
        finally:
            if self.pid != os.getpid():
                raise RuntimeError("S3 transport session belongs to another process")
            with self._lock:
                self._active -= 1
                released = self._detach_if_idle()
            self._close_transport(released, preserve_failure=failed)

    def close(self, *, preserve_failure: bool = False) -> None:
        if self.pid != os.getpid():
            return
        with self._lock:
            self._closed = True
            released = self._detach_if_idle()
        self._close_transport(released, preserve_failure=preserve_failure)

    def _detach_if_idle(self):
        if self._closed and self._active == 0:
            client, self._client = self._client, None
            return client
        return None

    @staticmethod
    def _close_transport(client, *, preserve_failure: bool) -> None:
        if client is not None:
            try:
                client.close()
            except Exception:
                if not preserve_failure:
                    raise
