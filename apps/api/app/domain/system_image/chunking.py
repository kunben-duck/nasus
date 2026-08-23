from __future__ import annotations

from hashlib import sha256


DEFAULT_CHUNK_MAX_CHARS = 4000


def split_chunk_text(text: str, *, max_chars: int = DEFAULT_CHUNK_MAX_CHARS) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            newline = normalized.rfind("\n", start, end)
            if newline > start + max_chars // 2:
                end = newline
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end, start + 1)
    return chunks


def content_hash(text: str) -> str:
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()


def stable_hash(parts: list[str]) -> str:
    return "sha256:" + sha256("|".join(parts).encode("utf-8")).hexdigest()


def chunk_id(project_id: str, source_id: str, section_path: str, chunk_index: int, chunk_hash: str) -> str:
    digest = sha256("|".join([project_id, source_id, section_path, str(chunk_index), chunk_hash]).encode("utf-8")).hexdigest()
    return f"chunk_{project_id}_{digest[:16]}"


def chunk_kind(source_type: str) -> str:
    if source_type == "code":
        return "code"
    if source_type == "us_doc":
        return "requirement"
    if source_type == "test_asset":
        return "test"
    return "summary"


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))
