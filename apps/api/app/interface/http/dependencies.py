from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ...application.agent import AgentApplicationService
from ...application.platform.project_workspace import ProjectWorkspaceApplicationService
from ...application.platform.governance import GovernanceApplicationService
from ...application.platform.identity_administration import (
    IdentityAdministrationApplicationService,
)
from ...application.platform.readiness import ReadinessApplicationService
from ...application.platform.operational_metrics import OperationalMetricsExportPort
from ...application.platform.use_cases import PlatformApplicationService
from ...application.system_image import SystemImageApplicationService
from ...application.system_image.source_uploads import SourceUploadApplicationService
from ...application.system_image.evidence_queries import EvidenceQueryApplicationService
from ...application.system_image.code_analysis_queries import CodeAnalysisQueryApplicationService
from ...application.system_image.code_index_lifecycle import CodeIndexLifecycleApplicationService
from ...application.system_image.source_deltas import SourceDeltaQueryApplicationService
from ...application.system_image.context_change_impact import ContextChangeImpactApplicationService
from ...application.system_image.source_context_roots import SourceContextRootApplicationService
from ...application.system_image.context_invalidations import ContextInvalidationApplicationService
from ...application.system_image.document_queries import DocumentQueryApplicationService
from ...application.system_image.image_revision_queries import ImageRevisionQueryApplicationService
from ...application.system_image.build_plans import BuildPlanApplicationService
from ...application.system_image.structure_cancellations import StructureCancellationApplicationService
from ...application.system_image.investigations import InvestigationApplicationService
from ...application.system_image.gap_ownership import GapOwnershipApplicationService
from ...application.platform.tool_build_completions import ToolBuildCompletionObservationApplicationService
from ...application.system_image.reference_links import ReferenceLinkApplicationService
from ...application.system_image.semantic_evaluations import SemanticEvaluationApplicationService
from ...application.system_image.semantic_review import SemanticReviewApplicationService
from ...application.quality_loop.acceptance_specifications import AcceptanceSpecificationApplicationService
from ...application.quality_loop.business_rules import BusinessRuleApplicationService
from ...application.quality_loop.test_design_scopes import TestDesignScopeApplicationService
from ...application.quality_loop.test_design_generation import TestDesignGenerationApplicationService
from ...application.quality_loop.test_design_results import TestDesignResultApplicationService
from ...application.quality_loop.test_design_mappings import TestDesignMappingApplicationService
from ...application.quality_loop.automation_inputs import AutomationInputApplicationService
from ...application.quality_loop.case_approvals import CaseApprovalApplicationService
from ...application.quality_loop.automation_script_generation import AutomationScriptGenerationApplicationService
from ...application.quality_loop.automation_script_reviews import AutomationScriptReviewApplicationService
from ...application.quality_loop.run_plans import RunPlanApplicationService
from ...application.quality_loop.run_plan_locators import RunPlanLocatorApplicationService
from ...application.quality_loop.http_locator_records import HttpLocatorRecordApplicationService
from ...application.quality_loop.http_fixture_recipes import HttpFixtureRecipeApplicationService
from ...application.quality_loop.http_fixture_grants import HttpFixtureGrantApplicationService
from ...application.quality_loop.http_fixture_jobs import HttpFixtureJobApplicationService
from ...application.quality_loop.run_plan_case_jobs import RunPlanCaseJobApplicationService
from ...application.quality_loop.run_plan_builds import RunPlanBuildApplicationService
from ...application.quality_loop.environment_observation_records import EnvironmentObservationRecordApplicationService
from ...application.quality_loop.environment_health_records import EnvironmentHealthRecordApplicationService
from ...application.quality_loop.run_plan_observation_records import RunPlanObservationRecordApplicationService
from ...application.quality_loop.native_builds import NativeBuildApplicationService
from ...application.quality_loop.mapping_part_staging import MappingPartStagingApplicationService
from ...application.quality_loop.generation_jobs import GenerationJobApplicationService
from ...application.system_image.context_packs import ContextPackApplicationService
from ...application.system_image.publications import ImagePublicationApplicationService
from ...application.system_image.link_decisions import LinkDecisionApplicationService
from ...application.platform.tool_evidence import ToolEvidenceObservationApplicationService
from ...application.platform.tool_images import ToolImageObservationApplicationService


def get_agent_application(request: Request) -> AgentApplicationService:
    return request.app.state.container.agent


def get_platform_application(request: Request) -> PlatformApplicationService:
    return request.app.state.container.platform


def get_project_workspace_application(request: Request) -> ProjectWorkspaceApplicationService:
    return request.app.state.container.project_workspace


def get_system_image_application(request: Request) -> SystemImageApplicationService:
    return request.app.state.container.system_image


def get_source_upload_application(request: Request) -> SourceUploadApplicationService:
    return request.app.state.container.source_uploads


def get_evidence_application(request: Request) -> EvidenceQueryApplicationService:
    return request.app.state.container.evidence


def get_code_analysis_application(request: Request) -> CodeAnalysisQueryApplicationService:
    return request.app.state.container.code_analysis


def get_code_index_lifecycle_application(request: Request) -> CodeIndexLifecycleApplicationService:
    return request.app.state.container.code_index_lifecycle


CodeIndexLifecycleApp = Annotated[CodeIndexLifecycleApplicationService, Depends(get_code_index_lifecycle_application)]


def get_source_delta_application(request: Request) -> SourceDeltaQueryApplicationService:
    return request.app.state.container.source_deltas


def get_context_change_impact_application(request: Request) -> ContextChangeImpactApplicationService:
    return request.app.state.container.context_change_impacts


def get_source_context_root_application(request: Request) -> SourceContextRootApplicationService:
    return request.app.state.container.source_context_roots


def get_context_invalidation_application(request: Request) -> ContextInvalidationApplicationService:
    return request.app.state.container.context_invalidations


ContextInvalidationApp = Annotated[ContextInvalidationApplicationService, Depends(get_context_invalidation_application)]


def get_document_application(request: Request) -> DocumentQueryApplicationService:
    return request.app.state.container.source_documents


def get_image_revision_application(request: Request) -> ImageRevisionQueryApplicationService:
    return request.app.state.container.image_revisions


def get_acceptance_application(request: Request) -> AcceptanceSpecificationApplicationService:
    return request.app.state.container.acceptance_specifications


AcceptanceApp = Annotated[AcceptanceSpecificationApplicationService, Depends(get_acceptance_application)]


def get_business_rule_application(request: Request) -> BusinessRuleApplicationService:
    return request.app.state.container.business_rules


BusinessRuleApp = Annotated[BusinessRuleApplicationService, Depends(get_business_rule_application)]


def get_test_design_scope_application(request: Request) -> TestDesignScopeApplicationService:
    return request.app.state.container.test_design_scopes


TestDesignScopeApp = Annotated[TestDesignScopeApplicationService, Depends(get_test_design_scope_application)]


def get_test_design_generation_application(request: Request) -> TestDesignGenerationApplicationService:
    return request.app.state.container.test_design_generation


TestDesignGenerationApp = Annotated[TestDesignGenerationApplicationService, Depends(get_test_design_generation_application)]


def get_test_design_result_application(request: Request) -> TestDesignResultApplicationService:
    return request.app.state.container.test_design_results


TestDesignResultApp = Annotated[TestDesignResultApplicationService, Depends(get_test_design_result_application)]


def get_test_design_mapping_application(request: Request) -> TestDesignMappingApplicationService:
    return request.app.state.container.test_design_mappings


TestDesignMappingApp = Annotated[TestDesignMappingApplicationService, Depends(get_test_design_mapping_application)]


def get_automation_script_application(request: Request) -> AutomationScriptGenerationApplicationService:
    return request.app.state.container.automation_scripts


AutomationScriptApp = Annotated[AutomationScriptGenerationApplicationService, Depends(get_automation_script_application)]


def get_automation_script_review_application(request: Request) -> AutomationScriptReviewApplicationService:
    return request.app.state.container.automation_script_reviews


AutomationScriptReviewApp = Annotated[AutomationScriptReviewApplicationService, Depends(get_automation_script_review_application)]


def get_run_plan_application(request: Request) -> RunPlanApplicationService:
    return request.app.state.container.run_plans


RunPlanApp = Annotated[RunPlanApplicationService, Depends(get_run_plan_application)]


def get_run_plan_locator_application(request: Request) -> RunPlanLocatorApplicationService:
    return request.app.state.container.run_plan_locators


RunPlanLocatorApp = Annotated[RunPlanLocatorApplicationService, Depends(get_run_plan_locator_application)]


def get_run_plan_build_application(request: Request) -> RunPlanBuildApplicationService:
    return request.app.state.container.run_plan_builds


RunPlanBuildApp = Annotated[RunPlanBuildApplicationService, Depends(get_run_plan_build_application)]


def get_run_plan_observation_records(request: Request) -> RunPlanObservationRecordApplicationService:
    return request.app.state.container.run_plan_observation_records


RunPlanObservationsApp = Annotated[RunPlanObservationRecordApplicationService, Depends(get_run_plan_observation_records)]


def get_environment_observation_records(request: Request) -> EnvironmentObservationRecordApplicationService:
    return request.app.state.container.environment_observation_records


EnvironmentRecordsApp = Annotated[EnvironmentObservationRecordApplicationService, Depends(get_environment_observation_records)]


def get_environment_health_records(request: Request) -> EnvironmentHealthRecordApplicationService:
    return request.app.state.container.environment_health_records


EnvironmentHealthApp = Annotated[EnvironmentHealthRecordApplicationService, Depends(get_environment_health_records)]


def get_http_locator_records(request: Request) -> HttpLocatorRecordApplicationService:
    return request.app.state.container.http_locator_records


HttpLocatorRecordsApp = Annotated[HttpLocatorRecordApplicationService, Depends(get_http_locator_records)]


def get_http_fixture_recipes(request: Request) -> HttpFixtureRecipeApplicationService:
    return request.app.state.container.http_fixture_recipes


HttpFixtureRecipesApp = Annotated[HttpFixtureRecipeApplicationService, Depends(get_http_fixture_recipes)]


def get_http_fixture_grants(request: Request) -> HttpFixtureGrantApplicationService:
    return request.app.state.container.http_fixture_grants


HttpFixtureGrantsApp = Annotated[HttpFixtureGrantApplicationService, Depends(get_http_fixture_grants)]


def get_http_fixture_jobs(request: Request) -> HttpFixtureJobApplicationService:
    return request.app.state.container.http_fixture_jobs


HttpFixtureJobsApp = Annotated[HttpFixtureJobApplicationService, Depends(get_http_fixture_jobs)]


def get_run_plan_case_jobs(request: Request) -> RunPlanCaseJobApplicationService:
    return request.app.state.container.run_plan_case_jobs


RunPlanCaseJobsApp = Annotated[RunPlanCaseJobApplicationService, Depends(get_run_plan_case_jobs)]


def get_native_build_application(request: Request) -> NativeBuildApplicationService:
    return request.app.state.container.native_builds


NativeBuildApp = Annotated[NativeBuildApplicationService, Depends(get_native_build_application)]


def get_automation_input_application(request: Request) -> AutomationInputApplicationService:
    return request.app.state.container.automation_inputs


AutomationInputApp = Annotated[AutomationInputApplicationService, Depends(get_automation_input_application)]


def get_case_approval_application(request: Request) -> CaseApprovalApplicationService:
    return request.app.state.container.case_approvals


CaseApprovalApp = Annotated[CaseApprovalApplicationService, Depends(get_case_approval_application)]


def get_mapping_part_application(request: Request) -> MappingPartStagingApplicationService:
    return request.app.state.container.test_design_mapping_parts


MappingPartApp = Annotated[MappingPartStagingApplicationService, Depends(get_mapping_part_application)]


def get_generation_job_application(request: Request) -> GenerationJobApplicationService:
    return request.app.state.container.test_design_jobs


GenerationJobApp = Annotated[GenerationJobApplicationService, Depends(get_generation_job_application)]


def get_context_pack_application(request: Request) -> ContextPackApplicationService:
    return request.app.state.container.context_packs


ContextPackApp = Annotated[ContextPackApplicationService, Depends(get_context_pack_application)]


def get_image_publication_application(request: Request) -> ImagePublicationApplicationService:
    return request.app.state.container.image_publications


ImagePublicationApp = Annotated[ImagePublicationApplicationService, Depends(get_image_publication_application)]


def get_build_plan_application(request: Request) -> BuildPlanApplicationService:
    return request.app.state.container.build_plans


def get_structure_cancellation_application(request: Request) -> StructureCancellationApplicationService:
    return request.app.state.container.structure_cancellations


def get_investigation_application(request: Request) -> InvestigationApplicationService:
    return request.app.state.container.investigations


InvestigationApp = Annotated[InvestigationApplicationService, Depends(get_investigation_application)]


def get_build_completion_observation(request: Request) -> ToolBuildCompletionObservationApplicationService:
    return request.app.state.container.tool_build_completions


BuildCompletionObservationApp = Annotated[ToolBuildCompletionObservationApplicationService, Depends(get_build_completion_observation)]


def get_gap_ownership_application(request: Request) -> GapOwnershipApplicationService:
    return request.app.state.container.gap_ownership


GapOwnershipApp = Annotated[GapOwnershipApplicationService, Depends(get_gap_ownership_application)]


StructureCancellationApp = Annotated[
    StructureCancellationApplicationService, Depends(get_structure_cancellation_application)]


def get_tool_evidence_application(request: Request) -> ToolEvidenceObservationApplicationService:
    return request.app.state.container.tool_evidence


def get_tool_image_application(request: Request) -> ToolImageObservationApplicationService:
    return request.app.state.container.tool_images


def get_readiness_application(request: Request) -> ReadinessApplicationService:
    return request.app.state.readiness


def get_governance_application(request: Request) -> GovernanceApplicationService:
    return request.app.state.container.governance


def get_identity_administration_application(
    request: Request,
) -> IdentityAdministrationApplicationService:
    return request.app.state.container.identity_administration


def get_operational_metrics(request: Request) -> OperationalMetricsExportPort:
    return request.app.state.http_metrics


AgentApp = Annotated[AgentApplicationService, Depends(get_agent_application)]
PlatformApp = Annotated[PlatformApplicationService, Depends(get_platform_application)]
ProjectWorkspaceApp = Annotated[
    ProjectWorkspaceApplicationService,
    Depends(get_project_workspace_application),
]
SystemImageApp = Annotated[SystemImageApplicationService, Depends(get_system_image_application)]
EvidenceApp = Annotated[EvidenceQueryApplicationService, Depends(get_evidence_application)]
CodeAnalysisApp = Annotated[CodeAnalysisQueryApplicationService, Depends(get_code_analysis_application)]
SourceDeltaApp = Annotated[SourceDeltaQueryApplicationService, Depends(get_source_delta_application)]
ContextChangeImpactApp = Annotated[ContextChangeImpactApplicationService, Depends(get_context_change_impact_application)]
SourceContextRootApp = Annotated[SourceContextRootApplicationService, Depends(get_source_context_root_application)]
SourceDocumentApp = Annotated[DocumentQueryApplicationService, Depends(get_document_application)]
ImageRevisionApp = Annotated[ImageRevisionQueryApplicationService, Depends(get_image_revision_application)]
BuildPlanApp = Annotated[BuildPlanApplicationService, Depends(get_build_plan_application)]


def get_reference_link_application(request: Request) -> ReferenceLinkApplicationService:
    return request.app.state.container.reference_links


ReferenceLinkApp = Annotated[ReferenceLinkApplicationService, Depends(get_reference_link_application)]


def get_semantic_evaluation_application(request: Request) -> SemanticEvaluationApplicationService:
    return request.app.state.container.semantic_evaluations


SemanticEvaluationApp = Annotated[SemanticEvaluationApplicationService, Depends(get_semantic_evaluation_application)]

from ...application.system_image.frozen_indexes import FrozenIndexApplicationService


def get_frozen_index_application(request: Request) -> FrozenIndexApplicationService:
    return request.app.state.container.frozen_indexes


FrozenIndexApp = Annotated[FrozenIndexApplicationService, Depends(get_frozen_index_application)]

from ...application.system_image.context_retrieval import ContextRetrievalApplicationService


def get_context_retrieval_application(request: Request) -> ContextRetrievalApplicationService:
    return request.app.state.container.context_retrievals


ContextRetrievalApp = Annotated[ContextRetrievalApplicationService, Depends(get_context_retrieval_application)]


def get_semantic_review_application(request: Request) -> SemanticReviewApplicationService:
    return request.app.state.container.semantic_reviews


SemanticReviewApp = Annotated[SemanticReviewApplicationService, Depends(get_semantic_review_application)]


def get_link_decision_application(request: Request) -> LinkDecisionApplicationService:
    return request.app.state.container.link_decisions


LinkDecisionApp = Annotated[LinkDecisionApplicationService, Depends(get_link_decision_application)]
ToolEvidenceApp = Annotated[ToolEvidenceObservationApplicationService, Depends(get_tool_evidence_application)]
ToolImageApp = Annotated[ToolImageObservationApplicationService, Depends(get_tool_image_application)]
SourceUploadApp = Annotated[
    SourceUploadApplicationService,
    Depends(get_source_upload_application),
]
ReadinessApp = Annotated[ReadinessApplicationService, Depends(get_readiness_application)]
GovernanceApp = Annotated[GovernanceApplicationService, Depends(get_governance_application)]
IdentityAdministrationApp = Annotated[
    IdentityAdministrationApplicationService,
    Depends(get_identity_administration_application),
]
OperationalMetricsApp = Annotated[
    OperationalMetricsExportPort,
    Depends(get_operational_metrics),
]


__all__ = [
    "AgentApp",
    "GovernanceApp",
    "IdentityAdministrationApp",
    "OperationalMetricsApp",
    "PlatformApp",
    "ProjectWorkspaceApp",
    "ReadinessApp",
    "SourceUploadApp",
    "SystemImageApp",
    "get_agent_application",
    "get_governance_application",
    "get_identity_administration_application",
    "get_operational_metrics",
    "get_platform_application",
    "get_project_workspace_application",
    "get_readiness_application",
    "get_source_upload_application",
    "get_system_image_application",
]
