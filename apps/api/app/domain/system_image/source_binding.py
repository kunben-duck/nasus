from __future__ import annotations

import re
from typing import Iterable, Protocol


REQUIRED_SOURCE_TYPES = ("code",)
OPTIONAL_SOURCE_TYPES = ("us_doc", "test_asset")


class SourceBindingLike(Protocol):
    source_type: str
    source_uri: str
    content_hash: str
    evidence_refs: list[str]


def slugify_project_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def default_source_uri(project_name: str, source_type: str) -> str:
    slug = slugify_project_name(project_name)
    if source_type == "code":
        return f"git://{slug}"
    if source_type == "us_doc":
        return f"docs://{slug}/historical-us"
    return f"tests://{slug}/regression"


def is_placeholder_source(source: SourceBindingLike, project_name: str) -> bool:
    return (
        source.source_uri == default_source_uri(project_name, source.source_type)
        and not source.content_hash
        and not source.evidence_refs
    )


def missing_source_types(sources: Iterable[SourceBindingLike], project_name: str) -> list[str]:
    sources_by_type = {source.source_type: source for source in sources}
    missing: list[str] = []
    for source_type in REQUIRED_SOURCE_TYPES:
        source = sources_by_type.get(source_type)
        if source is None or is_placeholder_source(source, project_name):
            missing.append(source_type)
    return missing


def source_binding_incomplete(sources: Iterable[SourceBindingLike], project_name: str) -> bool:
    return bool(missing_source_types(sources, project_name))


def missing_optional_source_types(
    sources: Iterable[SourceBindingLike],
    project_name: str,
) -> list[str]:
    sources_by_type = {source.source_type: source for source in sources}
    return [
        source_type
        for source_type in OPTIONAL_SOURCE_TYPES
        if (
            source_type not in sources_by_type
            or is_placeholder_source(sources_by_type[source_type], project_name)
        )
    ]
