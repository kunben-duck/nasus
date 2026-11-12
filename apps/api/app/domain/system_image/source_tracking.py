"""Explicit Git branch, tag or commit identity, independent of current HEAD."""
from __future__ import annotations

import re


_FIXED_COMMIT = re.compile(r"[0-9a-f]{40}")


def is_fixed_git_commit(value: str | None) -> bool:
    return type(value) is str and _FIXED_COMMIT.fullmatch(value) is not None


def require_tracked_ref(source_type: str, value: str | None) -> str | None:
    if value is None:
        return None
    if source_type == "code" and is_fixed_git_commit(value):
        return value
    if (source_type != "code" or type(value) is not str
            or not value.startswith(("refs/heads/", "refs/tags/"))
            or len(value.encode("utf-8")) > 255 or value.endswith(("/", "."))
            or ".." in value or "@{" in value
            or any(ord(char) <= 32 or ord(char) == 127 or char in "~^:?*[\\" for char in value)
            or any(not part or part.startswith(".") or part.endswith(".lock") for part in value.split("/"))):
        raise ValueError("tracked_ref must be refs/heads/name, refs/tags/name, or a full lowercase 40-character Git commit for code")
    return value
