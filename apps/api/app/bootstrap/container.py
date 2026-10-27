from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from ..application.agent import AgentApplicationService
from ..application.agent.turns import ConversationTurnApplicationService
from ..application.agent.activities import AgentWorkflowActivityApplicationService
from ..application.platform.accounts import AccountApplicationService
from ..application.platform.governance import GovernanceApplicationService
from ..application.platform.identity_administration import (
    IdentityAdministrationApplicationService,
)
from ..application.platform.project_workspace import ProjectWorkspaceApplicationService
from ..application.platform.readiness import ReadinessApplicationService
from ..application.platform.use_cases import PlatformApplicationService
from ..application.system_image import SystemImageApplicationService
from ..application.system_image.source_uploads import SourceUploadApplicationService
from ..application.system_image.evidence_queries import EvidenceQueryApplicationService
from ..application.system_image.code_analysis_queries import CodeAnalysisQueryApplicationService
from ..application.system_image.code_index_lifecycle import CodeIndexLifecycleApplicationService
from ..application.system_image.source_deltas import SourceDeltaQueryApplicationService
from ..application.system_image.context_change_impact import ContextChangeImpactApplicationService
from ..application.system_image.source_context_roots import SourceContextRootApplicationService
from ..application.system_image.context_invalidations import ContextInvalidationApplicationService
from ..application.system_image.document_queries import DocumentQueryApplicationService
from ..application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from ..application.system_image.build_plans import BuildPlanApplicationService
from ..application.system_image.reference_links import ReferenceLinkApplicationService
from ..application.system_image.semantic_evaluations import SemanticEvaluationApplicationService
from ..application.system_image.semantic_review import SemanticReviewApplicationService
from ..application.quality_loop.acceptance_specifications import AcceptanceSpecificationApplicationService
from ..application.quality_loop.business_rules import BusinessRuleApplicationService
from ..application.quality_loop.test_design_scopes import TestDesignScopeApplicationService
from ..application.quality_loop.test_design_generation import TestDesignGenerationApplicationService
from ..application.quality_loop.test_design_results import TestDesignResultApplicationService
from ..application.quality_loop.test_design_mappings import TestDesignMappingApplicationService
from ..application.quality_loop.automation_inputs import AutomationInputApplicationService
from ..application.quality_loop.case_approvals import CaseApprovalApplicationService
from ..application.platform.case_approval_event_access import CaseApprovalEventAccess
from ..application.quality_loop.automation_script_generation import AutomationScriptGenerationApplicationService
from ..application.quality_loop.automation_script_reviews import AutomationScriptReviewApplicationService
from ..application.quality_loop.run_plans import RunPlanApplicationService
from ..application.quality_loop.run_plan_locators import RunPlanLocatorApplicationService
from ..application.quality_loop.http_locator_records import HttpLocatorRecordApplicationService
from ..application.quality_loop.http_fixture_recipes import HttpFixtureRecipeApplicationService
from ..application.quality_loop.http_fixture_grants import HttpFixtureGrantApplicationService
from ..application.quality_loop.http_fixture_execution import HttpFixtureExecutionApplicationService
from ..application.quality_loop.http_fixture_jobs import HttpFixtureJobApplicationService
from ..application.quality_loop.run_plan_case_jobs import RunPlanCaseJobApplicationService
from ..application.quality_loop.run_plan_cases import RunPlanCaseApplicationService
from ..application.quality_loop.run_plan_builds import RunPlanBuildApplicationService
from ..application.quality_loop.run_plan_environments import RunPlanEnvironmentApplicationService
from ..application.quality_loop.run_plan_environment_health import RunPlanEnvironmentHealthApplicationService
from ..application.quality_loop.environment_observation_records import EnvironmentObservationRecordApplicationService
from ..application.quality_loop.environment_health_records import EnvironmentHealthRecordApplicationService
from ..application.quality_loop.run_plan_observation_records import RunPlanObservationRecordApplicationService
from ..application.quality_loop.native_builds import NativeBuildApplicationService
from ..application.quality_loop.native_build_jobs import NativeBuildJobApplicationService
from ..application.quality_loop.mapping_part_staging import MappingPartStagingApplicationService
from ..application.quality_loop.generation_executor import GenerationExecutorApplicationService
from ..application.quality_loop.generation_jobs import GenerationJobApplicationService
from ..application.system_image.context_packs import ContextPackApplicationService
from ..application.system_image.publications import ImagePublicationApplicationService
from ..application.system_image.frozen_indexes import FrozenIndexApplicationService
from ..application.system_image.context_retrieval import ContextRetrievalApplicationService
from ..application.system_image.context_retrieval_jobs import ContextRetrievalJobApplicationService
from ..application.system_image.semantic_membership import SemanticMembershipApplicationService
from ..application.system_image.link_decisions import LinkDecisionApplicationService
from ..application.system_image.image_membership import ImageMembershipApplicationService
from ..application.system_image.structure_builds import StructureBuildApplicationService
from ..application.system_image.structure_jobs import StructureJobApplicationService
from ..application.system_image.structure_cancellations import StructureCancellationApplicationService
from ..application.system_image.investigations import InvestigationApplicationService
from ..application.system_image.build_completions import BuildCompletionApplicationService
from ..application.system_image.gap_ownership import GapOwnershipApplicationService
from ..application.platform.tool_build_completions import ToolBuildCompletionObservationApplicationService
from ..application.platform.tool_evidence import ToolEvidenceObservationApplicationService
from ..application.platform.tool_images import ToolImageObservationApplicationService
from ..infrastructure.config.runtime_config import current_runtime_profile
from ..infrastructure.llm import ModelRoutesReadinessProbe, PromptRegistryReadinessProbe
from ..infrastructure.persistence import DatabaseReadinessProbe, engine
from ..infrastructure.platform import (
    CallableCurrentUserProvider,
    SQLAlchemyAccountIdentityService,
    SQLAlchemyIdentityAdministrationAdapter,
    SQLAlchemyProjectWorkspaceReadModel,
)
from ..infrastructure.runner import AutomationRunnerReadinessProbe
from ..infrastructure.storage import ObjectStorage, ObjectStorageReadinessProbe
from ..infrastructure.system_image import (
    CodeIntelligenceReadinessProbe,
    GitSourceConnectorReadinessProbe,
)
from ..infrastructure.workflow import (
    LangGraphCheckpointReadinessProbe,
    TemporalWorkflowReadinessProbe,
)
from ..interface.http.auth import AuthConfig


@dataclass(frozen=True)
class ApplicationContainer:
    """Explicit services exposed to delivery adapters.

    The legacy projection runtime is intentionally not exposed. HTTP and
    Temporal adapters can only resolve application services from this object.
    """

    auth_config: AuthConfig
    platform: PlatformApplicationService
    agent: AgentApplicationService
    project_workspace: ProjectWorkspaceApplicationService
    system_image: SystemImageApplicationService
    source_uploads: SourceUploadApplicationService
    governance: GovernanceApplicationService
    identity_administration: IdentityAdministrationApplicationService
    readiness: ReadinessApplicationService
    agent_workflow_activities: AgentWorkflowActivityApplicationService
    conversation_turns: ConversationTurnApplicationService
    evidence: EvidenceQueryApplicationService
    code_analysis: CodeAnalysisQueryApplicationService
    code_index_lifecycle: CodeIndexLifecycleApplicationService
    source_deltas: SourceDeltaQueryApplicationService
    context_change_impacts: ContextChangeImpactApplicationService
    source_context_roots: SourceContextRootApplicationService
    context_invalidations: ContextInvalidationApplicationService
    source_documents: DocumentQueryApplicationService
    image_revisions: ImageRevisionQueryApplicationService
    build_plans: BuildPlanApplicationService
    reference_links: ReferenceLinkApplicationService
    semantic_evaluations: SemanticEvaluationApplicationService
    semantic_reviews: SemanticReviewApplicationService
    acceptance_specifications: AcceptanceSpecificationApplicationService
    business_rules: BusinessRuleApplicationService
    test_design_scopes: TestDesignScopeApplicationService
    test_design_generation: TestDesignGenerationApplicationService
    test_design_results: TestDesignResultApplicationService
    test_design_mappings: TestDesignMappingApplicationService
    automation_inputs: AutomationInputApplicationService
    case_approvals: CaseApprovalApplicationService
    case_approval_events: CaseApprovalEventAccess
    automation_scripts: AutomationScriptGenerationApplicationService
    automation_script_reviews: AutomationScriptReviewApplicationService
    run_plans: RunPlanApplicationService
    run_plan_locators: RunPlanLocatorApplicationService
    http_locator_records: HttpLocatorRecordApplicationService
    http_fixture_recipes: HttpFixtureRecipeApplicationService
    http_fixture_grants: HttpFixtureGrantApplicationService
    http_fixture_execution: HttpFixtureExecutionApplicationService
    http_fixture_jobs: HttpFixtureJobApplicationService
    run_plan_cases: RunPlanCaseApplicationService
    run_plan_case_jobs: RunPlanCaseJobApplicationService
    run_plan_builds: RunPlanBuildApplicationService
    run_plan_environments: RunPlanEnvironmentApplicationService
    run_plan_environment_health: RunPlanEnvironmentHealthApplicationService
    environment_observation_records: EnvironmentObservationRecordApplicationService
    environment_health_records: EnvironmentHealthRecordApplicationService
    run_plan_observation_records: RunPlanObservationRecordApplicationService
    native_builds: NativeBuildApplicationService
    native_build_jobs: NativeBuildJobApplicationService
    test_design_mapping_parts: MappingPartStagingApplicationService
    test_design_executor: GenerationExecutorApplicationService
    test_design_jobs: GenerationJobApplicationService
    context_packs: ContextPackApplicationService
    image_publications: ImagePublicationApplicationService
    frozen_indexes: FrozenIndexApplicationService
    context_retrievals: ContextRetrievalApplicationService
    context_retrieval_jobs: ContextRetrievalJobApplicationService
    semantic_membership: SemanticMembershipApplicationService
    link_decisions: LinkDecisionApplicationService
    image_membership: ImageMembershipApplicationService
    structure_builds: StructureBuildApplicationService
    structure_jobs: StructureJobApplicationService
    structure_cancellations: StructureCancellationApplicationService
    investigations: InvestigationApplicationService
    build_completions: BuildCompletionApplicationService
    gap_ownership: GapOwnershipApplicationService
    tool_build_completions: ToolBuildCompletionObservationApplicationService
    tool_evidence: ToolEvidenceObservationApplicationService
    tool_images: ToolImageObservationApplicationService


_container: ApplicationContainer | None = None
_container_lock = RLock()


def get_application_container() -> ApplicationContainer:
    global _container
    if _container is None:
        with _container_lock:
            if _container is None:
                _container = _build_application_container()
    return _container


def _build_application_container() -> ApplicationContainer:
    # Delayed import preserves production fail-fast validation before database
    # initialization and compatibility projection hydration.
    from ..store import get_runtime_assembly

    runtime = get_runtime_assembly()
    platform = PlatformApplicationService(
        accounts=AccountApplicationService(
            current_user=CallableCurrentUserProvider(lambda: runtime.user),
            identities=SQLAlchemyAccountIdentityService(),
        ),
        audit_events=runtime.platform_audit,
        llm_calls=runtime.llm_call_audit,
        model_configurations=runtime.model_configuration,
        top_level_content=runtime.top_level_content,
        tool_invocations=runtime.tool_invocations_app,
    )
    agent_workflow_activities = AgentWorkflowActivityApplicationService(
        loop_runtime=runtime.agent_loop_runtime,
        goal_projector=runtime.agent_goal_projection,
    )
    project_workspace = ProjectWorkspaceApplicationService(
        read_model=SQLAlchemyProjectWorkspaceReadModel(
            runtime.project_repository,
            runtime.quality_loop_repository,
            runtime.system_image_repository,
        ),
        authorization=runtime.project_access,
        tool_invocations=runtime.tool_invocations_app,
        conversations=runtime.conversation_management,
    )
    identity_administration = IdentityAdministrationApplicationService(
        current_user=CallableCurrentUserProvider(lambda: runtime.user),
        identities=SQLAlchemyIdentityAdministrationAdapter(),
        project_access=runtime.project_access,
        audit=runtime.platform_audit,
    )
    readiness = ReadinessApplicationService(
        (
            DatabaseReadinessProbe(engine),
            ObjectStorageReadinessProbe(ObjectStorage()),
            GitSourceConnectorReadinessProbe(),
            CodeIntelligenceReadinessProbe(runtime.code_intelligence),
            AutomationRunnerReadinessProbe(),
            ModelRoutesReadinessProbe(
                runtime.model_configuration.get_settings,
                require_live=current_runtime_profile().production_like,
            ),
            PromptRegistryReadinessProbe(runtime.prompt_registry),
            TemporalWorkflowReadinessProbe(),
            LangGraphCheckpointReadinessProbe(engine),
        )
    )
    return ApplicationContainer(
        auth_config=AuthConfig.from_env(),
        platform=platform,
        agent=runtime.agent_app,
        project_workspace=project_workspace,
        system_image=runtime.system_image_app,
        source_uploads=runtime.source_uploads,
        governance=runtime.governance,
        identity_administration=identity_administration,
        readiness=readiness,
        agent_workflow_activities=agent_workflow_activities,
        conversation_turns=runtime.conversation_turns,
        evidence=runtime.evidence,
        code_analysis=runtime.code_analysis,
        code_index_lifecycle=runtime.code_index_lifecycle,
        source_deltas=runtime.source_deltas,
        context_change_impacts=runtime.context_change_impacts,
        source_context_roots=runtime.source_context_roots,
        context_invalidations=runtime.context_invalidations,
        source_documents=runtime.source_documents,
        image_revisions=runtime.image_revisions,
        build_plans=runtime.build_plans,
        reference_links=runtime.reference_links,
        semantic_evaluations=runtime.semantic_evaluations,
        semantic_reviews=runtime.semantic_reviews,
        acceptance_specifications=runtime.acceptance_specifications,
        business_rules=runtime.business_rules,
        test_design_scopes=runtime.test_design_scopes,
        test_design_generation=runtime.test_design_generation,
        test_design_results=runtime.test_design_results,
        test_design_mappings=runtime.test_design_mappings,
        automation_inputs=runtime.automation_inputs,
        case_approvals=runtime.case_approvals,
        case_approval_events=runtime.case_approval_event_access,
        automation_scripts=runtime.automation_scripts,
        automation_script_reviews=runtime.automation_script_reviews,
        run_plans=runtime.run_plans,
        run_plan_locators=runtime.run_plan_locators,
        http_locator_records=runtime.http_locator_records,
        http_fixture_recipes=runtime.http_fixture_recipes,
        http_fixture_grants=runtime.http_fixture_grants,
        http_fixture_execution=runtime.http_fixture_execution,
        http_fixture_jobs=runtime.http_fixture_jobs,
        run_plan_cases=runtime.run_plan_cases,
        run_plan_case_jobs=runtime.run_plan_case_jobs,
        run_plan_builds=runtime.run_plan_builds,
        run_plan_environments=runtime.run_plan_environments,
        run_plan_environment_health=runtime.run_plan_environment_health,
        environment_observation_records=runtime.environment_observation_records,
        environment_health_records=runtime.environment_health_records,
        run_plan_observation_records=runtime.run_plan_observation_records,
        native_builds=runtime.native_builds,
        native_build_jobs=runtime.native_build_jobs,
        test_design_mapping_parts=runtime.test_design_mapping_parts,
        test_design_executor=runtime.test_design_executor,
        test_design_jobs=runtime.test_design_jobs,
        context_packs=runtime.context_packs,
        image_publications=runtime.image_publications,
        frozen_indexes=runtime.frozen_indexes,
        context_retrievals=runtime.context_retrievals,
        context_retrieval_jobs=runtime.context_retrieval_jobs,
        semantic_membership=runtime.semantic_membership,
        link_decisions=runtime.link_decisions,
        image_membership=runtime.image_membership,
        structure_builds=runtime.structure_builds,
        structure_jobs=runtime.structure_jobs,
        structure_cancellations=runtime.structure_cancellations,
        investigations=runtime.investigations,
        build_completions=runtime.build_completions,
        gap_ownership=runtime.gap_ownership,
        tool_build_completions=runtime.tool_build_completions,
        tool_evidence=runtime.tool_evidence,
        tool_images=runtime.tool_images,
    )
