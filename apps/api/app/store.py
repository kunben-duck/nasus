from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional

from .application.agent.loop import AgentLoopRuntime
from .application.agent.conversation_summary import (
    ConversationSummaryCheckpointApplicationService,
    ConversationSummaryCheckpointService,
)
from .application.agent.explanations import AgentGoalExplanationApplicationService
from .application.agent.memory import AgentMemoryManager
from .application.agent.conversations import ConversationManagementApplicationService
from .application.agent.goal_projection import AgentGoalProjectionApplicationService
from .application.agent.messages import ConversationMessageApplicationService
from .application.agent.message_writer import ConversationMessageWriterApplicationService
from .application.agent.planner import DeterministicAgentPlanner, LLMStructuredAgentPlanner
from .application.agent.planner_context import AgentPlannerContextApplicationService
from .application.agent.replies import AgentReplyApplicationService
from .application.agent.lifecycle import AgentService
from .application.agent.plans import AgentGoalPlanCompiler
from .application.agent.use_cases import AgentApplicationService
from .application.platform.account_models import UserProfile
from .application.platform.actor_context import current_user
from .application.platform.model_settings import (
    ModelConfigCreateRequest,
    ModelConfigTestRequest,
    ModelConfigUpdateRequest,
    StudioSettings,
    StudioSettingsConnectionTestRequest,
    StudioSettingsConnectionTestResponse,
    StudioSettingsPatch,
)
from .application.platform.model_configurations import ModelConfigurationApplicationService
from .application.platform.demo_seed import DemoSeedApplicationService
from .application.platform.documentation_catalog import product_documentation_entries
from .application.platform.governance import GovernanceApplicationService
from .application.platform.distributed_state_sync import (
    DistributedStateSynchronizationApplicationService,
    DistributedStateSynchronizationDependencies,
)
from .application.platform.project_access import ProjectAccessApplicationService
from .application.platform.scope_resolution import ProjectScopeResolutionApplicationService
from .application.platform.project_workspace import ProjectWorkspaceApplicationService
from .application.platform.read_model_refresh import ProjectReadModelRefreshApplicationService
from .application.platform.top_level_content import TopLevelContentApplicationService
from .application.platform.query_tools import QueryToolApplicationService
from .application.platform.tool_authorization import (
    ToolInvocationAuthorizationApplicationService,
)
from .application.platform.tool_handlers import (
    ToolHandlerDependencies,
    build_tool_handler_registry,
)
from .application.platform.tool_projection import ToolInvocationProjectionApplicationService
from .application.platform.tool_models import (
    AuditEvent,
    EventPayload,
    ToolDefinition,
    ToolInvocation,
    ToolInvocationRequest,
)
from .domain.agent.name_extraction import extract_project_name, extract_version_name
from .domain.agent.state_machine import AgentGoalStateMachine
from .infrastructure.persistence.database import init_database
from .infrastructure.persistence.project_mutation_lock import (
    SQLAlchemyProjectMutationLock,
)
from .infrastructure.agent import (
    AgentApplicationRuntimeAdapters,
    SQLAlchemyAgentApplicationPorts,
)
from .infrastructure.workflow.agent_workflow_factory import build_agent_workflow_runtime
from .infrastructure.workflow.agent_graph_factory import build_agent_graph_runtime
from .infrastructure.llm import LLMGateway, LLMQualityGenerationAdapter
from .infrastructure.platform import (
    CallablePlatformEventEntityReader,
    SQLAlchemyProjectScopeReadModel,
    RepositoryBackedProjectReadModelProjection,
    SQLAlchemyDemoSeedWorkspace,
    EventStreamWakeUpState,
    PlatformEventEntityAdapters,
    SQLAlchemyToolApprovalVerificationState,
    SQLAlchemyGovernanceCommandRepository,
    SQLAlchemyGovernanceWorkspace,
    SQLAlchemyToolInvocationProjectionState,
    SQLAlchemyAuditEventPersistence,
    SQLAlchemyModelConfigurationState,
    SQLAlchemyToolInvocationApplicationState,
    SQLAlchemyToolInvocationRuntimeState,
    SSEWakeUpBuffer,
    SQLAlchemyAgentQueryReadModel,
    SQLAlchemyProjectAccessReadModel,
    SQLAlchemyProjectWorkspaceReadModel,
    StaticToolCatalogRuntimeAdapter,
    event_stream_runtime_settings_from_env,
)
from .infrastructure.platform.top_level_content import SQLAlchemyTopLevelContentReadModel
from .infrastructure.storage import ObjectStorage
from .infrastructure.system_image import (
    CodebaseMemoryCodeIntelligenceAdapter,
    CompatibilitySystemImageIngestionProjection,
    CompositeCodeIntelligenceAdapter,
    DurableSystemImageWorkspaceAdapters,
    GitSourceConnector,
    ObjectStorageSourceConnector,
    ObjectStorageSourceUploadStorage,
    SQLAlchemySystemImageRetrievalIndex,
    SQLAlchemySystemImageRetriever,
    SQLAlchemySystemImageWorkspace,
    SourceIngestionService,
    TreeSitterCodeIntelligenceAdapter,
)
from .infrastructure.config import CodeGraphConfig
from .application.agent.agent_models import (
    AgentGoal,
    AgentGoalCreateRequest,
    AgentMemoryItem,
    AgentSwarmRun,
    ConversationArchiveRequest,
    ConversationMessage,
    ConversationMergeRequest,
    ConversationSession,
    ConversationSummaryCheckpoint,
)
from .application.quality_loop.quality_models import (
    ApprovalDetail,
    ApprovalSummary,
    AssetLane,
    ExecutionEvidence,
    FailureReport,
    QualityAssetPack,
    QualityLoopState,
    ReleaseDecision,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    USItem,
)
from .application.quality_loop.governance_models import MergedResolution
from .application.system_image.system_image_models import (
    BaselineRecord,
    ContextObjectOverlay,
    ContextRelationship,
    EmbeddingRecord,
    KnowledgeObject,
    QualityProfile,
    QualityMetricSnapshot,
    RawAssetChunk,
    RawAssetRecord,
    RerankRecord,
    RetrievalRun,
    SystemImageResponse,
    TaskContext,
)
from .application.system_image.use_cases import SystemImageApplicationService
from .application.system_image.source_uploads import SourceUploadApplicationService
from .application.platform.project_models import ProjectCard, VersionSummary
from .application.platform.read_models import (
    BuildResponse,
    DashboardResponse,
    DocumentationEntry,
    ProjectWorkspaceResponse,
    ReadModelSummaryService,
    WelcomeResponse,
)
from .application.agent.swarm import AgentSwarmCoordinator
from .application.quality_loop import (
    ProjectVersionApplicationService,
    QualityAssetPackApplicationService,
    QualityAssetProgressApplicationService,
    QualityFailureReportApplicationService,
    QualityImageUpdateApplicationService,
    QualityLoopApplicationService,
    QualityLoopContextQueryApplicationService,
    QualityLoopScopeQueryApplicationService,
    QualityLoopVersionContextApplicationService,
    QualityReleaseReadinessApplicationService,
    QualityRunExecutionApplicationService,
    QualityStepCompletionApplicationService,
)
from .infrastructure.persistence.conversation_repository import ConversationRepository
from .infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from .infrastructure.persistence.project_repository import ProjectRepository
from .infrastructure.persistence.project_access_repository import ProjectAccessRepository
from .infrastructure.persistence.quality_loop_repository import QualityLoopRepository
from .infrastructure.persistence.release_readiness_repository import (
    SQLAlchemyReleaseReadinessRepository,
)
from .infrastructure.persistence.model_config_test_grant_repository import (
    SQLAlchemyModelConfigTestGrantRepository,
)
from .infrastructure.persistence.llm_call_repository import SQLAlchemyLLMCallRepository
from .infrastructure.persistence.prompt_repository import SQLAlchemyPromptRegistry
from .infrastructure.persistence.settings_repository import SettingsRepository
from .infrastructure.persistence.system_image_repository import SystemImageRepository
from .infrastructure.config.runtime_config import current_runtime_profile
from .infrastructure.config.runtime_config import demo_seed_enabled
from .infrastructure.persistence.settings_store import SettingsPersistence
from .infrastructure.quality_loop import (
    SQLAlchemyProjectVersionWorkspace,
    SQLAlchemyQualityAssetPackWorkspace,
    SQLAlchemyQualityAssetProgressWorkspace,
    SQLAlchemyQualityFailureWorkspace,
    SQLAlchemyQualityLoopContextWorkspace,
    SQLAlchemyQualityLoopScopeWorkspace,
    SQLAlchemyQualityRunWorkspace,
)
from .infrastructure.runner import RunOrchestrator
from .application.system_image.service import SystemImageService
from .application.platform.tool_catalog import core_tool_definitions, system_image_tool_definitions
from .application.platform.approval_verifier import ToolApprovalVerifierApplicationService
from .application.platform.audit_events import PlatformAuditApplicationService
from .application.platform.llm_calls import LLMCallAuditApplicationService
from .application.platform.prompts import PromptRegistryApplicationService
from .application.platform.events import PlatformEventApplicationService
from .application.platform.event_streams import PlatformEventStreamApplicationService
from .domain.platform.tool_governance import ToolGovernance
from .domain.platform.prompt_registry import BUILTIN_PROMPTS
from .application.platform.runtime import ToolInvocationRuntime
from .application.platform.tool_invocations import ToolInvocationApplicationService


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeAssembly:
    """Process-local dependency graph for production application services.

    This object owns composition only. Delivery adapters resolve bounded-context
    application services from ``ApplicationContainer`` instead of calling the
    compatibility facade defined below.
    """

    def __init__(self) -> None:
        init_database()
        self.event_stream_lock = RLock()
        self.system_image_ingestion_lock = SQLAlchemyProjectMutationLock(
            "system-image-ingestion"
        )
        self.event_queues: Dict[str, asyncio.Queue[EventPayload]] = {}
        self.agent_goal_queues: Dict[str, asyncio.Queue[EventPayload]] = {}
        self.agent_swarm_queues: Dict[str, asyncio.Queue[EventPayload]] = {}
        self.entity_versions: Dict[str, int] = defaultdict(int)
        self._default_user = UserProfile(
            id="user_001",
            name="Uben",
            email="uben@example.com",
            role="platform_admin",
        )
        self.llm_call_repository = SQLAlchemyLLMCallRepository()
        self.llm_call_audit = LLMCallAuditApplicationService(
            self.llm_call_repository
        )
        self.prompt_repository = SQLAlchemyPromptRegistry()
        self.prompt_registry = PromptRegistryApplicationService(
            self.prompt_repository
        )
        self.prompt_registry.register_defaults(BUILTIN_PROMPTS)
        self.llm = LLMGateway(self.llm_call_repository)
        self.settings_repository = SettingsRepository()
        self.model_config_test_grant_repository = (
            SQLAlchemyModelConfigTestGrantRepository()
        )
        self.conversation_repository = ConversationRepository()
        self.event_outbox_repository = EventOutboxRepository()
        self.system_image_repository = SystemImageRepository()
        self.quality_loop_repository = QualityLoopRepository()
        self.release_readiness_repository = SQLAlchemyReleaseReadinessRepository()
        self.project_repository = ProjectRepository(
            system_image_repository=self.system_image_repository,
            quality_loop_repository=self.quality_loop_repository,
        )
        self.project_access_repository = ProjectAccessRepository()
        self.project_access_read_model = SQLAlchemyProjectAccessReadModel()
        default_actor = self._default_user
        self.project_access = ProjectAccessApplicationService(
            self.project_access_repository,
            self.project_access_read_model,
            lambda: current_user(default_actor),
        )
        self.tools = core_tool_definitions()
        self.tools.extend(system_image_tool_definitions())
        self.platform_query_read_model = SQLAlchemyAgentQueryReadModel(
            projects=self.project_repository,
            quality_loop=self.quality_loop_repository,
            conversations=self.conversation_repository,
            visible_project_ids=self.project_access.visible_project_ids,
            current_user_id=lambda: self.user.id,
            project_id_for_us=self.project_access_read_model.project_id_for_us,
            get_system_image=lambda project_id: self.system_image_app.get_system_image(
                project_id
            ),
        )
        self.agent_read_model_summaries = ReadModelSummaryService(
            self.platform_query_read_model
        )
        self.agent_scope_resolution = ProjectScopeResolutionApplicationService(
            SQLAlchemyProjectScopeReadModel()
        )
        self.agent_application_ports = SQLAlchemyAgentApplicationPorts(
            conversations=self.conversation_repository,
            projects=self.project_repository,
            quality_loop=self.quality_loop_repository,
            system_image=self.system_image_repository,
            tools=self.tools,
            runtime=AgentApplicationRuntimeAdapters(
                conversation_summary_fallback=(
                    self.agent_read_model_summaries.conversation_summary_fallback
                ),
                resolve_conversation_scope=(
                    self.agent_scope_resolution.resolve_conversation_scope
                ),
                current_user_id=lambda: self.user.id,
                require_project_access=self.project_access.require_project_access,
                require_conversation_access=(
                    self.project_access.require_conversation_access
                ),
                can_access_conversation=self.project_access.can_access_conversation,
                project_goal=lambda goal: (
                    self.agent_goal_projection.upsert_in_conversation(goal)
                ),
                record_goal_audit_event=lambda goal, **kwargs: (
                    self.platform_audit.record_agent_goal_audit_event(
                        goal,
                        **kwargs,
                    )
                ),
                append_text_message=lambda *args, **kwargs: (
                    self.conversation_message_writer.append_text_message(
                        *args,
                        **kwargs,
                    )
                ),
                push_goal_event=lambda *args, **kwargs: (
                    self.platform_events.push_goal_event(*args, **kwargs)
                ),
                push_conversation_event=lambda *args, **kwargs: (
                    self.platform_events.push_event(*args, **kwargs)
                ),
                maybe_create_summary_checkpoint=lambda conversation: (
                    self.conversation_summary_checkpoints_app.maybe_create_checkpoint(
                        conversation
                    )
                ),
                get_conversation=lambda conversation_id: (
                    self.conversation_management.get_conversation(conversation_id)
                ),
                plan_message=lambda conversation, user_message, canonical_action_id=None: (
                    self.planner.plan(
                        conversation,
                        user_message,
                        canonical_action_id=canonical_action_id,
                    )
                ),
                create_tool_invocation=lambda payload: (
                    self.tool_invocations_app.create_tool_invocation(payload)
                ),
                start_goal_from_proposal=lambda conversation_id, proposal: (
                    self.agent_service.start_from_proposal(
                        conversation_id,
                        proposal,
                    )
                ),
                is_confirmation_message=lambda content: (
                    self.tool_governance.is_confirmation_message(content)
                ),
                list_tool_invocations=lambda **kwargs: (
                    self.tool_invocations_app.list_tool_invocations(**kwargs)
                ),
                is_paused_goal=lambda goal_id: (
                    self.agent_service.is_paused_goal(goal_id)
                ),
                resume_goal=lambda goal_id: self.agent_service.resume_goal(goal_id),
                get_tool_invocation=lambda invocation_id: (
                    self.tool_invocations_app.get_tool_invocation(invocation_id)
                ),
                confirm_tool_invocation=lambda invocation_id: (
                    self.tool_invocations_app.confirm_tool_invocation(invocation_id)
                ),
                active_goal_for_conversation=lambda conversation_id: (
                    self.agent_service.active_goal_for_conversation(conversation_id)
                ),
                get_goal=lambda goal_id: self.agent_service.get_goal(goal_id),
                get_checkpoint=lambda goal_id: (
                    self.agent_service.get_checkpoint(goal_id)
                ),
                list_agent_memory_items=lambda **kwargs: (
                    self.agent_memory.list_items(**kwargs)
                ),
                list_audit_events=lambda **kwargs: (
                    self.tool_invocations_app.list_audit_events(**kwargs)
                ),
                create_goal_record=lambda payload: (
                    self.agent_service.create_goal_record(payload)
                ),
                create_summary_checkpoint=lambda **kwargs: (
                    self.agent_memory.create_summary_checkpoint(**kwargs)
                ),
                record_memory_item=lambda **kwargs: (
                    self.agent_memory.record_item(**kwargs)
                ),
                build_memory_context=lambda conversation, **kwargs: (
                    self.agent_memory.build_context(
                        conversation,
                        tools=self.tools,
                        **kwargs,
                    )
                ),
                quality_state=lambda project_id, us_id: (
                    self.quality_loop_context_queries.planner_quality_state(
                        project_id,
                        us_id,
                    )
                ),
                source_binding_incomplete=lambda project_id: (
                    self.system_image_app.source_binding_incomplete(project_id)
                ),
                accept_remote_goal=lambda goal: (
                    self.distributed_state_sync.accept_remote_goal(goal)
                ),
            ),
        )
        self.conversation_summaries = ConversationSummaryCheckpointService()
        self.conversation_summary_checkpoints_app = ConversationSummaryCheckpointApplicationService(
            self.agent_application_ports.conversation_summaries,
            self.agent_application_ports.events,
            self.conversation_summaries,
        )
        self.conversation_message_writer = ConversationMessageWriterApplicationService(
            self.agent_application_ports.conversation_messages,
            self.agent_application_ports.events,
        )
        self.settings_persistence = SettingsPersistence()
        self.tool_approval_verification_state = SQLAlchemyToolApprovalVerificationState(
            self.conversation_repository,
            self.quality_loop_repository,
        )
        self.tool_approval_verifier = ToolApprovalVerifierApplicationService(
            self.tool_approval_verification_state
        )
        self.tool_governance = ToolGovernance(
            approval_verifier=self.tool_approval_verifier.allows_tool_invocation,
        )
        persisted_settings, persisted_custom_keys = self.settings_repository.load()
        self.model_configuration_state = SQLAlchemyModelConfigurationState(
            self.settings_repository,
            self.llm,
        )
        self.model_configuration = ModelConfigurationApplicationService(
            state=self.model_configuration_state,
            repository=self.settings_repository,
            secrets=self.settings_persistence,
            gateway=self.llm,
            test_grants=self.model_config_test_grant_repository,
        )
        self.model_configuration.migrate_legacy_model_configs_if_needed(
            persisted_settings,
            persisted_custom_keys,
        )
        self.quality_generation = LLMQualityGenerationAdapter(
            llm=self.llm,
            settings_provider=self.get_settings,
            custom_api_key_provider=self.model_configuration.get_custom_model_api_key,
            fail_closed=current_runtime_profile().production_like,
            prompt_registry=self.prompt_registry,
        )
        self.planner_context = AgentPlannerContextApplicationService(
            self.agent_application_ports.planner_context
        )
        deterministic_planner = DeterministicAgentPlanner.build(
            tools=self.tools,
            project_name_extractor=self._extract_project_name,
            version_name_extractor=self._extract_version_name,
            summary_builder=self.planner_context.conversation_summary_fallback,
            quality_state_resolver=self.planner_context.quality_state,
        )
        self.planner = LLMStructuredAgentPlanner(
            fallback=deterministic_planner,
            llm=self.llm,
            tools=self.tools,
            settings_provider=self.get_settings,
            custom_api_key_provider=self.model_configuration.get_custom_model_api_key,
            memory_context_builder=self.planner_context.memory_context,
            allow_deterministic_write_fallback=not current_runtime_profile().production_like,
            prompt_registry=self.prompt_registry,
        )
        self.agent_goal_state_machine = AgentGoalStateMachine()
        self.agent_goal_plan_compiler = AgentGoalPlanCompiler(
            self.agent_application_ports.plan_state
        )
        self.agent_graph_runtime = build_agent_graph_runtime(
            self.agent_application_ports.graph_state,
            self.agent_goal_state_machine,
            self.agent_goal_plan_compiler,
            replanner=self.planner,
        )
        self.agent_loop_runtime = AgentLoopRuntime(
            self.agent_application_ports.loop_state,
            self.agent_graph_runtime,
            self.agent_goal_state_machine,
        )
        self.agent_workflow_runtime = build_agent_workflow_runtime(
            self.agent_loop_runtime,
            workflow_state=self.agent_application_ports.workflow_state,
        )
        self.agent_goal_explanations = AgentGoalExplanationApplicationService(
            self.agent_application_ports.goal_explanations
        )
        self.object_storage = ObjectStorage()
        self.project_read_model_projection = RepositoryBackedProjectReadModelProjection()
        self.project_read_model_refresh = ProjectReadModelRefreshApplicationService(
            self.project_read_model_projection
        )
        self.system_image_workspace_adapters = DurableSystemImageWorkspaceAdapters(
            project_repository=self.project_repository,
            quality_loop_repository=self.quality_loop_repository,
            system_image_repository=self.system_image_repository,
            project_read_model_refresh=self.project_read_model_refresh,
            project_access=self.project_access,
            object_storage=self.object_storage,
            model_gateway=self.llm,
            settings_provider=self.get_settings,
            custom_api_key_provider=self.model_configuration.get_custom_model_api_key,
        )
        self.system_image_workspace = SQLAlchemySystemImageWorkspace(
            self.system_image_workspace_adapters,
            require_live_model_routes=current_runtime_profile().production_like,
        )
        self.source_uploads = SourceUploadApplicationService(
            self.system_image_workspace,
            ObjectStorageSourceUploadStorage(self.object_storage),
        )
        self.source_ingestion = SourceIngestionService(
            connectors=(
                GitSourceConnector(),
                ObjectStorageSourceConnector(self.object_storage),
            )
        )
        self.code_graph_config = CodeGraphConfig.from_env()
        structural_code_intelligence = TreeSitterCodeIntelligenceAdapter()
        graph_code_intelligence = (
            None
            if self.code_graph_config.mode == "disabled"
            else CodebaseMemoryCodeIntelligenceAdapter(self.code_graph_config)
        )
        self.code_intelligence = CompositeCodeIntelligenceAdapter(
            structural_code_intelligence,
            graph_code_intelligence,
            mode=self.code_graph_config.mode,
        )
        self.system_image_retrieval_index = SQLAlchemySystemImageRetrievalIndex(self.system_image_repository)
        self.system_image_ingestion_projection = CompatibilitySystemImageIngestionProjection(
            self.system_image_ingestion_lock.acquire,
            self.system_image_workspace,
            self.project_read_model_refresh,
        )
        self.system_image_service = SystemImageService(
            self.system_image_workspace,
            self.source_ingestion,
            self.system_image_retrieval_index,
            self.system_image_ingestion_projection,
            self.code_intelligence,
        )
        self.system_image_app = SystemImageApplicationService(
            self.system_image_workspace,
            self.system_image_service,
        )
        self.system_image_memory_retriever = SQLAlchemySystemImageRetriever(
            system_images=self.system_image_repository,
            conversations=self.conversation_repository,
            retrieval_index=self.system_image_retrieval_index,
            workspace=self.system_image_workspace,
        )
        self.agent_memory = AgentMemoryManager(
            self.agent_application_ports.memory_state,
            self.system_image_memory_retriever,
            self.system_image_workspace,
            self.conversation_summaries,
            self.prompt_registry,
        )
        self.conversation_management = ConversationManagementApplicationService(
            self.agent_application_ports.conversation_management
        )
        self.conversation_messages = ConversationMessageApplicationService(
            self.agent_application_ports.conversation_runtime
        )
        self.agent_goal_projection = AgentGoalProjectionApplicationService(
            self.agent_application_ports.goal_projection
        )
        self.agent_service = AgentService(
            self.agent_application_ports.goal_lifecycle,
            self.agent_workflow_runtime,
        )
        self.quality_loop_context_workspace = SQLAlchemyQualityLoopContextWorkspace(
            self.system_image_repository,
            self.quality_loop_repository,
        )
        self.quality_loop_context_queries = QualityLoopContextQueryApplicationService(
            self.quality_loop_context_workspace
        )
        self.quality_loop_scope_workspace = SQLAlchemyQualityLoopScopeWorkspace(
            self.quality_loop_repository,
            self.conversation_repository,
        )
        self.quality_loop_scope_queries = QualityLoopScopeQueryApplicationService(
            self.quality_loop_scope_workspace
        )
        self.quality_asset_progress_workspace = (
            SQLAlchemyQualityAssetProgressWorkspace(
                self.quality_loop_repository,
            )
        )
        self.quality_asset_progress = QualityAssetProgressApplicationService(
            self.quality_asset_progress_workspace
        )
        self.project_version_workspace = SQLAlchemyProjectVersionWorkspace(
            self.project_repository,
            self.quality_loop_repository,
            self.system_image_repository,
            self.conversation_repository,
            lambda project_id, *, ready: self.system_image_service.ensure_state(
                project_id,
                ready=ready,
            ),
            self.project_access.grant_creator,
            self.get_or_create_conversation,
        )
        self.project_versions = ProjectVersionApplicationService(
            self.project_version_workspace,
            self.system_image_app,
            self.quality_loop_context_queries,
        )
        self.quality_loop_version_context = (
            QualityLoopVersionContextApplicationService(
                self.project_version_workspace,
                self.project_versions,
            )
        )
        self.quality_asset_pack_workspace = SQLAlchemyQualityAssetPackWorkspace(
            self.quality_loop_repository,
        )
        self.quality_asset_pack_app = QualityAssetPackApplicationService(
            self.quality_asset_pack_workspace,
            self.quality_loop_context_queries,
            self.quality_loop_version_context.active_or_create_version,
        )
        self.quality_run_workspace = SQLAlchemyQualityRunWorkspace(
            self.quality_loop_repository,
        )
        self.run_orchestrator = RunOrchestrator(
            self.quality_run_workspace,
            self.quality_loop_context_queries,
            self.object_storage,
        )
        self.quality_run_execution = QualityRunExecutionApplicationService(
            self.run_orchestrator,
            self.quality_loop_repository,
            self.quality_loop_repository,
        )
        self.quality_failure_workspace = SQLAlchemyQualityFailureWorkspace(
            self.quality_loop_repository,
        )
        self.quality_failure_reports = QualityFailureReportApplicationService(
            self.quality_failure_workspace,
            self.quality_loop_repository,
            self.run_orchestrator,
            max_healing_depth=2,
        )
        self.quality_release_readiness = QualityReleaseReadinessApplicationService(
            self.release_readiness_repository,
            self.quality_loop_version_context.active_or_create_version,
        )
        self.quality_image_updates = QualityImageUpdateApplicationService(
            self.system_image_workspace,
            self.quality_loop_version_context.active_or_create_version,
            self.system_image_service.ensure_state,
        )
        self.quality_steps = QualityStepCompletionApplicationService(
            read_model_refresh=self.project_read_model_refresh,
            context_queries=self.quality_loop_context_queries,
            scope_queries=self.quality_loop_scope_queries,
            asset_progress=self.quality_asset_progress,
            asset_packs=self.quality_asset_pack_app,
            release_readiness=self.quality_release_readiness,
            quality_image_updates=self.quality_image_updates,
            run_execution=self.quality_run_execution,
            quality_generator=self.quality_generation,
        )
        self.quality_loop = QualityLoopApplicationService(
            read_model_refresh=self.project_read_model_refresh,
            context_queries=self.quality_loop_context_queries,
            scope_queries=self.quality_loop_scope_queries,
            version_context=self.quality_loop_version_context,
            asset_progress=self.quality_asset_progress,
            asset_packs=self.quality_asset_pack_app,
            run_execution=self.quality_run_execution,
            failure_reports=self.quality_failure_reports,
            release_readiness=self.quality_release_readiness,
            quality_image_updates=self.quality_image_updates,
            quality_steps=self.quality_steps,
        )
        self.governance_workspace = SQLAlchemyGovernanceWorkspace(
            conversations=self.conversation_repository,
            projects=self.project_repository,
            quality_loop=self.quality_loop_repository,
            commands=SQLAlchemyGovernanceCommandRepository(),
            require_project_access=self.project_access.require_project_access,
            system_image_workspace=self.system_image_workspace,
        )
        self.governance = GovernanceApplicationService(self.governance_workspace)
        self.agent_swarm_coordinator = AgentSwarmCoordinator(
            self.agent_application_ports.swarm_state
        )
        self.tool_projection_state = SQLAlchemyToolInvocationProjectionState(
            self.conversation_repository,
        )
        self.tool_projection = ToolInvocationProjectionApplicationService(
            self.tool_projection_state
        )
        self.tool_application_state = SQLAlchemyToolInvocationApplicationState(
            tools=self.tools,
            repository=self.conversation_repository,
        )
        self.audit_event_persistence = SQLAlchemyAuditEventPersistence(
            self.conversation_repository,
        )
        self.platform_audit = PlatformAuditApplicationService(
            self.audit_event_persistence
        )
        self.event_stream_buffer = SSEWakeUpBuffer(
            EventStreamWakeUpState(
                conversation_queues=self.event_queues,
                goal_queues=self.agent_goal_queues,
                swarm_queues=self.agent_swarm_queues,
                entity_versions=self.entity_versions,
            ),
            lambda: self.event_stream_lock,
        )
        event_stream_settings = event_stream_runtime_settings_from_env()
        self.event_streams = PlatformEventStreamApplicationService(
            self.event_outbox_repository,
            self.event_stream_buffer,
            poll_seconds=event_stream_settings.poll_seconds,
            heartbeat_seconds=event_stream_settings.heartbeat_seconds,
        )
        self.platform_event_entities = CallablePlatformEventEntityReader(
            PlatformEventEntityAdapters(
                get_agent_goal=lambda goal_id: (
                    self.agent_service.get_goal(goal_id)
                    if self.agent_service.has_goal(goal_id)
                    else None
                ),
                get_tool_invocation=self.tool_application_state.get_invocation,
                get_agent_swarm=self.agent_swarm_coordinator.get_swarm,
            )
        )
        self.platform_events = PlatformEventApplicationService(
            self.event_streams,
            self.platform_event_entities,
            self.tool_projection,
        )
        self.agent_app = AgentApplicationService(
            conversations=self.conversation_management,
            events=self.platform_events,
            explanations=self.agent_goal_explanations,
            goals=self.agent_service,
            memory=self.agent_memory,
            messages=self.conversation_messages,
            swarm=self.agent_swarm_coordinator,
        )
        self.agent_replies = AgentReplyApplicationService(
            memory=self.agent_memory,
            generation=self.llm,
            model_settings=self.model_configuration,
            messages=self.conversation_message_writer,
            prompt_registry=self.prompt_registry,
        )
        self.tool_handler_registry = build_tool_handler_registry(
            ToolHandlerDependencies(
                project_versions=self.project_versions,
                quality_loop=self.quality_loop,
                queries=QueryToolApplicationService(
                    self.platform_query_read_model,
                    agent_replies=self.agent_replies,
                    summaries=self.agent_read_model_summaries,
                ),
                system_image=self.system_image_app,
                governance=self.governance,
                tool_invocations=self.platform_events,
                agent_replies=self.agent_replies,
                agent=self.agent_app,
            )
        )
        self.tool_runtime_state = SQLAlchemyToolInvocationRuntimeState(
            repository=self.conversation_repository,
        )
        self.tool_runtime_catalog = StaticToolCatalogRuntimeAdapter(self.tools)
        self.tool_runtime_authorization = ToolInvocationAuthorizationApplicationService(
            self.project_access,
            lambda: self.user,
        )
        self.tool_invocation_runtime = ToolInvocationRuntime(
            state=self.tool_runtime_state,
            catalog=self.tool_runtime_catalog,
            authorization=self.tool_runtime_authorization,
            governance=self.tool_governance,
            audit_events=self.platform_audit,
            agent_replies=self.agent_replies,
            events=self.platform_events,
            handlers=self.tool_handler_registry,
        )
        self.tool_invocations_app = ToolInvocationApplicationService(
            state=self.tool_application_state,
            runtime=self.tool_invocation_runtime,
            authorization=self.project_access,
            events=self.platform_events,
        )
        self.top_level_content = TopLevelContentApplicationService(
            SQLAlchemyTopLevelContentReadModel(
                projects=self.project_repository,
                quality_loop=self.quality_loop_repository,
                conversations=self.conversation_repository,
                visible_project_ids=self.project_access.visible_project_ids,
                current_user_id=lambda: self.user.id,
                documentation=product_documentation_entries(),
            )
        )
        self.project_workspace_read_model = SQLAlchemyProjectWorkspaceReadModel(
            self.project_repository,
            self.quality_loop_repository,
            self.system_image_repository,
        )
        self.project_workspace = ProjectWorkspaceApplicationService(
            read_model=self.project_workspace_read_model,
            authorization=self.project_access,
            tool_invocations=self.tool_invocations_app,
            conversations=self.conversation_management,
        )
        self.distributed_state_sync = DistributedStateSynchronizationApplicationService(
            DistributedStateSynchronizationDependencies(
                persist_goal=self.conversation_repository.upsert_goal,
                get_conversation=self.conversation_repository.get_conversation,
            )
        )
        self.demo_seed_workspace = SQLAlchemyDemoSeedWorkspace(
            project_repository=self.project_repository,
            quality_loop_repository=self.quality_loop_repository,
            system_image_repository=self.system_image_repository,
            get_or_create_conversation=self.get_or_create_conversation,
        )
        self.demo_seed = DemoSeedApplicationService(self.demo_seed_workspace)
        if demo_seed_enabled():
            self._seed()

    @property
    def user(self) -> UserProfile:
        """Compatibility accessor backed by request-local actor identity."""

        return current_user(self._default_user)

    def _refresh_project_read_models(self, project_id: str) -> None:
        self.project_read_model_refresh.refresh_project(project_id)

    def _seed(self) -> None:
        self.demo_seed.seed()

    def get_settings(self) -> StudioSettings:
        """Composition callback used by model-backed application services."""

        return self.model_configuration.get_settings()

    def get_or_create_conversation(
        self,
        space_type: str,
        space_id: str,
        title: str,
    ) -> ConversationSession:
        """Composition callback shared by project and demo-seed workspaces."""

        return self.conversation_management.get_or_create_conversation(
            space_type,
            space_id,
            title,
        )

    def _extract_project_name(self, content: str) -> str:
        return extract_project_name(
            content,
            fallback_index=len(self.project_repository.list_projects()) + 1,
        )

    def _extract_version_name(self, content: str) -> str:
        version_count = sum(
            len(self.project_repository.list_versions(project.id))
            for project in self.project_repository.list_projects()
        )
        return extract_version_name(content, fallback_index=version_count + 1)


class ApplicationRuntime:
    """Legacy facade over the production assembly during migration.

    Compatibility callers share the same queues, gateways, and repositories
    as the explicit production container instead of constructing a second
    process-local dependency graph.
    """

    def __init__(self, assembly: RuntimeAssembly | None = None) -> None:
        object.__setattr__(self, "_assembly", assembly or RuntimeAssembly())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._assembly, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._assembly, name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._assembly, name)

    def get_welcome(self) -> WelcomeResponse:
        return self.top_level_content.get_welcome()

    def get_build(self) -> BuildResponse:
        return self.top_level_content.get_build()

    def get_dashboard(self) -> DashboardResponse:
        return self.top_level_content.get_dashboard()

    def update_settings(self, payload: StudioSettingsPatch) -> StudioSettings:
        return self.model_configuration.update_settings(payload)

    async def test_settings_connection(
        self,
        payload: Optional[StudioSettingsConnectionTestRequest] = None,
    ) -> StudioSettingsConnectionTestResponse:
        return await self.model_configuration.test_settings_connection(payload)

    async def test_model_config_connection(self, payload: ModelConfigTestRequest) -> StudioSettingsConnectionTestResponse:
        return await self.model_configuration.test_model_config_connection(payload)

    def create_model_config(self, payload: ModelConfigCreateRequest) -> StudioSettings:
        return self.model_configuration.create_model_config(payload)

    def update_model_config(self, config_id: str, payload: ModelConfigUpdateRequest) -> StudioSettings:
        return self.model_configuration.update_model_config(config_id, payload)

    def list_model_configurations(self, route: Optional[str] = None):
        return self.model_configuration.list_model_configurations(route)

    def activate_model_config(self, config_id: str) -> StudioSettings:
        return self.model_configuration.activate_model_config(config_id)

    def use_system_default_model_config(self, route: str) -> StudioSettings:
        return self.model_configuration.use_system_default_model_config(route)

    def list_projects(self) -> List[ProjectCard]:
        return self.project_repository.list_projects()

    def list_documentation(self) -> List[DocumentationEntry]:
        return self.top_level_content.list_documentation()

    def create_project(self, name: str) -> ProjectCard:
        return self.project_versions.create_project_record(name)

    def get_project_workspace(self, project_id: str) -> ProjectWorkspaceResponse:
        return self.project_workspace.get_project_workspace(project_id)

    def list_knowledge_objects(self, project_id: str) -> List[KnowledgeObject]:
        return self.system_image_app.list_knowledge_objects(project_id)

    def get_knowledge_object(self, project_id: str, object_id: str) -> KnowledgeObject:
        return self.system_image_app.get_knowledge_object(project_id, object_id)

    def get_system_image(self, project_id: str) -> SystemImageResponse:
        return self.system_image_app.get_system_image(project_id)

    def get_run_detail(self, project_id: str, run_id: str) -> RunDetail:
        return self.project_workspace.get_run_detail(project_id, run_id)

    def get_approval_detail(self, project_id: str, approval_id: str) -> ApprovalDetail:
        return self.project_workspace.get_approval_detail(project_id, approval_id)

    def get_release_readiness(self, project_id: str) -> ReleaseReadiness:
        return self.project_workspace.get_release_readiness(project_id)

    def create_version(self, project_id: str, name: str) -> VersionSummary:
        return self.project_versions.create_version_record(project_id, name)

    def get_workspace_data(self, project_id: str, us_id: str) -> Dict[str, Any]:
        return self.project_workspace.get_workspace_data(project_id, us_id)

    def _resolve_conversation_scope(
        self,
        space_type: str,
        space_id: str,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        us_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        return self.conversation_management.resolve_conversation_scope(
            space_type,
            space_id,
            project_id=project_id,
            version_id=version_id,
            us_id=us_id,
        )

    def list_conversations(
        self,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        space_type: Optional[str] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> List[ConversationSession]:
        return self.conversation_management.list_conversations(
            project_id=project_id,
            version_id=version_id,
            space_type=space_type,
            status=status,
            q=q,
        )

    def get_conversation(self, conversation_id: str) -> ConversationSession:
        return self.conversation_management.get_conversation(conversation_id)

    def list_conversation_messages(self, conversation_id: str, before_message_id: Optional[str] = None) -> List[ConversationMessage]:
        return self.conversation_management.list_conversation_messages(conversation_id, before_message_id)

    def archive_conversation(self, conversation_id: str, payload: ConversationArchiveRequest) -> ConversationSession:
        return self.conversation_management.archive_conversation(conversation_id, payload)

    def merge_conversations(self, conversation_id: str, payload: ConversationMergeRequest) -> Dict[str, Any]:
        return self.conversation_management.merge_conversations(conversation_id, payload)

    def search_conversations(self, q: str) -> Dict[str, Any]:
        return self.conversation_management.search_conversations(q)

    async def create_tool_invocation(self, payload: ToolInvocationRequest) -> ToolInvocation:
        return await self.tool_invocations_app.create_tool_invocation(payload)

    async def _execute_tool_invocation(self, invocation: ToolInvocation) -> ToolInvocation:
        return await self.tool_invocations_app.execute_tool_invocation(invocation)

    async def _gate_tool_invocation_if_needed(self, invocation: ToolInvocation) -> bool:
        return await self.tool_invocations_app.gate_tool_invocation_if_needed(invocation)

    def _tool_definition(self, tool_id: str) -> ToolDefinition | None:
        return self.tool_invocations_app.tool_definition(tool_id)

    async def confirm_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return await self.tool_invocations_app.confirm_tool_invocation(invocation_id)

    def _pending_confirmation_invocation(self, conversation_id: str, content: str) -> ToolInvocation | None:
        return self.conversation_messages.pending_confirmation_invocation(conversation_id, content)

    async def _handle_confirmation_message_if_any(self, conversation_id: str, content: str) -> Dict[str, Any] | None:
        return await self.conversation_messages.handle_confirmation_message_if_any(conversation_id, content)

    async def _handle_source_binding_message_if_any(self, conversation_id: str, content: str) -> Dict[str, Any] | None:
        return await self.conversation_messages.handle_source_binding_message_if_any(conversation_id, content)

    def get_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        return self.tool_invocations_app.get_tool_invocation(invocation_id)

    def list_tool_invocations(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        tool_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ToolInvocation]:
        return self.tool_invocations_app.list_tool_invocations(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            tool_id=tool_id,
            status=status,
        )

    def _tool_invocation_created_at(self, invocation: ToolInvocation) -> str:
        return self.tool_invocations_app.tool_invocation_created_at(invocation)

    def record_audit_event(self, event: AuditEvent) -> None:
        self.platform_audit.record_audit_event(event)

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
        self.platform_audit.record_agent_goal_audit_event(
            goal,
            action=action,
            status=status,
            summary=summary,
            actor=actor,
            actor_kind=actor_kind,
            metadata=metadata,
        )

    def list_audit_events(
        self,
        *,
        conversation_id: str | None = None,
        tool_invocation_id: str | None = None,
        agent_goal_id: str | None = None,
    ) -> List[AuditEvent]:
        return self.tool_invocations_app.list_audit_events(
            conversation_id=conversation_id,
            tool_invocation_id=tool_invocation_id,
            agent_goal_id=agent_goal_id,
        )

    def create_agent_goal(self, payload: AgentGoalCreateRequest) -> AgentGoal:
        return self.agent_service.create_goal_record(payload)

    def get_agent_goal(self, goal_id: str) -> AgentGoal:
        return self.agent_service.get_goal(goal_id)

    def get_agent_goal_checkpoint(self, goal_id: str):
        return self.agent_service.get_checkpoint(goal_id)

    def get_agent_goal_explanation(self, goal_id: str) -> Dict[str, Any]:
        return self.agent_goal_explanations.get_explanation(goal_id)

    async def get_agent_memory_context(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        space_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self.agent_memory.get_context_view(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            space_ref=space_ref,
        )

    async def create_agent_memory_checkpoint(
        self,
        *,
        conversation_id: Optional[str] = None,
        agent_goal_id: Optional[str] = None,
        space_ref: Optional[str] = None,
        created_by: str = "user",
    ) -> ConversationSummaryCheckpoint:
        return await self.agent_memory.create_summary_checkpoint(
            conversation_id=conversation_id,
            agent_goal_id=agent_goal_id,
            space_ref=space_ref,
            created_by=created_by,
        )

    def record_agent_memory_item(
        self,
        *,
        memory_scope: str,
        owner_ref: str,
        summary: str,
        source_refs: Optional[List[str]] = None,
        object_refs: Optional[List[str]] = None,
        evidence_refs: Optional[List[str]] = None,
        expires_at: Optional[str] = None,
        link_refs: Optional[List[tuple[str, str, float]]] = None,
    ) -> AgentMemoryItem:
        return self.agent_memory.record_item(
            memory_scope=memory_scope,
            owner_ref=owner_ref,
            summary=summary,
            source_refs=source_refs,
            object_refs=object_refs,
            evidence_refs=evidence_refs,
            expires_at=expires_at,
            link_refs=link_refs,
        )

    def list_agent_memory_items(
        self,
        *,
        owner_ref: Optional[str] = None,
        memory_scope: Optional[str] = None,
        status: Optional[str] = None,
        source_ref: Optional[str] = None,
    ) -> List[AgentMemoryItem]:
        return self.agent_memory.list_items(
            owner_ref=owner_ref,
            memory_scope=memory_scope,
            status=status,
            source_ref=source_ref,
        )

    def get_agent_swarm(self, swarm_id: str) -> AgentSwarmRun:
        return self.agent_swarm_coordinator.get_swarm(swarm_id)

    def _upsert_goal_in_conversation(self, goal: AgentGoal) -> None:
        self.agent_goal_projection.upsert_in_conversation(goal)

    def _upsert_invocation_in_conversation(self, invocation: ToolInvocation) -> None:
        self.tool_projection.upsert_in_conversation(invocation)

    async def append_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        tone: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
        tool_refs: Optional[List[str]] = None,
        object_refs: Optional[List[str]] = None,
    ) -> ConversationMessage:
        return await self.conversation_message_writer.append_text_message(
            conversation_id,
            role,
            text,
            tone=tone,
            metadata=metadata,
            tool_refs=tool_refs,
            object_refs=object_refs,
        )

    async def handle_message(self, conversation_id: str, content: str) -> Dict[str, Any]:
        return await self.conversation_messages.post_message(conversation_id, content)

    async def stream_goal_events(self, goal_id: str, last_event_id: str | None = None):
        async for event in self.platform_events.stream_goal_events(goal_id, last_event_id):
            yield event

    async def stream_swarm_events(self, swarm_id: str, last_event_id: str | None = None):
        async for event in self.platform_events.stream_swarm_events(swarm_id, last_event_id):
            yield event

    def _swarm_snapshot_event(self, swarm_id: str) -> EventPayload:
        return self.platform_events.swarm_snapshot_event(swarm_id)

    async def interrupt_agent_goal(self, goal_id: str) -> AgentGoal:
        return await self.agent_service.interrupt_goal(goal_id)

    async def resume_agent_goal(self, goal_id: str) -> AgentGoal:
        return await self.agent_service.resume_goal(goal_id)

    async def add_goal_feedback(self, goal_id: str, feedback: str) -> AgentGoal:
        return await self.agent_service.add_feedback(goal_id, feedback)

    async def stream_events(self, conversation_id: str, last_event_id: str | None = None):
        async for event in self.platform_events.stream_conversation_events(conversation_id, last_event_id):
            yield event

ApplicationStore = ApplicationRuntime
InMemoryStore = ApplicationRuntime

_runtime_assembly: RuntimeAssembly | None = None
_application_runtime: ApplicationRuntime | None = None
_application_store_lock = RLock()


def get_runtime_assembly() -> RuntimeAssembly:
    """Return the production dependency graph without compatibility methods."""

    global _runtime_assembly
    if _runtime_assembly is None:
        with _application_store_lock:
            if _runtime_assembly is None:
                _runtime_assembly = RuntimeAssembly()
    return _runtime_assembly


def get_application_runtime() -> ApplicationRuntime:
    """Return the process-local compatibility facade without import-time I/O."""

    global _application_runtime
    if _application_runtime is None:
        with _application_store_lock:
            if _application_runtime is None:
                _application_runtime = ApplicationRuntime(get_runtime_assembly())
    return _application_runtime


def get_application_store() -> ApplicationStore:
    """Compatibility accessor retained for legacy tests and transitional callers."""

    return get_application_runtime()


class _LazyApplicationStoreProxy:
    """Temporary test/legacy facade; production composition uses the container."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_application_runtime(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(get_application_runtime(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(get_application_runtime(), name)


store = _LazyApplicationStoreProxy()
