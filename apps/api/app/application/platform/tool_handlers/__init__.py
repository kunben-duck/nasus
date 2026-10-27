"""Compatibility exports without loading every context for a query helper."""
from importlib import import_module


_EXPORT_MODULES = {
    "GovernanceToolHandler": "governance",
    "ProjectVersionToolHandler": "project_version",
    "QualityLoopToolHandler": "quality_loop",
    "QueryToolHandler": "query",
    "SystemImageToolHandler": "system_image",
    "FunctionToolInvocationHandler": "registry",
    "ToolHandlerDependencies": "registry",
    "ToolInvocationHandler": "registry",
    "ToolInvocationHandlerRegistry": "registry",
    "build_tool_handler_registry": "registry",
}

__all__ = [
    "FunctionToolInvocationHandler",
    "GovernanceToolHandler",
    "ProjectVersionToolHandler",
    "QualityLoopToolHandler",
    "QueryToolHandler",
    "SystemImageToolHandler",
    "ToolHandlerDependencies",
    "ToolInvocationHandler",
    "ToolInvocationHandlerRegistry",
    "build_tool_handler_registry",
]


def __getattr__(name):
    module = _EXPORT_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("." + module, __name__), name)
    globals()[name] = value
    return value
