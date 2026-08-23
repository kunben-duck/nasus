from __future__ import annotations

from typing import Protocol, Sequence

from ...domain.platform.prompt_registry import PromptDefinition


class PromptRegistryPort(Protocol):
    def register(self, definition: PromptDefinition) -> None: ...

    def get_active(self, prompt_id: str) -> PromptDefinition: ...

    def get(self, prompt_id: str, version: str) -> PromptDefinition | None: ...

    def list_versions(self, prompt_id: str | None = None) -> list[PromptDefinition]: ...

    def activate(self, prompt_id: str, version: str) -> PromptDefinition: ...


class PromptRegistryApplicationService:
    """Versioned prompt registration and active-version selection."""

    def __init__(self, repository: PromptRegistryPort) -> None:
        self._repository = repository

    def register_defaults(self, definitions: Sequence[PromptDefinition]) -> None:
        for definition in definitions:
            self._repository.register(definition)

    def get_active(self, prompt_id: str) -> PromptDefinition:
        return self._repository.get_active(prompt_id)

    def list_versions(self, prompt_id: str | None = None) -> list[PromptDefinition]:
        return self._repository.list_versions(prompt_id)

    def activate(self, prompt_id: str, version: str) -> PromptDefinition:
        return self._repository.activate(prompt_id, version)


__all__ = ["PromptRegistryApplicationService", "PromptRegistryPort"]
