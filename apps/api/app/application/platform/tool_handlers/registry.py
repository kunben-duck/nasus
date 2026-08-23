from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

from ...agent import AgentApplicationService, AgentReplyApplicationService
from ..governance import GovernanceApplicationService
from ..query_tools import QueryToolApplicationService
from ..tool_invocation_ports import ToolStatusEventPort
from ...quality_loop import ProjectVersionApplicationService, QualityLoopApplicationService
from ...system_image import SystemImageApplicationService
from ..tool_models import ToolInvocation
from .governance import GovernanceToolHandler
from .project_version import ProjectVersionToolHandler
from .quality_loop import QualityLoopToolHandler
from .query import QueryToolHandler
from .system_image import SystemImageToolHandler


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


@dataclass(frozen=True)
class ToolHandlerDependencies:
    project_versions: ProjectVersionApplicationService
    quality_loop: QualityLoopApplicationService
    queries: QueryToolApplicationService
    system_image: SystemImageApplicationService
    governance: GovernanceApplicationService
    tool_invocations: ToolStatusEventPort
    agent_replies: AgentReplyApplicationService
    agent: AgentApplicationService


def build_tool_handler_registry(dependencies: ToolHandlerDependencies) -> ToolInvocationHandlerRegistry:
    registry = ToolInvocationHandlerRegistry()
    project_version_handler = ProjectVersionToolHandler(
        dependencies.project_versions,
        dependencies.tool_invocations,
        dependencies.agent_replies,
    )
    quality_loop_handler = QualityLoopToolHandler(
        dependencies.quality_loop,
        dependencies.tool_invocations,
        dependencies.agent_replies,
    )
    query_handler = QueryToolHandler(dependencies.queries, dependencies.tool_invocations)
    system_image_handler = SystemImageToolHandler(
        dependencies.system_image,
        dependencies.tool_invocations,
        dependencies.agent_replies,
        dependencies.agent,
    )
    governance_handler = GovernanceToolHandler(dependencies.governance, dependencies.tool_invocations)

    registry.register("project.create", FunctionToolInvocationHandler(project_version_handler.create_project))
    registry.register("project.assets.connect", FunctionToolInvocationHandler(project_version_handler.connect_project_assets))
    registry.register("version.create", FunctionToolInvocationHandler(project_version_handler.create_version))
    registry.register("version.inputs.import", FunctionToolInvocationHandler(project_version_handler.import_version_inputs))
    registry.register("version.branch.bind", FunctionToolInvocationHandler(project_version_handler.bind_version_branch))
    registry.register("version.participants.assign", FunctionToolInvocationHandler(project_version_handler.assign_version_participants))
    registry.register("version.risk.initialize", FunctionToolInvocationHandler(project_version_handler.initialize_version_risk))
    registry.register("us.task.start", FunctionToolInvocationHandler(project_version_handler.start_us_task))
    registry.register("quality.scope.generate", FunctionToolInvocationHandler(quality_loop_handler.generate_scope))
    registry.register("quality.scenario.generate", FunctionToolInvocationHandler(quality_loop_handler.generate_scenarios))
    registry.register("quality.plan.generate", FunctionToolInvocationHandler(quality_loop_handler.generate_plan))
    registry.register("quality.case.generate", FunctionToolInvocationHandler(quality_loop_handler.generate_cases))
    registry.register("quality.asset-pack.refresh", FunctionToolInvocationHandler(quality_loop_handler.refresh_asset_pack))
    registry.register("automation.generate", FunctionToolInvocationHandler(quality_loop_handler.generate_automation))
    registry.register("quality.change-doc.generate", FunctionToolInvocationHandler(quality_loop_handler.generate_change_document))
    registry.register("run.start", FunctionToolInvocationHandler(quality_loop_handler.start_run))
    registry.register("run.retry", FunctionToolInvocationHandler(quality_loop_handler.retry_run))
    registry.register("failure.analyze", FunctionToolInvocationHandler(quality_loop_handler.analyze_failure))
    registry.register("healing.propose", FunctionToolInvocationHandler(quality_loop_handler.propose_healing))
    registry.register("release.advice.get", FunctionToolInvocationHandler(quality_loop_handler.get_release_advice))
    registry.register("release.assess", FunctionToolInvocationHandler(quality_loop_handler.assess_release))
    registry.register("approval.request", FunctionToolInvocationHandler(governance_handler.request_approval))
    registry.register("approval.decide", FunctionToolInvocationHandler(governance_handler.decide_approval))
    registry.register("resolution.merge", FunctionToolInvocationHandler(governance_handler.merge_resolution))
    registry.register("release.decision.submit", FunctionToolInvocationHandler(governance_handler.submit_release_decision))
    registry.register("baseline.promote", FunctionToolInvocationHandler(governance_handler.promote_baseline))
    registry.register("system_image.baseline.initialize", FunctionToolInvocationHandler(system_image_handler.initialize_baseline))
    registry.register("system_image.sources.register", FunctionToolInvocationHandler(system_image_handler.register_sources))
    registry.register("system_image.sources.ingest", FunctionToolInvocationHandler(system_image_handler.ingest_sources))
    registry.register("system_image.context.materialize", FunctionToolInvocationHandler(system_image_handler.materialize_context))
    for tool_id in (
        "project.status.get",
        "version.progress.get",
        "run.progress.get",
        "us.status.get",
        "progress.get",
        "risk.summary.get",
        "system-image.inspect",
        "conflicts.get",
    ):
        registry.register(tool_id, FunctionToolInvocationHandler(query_handler.handle))
    registry.register_prefix("query.", FunctionToolInvocationHandler(query_handler.handle))
    return registry
