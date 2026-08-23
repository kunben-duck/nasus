from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


CodeGraphMode = Literal["disabled", "optional", "required"]
CodeGraphIndexMode = Literal["fast", "moderate", "full"]


@dataclass(frozen=True)
class CodeGraphConfig:
    """Runtime policy for the replaceable external code-graph projection."""

    mode: CodeGraphMode
    binary: str
    index_mode: CodeGraphIndexMode
    timeout_seconds: float
    max_entities: int
    max_relationships: int
    page_size: int
    cache_dir: Path | None

    @classmethod
    def from_env(cls) -> "CodeGraphConfig":
        mode = _choice(
            "NASUS_CODE_GRAPH_MODE",
            "disabled",
            {"disabled", "optional", "required"},
        )
        index_mode = _choice(
            "NASUS_CODE_GRAPH_INDEX_MODE",
            "moderate",
            {"fast", "moderate", "full"},
        )
        cache_value = os.getenv("NASUS_CODE_GRAPH_CACHE_DIR", "").strip()
        return cls(
            mode=mode,  # type: ignore[arg-type]
            binary=os.getenv(
                "NASUS_CODE_GRAPH_BINARY",
                "codebase-memory-mcp",
            ).strip()
            or "codebase-memory-mcp",
            index_mode=index_mode,  # type: ignore[arg-type]
            timeout_seconds=_positive_float(
                "NASUS_CODE_GRAPH_TIMEOUT_SECONDS",
                180.0,
            ),
            max_entities=_positive_int(
                "NASUS_CODE_GRAPH_MAX_ENTITIES",
                10_000,
            ),
            max_relationships=_positive_int(
                "NASUS_CODE_GRAPH_MAX_RELATIONSHIPS",
                25_000,
            ),
            page_size=_positive_int("NASUS_CODE_GRAPH_PAGE_SIZE", 500),
            cache_dir=Path(cache_value).expanduser().resolve() if cache_value else None,
        )


def _choice(name: str, default: str, allowed: set[str]) -> str:
    value = os.getenv(name, default).strip().lower() or default
    if value not in allowed:
        values = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of {values}")
    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


__all__ = ["CodeGraphConfig", "CodeGraphIndexMode", "CodeGraphMode"]
