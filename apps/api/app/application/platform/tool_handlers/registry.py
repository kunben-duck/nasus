from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

from ...agent import AgentApplicationService, AgentReplyApplicationService
from ..governance import GovernanceApplicationService
from ..query_tools import QueryToolApplicationService
from ..tool_invocation_ports import ToolStatusEventPort
from ...quality_loop import ProjectVersionApplicationService, QualityLoopApplicationService
from ...system_image import SystemImageApplicationService
from ...system_image.evidence_tools import EvidenceToolPort
from ...system_image.image_query_tools import ImageQueryToolPort
from ..tool_models import ToolInvocation
from .governance import GovernanceToolHandler
from .project_version import ProjectVersionToolHandler
from .quality_loop import QualityLoopToolHandler
from .query import QueryToolHandler
from .system_image import SystemImageToolHandler
from .evidence import EvidenceToolAccessPort, EvidenceToolHandler, LIST_EVIDENCE_TOOL, READ_EVIDENCE_TOOL
from .image_queries import IMAGE_QUERY_INPUTS, ImageQueryToolHandler
from ...system_image.build_plans import BuildPlanApplicationService
from .build_plans import BuildPlanToolHandler, BuildPlanReadToolHandler
from ...system_image.build_plan_queries import BuildPlanQueryApplicationService, READ_BUILD_PLAN_TOOL
from ...system_image.structure_builds import StructureBuildApplicationService
from ...system_image.structure_jobs import StructureJobApplicationService
from .structure_builds import StructureBuildToolHandler
from .structure_cancellations import StructureCancellationToolHandler
from ...system_image.structure_cancel_inputs import STRUCTURE_CANCEL_TOOL
from ...system_image.structure_cancellations import StructureCancellationApplicationService
from ...system_image.investigations import InvestigationApplicationService, INVESTIGATE_TOOL, INVESTIGATION_READ_TOOL
from .investigations import InvestigationToolHandler
from ...system_image.build_completions import BuildCompletionApplicationService, COMPLETION_READ_TOOL
from .build_completions import BuildCompletionToolHandler
from ...system_image.gap_ownership import GapOwnershipApplicationService, ASSIGN_GAPS_TOOL
from .gap_ownership import GapOwnershipToolHandler
from ...system_image.code_index_lifecycle import CodeIndexLifecycleApplicationService, CODE_INDEX_LIST_TOOL, CODE_INDEX_STATUS_TOOL, CODE_INDEX_CANCEL_TOOL
from .code_indexes import CodeIndexLifecycleToolHandler
from ...system_image.build_authorizations import BuildAuthorizationApplicationService
from .build_authorizations import BuildAuthorizationToolHandler
from ...system_image.reference_links import ReferenceLinkApplicationService, PROPOSE_REFERENCES_TOOL
from .reference_links import ReferenceLinkToolHandler
from ...system_image.semantic_evaluations import SemanticEvaluationApplicationService, SEMANTIC_PREVIEW_TOOL, SEMANTIC_EVALUATE_TOOL
from .semantic_evaluations import SemanticEvaluationToolHandler
from ...system_image.frozen_indexes import FrozenIndexApplicationService
from ...system_image.index_inputs import INDEX_PREVIEW_TOOL, INDEX_BUILD_TOOL
from ...system_image.context_retrieval_inputs import CONTEXT_RETRIEVAL_PREVIEW_TOOL
from .frozen_indexes import FrozenIndexToolHandler
from .context_retrieval import ContextRetrievalToolHandler
from ...system_image.context_retrieval_jobs import ContextRetrievalJobApplicationService
from ...system_image.context_retrieval_ports import CONTEXT_RETRIEVE_TOOL, CONTEXT_CANCEL_TOOL, CONTEXT_RETRIEVAL_QUERY_TOOL
from ...system_image.semantic_review import SemanticReviewApplicationService
from ....domain.system_image.semantic_review import SEMANTIC_REVIEW_TOOL
from .semantic_review import SemanticReviewToolHandler
from ...system_image.semantic_membership import SemanticMembershipApplicationService
from ....domain.system_image.semantic_membership import FREEZE_SEMANTIC_TOOL
from .semantic_membership import SemanticMembershipToolHandler
from ...quality_loop.acceptance_specifications import AcceptanceSpecificationApplicationService
from ....domain.quality_loop.acceptance_specification import AC_TOOL
from .acceptance_specifications import AcceptanceSpecificationToolHandler, AC_QUERY_TOOL
from ...quality_loop.business_rules import BusinessRuleApplicationService
from ...quality_loop.test_design_scopes import TestDesignScopeApplicationService
from ...quality_loop.test_design_generation import TestDesignGenerationApplicationService
from ....domain.quality_loop.test_design_generation import GENERATION_QUERY_TOOL
from .test_design_generation import TestDesignGenerationQueryHandler
from ...quality_loop.generation_executor import GenerationExecutorApplicationService
from ...quality_loop.automation_script_generation import AutomationScriptGenerationApplicationService
from ...quality_loop.automation_script_reviews import AutomationScriptReviewApplicationService
from ....domain.quality_loop.automation_script_review import SCRIPT_REVIEW_QUERY_TOOL, SCRIPT_REVIEW_TOOL
from .automation_script_reviews import AutomationScriptReviewToolHandler
from ...quality_loop.automation_script_inputs import SCRIPT_TOOL, SCRIPT_PREVIEW_TOOL, SCRIPT_HISTORY_TOOL
from .automation_scripts import AutomationScriptToolHandler
from ...quality_loop.run_plans import RunPlanApplicationService
from ....domain.quality_loop.run_plan import RUN_PLAN_TOOL, RUN_PLAN_PREVIEW_TOOL
from .run_plans import RunPlanToolHandler
from ...quality_loop.run_plan_builds import RunPlanBuildApplicationService
from ....domain.quality_loop.run_plan_build import RUN_PLAN_BUILD_TOOL, RUN_PLAN_BUILD_PREVIEW_TOOL, RUN_PLAN_BUILD_QUERY_TOOL
from .run_plan_builds import RunPlanBuildToolHandler
from ...quality_loop.run_plan_environments import RunPlanEnvironmentApplicationService, RUN_PLAN_ENVIRONMENT_QUERY_TOOL
from .run_plan_environments import RunPlanEnvironmentToolHandler
from ...quality_loop.run_plan_locators import RunPlanLocatorApplicationService, RUN_PLAN_LOCATOR_QUERY_TOOL
from .run_plan_locators import RunPlanLocatorToolHandler
from ...quality_loop.http_locator_records import HttpLocatorRecordApplicationService
from ....domain.quality_loop.http_locator_record import LOCATOR_RECORD_TOOLS
from .http_locator_records import HttpLocatorRecordToolHandler
from ...quality_loop.http_fixture_recipes import HttpFixtureRecipeApplicationService
from ....domain.quality_loop.http_fixture_recipe import RECIPE_TOOLS
from .http_fixture_recipes import HttpFixtureRecipeToolHandler
from ...quality_loop.http_fixture_grants import HttpFixtureGrantApplicationService
from ....domain.quality_loop.http_fixture_grant import GRANT_TOOLS
from .http_fixture_grants import HttpFixtureGrantToolHandler
from ...quality_loop.http_fixture_jobs import HttpFixtureJobApplicationService
from ....domain.quality_loop.http_fixture_command import FIXTURE_JOB_TOOLS
from .http_fixture_jobs import HttpFixtureJobToolHandler
from ...quality_loop.run_plan_case_jobs import RunPlanCaseJobApplicationService
from ....domain.quality_loop.run_plan_case_job import CASE_JOB_TOOLS
from .run_plan_case_jobs import RunPlanCaseJobToolHandler
from ...quality_loop.environment_observation_records import EnvironmentObservationRecordApplicationService
from ....domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_TOOLS
from .environment_observation_records import EnvironmentObservationRecordToolHandler
from ...quality_loop.environment_health_records import EnvironmentHealthRecordApplicationService
from ....domain.quality_loop.environment_health_record import HEALTH_RECORD_TOOLS
from .environment_health_records import EnvironmentHealthRecordToolHandler
from ...quality_loop.run_plan_observation_records import RunPlanObservationRecordApplicationService, OBSERVATION_RECORD_TOOLS
from .run_plan_observation_records import RunPlanObservationRecordToolHandler
from ...quality_loop.native_build_inputs import NATIVE_BUILD_TOOL, NATIVE_BUILD_PREVIEW_TOOL, NATIVE_BUILD_QUERY_TOOL, NATIVE_BUILD_CANCEL_TOOL
from ...quality_loop.native_builds import NativeBuildApplicationService
from ...quality_loop.native_build_jobs import NativeBuildJobApplicationService
from .native_builds import NativeBuildToolHandler
from ...quality_loop.generation_jobs import GenerationJobApplicationService
from ...quality_loop.generation_job_ports import GENERATION_RECOVER_TOOL, GENERATION_CANCEL_TOOL, GENERATION_JOB_QUERY_TOOL, GENERATION_HISTORY_QUERY_TOOL
from ...quality_loop.generation_execution_inputs import GENERATION_EXECUTION_PREVIEW_TOOL, GENERATION_BATCH_PREVIEW_TOOL
from ...quality_loop.test_design_results import GENERATION_TOOL, TestDesignResultApplicationService
from ...quality_loop.test_design_review_queries import REVIEW_DRAFT_QUERY_TOOL
from .test_design_review_queries import TestDesignReviewQueryHandler
from .generation_execution import GenerationExecutionToolHandler
from ....domain.quality_loop.test_design_scope import SCOPE_TOOL, SCOPE_QUERY_TOOL
from .test_design_scopes import TestDesignScopeToolHandler
from ...quality_loop.test_design_mappings import TestDesignMappingApplicationService
from ...quality_loop.case_approvals import CaseApprovalApplicationService
from ....domain.quality_loop.case_approval import CASE_APPROVAL_TOOL
from .case_approvals import CaseApprovalToolHandler
from ....domain.quality_loop.test_design_mapping import MAPPING_TOOL, MAPPING_QUERY_TOOL
from ....domain.quality_loop.mapping_part_sets import FINALIZE_TOOL
from .test_design_mappings import TestDesignMappingToolHandler
from ...quality_loop.mapping_part_staging import MappingPartStagingApplicationService
from ...quality_loop.mapping_part_inputs import STAGE_PART_TOOL
from .mapping_part_staging import MappingPartStagingToolHandler
from ....domain.quality_loop.business_rule import RULE_TOOL, RULE_QUERY_TOOL
from .business_rules import BusinessRuleToolHandler
from ...system_image.context_packs import ContextPackApplicationService
from ....domain.system_image.context_pack import COMPILE_CONTEXT_TOOL
from ....domain.system_image.context_authorities import REGISTER_CONTEXT_AUTHORITIES_TOOL
from .context_packs import ContextPackToolHandler, CONTEXT_QUERY_INPUTS
from ...system_image.context_invalidations import ContextInvalidationApplicationService
from ....domain.system_image.context_invalidation import INVALIDATE_CONTEXT_TOOL
from .context_invalidations import ContextInvalidationToolHandler
from ...system_image.publications import ImagePublicationApplicationService
from ....domain.system_image.publication import (PUBLICATION_REVIEW_TOOL, PUBLICATION_QUERY_TOOL, PUBLICATION_HEAD_TOOL,
    ROLLBACK_QUERY_TOOL, ROLLBACK_REVIEW_TOOL, ROLLBACK_TOOL)
from .image_publications import ImagePublicationToolHandler
from ...system_image.link_decisions import LinkDecisionApplicationService
from .link_decisions import LinkDecisionToolHandler
from ...system_image.image_membership import ImageMembershipApplicationService
from .image_membership import ImageMembershipToolHandler


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
    evidence: EvidenceToolPort
    evidence_access: EvidenceToolAccessPort
    images: ImageQueryToolPort
    build_plans: BuildPlanApplicationService
    structure_builds: StructureBuildApplicationService
    code_index_lifecycle: CodeIndexLifecycleApplicationService
    build_authorizations: BuildAuthorizationApplicationService
    reference_links: ReferenceLinkApplicationService
    link_decisions: LinkDecisionApplicationService
    image_membership: ImageMembershipApplicationService
    semantic_evaluations: SemanticEvaluationApplicationService
    semantic_reviews: SemanticReviewApplicationService
    semantic_membership: SemanticMembershipApplicationService
    acceptance_specifications: AcceptanceSpecificationApplicationService
    business_rules: BusinessRuleApplicationService
    test_design_scopes: TestDesignScopeApplicationService
    test_design_mappings: TestDesignMappingApplicationService
    case_approvals: CaseApprovalApplicationService
    test_design_mapping_parts: MappingPartStagingApplicationService
    test_design_results: TestDesignResultApplicationService
    test_design_generation: TestDesignGenerationApplicationService
    test_design_executor: GenerationExecutorApplicationService
    automation_scripts: AutomationScriptGenerationApplicationService
    automation_script_reviews: AutomationScriptReviewApplicationService
    run_plans: RunPlanApplicationService
    run_plan_builds: RunPlanBuildApplicationService
    run_plan_environments: RunPlanEnvironmentApplicationService
    run_plan_locators: RunPlanLocatorApplicationService
    http_locator_records: HttpLocatorRecordApplicationService
    http_fixture_recipes: HttpFixtureRecipeApplicationService
    http_fixture_grants: HttpFixtureGrantApplicationService
    environment_observation_records: EnvironmentObservationRecordApplicationService
    environment_health_records: EnvironmentHealthRecordApplicationService
    run_plan_observation_records: RunPlanObservationRecordApplicationService
    native_builds: NativeBuildApplicationService
    native_build_jobs: NativeBuildJobApplicationService
    test_design_jobs: GenerationJobApplicationService
    context_packs: ContextPackApplicationService
    context_invalidations: ContextInvalidationApplicationService
    image_publications: ImagePublicationApplicationService
    frozen_indexes: FrozenIndexApplicationService
    context_retrieval_jobs: ContextRetrievalJobApplicationService
    structure_jobs: StructureJobApplicationService | None = None
    structure_cancellations: StructureCancellationApplicationService | None = None
    investigations: InvestigationApplicationService | None = None
    build_completions: BuildCompletionApplicationService | None = None
    gap_ownership: GapOwnershipApplicationService | None = None
    http_fixture_jobs: HttpFixtureJobApplicationService | None = None
    run_plan_case_jobs: RunPlanCaseJobApplicationService | None = None


def build_tool_handler_registry(dependencies: ToolHandlerDependencies) -> ToolInvocationHandlerRegistry:
    registry = ToolInvocationHandlerRegistry()
    if dependencies.run_plan_case_jobs is not None:
        for tool_id in CASE_JOB_TOOLS:
            registry.register(tool_id, RunPlanCaseJobToolHandler(dependencies.run_plan_case_jobs,
                dependencies.tool_invocations, dependencies.evidence_access))
    if dependencies.http_fixture_jobs is not None:
        for tool_id in FIXTURE_JOB_TOOLS:
            registry.register(tool_id, HttpFixtureJobToolHandler(dependencies.http_fixture_jobs,
                dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in GRANT_TOOLS:
        registry.register(tool_id, HttpFixtureGrantToolHandler(dependencies.http_fixture_grants,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in RECIPE_TOOLS:
        registry.register(tool_id, HttpFixtureRecipeToolHandler(dependencies.http_fixture_recipes,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in LOCATOR_RECORD_TOOLS:
        registry.register(tool_id, HttpLocatorRecordToolHandler(dependencies.http_locator_records,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in HEALTH_RECORD_TOOLS:
        registry.register(tool_id, EnvironmentHealthRecordToolHandler(dependencies.environment_health_records,
            dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(RUN_PLAN_ENVIRONMENT_QUERY_TOOL, RunPlanEnvironmentToolHandler(dependencies.run_plan_environments,
        dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(RUN_PLAN_LOCATOR_QUERY_TOOL, RunPlanLocatorToolHandler(dependencies.run_plan_locators,
        dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in ENVIRONMENT_RECORD_TOOLS:
        registry.register(tool_id, EnvironmentObservationRecordToolHandler(dependencies.environment_observation_records,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in OBSERVATION_RECORD_TOOLS:
        registry.register(tool_id, RunPlanObservationRecordToolHandler(dependencies.run_plan_observation_records,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (RUN_PLAN_BUILD_TOOL, RUN_PLAN_BUILD_PREVIEW_TOOL, RUN_PLAN_BUILD_QUERY_TOOL):
        registry.register(tool_id, RunPlanBuildToolHandler(dependencies.run_plan_builds,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (NATIVE_BUILD_TOOL, NATIVE_BUILD_PREVIEW_TOOL, NATIVE_BUILD_QUERY_TOOL, NATIVE_BUILD_CANCEL_TOOL):
        registry.register(tool_id, NativeBuildToolHandler(dependencies.native_builds, dependencies.native_build_jobs,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (RUN_PLAN_TOOL, RUN_PLAN_PREVIEW_TOOL):
        registry.register(tool_id, RunPlanToolHandler(dependencies.run_plans,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (SCRIPT_REVIEW_TOOL, SCRIPT_REVIEW_QUERY_TOOL):
        registry.register(tool_id, AutomationScriptReviewToolHandler(dependencies.automation_script_reviews,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (SCRIPT_TOOL, SCRIPT_PREVIEW_TOOL, SCRIPT_HISTORY_TOOL):
        registry.register(tool_id, AutomationScriptToolHandler(dependencies.automation_scripts,
            dependencies.tool_invocations, dependencies.evidence_access))
    if dependencies.gap_ownership is not None:
        registry.register(ASSIGN_GAPS_TOOL, GapOwnershipToolHandler(dependencies.gap_ownership,
            dependencies.tool_invocations, dependencies.evidence_access))
    if dependencies.build_completions is not None:
        registry.register(COMPLETION_READ_TOOL, BuildCompletionToolHandler(dependencies.build_completions,
            dependencies.tool_invocations, dependencies.evidence_access))
    if dependencies.investigations is not None:
        for tool_id in (INVESTIGATE_TOOL, INVESTIGATION_READ_TOOL):
            registry.register(tool_id, InvestigationToolHandler(dependencies.investigations,
                dependencies.tool_invocations, dependencies.evidence_access))
    if dependencies.structure_cancellations is not None:
        registry.register(STRUCTURE_CANCEL_TOOL, StructureCancellationToolHandler(dependencies.structure_cancellations,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (CODE_INDEX_LIST_TOOL, CODE_INDEX_STATUS_TOOL, CODE_INDEX_CANCEL_TOOL):
        registry.register(tool_id, CodeIndexLifecycleToolHandler(dependencies.code_index_lifecycle,
            dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(INVALIDATE_CONTEXT_TOOL, ContextInvalidationToolHandler(dependencies.context_invalidations,
        dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(STAGE_PART_TOOL, MappingPartStagingToolHandler(dependencies.test_design_mapping_parts,
        dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(REVIEW_DRAFT_QUERY_TOOL, TestDesignReviewQueryHandler(dependencies.test_design_results,
        dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(CASE_APPROVAL_TOOL, CaseApprovalToolHandler(dependencies.case_approvals,
        dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (MAPPING_TOOL, MAPPING_QUERY_TOOL, FINALIZE_TOOL):
        registry.register(tool_id, TestDesignMappingToolHandler(dependencies.test_design_mappings,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (SCOPE_TOOL, SCOPE_QUERY_TOOL):
        registry.register(tool_id, TestDesignScopeToolHandler(dependencies.test_design_scopes, dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(GENERATION_QUERY_TOOL, TestDesignGenerationQueryHandler(
        dependencies.test_design_generation, dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (GENERATION_EXECUTION_PREVIEW_TOOL, GENERATION_BATCH_PREVIEW_TOOL, GENERATION_TOOL, GENERATION_RECOVER_TOOL, GENERATION_CANCEL_TOOL, GENERATION_JOB_QUERY_TOOL, GENERATION_HISTORY_QUERY_TOOL):
        registry.register(tool_id, GenerationExecutionToolHandler(
            dependencies.test_design_executor, dependencies.tool_invocations, dependencies.evidence_access, dependencies.test_design_jobs))
    for tool_id in (CONTEXT_RETRIEVE_TOOL, CONTEXT_CANCEL_TOOL, CONTEXT_RETRIEVAL_QUERY_TOOL):
        registry.register(tool_id, ContextRetrievalToolHandler(dependencies.context_retrieval_jobs,
            dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (INDEX_PREVIEW_TOOL, INDEX_BUILD_TOOL, CONTEXT_RETRIEVAL_PREVIEW_TOOL):
        registry.register(tool_id, FrozenIndexToolHandler(dependencies.frozen_indexes, dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (RULE_TOOL, RULE_QUERY_TOOL):
        registry.register(tool_id, BusinessRuleToolHandler(dependencies.business_rules, dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (COMPILE_CONTEXT_TOOL, REGISTER_CONTEXT_AUTHORITIES_TOOL, *CONTEXT_QUERY_INPUTS):
        registry.register(tool_id, ContextPackToolHandler(dependencies.context_packs, dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (AC_TOOL, AC_QUERY_TOOL):
        registry.register(tool_id, AcceptanceSpecificationToolHandler(
            dependencies.acceptance_specifications, dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(FREEZE_SEMANTIC_TOOL, SemanticMembershipToolHandler(
        dependencies.semantic_membership, dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(SEMANTIC_REVIEW_TOOL, SemanticReviewToolHandler(
        dependencies.semantic_reviews, dependencies.tool_invocations, dependencies.evidence_access))
    for tool_id in (SEMANTIC_PREVIEW_TOOL, SEMANTIC_EVALUATE_TOOL):
        registry.register(tool_id, SemanticEvaluationToolHandler(
            dependencies.semantic_evaluations, dependencies.tool_invocations, dependencies.evidence_access))
    registry.register("system_image.revisions.freeze_links", ImageMembershipToolHandler(
        dependencies.image_membership, dependencies.tool_invocations, dependencies.evidence_access))
    registry.register("system_image.links.review", LinkDecisionToolHandler(
        dependencies.link_decisions, dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(PROPOSE_REFERENCES_TOOL, ReferenceLinkToolHandler(
        dependencies.reference_links, dependencies.tool_invocations, dependencies.evidence_access))
    registry.register("system_image.build.authorize", BuildAuthorizationToolHandler(
        dependencies.build_authorizations, dependencies.tool_invocations, dependencies.evidence_access))
    registry.register(READ_BUILD_PLAN_TOOL, BuildPlanReadToolHandler(
        BuildPlanQueryApplicationService(dependencies.build_plans), dependencies.tool_invocations, dependencies.evidence_access))
    registry.register("system_image.build.structure", StructureBuildToolHandler(
        dependencies.structure_builds, dependencies.tool_invocations, dependencies.evidence_access, dependencies.structure_jobs))
    registry.register("system_image.build.plan", BuildPlanToolHandler(
        dependencies.build_plans, dependencies.tool_invocations, dependencies.evidence_access))
    if dependencies.build_plans.revisions is not None:
        from ...system_image.build_plan_revisions import REVISE_PLAN_TOOL
        from .build_plan_revisions import BuildPlanRevisionToolHandler
        registry.register(REVISE_PLAN_TOOL, BuildPlanRevisionToolHandler(
            dependencies.build_plans.revisions, dependencies.tool_invocations, dependencies.evidence_access))
    if dependencies.build_plans.phases is not None:
        from ...agent.image_plan_phases import ACTIVATE_PLAN_REVISION_TOOL
        from .image_plan_phases import ImagePlanPhaseToolHandler
        registry.register(ACTIVATE_PLAN_REVISION_TOOL, ImagePlanPhaseToolHandler(
            dependencies.build_plans.phases, dependencies.tool_invocations, dependencies.evidence_access))
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
    evidence_handler = EvidenceToolHandler(dependencies.evidence, dependencies.tool_invocations, dependencies.evidence_access)
    image_handler = ImageQueryToolHandler(dependencies.images, dependencies.tool_invocations, dependencies.evidence_access)
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
    for tool_id in (PUBLICATION_REVIEW_TOOL, PUBLICATION_QUERY_TOOL, PUBLICATION_HEAD_TOOL, "baseline.promote",
                    ROLLBACK_QUERY_TOOL, ROLLBACK_REVIEW_TOOL, ROLLBACK_TOOL):
        registry.register(tool_id, ImagePublicationToolHandler(dependencies.image_publications, dependencies.tool_invocations,
            dependencies.evidence_access, governance_handler))
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
    registry.register(LIST_EVIDENCE_TOOL, evidence_handler)
    registry.register(READ_EVIDENCE_TOOL, evidence_handler)
    for tool_id in IMAGE_QUERY_INPUTS:
        registry.register(tool_id, image_handler)
    registry.register_prefix("query.", FunctionToolInvocationHandler(query_handler.handle))
    return registry
