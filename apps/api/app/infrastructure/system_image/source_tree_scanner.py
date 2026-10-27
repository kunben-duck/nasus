from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path
import stat

from ...domain.system_image.source_inventory import SourceInventory, SourceInventoryEntry


@dataclass(frozen=True)
class SourceTreeScan:
    inventory: SourceInventory
    files: tuple[tuple[str, bytes], ...]


class SourceTreeScanner:
    """Bounded raw acquisition, not language/parser coverage or semantic readiness."""

    def __init__(self, *, excluded_names: frozenset[str], max_files: int,
                 max_bytes: int, max_file_bytes: int, max_entries: int = 20000,
                 max_depth: int = 128) -> None:
        if min(max_files, max_bytes, max_file_bytes, max_entries, max_depth) < 1 or max_entries > 50000:
            raise ValueError("invalid source scan limits")
        self.excluded_names = excluded_names
        self.max_files, self.max_bytes, self.max_file_bytes = max_files, max_bytes, max_file_bytes
        self.max_entries, self.max_depth = max_entries, max_depth

    def scan(self, root: Path) -> SourceTreeScan:
        return _Scan(self).run(root)


class _Scan:
    def __init__(self, policy: SourceTreeScanner) -> None:
        self.policy = policy
        self.entries: dict[str, SourceInventoryEntry] = {}
        self.files: dict[str, bytes] = {}
        self.byte_count = 0
        self.enumeration_complete = True
        self.metadata_bytes = 0

    def _entry(self, path: str, kind: str, status: str, reason: str, body: bytes | None = None) -> None:
        entry = SourceInventoryEntry(
            path, kind, status, reason, len(body) if body is not None else 0,
            "sha256:" + hashlib.sha256(body).hexdigest() if body is not None else None,
        )
        if path not in self.entries:
            self.metadata_bytes += len(path.encode("utf-8")) + 512
        self.entries[path] = entry

    @staticmethod
    def _stamp(info: os.stat_result) -> tuple:
        return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns

    def run(self, root: Path) -> SourceTreeScan:
        # Open each descendant relative to its already-open parent. O_NOFOLLOW
        # prevents a rename/symlink race from escaping the authorized snapshot.
        parent_fd = None
        try:
            root = Path(os.path.abspath(root))
            parent_fd = self._open_parent(root)
            name = root.name or "."
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            relative = "." if stat.S_ISDIR(info.st_mode) else name
            self._entry(relative, "unknown", "failed", "not_scanned")
            self._visit(name, relative, info, parent_fd=parent_fd, depth=0)
        except OSError as exc:
            self._entry(".", "unknown", "failed", self._error(exc))
            self.enumeration_complete = False
        except (ValueError, UnicodeError):
            self._entry(".", "unknown", "failed", "unsafe_path")
            self.enumeration_complete = False
        finally:
            if parent_fd is not None:
                os.close(parent_fd)
        return SourceTreeScan(
            SourceInventory(tuple(self.entries[key] for key in sorted(self.entries)),
                            tuple(sorted(self.policy.excluded_names)), self.enumeration_complete),
            tuple(sorted(self.files.items())),
        )

    @staticmethod
    def _open_parent(root: Path) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(root.anchor, flags)
        try:
            for part in root.parent.parts[1:]:
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _error(exc: OSError) -> str:
        if exc.errno in {errno.EACCES, errno.EPERM}:
            return "permission_denied"
        if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
            return "source_changed"
        return "io_error"

    def _visit(self, name: str, relative: str, info: os.stat_result, *, parent_fd: int | None, depth: int) -> None:
        mode = info.st_mode
        kind = "directory" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "special"
        if stat.S_ISLNK(mode):
            self._entry(relative, "symlink", "unsupported", "symbolic_link")
            return
        if kind == "special":
            self._entry(relative, kind, "unsupported", "special_file")
            return
        if kind == "directory" and depth > self.policy.max_depth:
            self._entry(relative, kind, "failed", "depth_limit")
            self.enumeration_complete = False
            return
        if kind == "file":
            reason = (
                "file_count_limit" if len(self.files) >= self.policy.max_files else
                "file_size_limit" if info.st_size > self.policy.max_file_bytes else
                "total_size_limit" if self.byte_count + info.st_size > self.policy.max_bytes else None
            )
            if reason:
                self._entry(relative, kind, "failed", reason)
                return
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if kind == "directory":
            flags |= os.O_DIRECTORY
        try:
            fd = os.open(name, flags, dir_fd=parent_fd)
            try:
                if self._stamp(os.fstat(fd)) != self._stamp(info):
                    self._entry(relative, kind, "failed", "source_changed")
                    if kind == "directory":
                        self.enumeration_complete = False
                    return
                if kind == "directory":
                    self._directory(fd, relative, depth)
                else:
                    self._file(fd, relative, info.st_size)
                if self._stamp(os.fstat(fd)) != self._stamp(info):
                    self._entry(relative, kind, "failed", "source_changed")
                    if relative in self.files:
                        self.byte_count -= len(self.files.pop(relative))
                    if kind == "directory":
                        self.enumeration_complete = False
            finally:
                os.close(fd)
        except OSError as exc:
            self._entry(relative, kind, "failed", self._error(exc))
            if kind == "directory":
                self.enumeration_complete = False

    def _directory(self, fd: int, relative: str, depth: int) -> None:
        self._entry(relative, "directory", "enumerated", "scanned")
        # Reserve observed children before descending so the entire ledger stays
        # bounded. An omitted subtree is explicitly incomplete, never a deletion.
        children = []
        with os.scandir(fd) as iterator:
            for child in iterator:
                if len(self.entries) >= self.policy.max_entries:
                    self._entry(relative, "directory", "failed", "inventory_entry_limit")
                    self.enumeration_complete = False
                    break
                path = child.name if relative == "." else f"{relative}/{child.name}"
                try:
                    if self.metadata_bytes + len(path.encode("utf-8")) + 512 > 8 * 1024 * 1024:
                        self._entry(relative, "directory", "failed", "inventory_byte_limit")
                        self.enumeration_complete = False
                        break
                    self._entry(path, "unknown", "failed", "not_scanned")
                except (ValueError, UnicodeError):
                    self._entry(relative, "directory", "failed", "unsafe_path")
                    self.enumeration_complete = False
                    continue
                children.append((child.name, path))
        for name, path in sorted(children):
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except OSError as exc:
                self._entry(path, "unknown", "failed", self._error(exc))
                self.enumeration_complete = False
                continue
            if name in self.policy.excluded_names:
                kind = "directory" if stat.S_ISDIR(info.st_mode) else "symlink" if stat.S_ISLNK(info.st_mode) else "file"
                self._entry(path, kind, "excluded", "excluded_name")
                continue
            self._visit(name, path, info, parent_fd=fd, depth=depth + 1)

    def _file(self, fd: int, relative: str, size: int) -> None:
        remaining = min(self.policy.max_file_bytes, self.policy.max_bytes - self.byte_count, size) + 1
        chunks = []
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        if len(body) != size:
            self._entry(relative, "file", "failed", "source_changed")
            return
        self.files[relative] = body
        self.byte_count += len(body)
        self._entry(relative, "file", "included", "raw_bytes_captured", body)
