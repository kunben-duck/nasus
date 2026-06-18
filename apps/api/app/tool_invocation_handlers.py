from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable, Protocol

from .models import ToolInvocation
from .project_version_tool_handlers import ProjectVersionToolHandler
from .quality_loop_tool_handlers import QualityLoopToolHandler
from .query_tool_handlers import QueryToolHandler
from .system_image_tool_handlers import SystemImageToolHandler

if TYPE_CHECKING:
    from .store import ApplicationStore


class ToolInvocationHandler(Protocol):
    async def handle(self, invocation: ToolInvocation) -> None:
        ...


@dataclass(frozen=True)
class FunctionToolInvocationHandler:
    fn: Callable[[ToolInvocation], Awaitable[None]]

    async def handle(self, invocation: ToolInvocation) -> None:
        await self.fn(invocation)


@dataclass
class ToolInvocationHandlerRegistry:
    exact_handlers: dict[str, ToolInvocationHandler] = field(default_factory=dict)
    prefix_handlers: list[tuple[str, ToolInvocationHandler]] = field(default_factory=list)

    def register(self, tool_id: str, handler: ToolInvocationHandler) -> None:
        self.exact_handlers[tool_id] = handler

    def register_prefix(self, prefix: str, handler: ToolInvocationHandler) -> None:
        self.prefix_handlers.append((prefix, handler))

    def resolve(self, tool_id: str) -> ToolInvocationHandler | None:
        exact = self.exact_handlers.get(tool_id)
        if exact is not None:
            return exact
        for prefix, handler in self.prefix_handlers:
            if tool_id.startswith(prefix):
                return handler
        return None


def build_store_tool_handler_registry(store: "ApplicationStore") -> ToolInvocationHandlerRegistry:
    registry = ToolInvocationHandlerRegistry()
    project_version_handler = ProjectVersionToolHandler(store)
    quality_loop_handler = QualityLoopToolHandler(store)
    query_handler = QueryToolHandler(store)
    system_image_handler = SystemImageToolHandler(store)

    registry.register("project.create", FunctionToolInvocationHandler(project_version_handler.create_project))
    registry.register("version.create", FunctionToolInvocationHandler(project_version_handler.create_version))
    registry.register("quality.scenario.generate", FunctionToolInvocationHandler(quality_loop_handler.generate_scenarios))
    registry.register("system_image.baseline.initialize", FunctionToolInvocationHandler(system_image_handler.initialize_baseline))
    registry.register("system_image.sources.register", FunctionToolInvocationHandler(system_image_handler.register_sources))
    registry.register("system_image.sources.ingest", FunctionToolInvocationHandler(system_image_handler.ingest_sources))
    registry.register("system_image.context.materialize", FunctionToolInvocationHandler(system_image_handler.materialize_context))
    registry.register_prefix("query.", FunctionToolInvocationHandler(query_handler.handle))
    return registry
