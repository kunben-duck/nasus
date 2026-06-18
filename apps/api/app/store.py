from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .agent_loop_runtime import AgentLoopRuntime
from .agent_memory import AgentMemoryManager, memory_context_hash, memory_context_summary
from .agent_planner import DeterministicAgentPlanner, LLMStructuredAgentPlanner
from .agent_service import AgentService
from .agent_swarm import AgentSwarmCoordinator
from .agent_workflow_runtime import build_agent_workflow_runtime
from .database import init_database
from .llm import LLMGateway
from .models import (
    AgentGoal,
    AgentGoalCreateRequest,
    AgentSwarmRun,
    AgentStep,
    ApprovalDetail,
    ApprovalSummary,
    AuditEvent,
    AssetLane,
    BaselineRecord,
    BuildResponse,
    ConversationArchiveRequest,
    ConversationLink,
    ConversationMessage,
    ConversationMergeRequest,
    ConversationSession,
    ConversationSummaryCheckpoint,
    ContextObjectOverlay,
    ContextRelationship,
    DashboardResponse,
    DocumentationEntry,
    EventPayload,
    KnowledgeObject,
    MessageBlock,
    ProjectCard,
    ProjectWorkspaceResponse,
    QualityMetricSnapshot,
    RawAssetRecord,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    SessionKnowledgeBinding,
    CustomModelConfig,
    StudioSettings,
    StudioSettingsConnectionTestRequest,
    StudioSettingsConnectionTestResponse,
    StudioSettingsPatch,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationRequest,
    ToolResult,
    UserProfile,
    USItem,
    SystemImageResponse,
    VersionSummary,
    WelcomeResponse,
)
from .repositories import ConversationRepository, ProjectRepository, SettingsRepository
from .settings_store import SettingsPersistence
from .system_image_service import SystemImageService
from .system_image_tool_catalog import system_image_tool_definitions
from .tool_governance import ToolGovernance
from .tool_invocation_runtime import ToolInvocationRuntime


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


class ApplicationStore:
    def __init__(self) -> None:
        init_database()
        self.user = UserProfile(
            id="user_001",
            name="Uben",
            email="uben@example.com",
            role="platform_admin",
        )
        self.llm = LLMGateway()
        self.settings_repository = SettingsRepository()
        self.conversation_repository = ConversationRepository()
        self.project_repository = ProjectRepository()
        self.settings_persistence = SettingsPersistence()
        self.tool_governance = ToolGovernance()
        persisted_settings, persisted_custom_keys = self.settings_repository.load()
        self.settings = self.llm.build_settings(
            language=persisted_settings["language"],
            theme=persisted_settings["theme"],
            notification_mode=persisted_settings["notification_mode"],
            model_preset=persisted_settings["model_preset"],
            custom_model=CustomModelConfig(**persisted_settings["custom_model"]),
            model_profiles=persisted_settings.get("model_profiles"),
        )
        self.custom_model_api_keys_encrypted = dict(persisted_custom_keys)
        self.custom_model_api_key_encrypted = self.custom_model_api_keys_encrypted.get("chat", "")
        self.tools = [
            ToolDefinition(
                tool_id="project.create",
                label="Create Project",
                tool_kind="project",
                scope="central",
                risk_level="medium",
                confirmation_mode="none",
                description="Create a project draft and prepare system image initialization.",
                required_context=["project_name", "git_repo", "us_docs"],
                produced_objects=["Project", "ConversationSession"],
            ),
            ToolDefinition(
                tool_id="version.create",
                label="Create Version",
                tool_kind="version",
                scope="central",
                risk_level="medium",
                confirmation_mode="none",
                description="Fork a working version branch from the current project baseline.",
                required_context=["project_id", "version_name"],
                produced_objects=["Version"],
            ),
            ToolDefinition(
                tool_id="quality.scenario.generate",
                label="Generate Scenarios",
                tool_kind="analysis",
                scope="either",
                risk_level="low",
                confirmation_mode="none",
                description="Generate structured test scenarios for the selected US.",
                required_context=["project_id", "us_id"],
                produced_objects=["QualityAssetPack", "AgentGoal"],
            ),
            ToolDefinition(
                tool_id="query.dashboard.progress",
                label="Check Portfolio Progress",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Summarize overall project, version, execution, and approval progress from the dashboard.",
                required_context=[],
                produced_objects=["ConversationSession"],
            ),
            ToolDefinition(
                tool_id="query.project.status",
                label="Check Project Status",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Summarize project health, active version, and system image readiness.",
                required_context=["project_id"],
                produced_objects=["ConversationSession"],
            ),
            ToolDefinition(
                tool_id="query.version.status",
                label="Check Version Status",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Summarize version closure, blockers, and remaining quality work.",
                required_context=["project_id", "version_id"],
                produced_objects=["ConversationSession"],
            ),
            ToolDefinition(
                tool_id="query.workspace.status",
                label="Check Workspace Status",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Summarize the current US workspace, asset lanes, and the best next action.",
                required_context=["project_id", "us_id"],
                produced_objects=["ConversationSession"],
            ),
            ToolDefinition(
                tool_id="query.run.status",
                label="Check Run Status",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Explain current run health, failures, and suggested next action.",
                required_context=["project_id"],
                produced_objects=["ConversationSession"],
            ),
            ToolDefinition(
                tool_id="query.governance.status",
                label="Check Governance Queue",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Summarize approvals, merge pressure, and release blockers.",
                required_context=["project_id"],
                produced_objects=["ConversationSession"],
            ),
            ToolDefinition(
                tool_id="query.knowledge.status",
                label="Check Knowledge State",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Summarize the system image branch state and knowledge hotspots for a project.",
                required_context=["project_id"],
                produced_objects=["ConversationSession"],
            ),
            ToolDefinition(
                tool_id="query.system_image.status",
                label="Check System Image",
                tool_kind="query",
                scope="central",
                risk_level="low",
                confirmation_mode="none",
                description="Summarize source freshness, baseline readiness, relationships, and quality metric snapshots.",
                required_context=["project_id"],
                produced_objects=["ConversationSession"],
            ),
        ]
        self.tools.extend(system_image_tool_definitions())
        deterministic_planner = DeterministicAgentPlanner.build(
            tools=self.tools,
            project_name_extractor=self._extract_project_name,
            version_name_extractor=self._extract_version_name,
            summary_builder=self._conversation_summary_fallback,
        )
        self.planner = LLMStructuredAgentPlanner(
            fallback=deterministic_planner,
            llm=self.llm,
            tools=self.tools,
            settings_provider=self.get_settings,
            custom_api_key_provider=self._get_custom_model_api_key,
            memory_context_builder=self._planner_memory_context,
        )
        self.agent_loop_runtime = AgentLoopRuntime(self)
        self.agent_workflow_runtime = build_agent_workflow_runtime(self.agent_loop_runtime)
        self.projects: Dict[str, ProjectCard] = {}
        self.versions: Dict[str, List[VersionSummary]] = defaultdict(list)
        self.us_items: Dict[str, List[USItem]] = defaultdict(list)
        self.asset_lanes: Dict[str, List[AssetLane]] = defaultdict(list)
        self.runs: Dict[str, List[RunSummary]] = defaultdict(list)
        self.run_details: Dict[str, RunDetail] = {}
        self.approvals: Dict[str, List[ApprovalSummary]] = defaultdict(list)
        self.approval_details: Dict[str, ApprovalDetail] = {}
        self.knowledge_objects: Dict[str, List[KnowledgeObject]] = defaultdict(list)
        self.raw_assets: Dict[str, List[RawAssetRecord]] = defaultdict(list)
        self.baselines: Dict[str, List[BaselineRecord]] = defaultdict(list)
        self.context_relationships: Dict[str, List[ContextRelationship]] = defaultdict(list)
        self.context_object_overlays: Dict[str, List[ContextObjectOverlay]] = defaultdict(list)
        self.quality_metric_snapshots: Dict[str, List[QualityMetricSnapshot]] = defaultdict(list)
        self.documentation_entries: List[DocumentationEntry] = []
        self.release_readiness: Dict[str, ReleaseReadiness] = {}
        self.conversations: Dict[str, ConversationSession] = {}
        self.conversation_index: Dict[tuple[str, str], str] = {}
        self.conversation_links: Dict[str, ConversationLink] = {}
        self.conversation_summary_checkpoints: Dict[str, ConversationSummaryCheckpoint] = {}
        self.session_knowledge_bindings: Dict[str, SessionKnowledgeBinding] = {}
        self.event_queues: Dict[str, asyncio.Queue[EventPayload]] = {}
        self.agent_goals: Dict[str, AgentGoal] = {}
        self.agent_goal_queues: Dict[str, asyncio.Queue[EventPayload]] = {}
        self.agent_swarms: Dict[str, AgentSwarmRun] = {}
        self.agent_swarm_queues: Dict[str, asyncio.Queue[EventPayload]] = {}
        self.tool_invocations: Dict[str, ToolInvocation] = {}
        self.audit_events: Dict[str, AuditEvent] = {}
        self.entity_versions: Dict[str, int] = defaultdict(int)
        self.agent_memory = AgentMemoryManager(self)
        self.system_image_service = SystemImageService(self)
        self.agent_swarm_coordinator = AgentSwarmCoordinator(self)
        self.tool_invocation_runtime = ToolInvocationRuntime(self)
        self.agent_service = AgentService(self, self.agent_workflow_runtime)
        self._load_persisted_project_state()
        self._load_persisted_runtime_state()
        self._seed()

    def _load_persisted_project_state(self) -> None:
        self.projects = {project.id: project for project in self.project_repository.load_projects()}
        self.versions = defaultdict(list, self.project_repository.load_versions())
        self.us_items = defaultdict(list, self.project_repository.load_us_items())
        self.asset_lanes = defaultdict(list, self.project_repository.load_asset_lanes())
        persisted_runs, self.run_details = self.project_repository.load_runs()
        self.runs = defaultdict(list, persisted_runs)
        persisted_approvals, self.approval_details = self.project_repository.load_approvals()
        self.approvals = defaultdict(list, persisted_approvals)
        self.knowledge_objects = defaultdict(list, self.project_repository.load_knowledge_objects())
        self.raw_assets = defaultdict(list, self.project_repository.load_raw_assets())
        self.baselines = defaultdict(list, self.project_repository.load_baselines())
        self.context_relationships = defaultdict(list, self.project_repository.load_context_relationships())
        self.context_object_overlays = defaultdict(list, self.project_repository.load_context_object_overlays())
        self.quality_metric_snapshots = defaultdict(list, self.project_repository.load_quality_metric_snapshots())
        self.release_readiness = self.project_repository.load_release_readiness()

    def _load_persisted_runtime_state(self) -> None:
        persisted_conversations = self.conversation_repository.load_all()
        self.conversations = {conversation.id: conversation for conversation in persisted_conversations}
        self.conversation_index = {
            (conversation.space_type, conversation.space_id): conversation.id
            for conversation in persisted_conversations
        }
        self.agent_goals = {
            goal.id: goal
            for conversation in persisted_conversations
            for goal in conversation.agent_goals
        }
        self.tool_invocations = {
            invocation.id: invocation
            for invocation in self.conversation_repository.load_tool_invocations()
        }
        self.audit_events = {
            event.id: event
            for event in self.conversation_repository.load_audit_events()
        }
        self.agent_swarms = {
            swarm.id: swarm
            for swarm in self.conversation_repository.load_agent_swarms()
        }
        self.conversation_summary_checkpoints = {
            checkpoint.id: checkpoint
            for checkpoint in self.conversation_repository.load_summary_checkpoints()
        }
        self.session_knowledge_bindings = {
            binding.id: binding
            for binding in self.conversation_repository.load_session_knowledge_bindings()
        }

    def _refresh_project_read_models(self, project_id: str) -> None:
        projects = {project.id: project for project in self.project_repository.load_projects()}
        if project_id in projects:
            self.projects[project_id] = projects[project_id]

        persisted_versions = self.project_repository.load_versions()
        self.versions[project_id] = persisted_versions.get(project_id, [])

        persisted_us_items = self.project_repository.load_us_items()
        self.us_items[project_id] = persisted_us_items.get(project_id, [])

        persisted_asset_lanes = self.project_repository.load_asset_lanes()
        for us_item in self.us_items[project_id]:
            self.asset_lanes[us_item.id] = persisted_asset_lanes.get(us_item.id, [])

        persisted_runs, run_details = self.project_repository.load_runs()
        self.runs[project_id] = persisted_runs.get(project_id, [])
        self.run_details.update(run_details)

        persisted_approvals, approval_details = self.project_repository.load_approvals()
        self.approvals[project_id] = persisted_approvals.get(project_id, [])
        self.approval_details.update(approval_details)

        persisted_knowledge = self.project_repository.load_knowledge_objects()
        self.knowledge_objects[project_id] = persisted_knowledge.get(project_id, [])

        persisted_sources = self.project_repository.load_raw_assets()
        self.raw_assets[project_id] = persisted_sources.get(project_id, [])

        persisted_baselines = self.project_repository.load_baselines()
        self.baselines[project_id] = persisted_baselines.get(project_id, [])

        persisted_relationships = self.project_repository.load_context_relationships()
        self.context_relationships[project_id] = persisted_relationships.get(project_id, [])

        persisted_overlays = self.project_repository.load_context_object_overlays()
        self.context_object_overlays[project_id] = persisted_overlays.get(project_id, [])

        persisted_metrics = self.project_repository.load_quality_metric_snapshots()
        self.quality_metric_snapshots[project_id] = persisted_metrics.get(project_id, [])

        persisted_release_readiness = self.project_repository.load_release_readiness()
        self.release_readiness.update(persisted_release_readiness)

    def _get_or_create_event_queue(self, conversation_id: str) -> asyncio.Queue[EventPayload]:
        queue = self.event_queues.get(conversation_id)
        if queue is None:
            queue = asyncio.Queue()
            self.event_queues[conversation_id] = queue
        return queue

    def _get_or_create_goal_queue(self, goal_id: str) -> asyncio.Queue[EventPayload]:
        queue = self.agent_goal_queues.get(goal_id)
        if queue is None:
            queue = asyncio.Queue()
            self.agent_goal_queues[goal_id] = queue
        return queue

    def _get_or_create_swarm_queue(self, swarm_id: str) -> asyncio.Queue[EventPayload]:
        queue = self.agent_swarm_queues.get(swarm_id)
        if queue is None:
            queue = asyncio.Queue()
            self.agent_swarm_queues[swarm_id] = queue
        return queue

    def _seed(self) -> None:
        project = self.projects.get("proj_payment")
        if project is None:
            project = ProjectCard(
                id="proj_payment",
                name="Payment System",
                code="PAY",
                summary="Agent-first release quality loop for payments and checkout.",
                status="active",
                risk="medium",
                progress=68,
                active_version="2026.Q2",
                blocked_items=2,
                pending_approvals=1,
                system_image_status="ready",
            )
            version = VersionSummary(
                id="ver_payment_q2",
                name="2026.Q2",
                status="active",
                branch_name="release/2026-q2",
                us_total=8,
                us_closed=5,
                pending_runs=2,
                pending_approvals=1,
            )
            us_items = [
                USItem(
                    id="us_123",
                    title="Saved cards checkout flow",
                    owner="Alicia",
                    status="analysis",
                    risk="high",
                    progress=62,
                    next_action="Generate scenarios",
                ),
                USItem(
                    id="us_124",
                    title="Refund status timeline",
                    owner="Ryan",
                    status="execution",
                    risk="medium",
                    progress=81,
                    next_action="Review run failures",
                ),
            ]
            self.projects[project.id] = project
            self.versions[project.id] = [version]
            self.us_items[project.id] = us_items
            self.project_repository.upsert_project(project)
            self.project_repository.replace_versions(project.id, [version])
            self.project_repository.replace_us_items(project.id, version.id, us_items)

        version = self.versions[project.id][0] if self.versions[project.id] else VersionSummary(
            id="ver_payment_q2",
            name="2026.Q2",
            status="active",
            branch_name="release/2026-q2",
            us_total=8,
            us_closed=5,
            pending_runs=2,
            pending_approvals=1,
        )
        us_items = self.us_items[project.id] or [
            USItem(
                id="us_123",
                title="Saved cards checkout flow",
                owner="Alicia",
                status="analysis",
                risk="high",
                progress=62,
                next_action="Generate scenarios",
            ),
            USItem(
                id="us_124",
                title="Refund status timeline",
                owner="Ryan",
                status="execution",
                risk="medium",
                progress=81,
                next_action="Review run failures",
            ),
        ]
        lanes = self.asset_lanes.get("us_123") or [
            AssetLane(
                id="lane_scenarios",
                label="Scenarios",
                status="ready_for_review",
                summary="6 scenario groups covering happy path, fallback, and risk edges.",
                updated_at="2026-03-27 18:20",
            ),
            AssetLane(
                id="lane_cases",
                label="Cases",
                status="drafting",
                summary="12 structured cases in generation progress.",
                updated_at="2026-03-27 18:28",
            ),
            AssetLane(
                id="lane_automation",
                label="Automation",
                status="not_started",
                summary="Waiting for reviewed scenarios.",
                updated_at="2026-03-27 18:28",
            ),
        ]
        runs = self.runs.get(project.id) or [
            RunSummary(
                id="run_9021",
                status="failed",
                channel="web_runner",
                title="Saved cards smoke",
                summary="3 assertions failed after checkout redirect.",
                started_at="2026-03-27 17:50",
            )
        ]
        approvals = self.approvals.get(project.id) or [
            ApprovalSummary(
                id="approval_442",
                title="Scenario pack revision r3",
                status="waiting_approval",
                summary="Scenario baseline promotion is waiting reviewer confirmation.",
            )
        ]
        self.run_details["run_9021"] = self.run_details.get("run_9021") or RunDetail(
            id="run_9021",
            status="failed",
            channel="web_runner",
            title="Saved cards smoke",
            summary="3 assertions failed after checkout redirect.",
            started_at="2026-03-27 17:50",
            timeline=[
                "Queued with checkout regression pack.",
                "Started browser session against release candidate.",
                "Observed redirect mismatch on saved-card confirmation.",
                "Captured trace bundle and DOM snapshot for failure analysis.",
            ],
            evidence=["trace://run_9021", "screenshot://run_9021/step-3", "log://run_9021"],
            failure_summary="The checkout confirm selector changed after the redirect handoff, which broke the post-payment assertion path.",
            healing_status="not_started",
        )
        self.approval_details["approval_442"] = self.approval_details.get("approval_442") or ApprovalDetail(
            id="approval_442",
            title="Scenario pack revision r3",
            status="waiting_approval",
            summary="Scenario baseline promotion is waiting reviewer confirmation.",
            policy_reason="Version Shared promotion is allowed, but Official baseline write-back must remain blocked until release closure.",
            conflict_fields=["scenario_group.payment_recovery", "risk_pattern.checkout_redirect"],
            recommended_resolution="Accept the auto-merge on shared fields and keep the new risk edge candidate version-scoped until release sign-off.",
            evidence=["scenario-pack:r3", "run:run_9021", "policy:baseline_writeback_gate"],
        )
        if not self.knowledge_objects.get(project.id):
            self.knowledge_objects[project.id] = [
                KnowledgeObject(
                    id="OBJ-CHECKOUT",
                    name="Checkout Flow",
                    type="Feature",
                    branch="Version Shared",
                    confidence="0.91",
                    relations=["Payment Gateway App", "Order Summary", "Promo Engine"],
                    evidence=["PR #882", "Scenario Pack r3", "Run-9021"],
                    freshness="12 mins ago",
                ),
                KnowledgeObject(
                    id="OBJ-AUTH",
                    name="Auth Service",
                    type="System",
                    branch="Official",
                    confidence="0.97",
                    relations=["OAuth Callback", "Session Store", "Profile API"],
                    evidence=["System Image", "Legacy Regression Pack"],
                    freshness="1 hr ago",
                ),
                KnowledgeObject(
                    id="OBJ-ASSET",
                    name="Checkout Scenario Pack",
                    type="QualityAssetPack",
                    branch="Candidate",
                    confidence="0.88",
                    relations=["US-123", "Run-9021", "Release Gate"],
                    evidence=["Scenario Set", "Automation Draft"],
                    freshness="5 mins ago",
                ),
            ]
        self.documentation_entries = [
            DocumentationEntry(
                id="DOC-START",
                title="Getting Started",
                copy="How to create a project, connect sources, and initialize the Official System Image.",
                category="Guide",
            ),
            DocumentationEntry(
                id="DOC-BRANCHING",
                title="System Image & Branching",
                copy="Official baseline, version branch overlays, candidate promotion, and baseline write-back.",
                category="Concept",
            ),
            DocumentationEntry(
                id="DOC-ASSET",
                title="Quality Asset Pack",
                copy="How scenarios, scope, plans, cases, automation, performance, and change docs work together.",
                category="Reference",
            ),
        ]
        self.release_readiness[version.id] = self.release_readiness.get(version.id) or ReleaseReadiness(
            version_id=version.id,
            status="Conditionally Ready",
            score=71,
            blockers=3,
            approvals_open=2,
            pending_merge=1,
            execution_health="1 failed run pending review",
            summary="The version is close to release, but one failed run, one pending merge, and open governance items still need resolution.",
            blocker_items=[
                "Saved cards smoke run still failed after redirect.",
                "Scenario pack promotion is waiting approval.",
                "One merge resolution still needs review in governance.",
            ],
        )
        self.asset_lanes["us_123"] = lanes
        self.runs[project.id] = runs
        self.approvals[project.id] = approvals
        self.project_repository.replace_asset_lanes(project.id, "us_123", lanes)
        self.project_repository.replace_runs(project.id, [self.run_details["run_9021"]])
        self.project_repository.replace_approvals(project.id, [self.approval_details["approval_442"]])
        self.project_repository.replace_knowledge_objects(project.id, self.knowledge_objects[project.id])
        self.system_image_service.ensure_state(project.id, ready=True, version_id=version.id)
        self.project_repository.upsert_release_readiness(project.id, self.release_readiness[version.id])
        self.get_or_create_conversation("welcome", "welcome", "Welcome")
        self.get_or_create_conversation("build", "build", "Build")
        self.get_or_create_conversation("dashboard", "dashboard", "Dashboard")
        self.get_or_create_conversation("project", project.id, project.name)
        self.get_or_create_conversation("workspace", "us_123", "US-123 Workspace")

    def get_welcome(self) -> WelcomeResponse:
        recent_conversations = list(self.conversations.values())[:3]
        recent_versions = [version for versions in self.versions.values() for version in versions][:3]
        return WelcomeResponse(
            recent_projects=list(self.projects.values())[:3],
            recent_versions=recent_versions,
            recent_conversations=recent_conversations,
        )

    def get_build(self) -> BuildResponse:
        drafts = [project for project in self.projects.values() if project.status in {"draft", "active"}]
        return BuildResponse(
            drafts=drafts,
            imports_health=["Git reachable", "US parser ready", "UX parser pending optional sources"],
            provider_health="healthy",
        )

    def get_dashboard(self) -> DashboardResponse:
        return DashboardResponse(
            active_projects=len(self.projects),
            running_versions=sum(len(versions) for versions in self.versions.values()),
            blocked_items=sum(project.blocked_items for project in self.projects.values()),
            pending_approvals=sum(project.pending_approvals for project in self.projects.values()),
            failed_runs=sum(1 for runs in self.runs.values() for run in runs if run.status == "failed"),
            projects=list(self.projects.values()),
        )

    def get_settings(self) -> StudioSettings:
        self.settings = self.llm.build_settings(
            language=self.settings.language,
            theme=self.settings.theme,
            notification_mode=self.settings.notification_mode,
            model_preset=self.settings.model_preset,
            custom_model=self._current_custom_model("chat"),
            model_profiles=self._current_model_profiles(),
        )
        return self.settings

    def update_settings(self, payload: StudioSettingsPatch) -> StudioSettings:
        language = payload.language or self.settings.language
        theme = payload.theme or self.settings.theme
        notification_mode = payload.notification_mode or self.settings.notification_mode
        model_route = payload.model_route or "chat"
        profiles = self._current_model_profiles()
        profile = profiles[model_route]
        model_preset = payload.model_preset or profile.model_preset
        custom_model = profile.custom_model.model_copy(deep=True)

        if payload.custom_provider_kind is not None:
            custom_model.provider_kind = payload.custom_provider_kind
        if payload.custom_base_url is not None:
            custom_model.base_url = payload.custom_base_url.strip() or None
        if payload.custom_model_name is not None:
            custom_model.model_name = payload.custom_model_name.strip()
        if payload.custom_api_key is not None:
            raw_api_key = payload.custom_api_key.strip()
            self.custom_model_api_keys_encrypted[model_route] = self.settings_persistence.encrypt_api_key(raw_api_key)
            if model_route == "chat":
                self.custom_model_api_key_encrypted = self.custom_model_api_keys_encrypted.get("chat", "")
            custom_model.has_api_key = bool(raw_api_key)
            custom_model.api_key_masked = self.settings_persistence.mask_api_key(raw_api_key)
        else:
            custom_model.has_api_key = bool(self.custom_model_api_keys_encrypted.get(model_route))
            if not custom_model.has_api_key:
                custom_model.api_key_masked = None

        profile.model_preset = model_preset
        profile.custom_model = custom_model
        profiles[model_route] = profile
        chat_preset = profiles["chat"].model_preset
        self.settings = self.llm.build_settings(
            language=language,
            theme=theme,
            notification_mode=notification_mode,
            model_preset=chat_preset,
            custom_model=profiles["chat"].custom_model,
            model_profiles=profiles,
        )
        self.settings_repository.save(self.settings, self.custom_model_api_keys_encrypted)
        return self.settings

    async def test_settings_connection(
        self,
        payload: Optional[StudioSettingsConnectionTestRequest] = None,
    ) -> StudioSettingsConnectionTestResponse:
        request = payload or StudioSettingsConnectionTestRequest(model_route="chat", model_preset=self.settings.model_preset)
        model_route = request.model_route or "chat"
        profiles = self._current_model_profiles()
        profile = profiles[model_route]
        custom_model = profile.custom_model.model_copy(deep=True)
        if request.custom_provider_kind is not None:
            custom_model.provider_kind = request.custom_provider_kind
        if request.custom_base_url is not None:
            custom_model.base_url = request.custom_base_url.strip() or None
        if request.custom_model_name is not None:
            custom_model.model_name = request.custom_model_name.strip()

        custom_api_key = self._get_custom_model_api_key(model_route)
        if request.custom_api_key is not None:
            custom_api_key = request.custom_api_key.strip()
        custom_model.has_api_key = bool(custom_api_key)
        custom_model.api_key_masked = self.settings_persistence.mask_api_key(custom_api_key)

        profile.model_preset = request.model_preset or profile.model_preset
        profile.custom_model = custom_model
        profiles[model_route] = profile
        settings = self.llm.build_settings(
            language=self.settings.language,
            theme=self.settings.theme,
            notification_mode=self.settings.notification_mode,
            model_preset=profiles["chat"].model_preset,
            custom_model=profiles["chat"].custom_model,
            model_profiles=profiles,
        )
        return await self.llm.test_connection(settings=settings, route=model_route, custom_api_key=custom_api_key)

    def _current_model_profiles(self):
        profiles = self.settings.model_profiles or self.llm.build_model_profiles(
            model_preset=self.settings.model_preset,
            custom_model=self.settings.custom_model,
        )
        refreshed = {}
        for route, profile in profiles.items():
            cloned = profile.model_copy(deep=True)
            cloned.custom_model.has_api_key = bool(self.custom_model_api_keys_encrypted.get(route))
            if not cloned.custom_model.has_api_key:
                cloned.custom_model.api_key_masked = None
            refreshed[route] = cloned
        return refreshed

    def _current_custom_model(self, model_route: str = "chat") -> CustomModelConfig:
        profile = self._current_model_profiles()[model_route]
        custom_model = profile.custom_model.model_copy(deep=True)
        custom_model.has_api_key = bool(self.custom_model_api_keys_encrypted.get(model_route))
        if not custom_model.has_api_key:
            custom_model.api_key_masked = None
        return custom_model

    def _get_custom_model_api_key(self, model_route: str = "chat") -> str:
        try:
            return self.settings_persistence.decrypt_api_key(self.custom_model_api_keys_encrypted.get(model_route, ""))
        except RuntimeError:
            return ""

    def list_projects(self) -> List[ProjectCard]:
        return list(self.projects.values())

    def list_documentation(self) -> List[DocumentationEntry]:
        return self.documentation_entries

    def create_project(self, name: str) -> ProjectCard:
        project_id = f"proj_{_slugify(name)}_{len(self.projects) + 1}"
        project = ProjectCard(
            id=project_id,
            name=name,
            code=name[:3].upper(),
            summary="Newly created project awaiting source imports and system image initialization.",
            status="draft",
            risk="low",
            progress=12,
            active_version="Not started",
            blocked_items=0,
            pending_approvals=0,
            system_image_status="draft",
        )
        self.projects[project.id] = project
        self.versions[project.id] = []
        self.us_items[project.id] = []
        self.runs[project.id] = []
        self.approvals[project.id] = []
        self.knowledge_objects[project.id] = []
        self.project_repository.upsert_project(project)
        self.project_repository.replace_versions(project.id, [])
        self.project_repository.replace_us_items(project.id, None, [])
        self.project_repository.replace_runs(project.id, [])
        self.project_repository.replace_approvals(project.id, [])
        self.project_repository.replace_knowledge_objects(project.id, [])
        self.system_image_service.ensure_state(project.id, ready=False)
        self.get_or_create_conversation("project", project.id, project.name)
        return project

    def get_project_workspace(self, project_id: str) -> ProjectWorkspaceResponse:
        self._refresh_project_read_models(project_id)
        project = self.projects[project_id]
        versions = self.versions[project_id]
        current_version_id = versions[0].id if versions else ""
        primary_us = self.us_items[project_id][0].id if self.us_items[project_id] else ""
        return ProjectWorkspaceResponse(
            project=project,
            versions=versions,
            current_version_id=current_version_id,
            us_items=self.us_items[project_id],
            asset_lanes=self.asset_lanes.get(primary_us, []),
            runs=self.runs[project_id],
            approvals=self.approvals[project_id],
        )

    def list_knowledge_objects(self, project_id: str) -> List[KnowledgeObject]:
        self._refresh_project_read_models(project_id)
        return self.knowledge_objects[project_id]

    def get_knowledge_object(self, project_id: str, object_id: str) -> KnowledgeObject:
        self._refresh_project_read_models(project_id)
        return next(item for item in self.knowledge_objects[project_id] if item.id == object_id)

    def get_system_image(self, project_id: str) -> SystemImageResponse:
        return self.system_image_service.get(project_id)

    def get_run_detail(self, project_id: str, run_id: str) -> RunDetail:
        self._refresh_project_read_models(project_id)
        if run_id not in self.run_details or run_id not in {run.id for run in self.runs[project_id]}:
            raise KeyError(run_id)
        return self.run_details[run_id]

    def get_approval_detail(self, project_id: str, approval_id: str) -> ApprovalDetail:
        self._refresh_project_read_models(project_id)
        if approval_id not in self.approval_details or approval_id not in {item.id for item in self.approvals[project_id]}:
            raise KeyError(approval_id)
        return self.approval_details[approval_id]

    def get_release_readiness(self, project_id: str) -> ReleaseReadiness:
        self._refresh_project_read_models(project_id)
        version = self.versions[project_id][0]
        return self.release_readiness[version.id]

    def create_version(self, project_id: str, name: str) -> VersionSummary:
        version = VersionSummary(
            id=f"ver_{_slugify(name)}_{len(self.versions[project_id]) + 1}",
            name=name,
            status="draft",
            branch_name=f"release/{_slugify(name)}",
            us_total=0,
            us_closed=0,
            pending_runs=0,
            pending_approvals=0,
        )
        self.versions[project_id].insert(0, version)
        project = self.projects[project_id]
        project.active_version = name
        self.project_repository.upsert_project(project)
        self.project_repository.replace_versions(project_id, self.versions[project_id])
        self.release_readiness[version.id] = ReleaseReadiness(
            version_id=version.id,
            status="Draft",
            score=0,
            blockers=0,
            approvals_open=0,
            pending_merge=0,
            execution_health="No runs yet",
            summary="This version branch has been created and is ready for US import, assignment, and quality asset generation.",
            blocker_items=[],
        )
        self.project_repository.upsert_release_readiness(project_id, self.release_readiness[version.id])
        return version

    def get_workspace_data(self, project_id: str, us_id: str) -> Dict[str, Any]:
        us = next((item for item in self.us_items[project_id] if item.id == us_id), None)
        return {
            "project": self.projects[project_id],
            "version": self.versions[project_id][0] if self.versions[project_id] else None,
            "us_item": us,
            "asset_lanes": self.asset_lanes.get(us_id, []),
            "conversation": self.get_or_create_conversation("workspace", us_id, f"{us_id} Workspace"),
            "runs": self.runs[project_id],
            "approvals": self.approvals[project_id],
        }

    def _resolve_conversation_scope(
        self,
        space_type: str,
        space_id: str,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        us_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        resolved_project_id = project_id
        resolved_version_id = version_id
        resolved_us_id = us_id

        if space_type == "project":
            resolved_project_id = resolved_project_id or space_id
        elif space_type == "version":
            if resolved_project_id is None:
                for candidate_project_id, versions in self.versions.items():
                    matched = next((version for version in versions if version.id == space_id), None)
                    if matched is not None:
                        resolved_project_id = candidate_project_id
                        resolved_version_id = matched.id
                        break
            resolved_version_id = resolved_version_id or space_id
        elif space_type == "workspace":
            resolved_us_id = resolved_us_id or space_id
            if resolved_project_id is None:
                for candidate_project_id, items in self.us_items.items():
                    if any(item.id == resolved_us_id for item in items):
                        resolved_project_id = candidate_project_id
                        break
            if resolved_version_id is None and resolved_project_id and self.versions[resolved_project_id]:
                resolved_version_id = self.versions[resolved_project_id][0].id

        return resolved_project_id, resolved_version_id, resolved_us_id

    def get_or_create_conversation(self, space_type: str, space_id: str, title: str) -> ConversationSession:
        key = (space_type, space_id)
        if key in self.conversation_index:
            return self.conversations[self.conversation_index[key]]
        project_id, version_id, us_id = self._resolve_conversation_scope(space_type, space_id)
        conversation_id = f"conv_{uuid4().hex[:10]}"
        conversation = ConversationSession(
            id=conversation_id,
            session_id=f"session_{uuid4().hex[:8]}",
            title=title,
            space_type=space_type,  # type: ignore[arg-type]
            space_id=space_id,
            project_id=project_id,
            version_id=version_id,
            us_id=us_id,
            initiator_id=self.user.id,
            status="draft",
            messages=[],
            agent_goals=[],
        )
        self.conversations[conversation_id] = conversation
        self.conversation_index[key] = conversation_id
        self.conversation_repository.upsert_conversation(conversation)
        return conversation

    def list_conversations(
        self,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        space_type: Optional[str] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> List[ConversationSession]:
        conversations = list(self.conversations.values())
        if project_id:
            conversations = [conversation for conversation in conversations if conversation.project_id == project_id]
        if version_id:
            conversations = [conversation for conversation in conversations if conversation.version_id == version_id]
        if space_type:
            conversations = [conversation for conversation in conversations if conversation.space_type == space_type]
        if status:
            conversations = [conversation for conversation in conversations if conversation.status == status]
        if q:
            needle = q.lower()
            conversations = [
                conversation
                for conversation in conversations
                if needle in conversation.title.lower()
                or any(
                    block.text and needle in block.text.lower()
                    for message in conversation.messages
                    for block in message.blocks
                )
            ]
        return conversations

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self.conversations[conversation_id]

    def list_conversation_messages(self, conversation_id: str, before_message_id: Optional[str] = None) -> List[ConversationMessage]:
        messages = self.conversations[conversation_id].messages
        if before_message_id is None:
            return messages
        for index, message in enumerate(messages):
            if message.id == before_message_id:
                return messages[:index]
        return messages

    def archive_conversation(self, conversation_id: str, payload: ConversationArchiveRequest) -> ConversationSession:
        conversation = self.conversations[conversation_id]
        if payload.archive:
            conversation.status = "archived"
            conversation.archived_at = _now_iso()
        else:
            conversation.status = "active" if conversation.messages else "draft"
            conversation.archived_at = None
        self.conversation_repository.upsert_conversation(conversation)
        return conversation

    def merge_conversations(self, conversation_id: str, payload: ConversationMergeRequest) -> Dict[str, Any]:
        source = self.conversations[conversation_id]
        target = self.conversations[payload.target_conversation_id]

        target.messages.extend(deepcopy(source.messages))
        target.agent_goals.extend(deepcopy(source.agent_goals))
        target.last_message_at = target.messages[-1].created_at if target.messages else target.last_message_at
        target.status = "active" if target.messages else target.status

        source.status = "merged"
        source.merged_into_conversation_id = target.id

        link = ConversationLink(
            id=f"cl_{uuid4().hex[:10]}",
            left_conversation_id=source.id,
            right_conversation_id=target.id,
            link_kind="merged_from",
            reason="merged through API request",
            confidence=1.0,
            created_at=_now_iso(),
        )
        self.conversation_links[link.id] = link
        source.related_conversation_ids.append(target.id)
        target.related_conversation_ids.append(source.id)
        self.conversation_repository.upsert_conversation(source)
        self.conversation_repository.upsert_conversation(target)
        return {"target_conversation_id": target.id, "link": link}

    def search_conversations(self, q: str) -> Dict[str, Any]:
        matches = self.list_conversations(q=q)
        message_hits = []
        needle = q.lower()
        for conversation in matches:
            for message in conversation.messages:
                for block in message.blocks:
                    if block.text and needle in block.text.lower():
                        message_hits.append(
                            {
                                "conversation_id": conversation.id,
                                "message_id": message.id,
                                "excerpt": block.text[:180],
                            }
                        )
                        break

        related_links = [
            link
            for link in self.conversation_links.values()
            if link.left_conversation_id in {conversation.id for conversation in matches}
            or link.right_conversation_id in {conversation.id for conversation in matches}
        ]
        return {
            "query": q,
            "conversations": matches,
            "message_hits": message_hits,
            "related_links": related_links,
        }

    async def create_tool_invocation(self, payload: ToolInvocationRequest) -> ToolInvocation:
        return await self.tool_invocation_runtime.create(payload)

    async def _execute_tool_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        return await self.tool_invocation_runtime.execute(invocation)

    async def _gate_tool_invocation_if_needed(self, invocation: ToolInvocation) -> bool:
        return await self.tool_invocation_runtime.gate_if_needed(invocation)

    def _tool_definition(self, tool_id: str) -> ToolDefinition | None:
        return self.tool_invocation_runtime.tool_definition(tool_id)

    async def confirm_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return await self.tool_invocation_runtime.confirm(invocation_id)

    def _pending_confirmation_invocation(self, conversation_id: str, content: str) -> ToolInvocation | None:
        explicit_match = re.search(r"tool_[a-f0-9]+", content)
        explicit_invocation_id = explicit_match.group(0) if explicit_match else None
        candidates = [
            invocation
            for invocation in self.tool_invocations.values()
            if invocation.conversation_id == conversation_id and invocation.status == "waiting_confirmation"
        ]
        if explicit_invocation_id:
            return next((invocation for invocation in candidates if invocation.id == explicit_invocation_id), None)
        return candidates[-1] if candidates else None

    async def _handle_confirmation_message_if_any(self, conversation_id: str, content: str) -> Dict[str, Any] | None:
        if not self.tool_governance.is_confirmation_message(content):
            return None

        invocation = self._pending_confirmation_invocation(conversation_id, content)
        if invocation is None:
            return None

        goal_id = invocation.input_payload.get("agent_goal_id")
        if isinstance(goal_id, str) and goal_id in self.agent_goals and self.agent_goals[goal_id].status == "paused":
            goal = await self.agent_service.resume_goal(goal_id)
            return {"agent_goal": goal, "tool_invocation": self.tool_invocations[invocation.id]}

        confirmed = await self.confirm_tool_invocation(invocation.id)
        return {"tool_invocation": confirmed}

    async def _handle_source_binding_message_if_any(self, conversation_id: str, content: str) -> Dict[str, Any] | None:
        conversation = self.conversations[conversation_id]
        active_goal = self.agent_service.active_goal_for_conversation(conversation_id)
        if active_goal is None or active_goal.status != "paused" or active_goal.pause_reason != "missing_source_binding":
            return None

        from .conversation_orchestrator import ConversationOrchestrator

        source_specs = ConversationOrchestrator._extract_system_image_source_specs(content)
        if not source_specs:
            return None

        blocked_step = next(
            (
                step
                for step in active_goal.steps
                if step.status == "blocked" and step.selected_tool_id == "system_image.sources.register"
            ),
            None,
        )
        if blocked_step is None:
            return None

        existing_specs = blocked_step.tool_input_payload.get("source_specs")
        specs_by_type: Dict[str, Dict[str, str]] = {}
        if isinstance(existing_specs, list):
            for item in existing_specs:
                if isinstance(item, dict) and isinstance(item.get("source_type"), str):
                    specs_by_type[item["source_type"]] = {str(key): str(value) for key, value in item.items()}
        for spec in source_specs:
            specs_by_type[spec["source_type"]] = spec
        blocked_step.tool_input_payload["source_specs"] = [
            specs_by_type[source_type]
            for source_type in ("code", "us_doc", "test_asset")
            if source_type in specs_by_type
        ]

        self.conversation_repository.upsert_goal(active_goal)
        self._upsert_goal_in_conversation(active_goal)
        self.record_agent_goal_audit_event(
            active_goal,
            action="agent.goal.source_binding_received",
            status=active_goal.status,
            summary=f"Source bindings received for AgentGoal: {active_goal.title}",
            actor=self.user.id,
            actor_kind="user",
            metadata={"source_types": [spec["source_type"] for spec in source_specs]},
        )
        await self.append_message(
            conversation_id,
            "assistant",
            "I received the source bindings and will continue the system image build.",
            metadata={
                "planner_kind": "source_binding_received",
                "agent_goal_id": active_goal.id,
                "source_types": [spec["source_type"] for spec in source_specs],
            },
        )
        goal = await self.agent_service.resume_goal(active_goal.id)
        return {"agent_goal": goal}

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return self.tool_invocations[invocation_id]

    def list_tool_invocations(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        tool_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ToolInvocation]:
        invocations = list(self.tool_invocations.values())
        if conversation_id is not None:
            invocations = [item for item in invocations if item.conversation_id == conversation_id]
        if agent_goal_id is not None:
            invocations = [
                item
                for item in invocations
                if item.input_payload.get("agent_goal_id") == agent_goal_id
            ]
        if tool_id is not None:
            canonical_tool_id = self.tool_invocation_runtime.canonical_tool_id(tool_id)
            invocations = [item for item in invocations if item.tool_id == canonical_tool_id]
        if status is not None:
            invocations = [item for item in invocations if item.status == status]
        return sorted(invocations, key=self._tool_invocation_created_at)

    def _tool_invocation_created_at(self, invocation: ToolInvocation) -> str:
        created_events = [
            event.occurred_at
            for event in self.audit_events.values()
            if event.tool_invocation_id == invocation.id and event.action == "tool.invocation.created"
        ]
        return min(created_events) if created_events else invocation.id

    def record_audit_event(self, event: AuditEvent) -> None:
        self.audit_events[event.id] = event
        self.conversation_repository.upsert_audit_event(event)

    def record_agent_goal_audit_event(
        self,
        goal: AgentGoal,
        *,
        action: str,
        status: str | None = None,
        summary: str,
        actor: str = "agent",
        actor_kind: str = "agent",
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        object_refs: List[str] = []
        if goal.project_id:
            object_refs.append(f"project:{goal.project_id}")
        if goal.us_id:
            object_refs.append(f"us:{goal.us_id}")
        event_metadata: Dict[str, Any] = {
            "workflow_id": goal.workflow_id,
            "autonomy_level": goal.autonomy_level,
            "max_steps": goal.max_steps,
            "steps_completed": goal.steps_completed,
            "pause_reason": goal.pause_reason,
        }
        if metadata:
            event_metadata.update(metadata)
        self.record_audit_event(
            AuditEvent(
                id=f"audit_{uuid4().hex[:12]}",
                occurred_at=_now_iso(),
                actor=actor,
                actor_kind=actor_kind,  # type: ignore[arg-type]
                action=action,
                entity_type="agent_goal",
                entity_id=goal.id,
                status=status or goal.status,  # type: ignore[arg-type]
                summary=summary,
                conversation_id=goal.conversation_id,
                agent_goal_id=goal.id,
                object_refs=object_refs,
                metadata=event_metadata,
            )
        )

    def list_audit_events(
        self,
        *,
        conversation_id: str | None = None,
        tool_invocation_id: str | None = None,
        agent_goal_id: str | None = None,
    ) -> List[AuditEvent]:
        events = list(self.audit_events.values())
        if conversation_id is not None:
            events = [event for event in events if event.conversation_id == conversation_id]
        if tool_invocation_id is not None:
            events = [event for event in events if event.tool_invocation_id == tool_invocation_id]
        if agent_goal_id is not None:
            events = [event for event in events if event.agent_goal_id == agent_goal_id]
        return sorted(events, key=lambda event: event.occurred_at)

    def create_agent_goal(self, payload: AgentGoalCreateRequest) -> AgentGoal:
        goal = AgentGoal(
            id=f"goal_{uuid4().hex[:10]}",
            conversation_id=payload.conversation_id,
            project_id=payload.project_id,
            us_id=payload.us_id,
            title=payload.title,
            status="pending",
            summary=payload.summary,
            autonomy_level=payload.autonomy_level,
            max_steps=payload.max_steps,
            workflow_id=f"wf_{uuid4().hex[:8]}",
            steps=payload.steps
            or [
                AgentStep(id="step_context", title="Assemble context", status="pending"),
                AgentStep(id="step_impact", title="Review impact", status="pending"),
                AgentStep(id="step_output", title="Materialize output", status="pending"),
            ],
        )
        self.agent_goals[goal.id] = goal
        self.conversation_repository.upsert_goal(goal)
        self._upsert_goal_in_conversation(goal)
        self.record_agent_goal_audit_event(
            goal,
            action="agent.goal.created",
            status="pending",
            summary=f"Agent goal created: {goal.title}",
            actor="system",
            actor_kind="system",
        )
        return goal

    def get_agent_goal(self, goal_id: str) -> AgentGoal:
        return self.agent_goals[goal_id]

    def get_agent_goal_checkpoint(self, goal_id: str):
        return self.agent_workflow_runtime.checkpoint(goal_id)

    def get_agent_memory_context(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        space_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        conversation = self._conversation_for_memory_query(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            space_ref=space_ref,
        )
        goal = self.agent_goals.get(agent_goal_id) if agent_goal_id else self.agent_service.active_goal_for_conversation(conversation.id)
        memory_context = self.agent_memory.build_context(conversation, tools=self.tools)
        latest_checkpoint = self._latest_checkpoint_for_conversation(conversation.id)
        project_id = conversation.project_id

        return {
            "conversation_id": conversation.id,
            "agent_goal_id": goal.id if goal else None,
            "context_hash": memory_context_hash(memory_context),
            "context_summary": memory_context_summary(memory_context),
            "recent_turn_count": memory_context.recent_turn_count,
            "checkpoint_count": memory_context.checkpoint_count,
            "working_memory": self._working_memory_view(goal),
            "conversation_memory": {
                "latest_summary_checkpoint_id": latest_checkpoint.id if latest_checkpoint else None,
                "recent_message_refs": [message.id for message in conversation.messages[-6:]],
                "checkpoint_count": memory_context.checkpoint_count,
                "recent_turn_count": memory_context.recent_turn_count,
            },
            "project_long_term_memory": self._project_long_term_memory_view(project_id),
            "candidate_memory": self._candidate_memory_view(conversation, project_id),
            "tool_catalog": {
                "tool_count": len(self.tools),
                "tool_ids": [tool.tool_id for tool in self.tools],
            },
        }

    async def create_agent_memory_checkpoint(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        space_ref: Optional[str] = None,
        created_by: str = "user",
    ) -> ConversationSummaryCheckpoint:
        conversation = self._conversation_for_memory_query(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            space_ref=space_ref,
        )
        latest_checkpoint = self._latest_checkpoint_for_conversation(conversation.id)
        checkpoint = self._build_summary_checkpoint(conversation, force=True, created_by=created_by)
        if checkpoint is None:
            if latest_checkpoint is not None:
                return latest_checkpoint
            raise ValueError("No completed text messages are available to checkpoint.")
        if latest_checkpoint and latest_checkpoint.message_range_end == checkpoint.message_range_end:
            return latest_checkpoint

        self.conversation_summary_checkpoints[checkpoint.id] = checkpoint
        conversation.latest_summary_checkpoint_id = checkpoint.id
        self.conversation_repository.upsert_summary_checkpoint(checkpoint)
        self.conversation_repository.upsert_conversation(conversation)
        await self._push_event(
            conversation.id,
            event_type="agent.memory.checkpointed",
            entity_type="conversation",
            entity_id=conversation.id,
            mutation_kind="patch",
            patch={"latest_summary_checkpoint_id": checkpoint.id},
            query_keys=[["conversation", conversation.id], ["agent-memory", conversation.id]],
        )
        return checkpoint

    def _conversation_for_memory_query(
        self,
        *,
        conversation_id: Optional[str],
        agent_goal_id: Optional[str],
        space_ref: Optional[str],
    ) -> ConversationSession:
        if agent_goal_id:
            goal = self.agent_goals[agent_goal_id]
            return self.conversations[goal.conversation_id]
        if conversation_id:
            return self.conversations[conversation_id]
        if space_ref:
            space_type, _, space_id = space_ref.partition(":")
            if not space_type or not space_id:
                raise KeyError(space_ref)
            for conversation in self.conversations.values():
                if conversation.space_type == space_type and conversation.space_id == space_id:
                    return conversation
                if space_type == "project" and conversation.project_id == space_id:
                    return conversation
        raise KeyError("conversation_id, agent_goal_id, or space_ref is required")

    @staticmethod
    def _working_memory_view(goal: AgentGoal | None) -> Dict[str, Any]:
        if goal is None:
            return {
                "active_goal_id": None,
                "status": "idle",
                "current_step_id": None,
                "pause_reason": None,
            }
        current_step = next((step for step in goal.steps if step.status == "running"), None)
        if current_step is None:
            current_step = next((step for step in goal.steps if step.status == "blocked"), None)
        return {
            "active_goal_id": goal.id,
            "status": goal.status,
            "current_step_id": current_step.id if current_step else None,
            "pause_reason": goal.pause_reason,
            "steps_completed": goal.steps_completed,
            "max_steps": goal.max_steps,
        }

    def _project_long_term_memory_view(self, project_id: Optional[str]) -> Dict[str, Any]:
        if not project_id or project_id not in self.projects:
            return {
                "project_id": project_id,
                "system_image_status": None,
                "baseline_refs": [],
                "source_refs": [],
                "context_object_refs": [],
                "metric_groups": [],
            }
        project = self.projects[project_id]
        return {
            "project_id": project_id,
            "system_image_status": project.system_image_status,
            "baseline_refs": [f"baseline:{baseline.id}:{baseline.status}" for baseline in self.baselines.get(project_id, [])],
            "source_refs": [
                f"raw_asset:{source.id}:{source.source_type}:{source.ingestion_status}"
                for source in self.raw_assets.get(project_id, [])
            ],
            "context_object_refs": [
                f"context_object:{item.id}:{item.type}"
                for item in self.knowledge_objects.get(project_id, [])[:12]
            ],
            "metric_groups": sorted({metric.metric_group for metric in self.quality_metric_snapshots.get(project_id, [])}),
        }

    def _candidate_memory_view(self, conversation: ConversationSession, project_id: Optional[str]) -> Dict[str, Any]:
        session_refs = [
            binding.candidate_object_ref
            for binding in self.session_knowledge_bindings.values()
            if binding.conversation_id == conversation.id
        ]
        overlay_refs = []
        if project_id:
            overlay_refs = [
                f"context_overlay:{overlay.id}:{overlay.status}"
                for overlay in self.context_object_overlays.get(project_id, [])
                if overlay.status == "candidate"
            ]
        return {
            "session_only_refs": session_refs,
            "candidate_overlay_refs": overlay_refs,
        }

    def get_agent_swarm(self, swarm_id: str) -> AgentSwarmRun:
        return self.agent_swarm_coordinator.get_swarm(swarm_id)

    def _upsert_goal_in_conversation(self, goal: AgentGoal) -> None:
        conversation = self.conversations[goal.conversation_id]
        existing_index = next(
            (index for index, current in enumerate(conversation.agent_goals) if current.id == goal.id),
            None,
        )
        if existing_index is None:
            conversation.agent_goals.append(goal)
        else:
            conversation.agent_goals[existing_index] = goal
        self.conversation_repository.upsert_goal(goal)
        self.conversation_repository.upsert_conversation(conversation)

    def _recent_text_messages(self, conversation: ConversationSession) -> List[ConversationMessage]:
        return [
            message
            for message in conversation.messages
            if message.content_type in {"text", "markdown"} and message.status == "completed"
        ]

    def _latest_checkpoint_for_conversation(self, conversation_id: str) -> Optional[ConversationSummaryCheckpoint]:
        checkpoints = [
            checkpoint
            for checkpoint in self.conversation_summary_checkpoints.values()
            if checkpoint.conversation_id == conversation_id
        ]
        if not checkpoints:
            return None
        checkpoints.sort(key=lambda checkpoint: checkpoint.created_at)
        return checkpoints[-1]

    def _build_summary_checkpoint(
        self,
        conversation: ConversationSession,
        *,
        force: bool = False,
        created_by: str = "system",
    ) -> Optional[ConversationSummaryCheckpoint]:
        text_messages = self._recent_text_messages(conversation)
        if len(text_messages) < 8 and not force:
            return None
        if not text_messages:
            return None

        latest_checkpoint = self._latest_checkpoint_for_conversation(conversation.id)
        latest_checkpoint_end = latest_checkpoint.message_range_end if latest_checkpoint else None
        start_index = 0
        if latest_checkpoint_end:
            for index, message in enumerate(text_messages):
                if message.id == latest_checkpoint_end:
                    start_index = index + 1
                    break

        checkpoint_candidates = text_messages[start_index:]
        if not checkpoint_candidates:
            return None
        if len(checkpoint_candidates) < 6 and not force:
            return None

        messages_to_summarize = checkpoint_candidates if force else checkpoint_candidates[:-4]
        if len(messages_to_summarize) < 4 and not force:
            return None

        summary_lines: list[str] = []
        for message in messages_to_summarize[-8:]:
            text = " ".join(block.text.strip() for block in message.blocks if block.text.strip())
            if not text:
                continue
            compact_text = re.sub(r"\s+", " ", text)
            if len(compact_text) > 160:
                compact_text = f"{compact_text[:157]}..."
            actor = "User" if message.role == "user" else "Agent"
            summary_lines.append(f"{actor}: {compact_text}")

        if not summary_lines:
            return None

        return ConversationSummaryCheckpoint(
            id=f"chk_{uuid4().hex[:10]}",
            conversation_id=conversation.id,
            message_range_start=messages_to_summarize[0].id,
            message_range_end=messages_to_summarize[-1].id,
            summary_text="\n".join(summary_lines),
            summary_object_refs=[],
            summary_token_count=len(" ".join(summary_lines).split()),
            created_by=created_by,  # type: ignore[arg-type]
            created_at=_now_iso(),
        )

    def _conversation_history_snapshot(self, conversation: ConversationSession) -> str:
        return self.agent_memory.build_context(conversation).history_snapshot

    def _planner_memory_context(self, conversation: ConversationSession):
        return self.agent_memory.build_context(conversation, tools=self.tools)

    async def _maybe_create_summary_checkpoint(self, conversation: ConversationSession) -> None:
        checkpoint = self._build_summary_checkpoint(conversation)
        if checkpoint is None:
            return

        latest_checkpoint = self._latest_checkpoint_for_conversation(conversation.id)
        if latest_checkpoint and latest_checkpoint.message_range_end == checkpoint.message_range_end:
            return

        self.conversation_summary_checkpoints[checkpoint.id] = checkpoint
        conversation.latest_summary_checkpoint_id = checkpoint.id
        self.conversation_repository.upsert_summary_checkpoint(checkpoint)
        self.conversation_repository.upsert_conversation(conversation)

        await self._push_event(
            conversation.id,
            event_type="conversation.summary.updated",
            entity_type="conversation",
            entity_id=conversation.id,
            mutation_kind="patch",
            patch={"latest_summary_checkpoint_id": checkpoint.id},
            query_keys=[["conversation", conversation.id]],
        )

    async def append_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        tone: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConversationMessage:
        conversation = self.conversations[conversation_id]
        message = ConversationMessage(
            id=f"msg_{uuid4().hex[:10]}",
            role=role,  # type: ignore[arg-type]
            created_at=_now_iso(),
            status="completed",
            content_type="text",
            blocks=[MessageBlock(type="text", text=text, tone=tone)],
            metadata=metadata or {},
        )
        conversation.messages.append(message)
        conversation.last_message_at = message.created_at
        if conversation.status in {"draft", "idle"}:
            conversation.status = "active"
        self.conversation_repository.append_message(conversation_id, message)
        self.conversation_repository.upsert_conversation(conversation)
        await self._maybe_create_summary_checkpoint(conversation)
        await self._push_event(
            conversation_id,
            event_type="conversation.message.created",
            entity_type="conversation",
            entity_id=conversation_id,
            mutation_kind="patch",
            patch={"message_id": message.id},
            query_keys=[["conversation", conversation_id]],
            payload={"message_id": message.id, "message": message.model_dump()},
        )
        return message

    async def _push_event(
        self,
        conversation_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        mutation_kind: str,
        patch: Dict[str, Any],
        query_keys: List[List[str]],
        *,
        snapshot_hint: bool = False,
        payload: Dict[str, Any] | None = None,
    ) -> None:
        version_key = f"{entity_type}:{entity_id}"
        self.entity_versions[version_key] += 1
        event_id = f"evt_{uuid4().hex[:10]}"
        event = EventPayload(
            event_id=event_id,
            event_type=event_type,
            occurred_at=_now_iso(),
            correlation_id=str(patch.get("correlation_id") or patch.get("tool_invocation_id") or patch.get("agent_goal_id") or event_id),
            conversation_id=conversation_id,
            tool_invocation_id=entity_id if entity_type == "tool_invocation" else self._optional_str(patch.get("tool_invocation_id")),
            agent_goal_id=entity_id if entity_type == "agent_goal" else self._optional_str(patch.get("agent_goal_id")),
            agent_step_id=self._optional_str(patch.get("agent_step_id")),
            swarm_run_id=entity_id if entity_type == "agent_swarm" else self._optional_str(patch.get("swarm_run_id")),
            assignment_id=self._optional_str(patch.get("assignment_id")),
            task_id=entity_id if entity_type == "task" else self._optional_str(patch.get("task_id")),
            run_id=entity_id if entity_type == "run" else self._optional_str(patch.get("run_id")),
            entity_type=entity_type,
            entity_id=entity_id,
            entity_version=self.entity_versions[version_key],
            mutation_kind=mutation_kind,  # type: ignore[arg-type]
            patch=patch,
            query_keys=query_keys,
            snapshot_hint=snapshot_hint,
            payload=self._event_payload(entity_type, entity_id, patch, payload),
        )
        await self._get_or_create_event_queue(conversation_id).put(event)
        if event.swarm_run_id:
            await self._get_or_create_swarm_queue(event.swarm_run_id).put(event)

    async def _push_goal_event(
        self,
        goal_id: str,
        event_type: str,
        mutation_kind: str,
        patch: Dict[str, Any],
        query_keys: List[List[str]],
        *,
        snapshot_hint: bool = False,
        payload: Dict[str, Any] | None = None,
    ) -> None:
        version_key = f"agent_goal:{goal_id}"
        self.entity_versions[version_key] += 1
        goal = self.agent_goals.get(goal_id)
        event_id = f"evt_{uuid4().hex[:10]}"
        event = EventPayload(
            event_id=event_id,
            event_type=event_type,
            occurred_at=_now_iso(),
            correlation_id=str(patch.get("correlation_id") or patch.get("tool_invocation_id") or goal_id),
            conversation_id=goal.conversation_id if goal else self._optional_str(patch.get("conversation_id")),
            tool_invocation_id=self._optional_str(patch.get("tool_invocation_id")),
            agent_goal_id=goal_id,
            agent_step_id=self._optional_str(patch.get("agent_step_id")),
            swarm_run_id=self._optional_str(patch.get("swarm_run_id")),
            assignment_id=self._optional_str(patch.get("assignment_id")),
            task_id=self._optional_str(patch.get("task_id")),
            run_id=self._optional_str(patch.get("run_id")),
            entity_type="agent_goal",
            entity_id=goal_id,
            entity_version=self.entity_versions[version_key],
            mutation_kind=mutation_kind,  # type: ignore[arg-type]
            patch=patch,
            query_keys=query_keys,
            snapshot_hint=snapshot_hint,
            payload=self._event_payload("agent_goal", goal_id, patch, payload),
        )
        await self._get_or_create_goal_queue(goal_id).put(event)

    def _event_payload(
        self,
        entity_type: str,
        entity_id: str,
        patch: Dict[str, Any],
        payload: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        if payload is not None:
            return payload
        if entity_type == "agent_goal" and entity_id in self.agent_goals:
            return {"patch": patch, "agent_goal": self.agent_goals[entity_id].model_dump()}
        if entity_type == "agent_swarm" and entity_id in self.agent_swarms:
            return {"patch": patch, "agent_swarm": self.agent_swarms[entity_id].model_dump()}
        if entity_type == "tool_invocation" and entity_id in self.tool_invocations:
            return {"patch": patch, "tool_invocation": self.tool_invocations[entity_id].model_dump()}
        return patch

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None

    async def _emit_tool_status(
        self,
        invocation_id: str,
        status: str,
        summary: str,
        query_keys: List[List[str]],
        result: ToolResult | None = None,
    ) -> None:
        invocation = self.tool_invocations[invocation_id]
        invocation.status = status  # type: ignore[assignment]
        invocation.summary = summary
        if result is not None:
            invocation.result = result
        self.conversation_repository.upsert_tool_invocation(invocation)

        if invocation.conversation_id:
            await self._push_event(
                invocation.conversation_id,
                "tool.invocation.updated",
                "tool_invocation",
                invocation.id,
                "replace",
                {
                    "status": invocation.status,
                    "summary": invocation.summary,
                    "tool_id": invocation.tool_id,
                },
                query_keys,
            )

    def _conversation_system_prompt(self, conversation: ConversationSession) -> str:
        return self.agent_memory.build_context(conversation).system_prompt

    def _conversation_context_snapshot(self, conversation: ConversationSession) -> str:
        return self.agent_memory.build_context(conversation).context_snapshot

    async def _emit_llm_answer(
        self,
        conversation_id: str,
        invocation: ToolInvocation,
        *,
        user_message: str,
        fallback_text: str,
        query_keys: List[List[str]],
    ) -> None:
        conversation = self.conversations[conversation_id]
        llm_result = await self._generate_llm_content(
            conversation=conversation,
            user_message=user_message,
            fallback_text=fallback_text,
        )
        await self.append_message(
            conversation_id,
            "assistant",
            llm_result["content"],
            metadata=llm_result["metadata"],
        )
        await self._push_event(
            conversation_id,
            "tool.invocation.updated",
            "tool_invocation",
            invocation.id,
            "replace",
            {
                "status": "completed",
                "llm_provider": llm_result["metadata"]["llm_provider"],
                "llm_model": llm_result["metadata"]["llm_model"],
                "llm_mode": llm_result["metadata"]["llm_mode"],
            },
            query_keys,
        )

    async def _generate_llm_content(
        self,
        *,
        conversation: ConversationSession,
        user_message: str,
        fallback_text: str,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        memory_context = self.agent_memory.build_context(conversation)
        reply = await self.llm.generate_reply(
            settings=self.get_settings(),
            system_prompt=system_prompt or memory_context.system_prompt,
            user_message=user_message,
            context_snapshot=memory_context.context_snapshot,
            history_snapshot=memory_context.history_snapshot,
            fallback_text=fallback_text,
            custom_api_key=self._get_custom_model_api_key(),
        )
        return {
            "content": reply.content,
            "metadata": {
                "llm_provider": reply.provider,
                "llm_model": reply.model_name,
                "llm_mode": reply.mode,
                "llm_reason": reply.reason,
                "settings_preset": self.settings.model_preset,
                "memory_recent_turns": memory_context.recent_turn_count,
                "memory_checkpoint_count": memory_context.checkpoint_count,
            },
        }

    def _conversation_summary_fallback(self, conversation: ConversationSession) -> str:
        if conversation.space_type == "welcome":
            return (
                "You can start from Build to create a new project, connect Git, US documents, and UX boards, or open "
                "Dashboard to inspect project progress and release risk across the portfolio."
            )
        if conversation.space_type == "dashboard":
            return self._build_dashboard_summary("")
        if conversation.space_type == "project":
            project_id = conversation.project_id or conversation.space_id
            return self._project_status_summary(project_id)
        if conversation.space_type == "version":
            project_id = conversation.project_id or next(iter(self.projects))
            version_id = conversation.version_id or (
                self.versions[project_id][0].id if self.versions[project_id] else ""
            )
            return self._version_status_summary(project_id, version_id)
        if conversation.space_type == "workspace":
            return self._workspace_status_summary(conversation.us_id or conversation.space_id)
        if conversation.space_type == "knowledge":
            project_id = conversation.project_id or conversation.space_id
            return self._knowledge_status_summary(project_id)
        if conversation.space_type == "runs":
            project_id = conversation.project_id or conversation.space_id
            return self._run_status_summary(project_id)
        if conversation.space_type == "governance":
            project_id = conversation.project_id or conversation.space_id
            return self._governance_status_summary(project_id)
        if conversation.space_type == "documentation":
            return (
                "Nasus uses an agent-first workflow: conversation drives tool invocation, tool invocation materializes "
                "project, version, run, and governance objects, and all important actions remain visible through the "
                "workspace shell."
            )
        if conversation.space_type == "build":
            return (
                "You can create a project, connect Git, import US documents, import UX boards, and initialize the "
                "Official System Image from here."
            )
        return (
            "I can help with project creation, version setup, dashboard progress checks, or quality asset generation. "
            "Tell me which step you want to move forward."
        )

    async def handle_message(self, conversation_id: str, content: str) -> Dict[str, Any]:
        conversation = self.conversations[conversation_id]
        await self.append_message(conversation_id, "user", content)
        source_binding_result = await self._handle_source_binding_message_if_any(conversation_id, content)
        if source_binding_result is not None:
            return source_binding_result
        confirmation_result = await self._handle_confirmation_message_if_any(conversation_id, content)
        if confirmation_result is not None:
            return confirmation_result

        decision = await self.planner.plan(conversation, content)

        if decision.kind == "clarification" and decision.clarification:
            await self.append_message(
                conversation_id,
                "assistant",
                decision.clarification.question,
                metadata={
                    "planner_kind": "clarification",
                    "clarification_kind": decision.clarification.reason,
                    "missing_context": decision.clarification.missing_context,
                },
            )
            return {"clarification": decision.clarification.__dict__}

        if decision.kind == "tool_plan" and decision.tool_plan:
            tool_invocations = []
            for step in decision.tool_plan.steps:
                invocation = await self.create_tool_invocation(
                    ToolInvocationRequest(
                        conversation_id=conversation_id,
                        tool_id=step.tool_id,
                        input=step.input_payload,
                        initiator_surface="chat",
                        initiator_actor="user",
                        target_scope=step.target_scope,
                    )
                )
                tool_invocations.append(invocation)
            return {"tool_invocations": tool_invocations}

        if decision.kind == "agent_goal" and decision.agent_goal:
            goal = await self.agent_service.start_from_proposal(conversation_id, decision.agent_goal)
            return {"agent_goal": goal}

        tool_invocation = ToolInvocation(
            id=f"tool_{uuid4().hex[:10]}",
            conversation_id=conversation_id,
            tool_id="query.answer",
            status="completed",
            summary="Answer generated",
            initiator_surface="chat",
            initiator_actor="user",
            target_scope="central",
        )
        direct_answer = decision.direct_answer
        fallback_text = direct_answer.fallback_text if direct_answer else self._conversation_summary_fallback(conversation)
        query_keys = direct_answer.query_keys if direct_answer else [["conversation", conversation_id]]
        asyncio.create_task(
            self._emit_llm_answer(
                conversation_id,
                tool_invocation,
                user_message=content,
                fallback_text=fallback_text,
                query_keys=query_keys,
            )
        )
        return {"tool_invocation": tool_invocation}

    def _build_dashboard_summary(self, lowered: str) -> str:
        riskiest_project = max(
            self.projects.values(),
            key=lambda project: (project.blocked_items, project.pending_approvals, 100 - project.progress),
        )
        if "risk" in lowered or "riskiest" in lowered or "风险" in lowered:
            return (
                f"{riskiest_project.name} is currently the riskiest active project because it has "
                f"{riskiest_project.blocked_items} blocked items, {riskiest_project.pending_approvals} pending approvals, "
                f"and its active version is still only {riskiest_project.progress}% through the closure path."
            )

        return (
            f"There are {len(self.projects)} active projects across {sum(len(versions) for versions in self.versions.values())} running versions. "
            f"The portfolio currently has {sum(project.blocked_items for project in self.projects.values())} blocked items, "
            f"{sum(project.pending_approvals for project in self.projects.values())} pending approvals, and "
            f"{sum(1 for runs in self.runs.values() for run in runs if run.status == 'failed')} failed runs."
        )

    def _project_status_summary(self, project_id: str) -> str:
        project = self.projects[project_id]
        versions = self.versions[project_id]
        active_version = versions[0] if versions else None
        return (
            f"{project.name} is {project.progress}% through its quality loop. "
            f"The Official System Image is {project.system_image_status}, "
            f"the active version is {active_version.name if active_version else 'not started'}, "
            f"and there are {project.blocked_items} blocked items with {project.pending_approvals} approvals still open."
        )

    def _version_status_summary(self, project_id: str, version_id: str) -> str:
        versions = self.versions[project_id]
        version = next((item for item in versions if item.id == version_id), versions[0] if versions else None)
        us_items = self.us_items[project_id]
        high_risk = sum(1 for item in us_items if item.risk == "high")
        if version is None:
            return "No active version branch exists yet. Create a version to start US assignment and quality closure."
        return (
            f"{version.name} is currently {version.status}. "
            f"{version.us_closed} of {version.us_total or len(us_items)} US items are closed, "
            f"{version.pending_runs} runs are still pending, and {high_risk} US items remain in the high-risk bucket."
        )

    def _workspace_status_summary(self, us_id: str) -> str:
        lanes = self.asset_lanes.get(us_id, [])
        ready = [lane.label for lane in lanes if lane.status in {"approved", "ready_for_review"}]
        drafting = [lane.label for lane in lanes if lane.status in {"drafting", "not_started"}]
        return (
            f"For {us_id}, the ready lanes are {', '.join(ready) if ready else 'none yet'}, "
            f"while {', '.join(drafting) if drafting else 'no remaining lanes'} still need work. "
            "You can continue with case generation, automation drafting, or execution preparation from here."
        )

    def _knowledge_status_summary(self, project_id: str) -> str:
        project = self.projects[project_id]
        return (
            f"{project.name} currently has an active system image and version-scoped knowledge changes awaiting promotion. "
            "The most relevant hotspots are checkout flow recovery, payment gateway fallback, and quality asset packs linked to the active release branch."
        )

    def _system_image_status_summary(self, project_id: str) -> str:
        image = self.get_system_image(project_id)
        indexed = sum(1 for source in image.sources if source.ingestion_status == "indexed")
        metric_groups = ", ".join(sorted({metric.metric_group for metric in image.metric_snapshots})) or "none"
        return (
            f"{image.project.name} system image is {image.project.system_image_status}. "
            f"{indexed}/{len(image.sources)} source groups are indexed across code, historical US docs, and test assets. "
            f"It currently has {len(image.objects)} objects, {len(image.relationships)} relationships, "
            f"and metric groups: {metric_groups}."
        )

    def _run_status_summary(self, project_id: str) -> str:
        runs = self.runs.get(project_id, [])
        if not runs:
            return "No runs have been materialized for this project yet."
        latest = runs[0]
        return (
            f"The latest run is {latest.title} on {latest.channel} and it is currently {latest.status}. "
            f"Summary: {latest.summary}. The next best action is to inspect failure evidence and decide whether healing should stay automated or fall back to human review."
        )

    def _governance_status_summary(self, project_id: str) -> str:
        approvals = self.approvals.get(project_id, [])
        waiting = [approval for approval in approvals if approval.status == "waiting_approval"]
        if waiting:
            first = waiting[0]
            return (
                f"There are {len(waiting)} approval items waiting in governance. "
                f"The top item is {first.title}: {first.summary}. Resolve that first if you want the release gate to progress."
            )
        return "Governance is currently clear. There are no waiting approvals blocking the project at this moment."

    async def _emit_simple_answer(
        self,
        conversation_id: str,
        message: str,
        invocation: ToolInvocation,
        query_keys: List[List[str]],
    ) -> None:
        await self.append_message(conversation_id, "assistant", message)
        await self._push_event(
            conversation_id,
            "tool.invocation.updated",
            "tool_invocation",
            invocation.id,
            "replace",
            {"status": "completed"},
            query_keys,
        )

    async def stream_goal_events(self, goal_id: str):
        queue = self._get_or_create_goal_queue(goal_id)
        while True:
            event = await queue.get()
            yield event

    async def stream_swarm_events(self, swarm_id: str):
        yield self._swarm_snapshot_event(swarm_id)
        queue = self._get_or_create_swarm_queue(swarm_id)
        while True:
            event = await queue.get()
            yield event

    def _swarm_snapshot_event(self, swarm_id: str) -> EventPayload:
        swarm = self.agent_swarms[swarm_id]
        version_key = f"agent_swarm:{swarm_id}"
        return EventPayload(
            event_id=f"evt_{uuid4().hex[:10]}",
            event_type="agent.swarm.snapshot",
            occurred_at=_now_iso(),
            correlation_id=swarm_id,
            conversation_id=swarm.conversation_id,
            agent_goal_id=swarm.parent_goal_id,
            swarm_run_id=swarm_id,
            entity_type="agent_swarm",
            entity_id=swarm_id,
            entity_version=self.entity_versions.get(version_key, 0),
            mutation_kind="replace",
            patch={"status": swarm.status, "result_summary": swarm.result_summary},
            query_keys=[["conversation", swarm.conversation_id], ["agent-swarm", swarm_id]],
            snapshot_hint=True,
            payload={"agent_swarm": swarm.model_dump()},
        )

    async def interrupt_agent_goal(self, goal_id: str) -> AgentGoal:
        return await self.agent_service.interrupt_goal(goal_id)

    async def resume_agent_goal(self, goal_id: str) -> AgentGoal:
        return await self.agent_service.resume_goal(goal_id)

    async def add_goal_feedback(self, goal_id: str, feedback: str) -> AgentGoal:
        return await self.agent_service.add_feedback(goal_id, feedback)

    async def stream_events(self, conversation_id: str):
        queue = self._get_or_create_event_queue(conversation_id)
        while True:
            event = await queue.get()
            yield event

    def _extract_project_name(self, content: str) -> str:
        quoted = re.search(r"['\"]([^'\"]+)['\"]", content)
        if quoted:
            return quoted.group(1)
        named = re.search(r"project(?: called| named)? ([A-Za-z0-9 _-]+)", content, re.IGNORECASE)
        if named:
            return named.group(1).strip()
        chinese_named = re.search(r"(?:名字叫|叫做|名为)([^，。,\\n]+)", content)
        if chinese_named:
            return chinese_named.group(1).strip()
        if "项目" in content:
            return "New Quality Project"
        return f"Project {len(self.projects) + 1}"

    def _extract_version_name(self, content: str) -> str:
        quoted = re.search(r"['\"]([^'\"]+)['\"]", content)
        if quoted:
            return quoted.group(1)
        named = re.search(r"version(?: called| named| branch)? ([A-Za-z0-9._ -]+)", content, re.IGNORECASE)
        if named:
            return named.group(1).strip()
        chinese_named = re.search(r"(?:版本(?:叫|名为)?|分支(?:叫|名为)?)([^，。,\\n]+)", content)
        if chinese_named:
            return chinese_named.group(1).strip()
        if "版本" in content:
            return f"Version {len(self.versions) + 1}"
        return "New Version"

InMemoryStore = ApplicationStore
store = ApplicationStore()
