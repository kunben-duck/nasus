from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace

from ...application.system_image.source_ports import CodeEntityCandidate, CodeIntelligenceResult
from ...domain.system_image.code_provider import CodeProjectionGap


def attach_symbol_keys(
    result: CodeIntelligenceResult, reference: CodeIntelligenceResult,
) -> CodeIntelligenceResult:
    """Map public provider candidates to syntax-verified, provider-neutral keys.

    The reference is extracted from the same immutable text units. A provider's
    qualified-name convention is deliberately not used as a canonical identity.
    """
    by_symbol: dict[tuple[str, str, str, str], list[CodeEntityCandidate]] = defaultdict(list)
    for entity in reference.entities:
        by_symbol[_symbol_selector(entity)].append(entity)
    mapped: list[CodeEntityCandidate] = []
    for entity in result.entities:
        matches = by_symbol.get(_symbol_selector(entity), [])
        if len(matches) > 1 and entity.location_precision == "exact":
            matches = [item for item in matches if (
                item.start_line == entity.start_line and item.end_line == entity.end_line
            )]
        match = matches[0] if len(matches) == 1 else None
        if match is not None and match.symbol_key is not None:
            # A unique name establishes identity, not the correctness of a
            # provider's span. Preserve disputed coordinates as approximate.
            if entity.location_precision == "exact" and (
                match.location_precision != "exact"
                or (entity.start_line, entity.end_line) != (match.start_line, match.end_line)
            ):
                refs = tuple(
                    "code-graph-location:provider-claimed-exact" if ref == "code-graph-location:exact" else ref
                    for ref in entity.evidence_refs
                )
                entity = replace(entity, location_precision="approximate", evidence_refs=tuple(dict.fromkeys(
                    (*refs, "code-graph-location:approximate", "code-graph-location:syntax-mismatch")
                )))
            mapped.append(replace(entity, symbol_key=match.symbol_key, identity_status="exact",
                                  supporting_spans=match.supporting_spans))
        else:
            ambiguous = len(matches) > 1 or (match is not None and match.identity_status == "ambiguous")
            mapped.append(replace(entity, symbol_key=None, identity_status="ambiguous" if ambiguous else "unresolved"))
    # Do not map two provider nodes to one formal symbol merely because their
    # public fields are indistinguishable. Keep that ambiguity visible.
    counts = Counter(item.symbol_key for item in mapped if item.symbol_key is not None)
    entities = tuple(
        replace(item, symbol_key=None, identity_status="ambiguous")
        if item.symbol_key is not None and counts[item.symbol_key] > 1 else item
        for item in mapped
    )
    identity_counts = Counter(item.identity_status for item in entities)
    reasons = {status: status + "_symbol_identity" for status in ("unresolved", "ambiguous")}
    observations = tuple(replace(report, gaps=(
        *(gap for gap in report.gaps if gap.reason not in reasons.values()),
        *(CodeProjectionGap(reason, identity_counts[status]) for status, reason in reasons.items()
          if identity_counts[status]),
    )) if report.availability == "observed" and report.capabilities.provider == result.provider else report
        for report in result.provider_observations)
    return replace(result, entities=entities, provider_observations=observations)


def _symbol_selector(entity: CodeEntityCandidate) -> tuple[str, str, str, str]:
    return entity.relative_path, entity.language, entity.entity_kind, entity.name
