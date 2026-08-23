from __future__ import annotations

from .read_models import DocumentationEntry


def product_documentation_entries() -> tuple[DocumentationEntry, ...]:
    """Return the product documentation index available in every runtime profile."""

    return (
        DocumentationEntry(
            id="DOC-START",
            title="Getting Started",
            copy=(
                "How to create a project, connect sources, and initialize the "
                "Official System Image."
            ),
            category="Guide",
        ),
        DocumentationEntry(
            id="DOC-BRANCHING",
            title="System Image & Branching",
            copy=(
                "Official baseline, version branch overlays, candidate promotion, "
                "and baseline write-back."
            ),
            category="Concept",
        ),
        DocumentationEntry(
            id="DOC-ASSET",
            title="Quality Asset Pack",
            copy=(
                "How scenarios, scope, plans, cases, automation, performance, and "
                "change docs work together."
            ),
            category="Reference",
        ),
    )


__all__ = ["product_documentation_entries"]
