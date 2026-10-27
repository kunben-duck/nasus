"""Bounded private SDK/runtime copies; not a hermetic operating-system sandbox."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import stat
import time

from ...application.system_image.source_ports import CodeIntelligenceUnavailable
from ...domain.system_image.source_snapshots import snapshot_digest


class CodeGraphSDKError(CodeIntelligenceUnavailable):
    pass


MAX_RUNTIME_BYTES = 1024 * 1024 * 1024
MAX_RUNTIME_FILES = 30000


def _io(operation, *args):
    try:
        return operation(*args)
    except OSError as error:
        raise CodeGraphSDKError("CodeGraph runtime assets are unavailable") from error


def _signature(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _runtime_assets(package_path, platform_path, *, destinations=None, check_current):
    next_check = 0.0
    def check(*, force=False):
        nonlocal next_check
        if force or time.monotonic() >= next_check:
            check_current()
            next_check = time.monotonic() + .05
    # Keep the same bounded control cadence as projection dependency hashing;
    # a small asset must not cause several full PostgreSQL fencing transactions.
    check(force=True)
    entries, total = [], 0
    for label, root in (("sdk", Path(package_path)), ("platform", Path(platform_path))):
        if root.is_symlink() or not root.is_dir():
            raise CodeGraphSDKError("CodeGraph runtime is not a preinstalled directory")
        for path in sorted(root.rglob("*")):
            check()
            info = _io(path.lstat)
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise CodeGraphSDKError("CodeGraph runtime contains a symbolic link or non-regular asset")
            total += info.st_size
            if total > MAX_RUNTIME_BYTES or len(entries) >= MAX_RUNTIME_FILES:
                raise CodeGraphSDKError("CodeGraph runtime exceeds fingerprint limits")
            relative = path.relative_to(root)
            with ExitStack() as resources:
                fd = _io(os.open, path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
                try:
                    opened = _io(os.fstat, fd)
                    if _signature(info) != _signature(opened) or not stat.S_ISREG(opened.st_mode):
                        raise CodeGraphSDKError("CodeGraph runtime changed before opening an asset")
                    handle = _io(os.fdopen, fd, "rb")
                except BaseException:
                    os.close(fd)
                    raise
                resources.enter_context(handle)
                output = None
                if destinations is not None:
                    target = destinations[label] / relative
                    _io(target.parent.mkdir, 0o700, True, True)
                    output = resources.enter_context(_io(target.open, "xb"))
                consumed, digest = 0, hashlib.sha256()
                for chunk in iter(lambda: _io(handle.read, 1024 * 1024), b""):
                    check()
                    consumed += len(chunk)
                    if consumed > info.st_size:
                        raise CodeGraphSDKError("CodeGraph runtime changed while reading an asset")
                    digest.update(chunk)
                    if output is not None:
                        _io(output.write, chunk)
                check()
                if (consumed != info.st_size or _signature(info) != _signature(_io(os.fstat, handle.fileno()))
                        or _signature(info) != _signature(_io(path.lstat))):
                    raise CodeGraphSDKError("CodeGraph runtime changed while taking its snapshot")
            if destinations is not None:
                _io(target.chmod, 0o500 if label == "platform" and relative.as_posix() == "node" else 0o400)
            entries.append((label + "/" + relative.as_posix(), consumed, digest.hexdigest()))
    check(force=True)
    return snapshot_digest(entries)


def codegraph_runtime_fingerprint(package_path: Path, platform_path: Path, *, check_current=lambda: None) -> str:
    return _runtime_assets(package_path, platform_path, check_current=check_current)


def stage_codegraph_runtime(package_path, platform_path, root, expected_hash, *, check_current):
    # The public SDK resolves its scoped optional dependency through Node's module search.
    modules = Path(root) / "node_modules" / "@colbymchenry"
    copied_sdk, copied_platform = modules / "codegraph", modules / platform_path.name
    copied_sdk.mkdir(mode=0o700, parents=True)
    copied_platform.mkdir(mode=0o700)
    digest = _runtime_assets(package_path, platform_path,
        destinations={"sdk": copied_sdk, "platform": copied_platform}, check_current=check_current)
    if digest != expected_hash or codegraph_runtime_fingerprint(copied_sdk, copied_platform, check_current=check_current) != expected_hash:
        raise CodeGraphSDKError("CodeGraph runtime copy does not match its pinned assets")
    return copied_sdk, copied_platform
