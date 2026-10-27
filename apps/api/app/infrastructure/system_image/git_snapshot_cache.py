from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Sequence


class GitSnapshotCache:
    """Publish detached, revision-specific checkouts; never refresh them in place."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def materialize(
        self,
        *,
        namespace: str,
        revision: str,
        repository: Path,
        run_git: Callable[[Sequence[str]], str],
    ) -> Path:
        destination = self.root / namespace / revision
        if destination.exists():
            self._validate(destination, revision, run_git)
            return destination

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=destination.parent))
        try:
            # Fetch the exact object, including commits outside the cache's
            # current branch. Transfer objects instead of sharing hardlinks.
            run_git(["init", "--quiet", str(temporary)])
            run_git([
                "-C", str(temporary), "fetch", "--depth", "1", "--no-tags",
                "--", str(repository), revision,
            ])
            run_git(["-C", str(temporary), "checkout", "--detach", revision])
            self._validate(temporary, revision, run_git)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return destination

    @staticmethod
    def _validate(
        checkout: Path,
        revision: str,
        run_git: Callable[[Sequence[str]], str],
    ) -> None:
        if checkout.is_symlink() or (checkout / ".git").is_symlink() or not (checkout / ".git").is_dir():
            raise OSError("Git snapshot cache is not a detached repository")
        actual = run_git(["-C", str(checkout), "rev-parse", "HEAD"]).strip()
        if actual != revision:
            raise OSError("Git snapshot revision does not match its identity")
        index = run_git(["-C", str(checkout), "ls-files", "-v", "-z"])
        if any(item and (item[0].islower() or item[0] == "S") for item in index.split("\0")):
            raise OSError("Git snapshot index skips content validation")
        changed = run_git([
            "-C", str(checkout), "status", "--porcelain", "--untracked-files=all",
            "--ignored=matching",
        ])
        if changed.strip():
            raise OSError("Git snapshot contents changed after materialization")


__all__ = ["GitSnapshotCache"]
