from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import math
import re
import unicodedata


LINK_RECALL_METHOD = "nasus.link-recall.lexical.v1"
_IDENTIFIERS = re.compile(r"\b(?:US|REQ|AC|BR|RULE|TC)-[\w.-]+", re.I)
_STOP_WORDS = frozenset("a an the of to in on for and or with from is are be by as this that should must shall test case result expected description".split())


def recall_terms(text: str) -> frozenset[str]:
    """Identifier mentions are a separate recall signal, never semantic proof."""
    text = _IDENTIFIERS.sub(" ", unicodedata.normalize("NFKC", text))
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).casefold()
    terms = {word for word in re.findall(r"[a-z0-9]+", text) if len(word) > 1 and word not in _STOP_WORDS}
    # CJK bigrams avoid an external tokenizer and support unspaced source text.
    for run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", text):
        terms.update(run[i:i + 2] for i in range(len(run) - 1))
    return frozenset(terms)


@dataclass(frozen=True)
class LinkRecallInput:
    object_id: str
    text: str
    explicit_reference: bool = False


@dataclass(frozen=True)
class RankedLinkCandidate:
    object_id: str
    retrieval_score: float
    matched_terms: tuple[str, ...]
    signals: tuple[str, ...]


def rank_link_candidates(query: str, candidates: tuple[LinkRecallInput, ...]) -> tuple[RankedLinkCandidate, ...]:
    if len(candidates) > 10000 or len({item.object_id for item in candidates}) != len(candidates):
        raise ValueError("invalid or oversized link recall input")
    if len(query) > 65536 or any(len(item.text) > 65536 for item in candidates) or sum(len(item.text) for item in candidates) > 8 * 1024 * 1024:
        raise ValueError("link recall text exceeds budget")
    query_terms = recall_terms(query)
    terms = [recall_terms(item.text) for item in candidates]
    frequencies = Counter(term for words in terms for term in words & query_terms)
    weights = {term: 1 + math.log((len(candidates) + 1) / (1 + frequencies[term])) for term in sorted(query_terms)}
    denominator = sum(weights.values()) or 1
    result = []
    for item, words in zip(candidates, terms):
        matched = query_terms & words
        if not matched and not item.explicit_reference:
            continue
        score = sum(weights[term] for term in sorted(matched)) / denominator
        signals = (("lexical_overlap",) if matched else ()) + (("explicit_requirement_reference",) if item.explicit_reference else ())
        result.append(RankedLinkCandidate(item.object_id, round(score + (0.25 if item.explicit_reference else 0), 6),
                                          tuple(sorted(matched)), signals))
    return tuple(sorted(result, key=lambda item: (-item.retrieval_score, item.object_id)))
