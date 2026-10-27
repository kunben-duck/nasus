"""Explicit Git branch/tag identity, independent of provider and current HEAD."""
from __future__ import annotations


def require_tracked_ref(source_type: str, value: str | None) -> str | None:
    if value is None:
        return None
    if (source_type != "code" or type(value) is not str
            or not value.startswith(("refs/heads/", "refs/tags/"))
            or len(value.encode("utf-8")) > 255 or value.endswith(("/", "."))
            or ".." in value or "@{" in value
            or any(ord(char) <= 32 or ord(char) == 127 or char in "~^:?*[\\" for char in value)
            or any(not part or part.startswith(".") or part.endswith(".lock") for part in value.split("/"))):
        raise ValueError("tracked_ref must be an explicit code branch or tag: refs/heads/name or refs/tags/name")
    return value
