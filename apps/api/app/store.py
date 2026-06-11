from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .agent_loop_runtime import AgentLoopRuntime
from .conversation_orchestrator import ConversationOrchestrator
from .database import init_database
from .llm import LLMGateway
from .models import (
    AgentGoal,
    AgentGoalCreateRequest,
    AgentStep,
    ApprovalDetail,
    ApprovalSummary,
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
        persisted_settings, persisted_custom_key = self.settings_repository.load()
        self.settings = self.llm.build_settings(
            language=persisted_settings["language"],
            theme=persisted_settings["theme"],
            notification_mode=persisted_settings["notification_mode"],
            model_preset=persisted_settings["model_preset"],
            custom_model=CustomModelConfig(**persisted_settings["custom_model"]),
        )
        self.custom_model_api_key_encrypted = persisted_custom_key
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
                tool_id="baseline.initialize",
                label="Initialize System Image",
                tool_kind="project",
                scope="central",
                risk_level="high",
                confirmation_mode="user_confirm",
                description="Build the first Official System Image from code, US documents, and historical test assets.",
                required_context=["project_id", "code_source", "us_doc_source", "test_asset_source"],
                produced_objects=["Baseline", "ContextObject", "QualityMetricSnapshot"],
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
        self.orchestrator = ConversationOrchestrator(
            tools=self.tools,
            project_name_extractor=self._extract_project_name,
            version_name_extractor=self._extract_version_name,
            summary_builder=self._conversation_summary_fallback,
        )
        self.agent_loop_runtime = AgentLoopRuntime(self)
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
        self.tool_invocations: Dict[str, ToolInvocation] = {}
        self.entity_versions: Dict[str, int] = defaultdict(int)
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
        self._ensure_system_image_state(project.id, ready=True, version_id=version.id)
        self.project_repository.upsert_release_readiness(project.id, self.release_readiness[version.id])
        self.get_or_create_conversation("welcome", "welcome", "Welcome")
        self.get_or_create_conversation("build", "build", "Build")
        self.get_or_create_conversation("dashboard", "dashboard", "Dashboard")
        self.get_or_create_conversation("project", project.id, project.name)
        self.get_or_create_conversation("workspace", "us_123", "US-123 Workspace")

    def _ensure_system_image_state(self, project_id: str, *, ready: bool, version_id: Optional[str] = None) -> None:
        project = self.projects[project_id]
        now = _now_iso()
        baseline_id = f"base_{project_id}_official"
        status = "ready" if ready else "draft"
        source_status = "indexed" if ready else "pending"
        object_count = len(self.knowledge_objects.get(project_id, []))
        relationship_count = 4 if ready else 0
        metric_count = 4 if ready else 0

        if not self.raw_assets.get(project_id):
            self.raw_assets[project_id] = [
                RawAssetRecord(
                    id=f"raw_{project_id}_code",
                    project_id=project_id,
                    version_id=version_id,
                    source_type="code",
                    source_uri=f"git://{_slugify(project.name)}",
                    ingestion_status=source_status,
                    content_hash=f"hash:{project_id}:code",
                    content_ref=f"minio://nasus/raw/{project_id}/code",
                    evidence_refs=["source:git", "parser:tree-sitter", "index:opengrok"] if ready else [],
                    last_ingested_at=now if ready else None,
                ),
                RawAssetRecord(
                    id=f"raw_{project_id}_us",
                    project_id=project_id,
                    version_id=version_id,
                    source_type="us_doc",
                    source_uri=f"docs://{_slugify(project.name)}/historical-us",
                    ingestion_status=source_status,
                    content_hash=f"hash:{project_id}:us",
                    content_ref=f"minio://nasus/raw/{project_id}/us-docs",
                    evidence_refs=["source:historical-us", "parser:document-chunker"] if ready else [],
                    last_ingested_at=now if ready else None,
                ),
                RawAssetRecord(
                    id=f"raw_{project_id}_tests",
                    project_id=project_id,
                    version_id=version_id,
                    source_type="test_asset",
                    source_uri=f"tests://{_slugify(project.name)}/regression",
                    ingestion_status=source_status,
                    content_hash=f"hash:{project_id}:tests",
                    content_ref=f"minio://nasus/raw/{project_id}/test-assets",
                    evidence_refs=["source:test-cases", "source:automation-scripts"] if ready else [],
                    last_ingested_at=now if ready else None,
                ),
            ]
        elif ready:
            for source in self.raw_assets[project_id]:
                source.ingestion_status = "indexed"
                source.last_ingested_at = source.last_ingested_at or now
                if not source.evidence_refs:
                    if source.source_type == "code":
                        source.evidence_refs = ["source:git", "parser:tree-sitter", "index:opengrok"]
                    elif source.source_type == "us_doc":
                        source.evidence_refs = ["source:historical-us", "parser:document-chunker"]
                    else:
                        source.evidence_refs = ["source:test-cases", "source:automation-scripts"]

        self.baselines[project_id] = [
            BaselineRecord(
                id=baseline_id,
                project_id=project_id,
                kind="official",
                status=status,
                fork_strategy="copy_on_write",
                object_count=object_count,
                relationship_count=relationship_count,
                metric_snapshot_count=metric_count,
                updated_at=now,
            )
        ]

        if ready and self.knowledge_objects.get(project_id):
            objects = self.knowledge_objects[project_id]
            checkout = next((item for item in objects if "CHECKOUT" in item.id), objects[0])
            asset = next((item for item in objects if item.type == "QualityAssetPack"), objects[-1])
            self.context_relationships[project_id] = [
                ContextRelationship(
                    id=f"rel_{project_id}_code_feature",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id=checkout.id,
                    relationship_type="implements",
                    to_object_id="raw:code",
                    confidence=0.89,
                    source_refs=[f"raw:{project_id}:code"],
                ),
                ContextRelationship(
                    id=f"rel_{project_id}_us_feature",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id="US-123",
                    relationship_type="impacts",
                    to_object_id=checkout.id,
                    confidence=0.84,
                    source_refs=[f"raw:{project_id}:us_doc"],
                ),
                ContextRelationship(
                    id=f"rel_{project_id}_tests_feature",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id=asset.id,
                    relationship_type="covers",
                    to_object_id=checkout.id,
                    confidence=0.88,
                    source_refs=[f"raw:{project_id}:test_asset"],
                ),
                ContextRelationship(
                    id=f"rel_{project_id}_evidence_metric",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id=checkout.id,
                    relationship_type="evidenced_by",
                    to_object_id="metric:test_quality",
                    confidence=0.91,
                    source_refs=["run:run_9021", "scenario-pack:r3"],
                ),
            ]
        else:
            self.context_relationships[project_id] = []

        overlay_object_id = self.knowledge_objects[project_id][0].id if self.knowledge_objects.get(project_id) else "context:pending"
        self.context_object_overlays[project_id] = [
            ContextObjectOverlay(
                id=f"overlay_{project_id}_version_risk",
                project_id=project_id,
                baseline_id=baseline_id,
                object_id=overlay_object_id,
                field_path="risk_patterns.checkout_redirect",
                operation="add",
                value_ref="candidate:risk-pattern:checkout-redirect",
                source_refs=["run:run_9021", "approval:approval_442"],
                status="candidate",
            )
        ] if ready else []

        self.quality_metric_snapshots[project_id] = [
            QualityMetricSnapshot(
                id=f"metric_{project_id}_code",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="code_quality",
                metrics={"changed_modules": 3, "critical_paths": 2, "code_risk_score": 67},
                evidence_refs=[f"raw:{project_id}:code"],
                captured_at=now,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_us",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                us_id="us_123" if ready else None,
                metric_group="us_completion_quality",
                metrics={"requirements_clarity": 0.82, "acceptance_criteria_coverage": 0.76},
                evidence_refs=[f"raw:{project_id}:us_doc"],
                captured_at=now,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_tests",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="test_quality",
                metrics={"scenario_coverage": 0.78, "automation_coverage": 0.52, "failed_runs": 1 if ready else 0},
                evidence_refs=[f"raw:{project_id}:test_asset"],
                captured_at=now,
            ),
            QualityMetricSnapshot(
                id=f"metric_{project_id}_release",
                project_id=project_id,
                baseline_id=baseline_id,
                version_id=version_id,
                metric_group="release_readiness",
                metrics={"release_score": project.progress, "open_blockers": project.blocked_items},
                evidence_refs=["approval:approval_442"] if ready else [],
                captured_at=now,
            ),
        ] if ready else []

        self.project_repository.replace_system_image(
            project_id,
            sources=self.raw_assets[project_id],
            baselines=self.baselines[project_id],
            relationships=self.context_relationships[project_id],
            overlays=self.context_object_overlays[project_id],
            metric_snapshots=self.quality_metric_snapshots[project_id],
        )

    def _initialize_system_image(self, project_id: str) -> SystemImageResponse:
        project = self.projects[project_id]
        if not self.knowledge_objects.get(project_id):
            object_prefix = f"OBJ-{project_id.upper().replace('-', '_')}"
            self.knowledge_objects[project_id] = [
                KnowledgeObject(
                    id=f"{object_prefix}-CORE",
                    name=f"{project.name} Core",
                    type="System",
                    branch="Official",
                    confidence="0.72",
                    relations=["Imported Code", "Historical US", "Regression Tests"],
                    evidence=["Source import placeholders"],
                    freshness="just now",
                ),
                KnowledgeObject(
                    id=f"{object_prefix}-US",
                    name="Historical US Baseline",
                    type="Feature",
                    branch="Official",
                    confidence="0.68",
                    relations=[f"{project.name} Core", "Quality Loop"],
                    evidence=["US document import"],
                    freshness="just now",
                ),
                KnowledgeObject(
                    id=f"{object_prefix}-TESTS",
                    name="Regression Quality Pack",
                    type="QualityAssetPack",
                    branch="Official",
                    confidence="0.66",
                    relations=[f"{project.name} Core", "Release Gate"],
                    evidence=["Historical cases", "Automation scripts"],
                    freshness="just now",
                ),
            ]
            self.project_repository.replace_knowledge_objects(project_id, self.knowledge_objects[project_id])

        project.system_image_status = "ready"
        project.progress = max(project.progress, 28)
        self.projects[project_id] = project
        self.project_repository.upsert_project(project)
        version_id = self.versions[project_id][0].id if self.versions.get(project_id) else None
        self._ensure_system_image_state(project_id, ready=True, version_id=version_id)
        self._refresh_project_read_models(project_id)
        return self.get_system_image(project_id)

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
            custom_model=self._current_custom_model(),
        )
        return self.settings

    def update_settings(self, payload: StudioSettingsPatch) -> StudioSettings:
        language = payload.language or self.settings.language
        theme = payload.theme or self.settings.theme
        notification_mode = payload.notification_mode or self.settings.notification_mode
        model_preset = payload.model_preset or self.settings.model_preset
        custom_model = self._current_custom_model()

        if payload.custom_provider_kind is not None:
            custom_model.provider_kind = payload.custom_provider_kind
        if payload.custom_base_url is not None:
            custom_model.base_url = payload.custom_base_url.strip() or None
        if payload.custom_model_name is not None:
            custom_model.model_name = payload.custom_model_name.strip()
        if payload.custom_api_key is not None:
            raw_api_key = payload.custom_api_key.strip()
            self.custom_model_api_key_encrypted = self.settings_persistence.encrypt_api_key(raw_api_key)
            custom_model.has_api_key = bool(raw_api_key)
            custom_model.api_key_masked = self.settings_persistence.mask_api_key(raw_api_key)
        else:
            custom_model.has_api_key = bool(self.custom_model_api_key_encrypted)
            if not custom_model.has_api_key:
                custom_model.api_key_masked = None

        self.settings = self.llm.build_settings(
            language=language,
            theme=theme,
            notification_mode=notification_mode,
            model_preset=model_preset,
            custom_model=custom_model,
        )
        self.settings_repository.save(self.settings, self.custom_model_api_key_encrypted)
        return self.settings

    async def test_settings_connection(
        self,
        payload: Optional[StudioSettingsConnectionTestRequest] = None,
    ) -> StudioSettingsConnectionTestResponse:
        request = payload or StudioSettingsConnectionTestRequest(model_preset=self.settings.model_preset)
        custom_model = self._current_custom_model()
        if request.custom_provider_kind is not None:
            custom_model.provider_kind = request.custom_provider_kind
        if request.custom_base_url is not None:
            custom_model.base_url = request.custom_base_url.strip() or None
        if request.custom_model_name is not None:
            custom_model.model_name = request.custom_model_name.strip()

        custom_api_key = self._get_custom_model_api_key()
        if request.custom_api_key is not None:
            custom_api_key = request.custom_api_key.strip()
        custom_model.has_api_key = bool(custom_api_key)
        custom_model.api_key_masked = self.settings_persistence.mask_api_key(custom_api_key)

        settings = self.llm.build_settings(
            language=self.settings.language,
            theme=self.settings.theme,
            notification_mode=self.settings.notification_mode,
            model_preset=request.model_preset or self.settings.model_preset,
            custom_model=custom_model,
        )
        return await self.llm.test_connection(settings=settings, custom_api_key=custom_api_key)

    def _current_custom_model(self) -> CustomModelConfig:
        custom_model = self.settings.custom_model.model_copy(deep=True)
        custom_model.has_api_key = bool(self.custom_model_api_key_encrypted)
        if not custom_model.has_api_key:
            custom_model.api_key_masked = None
        return custom_model

    def _get_custom_model_api_key(self) -> str:
        try:
            return self.settings_persistence.decrypt_api_key(self.custom_model_api_key_encrypted)
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
        self._ensure_system_image_state(project.id, ready=False)
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
        self._refresh_project_read_models(project_id)
        project = self.projects[project_id]
        baseline = self.baselines[project_id][0] if self.baselines.get(project_id) else None
        source_counts = {
            source_type: sum(1 for source in self.raw_assets[project_id] if source.source_type == source_type)
            for source_type in ["code", "us_doc", "test_asset"]
        }
        summary = (
            f"{project.name} system image is {project.system_image_status}. "
            f"Sources: code={source_counts['code']}, us_doc={source_counts['us_doc']}, "
            f"test_asset={source_counts['test_asset']}. "
            f"Baseline {baseline.id if baseline else 'not initialized'} has "
            f"{baseline.object_count if baseline else 0} objects and "
            f"{baseline.relationship_count if baseline else 0} relationships."
        )
        return SystemImageResponse(
            project=project,
            summary=summary,
            baselines=self.baselines[project_id],
            sources=self.raw_assets[project_id],
            objects=self.knowledge_objects[project_id],
            relationships=self.context_relationships[project_id],
            overlays=self.context_object_overlays[project_id],
            metric_snapshots=self.quality_metric_snapshots[project_id],
        )

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
        invocation = ToolInvocation(
            id=f"tool_{uuid4().hex[:10]}",
            conversation_id=payload.conversation_id,
            tool_id=payload.tool_id,
            status="pending",
            summary=f"Preparing {payload.tool_id}",
            initiator_surface=payload.initiator_surface,
            initiator_actor=payload.initiator_actor,
            target_scope=payload.target_scope,
            input_payload=payload.input,
        )
        self.tool_invocations[invocation.id] = invocation
        self.conversation_repository.upsert_tool_invocation(invocation)

        if payload.tool_id == "project.create":
            name = str(payload.input.get("name") or "New Quality Project")
            await self._run_project_create_invocation(invocation.id, name)
        elif payload.tool_id == "version.create":
            project_id = str(payload.input.get("project_id") or "")
            version_name = str(payload.input.get("name") or "New Version")
            await self._run_version_create_invocation(invocation.id, project_id, version_name)
        elif payload.tool_id == "quality.scenario.generate":
            project_id = str(payload.input.get("project_id") or "")
            us_id = str(payload.input.get("us_id") or "")
            await self._run_scenario_invocation(invocation.id, project_id, us_id)
        elif payload.tool_id == "baseline.initialize":
            project_id = str(payload.input.get("project_id") or "")
            await self._run_baseline_initialize_invocation(invocation.id, project_id)
        elif payload.tool_id.startswith("query."):
            await self._run_query_invocation(invocation.id)
        else:
            invocation.status = "failed"
            invocation.summary = f"Unknown tool: {payload.tool_id}"
            invocation.result = ToolResult(
                invocation_id=invocation.id,
                status="failed",
                summary=invocation.summary,
            )
            self.conversation_repository.upsert_tool_invocation(invocation)

        return invocation

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return self.tool_invocations[invocation_id]

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
        return goal

    def get_agent_goal(self, goal_id: str) -> AgentGoal:
        return self.agent_goals[goal_id]

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

    def _build_summary_checkpoint(self, conversation: ConversationSession) -> Optional[ConversationSummaryCheckpoint]:
        text_messages = self._recent_text_messages(conversation)
        if len(text_messages) < 8:
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
        if len(checkpoint_candidates) < 6:
            return None

        messages_to_summarize = checkpoint_candidates[:-4]
        if len(messages_to_summarize) < 4:
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
            created_by="system",
            created_at=_now_iso(),
        )

    def _conversation_history_snapshot(self, conversation: ConversationSession) -> str:
        segments: list[str] = []
        latest_checkpoint = self._latest_checkpoint_for_conversation(conversation.id)
        if latest_checkpoint:
            segments.append(f"Checkpoint summary:\n{latest_checkpoint.summary_text}")

        recent_messages = self._recent_text_messages(conversation)[-6:]
        if recent_messages:
            turns = []
            for message in recent_messages:
                text = " ".join(block.text.strip() for block in message.blocks if block.text.strip())
                if not text:
                    continue
                actor = "User" if message.role == "user" else "Agent"
                normalized_text = re.sub(r"\s+", " ", text)
                turns.append(f"{actor}: {normalized_text}")
            if turns:
                segments.append("Recent turns:\n" + "\n".join(turns))

        bindings = [
            binding.candidate_object_ref
            for binding in self.session_knowledge_bindings.values()
            if binding.conversation_id == conversation.id
        ]
        if bindings:
            segments.append("Session knowledge:\n" + "\n".join(f"- {ref}" for ref in bindings))

        if not segments:
            return "No prior conversation history."

        return "\n\n".join(segments)

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
    ) -> None:
        version_key = f"{entity_type}:{entity_id}"
        self.entity_versions[version_key] += 1
        event = EventPayload(
            event_id=f"evt_{uuid4().hex[:10]}",
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_version=self.entity_versions[version_key],
            mutation_kind=mutation_kind,  # type: ignore[arg-type]
            patch=patch,
            query_keys=query_keys,
        )
        await self._get_or_create_event_queue(conversation_id).put(event)

    async def _push_goal_event(
        self,
        goal_id: str,
        event_type: str,
        mutation_kind: str,
        patch: Dict[str, Any],
        query_keys: List[List[str]],
    ) -> None:
        version_key = f"agent_goal:{goal_id}"
        self.entity_versions[version_key] += 1
        event = EventPayload(
            event_id=f"evt_{uuid4().hex[:10]}",
            event_type=event_type,
            entity_type="agent_goal",
            entity_id=goal_id,
            entity_version=self.entity_versions[version_key],
            mutation_kind=mutation_kind,  # type: ignore[arg-type]
            patch=patch,
            query_keys=query_keys,
        )
        await self._get_or_create_goal_queue(goal_id).put(event)

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
        return (
            "You are Nasus Agent, an agent-first quality orchestration assistant. "
            "Be concise, grounded in the provided workspace context, and action-oriented. "
            "Explain project, version, run, governance, or knowledge status clearly. "
            "Do not invent objects that are not present in the context snapshot."
        )

    def _conversation_context_snapshot(self, conversation: ConversationSession) -> str:
        sections: list[str] = [f"space_type={conversation.space_type}", f"space_id={conversation.space_id}"]

        if conversation.project_id and conversation.project_id in self.projects:
            project = self.projects[conversation.project_id]
            sections.append(
                f"project={project.name}; progress={project.progress}; risk={project.risk}; blocked_items={project.blocked_items}; pending_approvals={project.pending_approvals}; system_image={project.system_image_status}"
            )

        if conversation.project_id and conversation.project_id in self.versions and self.versions[conversation.project_id]:
            version = self.versions[conversation.project_id][0]
            sections.append(
                f"version={version.name}; status={version.status}; us_closed={version.us_closed}; us_total={version.us_total}; pending_runs={version.pending_runs}; pending_approvals={version.pending_approvals}"
            )

        if conversation.us_id:
            us_item = next(
                (
                    item
                    for items in self.us_items.values()
                    for item in items
                    if item.id == conversation.us_id
                ),
                None,
            )
            if us_item is not None:
                sections.append(
                    f"us={us_item.id}; title={us_item.title}; owner={us_item.owner}; status={us_item.status}; risk={us_item.risk}; progress={us_item.progress}; next_action={us_item.next_action}"
                )
                for lane in self.asset_lanes.get(us_item.id, []):
                    sections.append(f"asset_lane={lane.label}; status={lane.status}; summary={lane.summary}")

        if conversation.project_id:
            for run in self.runs.get(conversation.project_id, [])[:3]:
                sections.append(f"run={run.id}; title={run.title}; status={run.status}; channel={run.channel}; summary={run.summary}")
            for approval in self.approvals.get(conversation.project_id, [])[:3]:
                sections.append(f"approval={approval.id}; title={approval.title}; status={approval.status}; summary={approval.summary}")
            for item in self.knowledge_objects.get(conversation.project_id, [])[:3]:
                sections.append(f"knowledge={item.id}; name={item.name}; branch={item.branch}; type={item.type}; freshness={item.freshness}")

        return "\n".join(sections)

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
        history_snapshot = self._conversation_history_snapshot(conversation)
        recent_turn_count = len(self._recent_text_messages(conversation)[-6:])
        checkpoint_count = sum(
            1 for checkpoint in self.conversation_summary_checkpoints.values() if checkpoint.conversation_id == conversation.id
        )
        reply = await self.llm.generate_reply(
            settings=self.get_settings(),
            system_prompt=system_prompt or self._conversation_system_prompt(conversation),
            user_message=user_message,
            context_snapshot=self._conversation_context_snapshot(conversation),
            history_snapshot=history_snapshot,
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
                "memory_recent_turns": recent_turn_count,
                "memory_checkpoint_count": checkpoint_count,
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
        decision = self.orchestrator.plan(conversation, content)

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
            goal = await self.agent_loop_runtime.start_goal(conversation_id, decision.agent_goal)
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

    async def _run_project_create_invocation(self, invocation_id: str, project_name: str) -> None:
        invocation = self.tool_invocations[invocation_id]
        await self._emit_tool_status(
            invocation_id,
            "running",
            f"Creating project {project_name}",
            [["build"], ["dashboard"], ["welcome"], ["projects"]],
        )
        await asyncio.sleep(0.2)
        project = self.create_project(project_name)
        if invocation.conversation_id:
            await self.append_message(
                invocation.conversation_id,
                "assistant",
                f"I created the draft project **{project.name}**. Next we should connect a Git repository, import US documents, and confirm whether UX boards or historical quality assets are available before initializing the Official System Image.",
            )
        await self._emit_tool_status(
            invocation_id,
            "completed",
            f"Created draft project {project.name}",
            [["build"], ["dashboard"], ["welcome"], ["projects"]],
            ToolResult(
                invocation_id=invocation_id,
                status="completed",
                summary=f"Created draft project {project.name}",
                object_refs=[f"project:{project.id}"],
                next_recommended_tools=["baseline.initialize", "version.create"],
            ),
        )

    async def _run_version_create_invocation(self, invocation_id: str, project_id: str, version_name: str) -> None:
        invocation = self.tool_invocations[invocation_id]
        await self._emit_tool_status(
            invocation_id,
            "running",
            f"Creating version branch {version_name}",
            [["project", project_id], ["dashboard"], ["welcome"]],
        )
        await asyncio.sleep(0.2)
        version = self.create_version(project_id, version_name)
        if invocation.conversation_id:
            await self.append_message(
                invocation.conversation_id,
                "assistant",
                f"The version branch **{version.name}** is active. US board, risk pulse, and asset pack generation are now available in Version Space.",
            )
        await self._emit_tool_status(
            invocation_id,
            "completed",
            f"Created version {version.name}",
            [["project", project_id], ["dashboard"], ["welcome"]],
            ToolResult(
                invocation_id=invocation_id,
                status="completed",
                summary=f"Created version {version.name}",
                object_refs=[f"version:{version.id}"],
                next_recommended_tools=["quality.scenario.generate"],
            ),
        )

    async def _run_baseline_initialize_invocation(self, invocation_id: str, project_id: str) -> None:
        invocation = self.tool_invocations[invocation_id]
        if not project_id:
            invocation.status = "failed"
            invocation.summary = "project_id is required to initialize a system image"
            invocation.result = ToolResult(
                invocation_id=invocation.id,
                status="failed",
                summary=invocation.summary,
            )
            self.conversation_repository.upsert_tool_invocation(invocation)
            return

        await self._emit_tool_status(
            invocation_id,
            "running",
            "Initializing Official System Image from code, US docs, and test assets",
            [["project", project_id], ["system-image", project_id], ["dashboard"]],
        )
        await asyncio.sleep(0.2)
        system_image = self._initialize_system_image(project_id)
        if invocation.conversation_id:
            await self.append_message(
                invocation.conversation_id,
                "assistant",
                (
                    f"The Official System Image for **{system_image.project.name}** is ready. "
                    f"I indexed {len(system_image.sources)} source groups, materialized "
                    f"{len(system_image.objects)} context objects, {len(system_image.relationships)} relationships, "
                    f"and {len(system_image.metric_snapshots)} quality metric snapshots."
                ),
            )
        await self._emit_tool_status(
            invocation_id,
            "completed",
            f"Initialized system image for {system_image.project.name}",
            [["project", project_id], ["system-image", project_id], ["dashboard"], ["knowledge", project_id]],
            ToolResult(
                invocation_id=invocation_id,
                status="completed",
                summary=system_image.summary,
                object_refs=[f"project:{project_id}", f"baseline:{system_image.baselines[0].id}"],
                evidence_refs=[source.id for source in system_image.sources],
                next_recommended_tools=["query.system_image.status", "version.create"],
            ),
        )

    async def _run_scenario_invocation(self, invocation_id: str, project_id: str, us_id: str) -> None:
        invocation = self.tool_invocations[invocation_id]
        if not invocation.conversation_id:
            return

        conversation = self.conversations.get(invocation.conversation_id)
        if not project_id and conversation:
            project_id = conversation.project_id or ""
        if not us_id and project_id:
            first_us = next(iter(self.us_items.get(project_id, [])), None)
            us_id = first_us.id if first_us is not None else ""
        if not project_id or not us_id:
            await self.append_message(
                invocation.conversation_id,
                "assistant",
                "I need at least one imported US work item before I can start the quality loop. Import US documents first, then I can generate scenarios, cases, automation, and release evidence.",
                metadata={"planner_kind": "quality_loop_blocked", "missing_context": ["us_work_item"]},
            )
            await self._emit_tool_status(
                invocation_id,
                "failed",
                "US work item is required before scenario generation",
                [["conversation", invocation.conversation_id], ["project", project_id]],
                ToolResult(
                    invocation_id=invocation_id,
                    status="failed",
                    summary="US work item is required before scenario generation",
                    next_recommended_tools=["project.import_us_docs"],
                ),
            )
            return

        existing_goal_id = invocation.input_payload.get("agent_goal_id")
        if isinstance(existing_goal_id, str) and existing_goal_id in self.agent_goals:
            goal = self.agent_goals[existing_goal_id]
        else:
            goal = self.create_agent_goal(
                AgentGoalCreateRequest(
                    conversation_id=invocation.conversation_id,
                    title="Generate scenario pack",
                    summary="Building a structured scenario set from system image, US context, and recent change evidence.",
                    project_id=project_id,
                    us_id=us_id,
                )
            )
        goal.steps[0].status = "running"
        goal.steps[0].phase = "thinking"
        goal.steps[0].selected_tool_id = invocation.tool_id
        goal.steps[0].tool_invocation_id = invocation.id
        goal.status = "running"
        self.conversation_repository.upsert_goal(goal)
        self._upsert_goal_in_conversation(goal)

        await self._emit_tool_status(
            invocation_id,
            "running",
            "Generating test scenarios",
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id], ["project", project_id]],
        )
        await self._push_event(
            invocation.conversation_id,
            "agent.goal.updated",
            "agent_goal",
            goal.id,
            "replace",
            {"status": "running"},
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id]],
        )
        await self._push_goal_event(
            goal.id,
            "agent.goal.updated",
            "replace",
            {"status": "running"},
            [["agent-goal", goal.id]],
        )

        await asyncio.sleep(0.2)
        goal.steps[0].status = "completed"
        goal.steps[0].decision = "continue"
        goal.steps[1].status = "running"
        goal.steps[1].phase = "observing"
        goal.steps[1].tool_invocation_id = invocation.id
        goal.steps_completed = 1
        self.conversation_repository.upsert_goal(goal)
        self._upsert_goal_in_conversation(goal)
        await self._push_event(
            invocation.conversation_id,
            "agent.goal.updated",
            "agent_goal",
            goal.id,
            "patch",
            {"current_step": "Review impact"},
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id]],
        )
        await self._push_goal_event(
            goal.id,
            "agent.goal.updated",
            "patch",
            {"current_step": "Review impact"},
            [["agent-goal", goal.id]],
        )

        await asyncio.sleep(0.2)
        goal.steps[1].status = "completed"
        goal.steps[1].decision = "continue"
        goal.steps[2].status = "running"
        goal.steps[2].phase = "deciding"
        goal.steps[2].tool_invocation_id = invocation.id
        goal.steps_completed = 2
        self.conversation_repository.upsert_goal(goal)
        self._upsert_goal_in_conversation(goal)
        planning_update = await self._generate_llm_content(
            conversation=self.conversations[invocation.conversation_id],
            user_message="Summarize the current scenario planning progress for this US.",
            fallback_text="I narrowed the scope to checkout fallback, saved-card recovery, and post-redirect assertion coverage. I am now drafting the scenario pack with explicit recovery and fraud-edge branches.",
            system_prompt="You are Nasus Agent. Summarize scenario planning progress in one concise paragraph and keep it grounded in the provided workspace context.",
        )
        await self.append_message(
            invocation.conversation_id,
            "assistant",
            planning_update["content"],
            metadata=planning_update["metadata"],
        )

        await asyncio.sleep(0.2)
        goal.steps[2].status = "completed"
        goal.steps_completed = 3
        goal.status = "completed"
        self.conversation_repository.upsert_goal(goal)
        self._upsert_goal_in_conversation(goal)
        for lane in self.asset_lanes.get(us_id, []):
            if lane.id == "lane_scenarios":
                lane.status = "approved"
                lane.summary = "8 scenarios grouped into happy path, redirect recovery, risk edges, and observability checks."
                lane.updated_at = "2026-03-27 19:10"
            if lane.id == "lane_cases":
                lane.status = "ready_for_review"
                lane.summary = "12 cases suggested from the approved scenario structure."
                lane.updated_at = "2026-03-27 19:10"
        self.project_repository.replace_asset_lanes(project_id, us_id, self.asset_lanes.get(us_id, []))
        completion_update = await self._generate_llm_content(
            conversation=self.conversations[invocation.conversation_id],
            user_message="Summarize the completed scenario generation result and the best next action.",
            fallback_text="Scenario generation is complete. The scenario lane is now approved and the case lane is ready for review, so we can continue into case generation or move directly toward automation drafting.",
            system_prompt="You are Nasus Agent. Summarize completed scenario generation with a short next-step recommendation.",
        )
        await self.append_message(
            invocation.conversation_id,
            "assistant",
            completion_update["content"],
            metadata=completion_update["metadata"],
        )
        await self._push_event(
            invocation.conversation_id,
            "agent.goal.updated",
            "agent_goal",
            goal.id,
            "replace",
            {"status": "completed"},
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id]],
        )
        await self._push_goal_event(
            goal.id,
            "agent.goal.updated",
            "replace",
            {"status": "completed"},
            [["agent-goal", goal.id]],
        )
        await self._emit_tool_status(
            invocation_id,
            "completed",
            "Generated scenario pack",
            [["conversation", invocation.conversation_id], ["workspace", project_id, us_id], ["project", project_id]],
            ToolResult(
                invocation_id=invocation_id,
                status="completed",
                summary="Generated scenario pack",
                object_refs=[f"us:{us_id}", "quality_asset_pack:scenario"],
                next_recommended_tools=["quality.case.generate", "automation.generate"],
            ),
        )

    async def _run_query_invocation(self, invocation_id: str) -> None:
        invocation = self.tool_invocations[invocation_id]
        conversation = self.conversations.get(invocation.conversation_id or "")
        project_id = str(invocation.input_payload.get("project_id") or (conversation.project_id if conversation else "") or "")
        version_id = str(invocation.input_payload.get("version_id") or (conversation.version_id if conversation else "") or "")
        us_id = str(invocation.input_payload.get("us_id") or (conversation.us_id if conversation else "") or "")

        fallback_text = "I reviewed the current workspace state and prepared a concise summary."
        query_keys: list[list[str]] = [["conversation", invocation.conversation_id]] if invocation.conversation_id else []
        effective_query_keys = query_keys or ([["conversation", invocation.conversation_id]] if invocation.conversation_id else [])

        if invocation.tool_id == "query.dashboard.progress":
            fallback_text = self._build_dashboard_summary("")
            query_keys.extend([["dashboard"], ["welcome"]])
        elif invocation.tool_id == "query.project.status" and project_id:
            fallback_text = self._project_status_summary(project_id)
            query_keys.extend([["project", project_id], ["dashboard"]])
        elif invocation.tool_id == "query.version.status" and project_id and version_id:
            fallback_text = self._version_status_summary(project_id, version_id)
            query_keys.extend([["project", project_id], ["version", version_id]])
        elif invocation.tool_id == "query.workspace.status" and us_id:
            fallback_text = self._workspace_status_summary(us_id)
            if project_id:
                query_keys.append(["workspace", project_id, us_id])
        elif invocation.tool_id == "query.knowledge.status" and project_id:
            fallback_text = self._knowledge_status_summary(project_id)
            query_keys.extend([["knowledge", project_id], ["project", project_id]])
        elif invocation.tool_id == "query.system_image.status" and project_id:
            fallback_text = self._system_image_status_summary(project_id)
            query_keys.extend([["system-image", project_id], ["knowledge", project_id], ["project", project_id]])
        elif invocation.tool_id == "query.run.status" and project_id:
            fallback_text = self._run_status_summary(project_id)
            query_keys.extend([["runs", project_id], ["project", project_id]])
        elif invocation.tool_id == "query.governance.status" and project_id:
            fallback_text = self._governance_status_summary(project_id)
            query_keys.extend([["governance", project_id], ["project", project_id]])

        await self._emit_tool_status(
            invocation_id,
            "running",
            f"Querying {invocation.tool_id}",
            effective_query_keys,
        )
        await asyncio.sleep(0.05)

        content = fallback_text
        metadata: dict[str, Any] = {"planner_kind": "tool_query", "tool_id": invocation.tool_id}
        if conversation:
            llm_update = await self._generate_llm_content(
                conversation=conversation,
                user_message=f"Summarize the current state for {invocation.tool_id}.",
                fallback_text=fallback_text,
                system_prompt="You are Nasus Agent. Summarize the current domain state concisely and recommend the next best action.",
            )
            content = llm_update["content"]
            metadata = {**metadata, **llm_update["metadata"]}

        if invocation.conversation_id:
            await self.append_message(
                invocation.conversation_id,
                "assistant",
                content,
                metadata=metadata,
            )

        await self._emit_tool_status(
            invocation_id,
            "completed",
            f"Completed {invocation.tool_id}",
            effective_query_keys,
            ToolResult(
                invocation_id=invocation_id,
                status="completed",
                summary=fallback_text,
                object_refs=[f"project:{project_id}"] if project_id else [],
                next_recommended_tools=["quality.scenario.generate"] if invocation.tool_id == "query.workspace.status" else [],
            ),
        )

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

    async def interrupt_agent_goal(self, goal_id: str) -> AgentGoal:
        goal = self.agent_goals[goal_id]
        goal.status = "paused"
        goal.pause_reason = "user_interrupt"
        self.conversation_repository.upsert_goal(goal)
        self._upsert_goal_in_conversation(goal)
        await self._push_goal_event(goal_id, "agent.goal.updated", "patch", {"status": "paused", "pause_reason": "user_interrupt"}, [["agent-goal", goal_id]])
        if goal.conversation_id:
            await self._push_event(goal.conversation_id, "agent.goal.updated", "agent_goal", goal_id, "patch", {"status": "paused", "pause_reason": "user_interrupt"}, [["conversation", goal.conversation_id]])
        return goal

    async def resume_agent_goal(self, goal_id: str) -> AgentGoal:
        goal = self.agent_goals[goal_id]
        goal.status = "running"
        goal.pause_reason = None
        self.conversation_repository.upsert_goal(goal)
        self._upsert_goal_in_conversation(goal)
        await self._push_goal_event(goal_id, "agent.goal.updated", "patch", {"status": "running"}, [["agent-goal", goal_id]])
        if goal.conversation_id:
            await self._push_event(goal.conversation_id, "agent.goal.updated", "agent_goal", goal_id, "patch", {"status": "running"}, [["conversation", goal.conversation_id]])
        return goal

    async def add_goal_feedback(self, goal_id: str, feedback: str) -> AgentGoal:
        goal = self.agent_goals[goal_id]
        summary = f"{goal.summary} Feedback: {feedback}"
        goal.summary = summary
        self.conversation_repository.upsert_goal(goal)
        self._upsert_goal_in_conversation(goal)
        await self._push_goal_event(goal_id, "agent.goal.feedback", "patch", {"feedback": feedback}, [["agent-goal", goal_id]])
        if goal.conversation_id:
            await self.append_message(goal.conversation_id, "assistant", f"Feedback acknowledged for goal **{goal.title}**: {feedback}")
        return goal

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
