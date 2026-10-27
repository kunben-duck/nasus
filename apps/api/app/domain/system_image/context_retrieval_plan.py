"""Deterministic, bounded queries from frozen source requirements, not approved oracles."""
from dataclasses import asdict, dataclass
import math

from .context_partition import MAX_CONSTRAINTS
from .image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from .retrieval_index import BATCH_SIZE
from .source_snapshots import snapshot_digest

CONTEXT_QUERY_METHOD = "nasus.context-retrieval-plan.v1"
MAX_QUERY_BYTES = 4096
MAX_TOTAL_QUERY_BYTES = MAX_CONSTRAINTS * MAX_QUERY_BYTES


@dataclass(frozen=True)
class ContextRetrievalQuery:
    target_object_id: str
    target_revision_id: str
    parent_object_id: str
    parent_revision_id: str
    source_revision_id: str
    binding_id: str
    evidence_selections: tuple[tuple[str, str], ...]
    text: str


def source_query(ac_values: tuple[str, ...], descriptions: tuple[str, ...]) -> str:
    if not ac_values or any(not value.strip() for value in ac_values):
        raise ImageRevisionIntegrityError("context retrieval requires complete nonempty source AC fields")
    parts = ["Acceptance criterion:\n" + "\n".join(ac_values)]
    if descriptions:
        parts.insert(0, "Requirement description:\n" + "\n".join(descriptions))
    text = "\n\n".join(parts)
    if len(text.encode("utf-8")) > MAX_QUERY_BYTES:
        raise ImageRevisionPageTooLarge("a context query exceeds 4096 UTF-8 bytes; no fields were truncated")
    return text


def query_plan_budget(queries: tuple[ContextRetrievalQuery, ...]) -> dict:
    ids = [query.target_object_id for query in queries]
    if len(ids) != len(set(ids)) or ids != sorted(ids):
        raise ImageRevisionIntegrityError("context queries require unique sorted AC identities")
    sizes = [len(query.text.encode("utf-8")) for query in queries]
    if (len(queries) > MAX_CONSTRAINTS or any(size > MAX_QUERY_BYTES for size in sizes)
            or sum(sizes) > MAX_TOTAL_QUERY_BYTES):
        raise ImageRevisionPageTooLarge("context query plan exceeds its budget; no AC was omitted")
    if any(not query.text.strip() or not query.evidence_selections for query in queries):
        raise ImageRevisionIntegrityError("context query has no source text or evidence")
    return {"query_count": len(queries), "input_bytes": sum(sizes), "max_query_bytes": max(sizes, default=0),
        "max_model_calls": math.ceil(len(queries) / BATCH_SIZE), "batch_size": BATCH_SIZE,
        "timeout_per_call_seconds": 60, "max_query_count": MAX_CONSTRAINTS,
        "query_byte_limit": MAX_QUERY_BYTES, "total_byte_limit": MAX_TOTAL_QUERY_BYTES,
        "queries_digest": snapshot_digest([asdict(query) for query in queries])}
