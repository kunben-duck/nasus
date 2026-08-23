from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Sequence


EntityKind = Literal["code", "us_doc", "test_asset"]
RelationshipKind = Literal["implements", "covers", "validates"]


@dataclass(frozen=True)
class EntityCandidate:
    object_id: str
    entity_kind: EntityKind
    label: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedEntityLink:
    from_object_id: str
    relationship_type: RelationshipKind
    to_object_id: str
    confidence: float
    source_refs: tuple[str, ...]


class CrossSourceEntityResolver:
    """Deterministically links requirement, code, and test objects.

    The resolver is deliberately provider-neutral. A built-in parser, an MCP
    code graph, or a future graph engine can all supply the same candidates.
    """

    _PAIR_RULES: tuple[tuple[EntityKind, EntityKind, RelationshipKind], ...] = (
        ("code", "us_doc", "implements"),
        ("test_asset", "code", "covers"),
        ("test_asset", "us_doc", "validates"),
    )
    _STOP_WORDS = {
        "a",
        "an",
        "and",
        "as",
        "asset",
        "class",
        "code",
        "def",
        "document",
        "feature",
        "file",
        "for",
        "from",
        "function",
        "i",
        "in",
        "it",
        "md",
        "module",
        "of",
        "py",
        "requirement",
        "section",
        "service",
        "src",
        "test",
        "tests",
        "that",
        "the",
        "to",
        "us",
        "with",
    }

    def __init__(self, *, minimum_confidence: float = 0.42, max_links_per_object: int = 3) -> None:
        self.minimum_confidence = minimum_confidence
        self.max_links_per_object = max_links_per_object

    def resolve(self, candidates: Sequence[EntityCandidate]) -> list[ResolvedEntityLink]:
        by_kind = {
            kind: [candidate for candidate in candidates if candidate.entity_kind == kind]
            for kind in ("code", "us_doc", "test_asset")
        }
        links: list[ResolvedEntityLink] = []
        for from_kind, to_kind, relationship_type in self._PAIR_RULES:
            for source in by_kind[from_kind]:
                ranked = sorted(
                    (
                        (self._similarity(source.label, target.label), target)
                        for target in by_kind[to_kind]
                    ),
                    key=lambda item: (-item[0], item[1].object_id),
                )
                accepted = 0
                for confidence, target in ranked:
                    if confidence < self.minimum_confidence:
                        continue
                    links.append(
                        ResolvedEntityLink(
                            from_object_id=source.object_id,
                            relationship_type=relationship_type,
                            to_object_id=target.object_id,
                            confidence=confidence,
                            source_refs=tuple(
                                dict.fromkeys((*source.evidence_refs, *target.evidence_refs))
                            ),
                        )
                    )
                    accepted += 1
                    if accepted >= self.max_links_per_object:
                        break
        return links

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        left_tokens = cls._tokens(left)
        right_tokens = cls._tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        shared = left_tokens & right_tokens
        if not shared:
            return 0.0
        overlap = len(shared) / min(len(left_tokens), len(right_tokens))
        jaccard = len(shared) / len(left_tokens | right_tokens)
        distinctive = max((len(token) for token in shared), default=0)
        distinctive_bonus = min(0.12, max(0, distinctive - 5) * 0.02)
        return round(min(0.98, 0.16 + overlap * 0.52 + jaccard * 0.20 + distinctive_bonus), 2)

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", expanded.lower())
            if len(token) >= 3 and token not in cls._STOP_WORDS and not token.isdigit()
        }
        return tokens


__all__ = [
    "CrossSourceEntityResolver",
    "EntityCandidate",
    "EntityKind",
    "ResolvedEntityLink",
    "RelationshipKind",
]
