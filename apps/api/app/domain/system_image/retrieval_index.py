"""Immutable index inputs. Embeddings are recall hints, never relationship authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import struct

from .source_snapshots import snapshot_digest
from .image_revision import ImageRevisionIntegrityError


class IndexConfigurationChanged(ImageRevisionIntegrityError):
    """A valid historical index no longer matches its live model configuration."""

INDEX_METHOD = "nasus.frozen-evidence-index.v1"
CHUNK_BYTES = 4096
BATCH_SIZE = 32
MAX_DOCUMENTS = 4096
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_DIMENSIONS = 4096


@dataclass(frozen=True)
class IndexDocument:
    document_id: str
    object_id: str
    revision_id: str
    source_revision_id: str
    binding_id: str
    evidence_id: str
    kind: str
    ordinal: int
    text: str
    text_hash: str

    @property
    def digest(self):
        return snapshot_digest(asdict(self))


def split_utf8(text: str, *, max_bytes: int = CHUNK_BYTES) -> tuple[str, ...]:
    if not text or max_bytes < 4:
        raise ValueError("nonempty text and a UTF-8-safe chunk budget are required")
    parts, chars, size = [], [], 0
    for char in text:
        width = len(char.encode("utf-8"))
        if size + width > max_bytes:
            parts.append("".join(chars))
            chars, size = [], 0
        chars.append(char)
        size += width
    if chars:
        parts.append("".join(chars))
    return tuple(parts)


def validate_vectors(values, count: int, dimensions: int | None = None) -> tuple[tuple[float, ...], ...]:
    if not isinstance(values, (tuple, list)) or len(values) != count or count < 1:
        raise ValueError("embedding count mismatch")
    result = []
    for vector in values:
        if not isinstance(vector, (tuple, list)) or not 1 <= len(vector) <= MAX_DIMENSIONS:
            raise ValueError("invalid embedding dimensions")
        dimensions = dimensions or len(vector)
        if len(vector) != dimensions or any(type(v) not in {int, float} or not math.isfinite(v) for v in vector):
            raise ValueError("non-finite or inconsistent embedding")
        try:
            # PostgreSQL vector stores float32. Hash exactly the persisted values.
            converted = tuple(struct.unpack("!f", struct.pack("!f", v))[0] for v in vector)
        except (OverflowError, struct.error):
            raise ValueError("embedding exceeds float32 range") from None
        if not all(math.isfinite(v) for v in converted) or not any(converted):
            raise ValueError("zero or non-finite embedding")
        result.append(converted)
    return tuple(result)


def fuse_ranks(vector_ids, lexical_ids, *, limit: int):
    scores = {}
    for ids, weight in ((vector_ids, 0.7), (lexical_ids, 0.3)):
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate retrieval candidates")
        for rank, key in enumerate(ids, 1):
            scores[key] = scores.get(key, 0.0) + weight / (60 + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
