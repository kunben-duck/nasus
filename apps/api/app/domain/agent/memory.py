from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re


@dataclass(frozen=True)
class AgentMemoryContext:
    system_prompt: str
    context_snapshot: str
    history_snapshot: str
    recent_turn_count: int
    checkpoint_count: int
    retrieval_query: str = ""
    retrieved_context_refs: list[str] = field(default_factory=list)
    retrieved_context_summary: str = ""
    retrieval_run_refs: list[str] = field(default_factory=list)


def memory_context_hash(memory_context: AgentMemoryContext) -> str:
    payload = "\n\n".join(
        [
            memory_context.system_prompt,
            memory_context.context_snapshot,
            memory_context.history_snapshot,
        ]
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def memory_context_summary(memory_context: AgentMemoryContext) -> str:
    sections = [
        match.group(1)
        for line in memory_context.context_snapshot.splitlines()
        if (match := re.fullmatch(r"\[([a-z0-9_]+)\]", line.strip()))
    ]
    section_summary = ", ".join(sections[:8]) if sections else "space"
    return (
        f"sections={section_summary}; "
        f"recent_turns={memory_context.recent_turn_count}; "
        f"checkpoints={memory_context.checkpoint_count}"
    )
