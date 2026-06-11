from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from .agent_runtime_models import (
    AgentGoalProposal,
    ClarificationRequest,
    DirectAnswer,
    OrchestratorDecision,
    ToolInvocationPlan,
    ToolPlanStep,
)
from .models import ConversationMessage, ConversationSession, ToolDefinition


SummaryBuilder = Callable[[ConversationSession], str]
NameExtractor = Callable[[str], str]


@dataclass
class ConversationOrchestrator:
    tools: list[ToolDefinition]
    project_name_extractor: NameExtractor
    version_name_extractor: NameExtractor
    summary_builder: SummaryBuilder

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
            tool_id = "query.knowledge.status"
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

    def _quality_loop_goal(self, conversation: ConversationSession, user_message: str) -> OrchestratorDecision:
        project_id = conversation.project_id or ""
        us_id = conversation.us_id or conversation.space_id
        return OrchestratorDecision(
            kind="agent_goal",
            agent_goal=AgentGoalProposal(
                goal_template="quality_loop",
                title=f"Advance quality loop for {us_id}",
                summary="Drive the current US through the next quality step and keep the user updated with clear progress.",
                goal_description=user_message,
                estimated_steps=4,
                initial_tool_id="quality.scenario.generate",
                initial_tool_input={"project_id": project_id, "us_id": us_id},
                target_refs=[f"project:{project_id}", f"us:{us_id}"],
                query_keys=[["workspace", project_id, us_id], ["conversation", conversation.id]],
                kickoff_message=(
                    f"I'll take over the next quality step for **{us_id}**. I will review the current workspace context, "
                    "generate the scenario pack, observe the result, and then propose the best next action."
                ),
            ),
        )

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

    def _looks_like_quality_goal(self, conversation: ConversationSession, lowered: str, raw: str) -> bool:
        if conversation.space_type != "workspace":
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
