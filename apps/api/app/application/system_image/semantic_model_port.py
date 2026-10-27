from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..platform.model_execution_profiles import ResolvedModelExecution
from ...domain.system_image.semantic_link_input import SemanticLinkInput


SEMANTIC_TIMEOUT_SECONDS = 60
SEMANTIC_MAX_OUTPUT_TOKENS = 8192


@dataclass(frozen=True)
class SemanticModelReply:
    content: str
    input_tokens: int
    output_tokens: int
    usage_source: str


class SemanticModelPort(Protocol):
    async def generate(self, prepared: SemanticLinkInput, model: ResolvedModelExecution) -> SemanticModelReply: ...
