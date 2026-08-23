from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import TypeVar


Key = TypeVar("Key")
Value = TypeVar("Value")


def replace_projection(
    target: MutableMapping[Key, Value],
    source: Mapping[Key, Value],
) -> None:
    """Replace projection contents while preserving injected mapping identity."""

    target.clear()
    target.update(source)


__all__ = ["replace_projection"]
