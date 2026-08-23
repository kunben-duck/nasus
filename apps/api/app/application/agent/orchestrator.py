from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from .agent_models import ConversationMessage, ConversationSession
from ...domain.agent.runtime_models import (
    AgentGoalProposal,
    ClarificationRequest,
    DirectAnswer,
    OrchestratorDecision,
    ToolInvocationPlan,
    ToolPlanStep,
)
from ..platform.tool_models import ToolDefinition


SummaryBuilder = Callable[[ConversationSession], str]
NameExtractor = Callable[[str], str]
QualityStateResolver = Callable[[Optional[str], Optional[str]], dict[str, str]]


def _empty_quality_state_resolver(project_id: Optional[str], us_id: Optional[str]) -> dict[str, str]:
    return {}


@dataclass
class ConversationOrchestrator:
    tools: list[ToolDefinition]
    project_name_extractor: NameExtractor
    version_name_extractor: NameExtractor
    summary_builder: SummaryBuilder
    quality_state_resolver: QualityStateResolver = _empty_quality_state_resolver

    def plan(self, conversation: ConversationSession, user_message: str) -> OrchestratorDecision:
        lowered = user_message.lower()
        last_assistant = self._latest_assistant_message(conversation)
        pending_clarification = (last_assistant.metadata or {}).get("clarification_kind") if last_assistant else None

        if pending_clarification == "project_setup":
            explicit_name = self._extract_explicit_project_name(user_message)
            if explicit_name:
                return self._project_setup_goal(conversation, explicit_name)

        if pending_clarification == "version_setup":
            explicit_name = self._extract_explicit_version_name(user_message)
            if explicit_name:
                return self._version_setup_plan(conversation, explicit_name)

        if pending_clarification == "quality_execution_target":
            return self._quality_loop_goal(
                conversation,
                f"Run the current automation asset against {user_message}",
            )

        if self._looks_like_project_creation(conversation, lowered, user_message):
            explicit_name = self._extract_explicit_project_name(user_message)
            if explicit_name:
                return self._project_setup_goal(conversation, explicit_name)
            return OrchestratorDecision(
                kind="clarification",
                clarification=ClarificationRequest(
                    question=(
                        "I can set up the project for you. Tell me the project name first, then we can connect Git, "
                        "US documents, UX boards, and initialize the Official System Image."
                    ),
                    reason="project_setup",
                    missing_context=["project_name"],
                ),
            )

        if self._looks_like_version_creation(conversation, lowered, user_message):
            explicit_name = self._extract_explicit_version_name(user_message)
            if explicit_name:
                return self._version_setup_plan(conversation, explicit_name)
            return OrchestratorDecision(
                kind="clarification",
                clarification=ClarificationRequest(
                    question=(
                        "I can create the version branch. Tell me the version name or release label you want to use."
                    ),
                    reason="version_setup",
                    missing_context=["version_name"],
                ),
            )

        if self._looks_like_system_image_initialization(conversation, lowered, user_message):
            return self._system_image_initialization_plan(conversation, user_message)

        if self._looks_like_system_image_query(conversation, lowered, user_message):
            return self._system_image_query_plan(conversation)

        if self._looks_like_quality_goal(conversation, lowered, user_message):
            return self._quality_loop_goal(conversation, user_message)

        if self._looks_like_direct_query(conversation, lowered):
            query_plan = self._query_plan_for_space(conversation)
            if query_plan is not None:
                return OrchestratorDecision(kind="tool_plan", tool_plan=query_plan)
            return OrchestratorDecision(
                kind="direct_answer",
                direct_answer=DirectAnswer(
                    fallback_text=self.summary_builder(conversation),
                    query_keys=self._default_query_keys(conversation),
                ),
            )

        return OrchestratorDecision(
            kind="direct_answer",
            direct_answer=DirectAnswer(
                fallback_text=(
                    "I can help you create projects, create version branches, inspect portfolio status, or drive the "
                    "quality loop for the current US. Tell me the outcome you want and I will plan the next action."
                ),
                query_keys=self._default_query_keys(conversation),
            ),
        )

    def _query_plan_for_space(self, conversation: ConversationSession) -> ToolInvocationPlan | None:
        tool_id: str | None = None
        input_payload: dict[str, str] = {}

        if conversation.space_type == "dashboard":
            tool_id = "query.dashboard.progress"
        elif conversation.space_type == "project":
            tool_id = "query.project.status"
            input_payload = {"project_id": conversation.project_id or conversation.space_id}
        elif conversation.space_type == "version":
            tool_id = "query.version.status"
            input_payload = {
                "project_id": conversation.project_id or conversation.space_id,
                "version_id": conversation.version_id or conversation.space_id,
            }
        elif conversation.space_type == "workspace":
            tool_id = "query.workspace.status"
            input_payload = {
                "project_id": conversation.project_id or "",
                "us_id": conversation.us_id or conversation.space_id,
            }
        elif conversation.space_type == "knowledge":
            tool_id = "query.system_image.status"
            input_payload = {"project_id": conversation.project_id or conversation.space_id}
        elif conversation.space_type == "runs":
            tool_id = "query.run.status"
            input_payload = {"project_id": conversation.project_id or conversation.space_id}
        elif conversation.space_type == "governance":
            tool_id = "query.governance.status"
            input_payload = {"project_id": conversation.project_id or conversation.space_id}

        if not tool_id or not any(tool.tool_id == tool_id for tool in self.tools):
            return None

        return ToolInvocationPlan(
            intent_kind=f"{conversation.space_type}_query",
            confidence=0.86,
            steps=[
                ToolPlanStep(
                    tool_id=tool_id,
                    input_payload=input_payload,
                    reason="Query the canonical domain state for the current space and summarize the next action.",
                )
            ],
            recommended_next_tools=["quality.scenario.generate"] if conversation.space_type == "workspace" else [],
        )

    def _project_setup_goal(self, conversation: ConversationSession, project_name: str) -> OrchestratorDecision:
        return OrchestratorDecision(
            kind="agent_goal",
            agent_goal=AgentGoalProposal(
                goal_template="project_setup",
                title=f"Create project {project_name}",
                summary="Set up a new project shell and guide the user into source import and system image initialization.",
                goal_description=f"Create a new project named {project_name} and prepare the next setup steps.",
                estimated_steps=3,
                initial_tool_id="project.create",
                initial_tool_input={"name": project_name},
                target_refs=[f"space:{conversation.space_type}:{conversation.space_id}"],
                query_keys=[["build"], ["dashboard"], ["welcome"], ["projects"]],
                kickoff_message=(
                    f"I'll create **{project_name}** as a draft project, then I will guide the next setup steps for "
                    "Git, US documents, UX assets, and Official System Image initialization."
                ),
            ),
        )

    def _version_setup_plan(self, conversation: ConversationSession, version_name: str) -> OrchestratorDecision:
        project_id = conversation.project_id or conversation.space_id
        return OrchestratorDecision(
            kind="tool_plan",
            tool_plan=ToolInvocationPlan(
                intent_kind="version_setup",
                confidence=0.91,
                steps=[
                    ToolPlanStep(
                        tool_id="version.create",
                        input_payload={"project_id": project_id, "name": version_name},
                        reason="Create a version branch in the current project context.",
                    )
                ],
                recommended_next_tools=["quality.scenario.generate"],
            ),
        )

    def _system_image_initialization_plan(self, conversation: ConversationSession, user_message: str) -> OrchestratorDecision:
        project_id = conversation.project_id or conversation.space_id
        if conversation.space_type not in {"project", "knowledge"} or not project_id:
            return OrchestratorDecision(
                kind="clarification",
                clarification=ClarificationRequest(
                    question="Tell me which project should receive the Official System Image baseline.",
                    reason="system_image_initialization",
                    missing_context=["project_id"],
                ),
            )

        source_specs = self._extract_system_image_source_specs(user_message)
        register_input: dict[str, object] = {"project_id": project_id}
        if source_specs:
            register_input["source_specs"] = source_specs

        planned_tools = [
            ToolPlanStep(
                tool_id="system_image.sources.register",
                input_payload=register_input,
                reason=(
                    "Register the explicit source references provided by the user."
                    if source_specs
                    else "Register the required code source and any optional historical US documents or test assets."
                ),
            ),
            ToolPlanStep(
                tool_id="system_image.sources.ingest",
                input_payload={"project_id": project_id},
                reason="Ingest and index the registered sources so downstream context assembly has evidence refs.",
            ),
            ToolPlanStep(
                tool_id="system_image.context.materialize",
                input_payload={"project_id": project_id},
                reason="Materialize context objects, relationships, overlays, and quality metric snapshots.",
            ),
            ToolPlanStep(
                tool_id="system_image.baseline.initialize",
                input_payload={"project_id": project_id},
                reason="Promote the materialized context into the initial Official System Image baseline.",
            ),
        ]
        return OrchestratorDecision(
            kind="agent_goal",
            agent_goal=AgentGoalProposal(
                goal_template="system_image_build",
                title="Build Official System Image",
                summary="Build the project baseline from code and any optional historical US documents or test assets.",
                goal_description="Register sources, ingest evidence, materialize context, and initialize the baseline.",
                suggested_autonomy_level="semi_auto",
                estimated_steps=len(planned_tools) * 2 + 2,
                planned_tools=planned_tools,
                initial_tool_id=planned_tools[0].tool_id,
                initial_tool_input=planned_tools[0].input_payload,
                target_refs=[f"project:{project_id}", f"system-image:{project_id}"],
                query_keys=[["project", project_id], ["system-image", project_id], ["knowledge", project_id]],
                kickoff_message=(
                    "I will build the Official System Image as a multi-step agent goal: register source groups, "
                    "ingest available code/US/test evidence, materialize context, and then initialize the baseline."
                    + (
                        " I found explicit source references in your message and will bind them to the first tool call."
                        if source_specs
                        else ""
                    )
                ),
            ),
        )

    def _system_image_query_plan(self, conversation: ConversationSession) -> OrchestratorDecision:
        project_id = conversation.project_id or conversation.space_id
        return OrchestratorDecision(
            kind="tool_plan",
            tool_plan=ToolInvocationPlan(
                intent_kind="system_image_query",
                confidence=0.88,
                steps=[
                    ToolPlanStep(
                        tool_id="query.system_image.status",
                        input_payload={"project_id": project_id},
                        reason="Summarize source freshness, baseline readiness, relationships, and quality metrics.",
                    )
                ],
                recommended_next_tools=["system_image.baseline.initialize"] if conversation.space_type == "project" else [],
            ),
        )

    def _quality_loop_goal(self, conversation: ConversationSession, user_message: str) -> OrchestratorDecision:
        project_id = conversation.project_id or (conversation.space_id if conversation.space_type == "project" else "")
        us_id = conversation.us_id or (conversation.space_id if conversation.space_type == "workspace" else "")
        quality_state = self.quality_state_resolver(project_id or None, us_id or None)
        project_id = quality_state.get("project_id") or project_id
        us_id = quality_state.get("us_id") or us_id
        subject = us_id or project_id or "current project"
        planned_tools = self._quality_steps_for_request(user_message, project_id, us_id, quality_state)
        if not planned_tools:
            return OrchestratorDecision(
                kind="clarification",
                clarification=ClarificationRequest(
                    question=(
                        "The generated automation asset is ready to run. Provide the target environment URL "
                        "(for example, https://staging.example.com) so I can start governed execution."
                    ),
                    reason="quality_execution_target",
                    missing_context=["base_url"],
                ),
            )
        return OrchestratorDecision(
            kind="agent_goal",
            agent_goal=AgentGoalProposal(
                goal_template="quality_loop",
                title=f"Advance quality loop for {subject}",
                summary=(
                    "Drive the current US through generated quality assets, governed automation execution, "
                    "and release readiness."
                ),
                goal_description=user_message,
                estimated_steps=len(planned_tools) * 2 + 2,
                planned_tools=planned_tools,
                initial_tool_id=planned_tools[0].tool_id,
                initial_tool_input=planned_tools[0].input_payload,
                target_refs=[f"project:{project_id}"] + ([f"us:{us_id}"] if us_id else []),
                query_keys=[["project", project_id], ["conversation", conversation.id]]
                + ([["workspace", project_id, us_id]] if project_id and us_id else []),
                kickoff_message=(
                    f"I'll take over the quality loop for **{subject}**. I will continue from "
                    f"**{planned_tools[0].tool_id}** through the canonical tool chain."
                ),
            ),
        )

    def _quality_steps_for_request(
        self,
        user_message: str,
        project_id: str,
        us_id: str,
        quality_state: dict[str, str],
    ) -> list[ToolPlanStep]:
        requested_step = self._requested_quality_step(user_message)
        full_loop = self._requests_full_quality_loop(user_message)
        start_step = self._first_incomplete_quality_step(quality_state) if full_loop else (
            requested_step or self._first_incomplete_quality_step(quality_state)
        )
        step_order = [
            "scope",
            "scenarios",
            "verification_plan",
            "cases",
            "automation",
            "execution",
            "change_document",
            "release",
        ]
        start_index = step_order.index(start_step)
        selected_steps = step_order[start_index:] if full_loop or requested_step is None else [start_step]
        base_url = self._extract_target_base_url(user_message)
        if "execution" in selected_steps and not base_url:
            selected_steps = selected_steps[: selected_steps.index("execution")]
        return [
            self._quality_tool_step(step, project_id, us_id, base_url=base_url)
            for step in selected_steps
        ]

    @staticmethod
    def _quality_tool_step(
        step: str,
        project_id: str,
        us_id: str,
        *,
        base_url: str | None = None,
    ) -> ToolPlanStep:
        payload = {"project_id": project_id, "us_id": us_id}
        if base_url:
            payload["base_url"] = base_url
        if step == "scope":
            return ToolPlanStep(
                tool_id="quality.scope.generate",
                input_payload=payload,
                reason="Generate a traceable risk-based scope from the current system image and US context.",
            )
        if step == "scenarios":
            return ToolPlanStep(
                tool_id="quality.scenario.generate",
                input_payload=payload,
                reason="Generate risk-based scenario coverage from the current system image and US context.",
            )
        if step == "verification_plan":
            return ToolPlanStep(
                tool_id="quality.plan.generate",
                input_payload=payload,
                reason="Plan priorities, environments, data, execution allocation, performance checks, and approvals.",
            )
        if step == "cases":
            return ToolPlanStep(
                tool_id="quality.case.generate",
                input_payload=payload,
                reason="Turn approved scenario coverage into structured cases with assertions and data hints.",
            )
        if step == "automation":
            return ToolPlanStep(
                tool_id="automation.generate",
                input_payload=payload,
                reason="Generate a versioned, reviewable automation asset from approved cases without executing it.",
            )
        if step == "execution":
            return ToolPlanStep(
                tool_id="run.start",
                input_payload=payload,
                reason="Execute a selected script from the current automation asset against the supplied target URL.",
            )
        if step == "change_document":
            return ToolPlanStep(
                tool_id="quality.change-doc.generate",
                input_payload=payload,
                reason="Consolidate requirement, code, system-image, quality-asset, risk, and execution evidence deltas.",
            )
        return ToolPlanStep(
            tool_id="release.assess",
            input_payload=payload,
            reason="Score release readiness from approved assets, execution evidence, and governance state.",
        )

    @staticmethod
    def _requested_quality_step(user_message: str) -> str | None:
        lowered = user_message.lower()
        if any(token in lowered for token in ["release", "readiness", "放行"]):
            return "release"
        if any(token in lowered for token in ["change document", "change doc", "变更文档", "变更方案"]):
            return "change_document"
        if any(token in lowered for token in ["execute", "execution", "run", "执行", "运行"]):
            return "execution"
        if any(token in lowered for token in ["automation", "script", "自动化", "脚本"]):
            return "automation"
        if any(token in lowered for token in ["case", "用例"]):
            return "cases"
        if any(token in lowered for token in ["verification plan", "test plan", "验证计划", "测试计划"]):
            return "verification_plan"
        if any(token in lowered for token in ["scope", "范围"]):
            return "scope"
        if any(token in lowered for token in ["scenario", "场景"]):
            return "scenarios"
        return None

    @staticmethod
    def _requests_full_quality_loop(user_message: str) -> bool:
        lowered = user_message.lower()
        return any(token in lowered for token in ["complete", "continue", "quality loop", "end-to-end", "闭环", "完成", "继续"])

    @staticmethod
    def _first_incomplete_quality_step(quality_state: dict[str, str]) -> str:
        complete_statuses = {"approved", "completed"}
        if quality_state.get("scope") not in {"ready_for_review", *complete_statuses}:
            return "scope"
        if quality_state.get("scenarios") not in complete_statuses:
            return "scenarios"
        if quality_state.get("verification_plan") not in complete_statuses:
            return "verification_plan"
        if quality_state.get("cases") not in complete_statuses:
            return "cases"
        if quality_state.get("automation") not in {"ready_for_review", "approved", "completed"}:
            return "automation"
        if quality_state.get("automation") != "completed":
            return "execution"
        if quality_state.get("change_document") not in complete_statuses:
            return "change_document"
        return "release"

    @staticmethod
    def _extract_target_base_url(user_message: str) -> str | None:
        match = re.search(r"https?://[^\s<>{}\[\]\"]+", user_message, flags=re.IGNORECASE)
        if match is None:
            return None
        return match.group(0).rstrip(".,;:!?)]}'")

    def _default_query_keys(self, conversation: ConversationSession) -> list[list[str]]:
        keys: list[list[str]] = [["conversation", conversation.id]]
        if conversation.space_type == "welcome":
            keys.append(["welcome"])
        if conversation.space_type == "build":
            keys.extend([["build"], ["projects"]])
        if conversation.space_type == "dashboard":
            keys.append(["dashboard"])
        if conversation.project_id:
            keys.append(["project", conversation.project_id])
        if conversation.space_type == "workspace" and conversation.project_id and conversation.us_id:
            keys.append(["workspace", conversation.project_id, conversation.us_id])
        return keys

    def _looks_like_project_creation(self, conversation: ConversationSession, lowered: str, raw: str) -> bool:
        if conversation.space_type not in {"build", "welcome"}:
            return False
        return any(
            needle in lowered
            for needle in ["create project", "new project", "set up project", "project setup"]
        ) or "创建" in raw and "项目" in raw

    def _looks_like_version_creation(self, conversation: ConversationSession, lowered: str, raw: str) -> bool:
        if conversation.space_type not in {"project", "version"}:
            return False
        return any(
            needle in lowered
            for needle in ["create version", "new version", "version branch", "release branch"]
        ) or "版本" in raw

    def _looks_like_system_image_initialization(self, conversation: ConversationSession, lowered: str, raw: str) -> bool:
        if conversation.space_type not in {"project", "knowledge"}:
            return False
        return (
            any(
                needle in lowered
                for needle in ["initialize system image", "init system image", "build baseline", "initialize baseline"]
            )
            or ("initialize" in lowered and ("system image" in lowered or "baseline" in lowered))
            or ("build" in lowered and "system image" in lowered)
            or ("初始化" in raw and ("系统画像" in raw or "基线" in raw))
            or ("构建" in raw and "系统画像" in raw)
        )

    def _looks_like_system_image_query(self, conversation: ConversationSession, lowered: str, raw: str) -> bool:
        if conversation.space_type not in {"project", "knowledge"}:
            return False
        return (
            any(needle in lowered for needle in ["system image", "baseline", "knowledge state", "source freshness"])
            or "系统画像" in raw
            or "基线" in raw
        )

    def _looks_like_quality_goal(self, conversation: ConversationSession, lowered: str, raw: str) -> bool:
        if conversation.space_type not in {"workspace", "project"}:
            return False
        quality_needles = [
            "quality loop",
            "scenario",
            "case generation",
            "test case",
            "automation",
            "test plan",
            "continue",
            "complete",
        ]
        return any(needle in lowered for needle in quality_needles) or any(
            token in raw for token in ["闭环", "场景", "测试", "用例", "自动化", "计划"]
        )

    def _looks_like_direct_query(self, conversation: ConversationSession, lowered: str) -> bool:
        if conversation.space_type in {"dashboard", "project", "version", "knowledge", "runs", "governance", "documentation"}:
            return True
        query_needles = ["status", "progress", "risk", "show", "view", "what", "summary", "health", "进度", "状态", "风险"]
        return any(needle in lowered for needle in query_needles)

    @staticmethod
    def _latest_assistant_message(conversation: ConversationSession) -> Optional[ConversationMessage]:
        for message in reversed(conversation.messages):
            if message.role == "assistant":
                return message
        return None

    def _extract_explicit_project_name(self, content: str) -> Optional[str]:
        quoted = re.search(r"['\"]([^'\"]+)['\"]", content)
        if quoted:
            return quoted.group(1).strip()
        chinese_named = re.search(r"(?:名字叫|叫做|名为)([^，。,\\n]+)", content)
        if chinese_named:
            return chinese_named.group(1).strip()
        english_named = re.search(r"(?:project(?: called| named)?|call it)\s+([A-Za-z0-9][A-Za-z0-9 _-]+)", content, re.IGNORECASE)
        if english_named:
            value = english_named.group(1).strip()
            if len(value) >= 2:
                return value
        plain = content.strip()
        if 1 < len(plain) <= 60 and not any(token in plain.lower() for token in ["http://", "https://", "git@", "create", "project", "版本", "项目"]):
            return plain
        return None

    def _extract_explicit_version_name(self, content: str) -> Optional[str]:
        quoted = re.search(r"['\"]([^'\"]+)['\"]", content)
        if quoted:
            return quoted.group(1).strip()
        chinese_named = re.search(r"(?:版本(?:叫|名为)?|分支(?:叫|名为)?)([^，。,\\n]+)", content)
        if chinese_named:
            return chinese_named.group(1).strip()
        english_named = re.search(r"(?:version(?: called| named| branch)?|release(?: branch)?)\s+([A-Za-z0-9._ -]+)", content, re.IGNORECASE)
        if english_named:
            value = english_named.group(1).strip()
            if len(value) >= 2:
                return value
        plain = content.strip()
        if 1 < len(plain) <= 40 and not any(token in plain.lower() for token in ["create", "version", "branch", "project"]):
            return plain
        return None

    @classmethod
    def _extract_system_image_source_specs(cls, content: str) -> list[dict[str, str]]:
        source_label_groups: dict[str, list[str]] = {
            "code": ["code", "repo", "repository", "git", "source code", "代码", "代码库", "仓库"],
            "us_doc": ["us", "us docs", "us doc", "story docs", "requirements", "需求", "需求文档", "US文档", "用户故事"],
            "test_asset": [
                "tests",
                "test",
                "test assets",
                "test cases",
                "automation scripts",
                "测试",
                "测试资产",
                "测试用例",
                "自动化脚本",
                "脚本",
            ],
        }
        specs_by_type: dict[str, dict[str, str]] = {}
        for source_type, labels in source_label_groups.items():
            label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
            pattern = re.compile(
                rf"(?:^|[\s,，;；])"
                rf"(?:{label_pattern})"
                rf"(?:\s*(?:path|dir|directory|url|uri|地址|路径|目录|位置|为|是|在))?"
                rf"\s*(?:=|:|：|->|=>)?\s*"
                rf"(?P<uri>(?:file://|https?://|ssh://|s3://|local-object://|git@|/|~|\.\.?/)[^\s,，;；]+)",
                re.IGNORECASE,
            )
            match = pattern.search(content)
            if not match:
                continue
            uri = cls._clean_source_uri(match.group("uri"))
            if uri:
                specs_by_type[source_type] = {"source_type": source_type, "source_uri": uri}

        return [specs_by_type[source_type] for source_type in ["code", "us_doc", "test_asset"] if source_type in specs_by_type]

    @staticmethod
    def _clean_source_uri(uri: str) -> str:
        return uri.strip().rstrip(".,，;；。)]}'\"")
