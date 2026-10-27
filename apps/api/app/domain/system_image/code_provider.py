"""Provider declarations describe static projections, never business authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import re


PROJECTION_SCHEMA = "nasus.code-provider-projection.v1"
OPERATIONS = frozenset({"capabilities", "analyze", "analyze_controlled", "prepare_index", "status",
                        "entities", "relations", "locate", "impact", "cancel"})
ENUMERATION = frozenset({"complete", "partial", "unknown", "not_run"})


def _identifier(value):
    if type(value) is not str or re.fullmatch(r"[a-zA-Z0-9_.+|:-]{1,240}", value) is None:
        raise ValueError("invalid code provider metadata identifier")


def _count(value):
    if type(value) is not int or not 0 <= value <= 100000000:
        raise ValueError("invalid code provider observation count")


@dataclass(frozen=True)
class CodeProviderLimits:
    max_entities: int | None = None
    max_relationships: int | None = None
    page_size: int | None = None
    max_relationship_queries: int | None = None
    command_timeout_seconds: float | None = None

    def __post_init__(self):
        for value in (self.max_entities, self.max_relationships, self.page_size, self.max_relationship_queries):
            if value is not None:
                _count(value)
                if value == 0:
                    raise ValueError("code provider limits must be positive")
        timeout = self.command_timeout_seconds
        if timeout is not None and (type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("invalid code provider command timeout")


@dataclass(frozen=True)
class CodeProviderCapabilities:
    provider: str
    provider_version: str
    operations: tuple[str, ...]
    languages: tuple[str, ...] = ()
    language_coverage: str = "unknown"
    limits: CodeProviderLimits = CodeProviderLimits()

    def __post_init__(self):
        _identifier(self.provider)
        if (type(self.provider_version) is not str
                or re.fullmatch(r"[a-zA-Z0-9_ .+|:()@-]{1,240}", self.provider_version) is None
                or self.provider_version.strip() != self.provider_version):
            raise ValueError("invalid code provider version metadata")
        if (type(self.operations) is not tuple or len(set(self.operations)) != len(self.operations)
                or not set(self.operations) <= OPERATIONS):
            raise ValueError("invalid code provider operations")
        if (self.language_coverage not in {"declared", "unknown"} or type(self.languages) is not tuple
                or len(self.languages) > 200 or len(set(self.languages)) != len(self.languages)
                or (self.language_coverage == "unknown" and self.languages)):
            raise ValueError("invalid code provider language declaration")
        for language in self.languages:
            _identifier(language)
        if not isinstance(self.limits, CodeProviderLimits):
            raise ValueError("invalid code provider limits")


@dataclass(frozen=True)
class CodeProjectionGap:
    reason: str
    count: int | None = None

    def __post_init__(self):
        _identifier(self.reason)
        if self.count is not None:
            _count(self.count)
            if self.count == 0:
                raise ValueError("counted code projection gaps must be nonzero")


@dataclass(frozen=True)
class CodeProviderObservation:
    capabilities: CodeProviderCapabilities
    entity_count: int
    relationship_count: int
    exact_locations: int
    approximate_locations: int
    entity_enumeration: str
    relationship_enumeration: str
    gaps: tuple[CodeProjectionGap, ...] = ()
    availability: str = "observed"

    def __post_init__(self):
        if not isinstance(self.capabilities, CodeProviderCapabilities):
            raise ValueError("missing code provider declaration")
        for value in (self.entity_count, self.relationship_count, self.exact_locations, self.approximate_locations):
            _count(value)
        if self.exact_locations + self.approximate_locations != self.entity_count:
            raise ValueError("code provider location counts do not match entities")
        if self.entity_enumeration not in ENUMERATION or self.relationship_enumeration not in ENUMERATION:
            raise ValueError("invalid code provider enumeration status")
        if (type(self.gaps) is not tuple or len(self.gaps) > 64
                or any(not isinstance(gap, CodeProjectionGap) for gap in self.gaps)
                or len({gap.reason for gap in self.gaps}) != len(self.gaps)):
            raise ValueError("invalid code provider gaps")
        if self.availability not in {"observed", "unavailable", "not_run"}:
            raise ValueError("invalid code provider availability")
        if self.availability != "observed" and (self.entity_count or self.relationship_count
                or self.entity_enumeration != "not_run" or self.relationship_enumeration != "not_run"):
            raise ValueError("unobserved provider cannot claim results")
        if self.availability == "observed" and ("not_run" in {self.entity_enumeration, self.relationship_enumeration}):
            raise ValueError("observed provider requires enumeration status")


def projection_payload(observations):
    if (type(observations) is not tuple or not 1 <= len(observations) <= 8
            or any(not isinstance(item, CodeProviderObservation) for item in observations)
            or len({item.capabilities.provider for item in observations}) != len(observations)):
        raise ValueError("invalid code projection provider set")
    complete = all(item.availability == "observed" and not item.gaps
                   and item.entity_enumeration == item.relationship_enumeration == "complete"
                   and not item.approximate_locations for item in observations)
    return json.loads(json.dumps({"schema": PROJECTION_SCHEMA,
        "scope": "normalized_static_projection_not_business_or_runtime_acceptance",
        "status": "complete" if complete else "partial", "providers": [asdict(item) for item in observations]}))


def validate_projection_payload(payload):
    """Rebuild metadata strictly; old reports must retain an explicit unknown."""
    try:
        if type(payload) is not dict or set(payload) != {"schema", "scope", "status", "providers"}:
            raise ValueError("invalid code projection envelope")
        if type(payload["providers"]) is not list or not 1 <= len(payload["providers"]) <= 8:
            raise ValueError("invalid code projection providers")
        observations = []
        for item in payload["providers"]:
            capabilities = item["capabilities"]
            if type(capabilities["operations"]) is not list or type(capabilities["languages"]) is not list or type(item["gaps"]) is not list:
                raise ValueError("invalid code projection metadata collections")
            declaration = CodeProviderCapabilities(**{**capabilities,
                "operations": tuple(capabilities["operations"]), "languages": tuple(capabilities["languages"]),
                "limits": CodeProviderLimits(**capabilities["limits"])})
            observations.append(CodeProviderObservation(**{**item, "capabilities": declaration,
                "gaps": tuple(CodeProjectionGap(**gap) for gap in item["gaps"])}))
        # JSON round trips convert tuples to arrays; compare canonical plain values.
        expected = projection_payload(tuple(observations))
        if expected != payload:
            raise ValueError("code projection status does not match observations")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("invalid code projection metadata") from exc
