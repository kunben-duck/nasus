from ..quality_loop.test_design_scope_inputs import ScopeQueryInput
from ..quality_loop.test_design_mapping_inputs import MappingQueryInput
from ..quality_loop.test_design_review_queries import REVIEW_DRAFT_QUERY_TOOL, ReviewDraftListInput
from ...domain.quality_loop.test_design_mapping import MAPPING_QUERY_TOOL
from ..quality_loop.test_design_generation import GenerationSelection
from ..quality_loop.generation_execution_inputs import GENERATION_EXECUTION_PREVIEW_TOOL, GenerationExecutionSelection
from ..quality_loop.automation_script_inputs import SCRIPT_PREVIEW_TOOL, SCRIPT_HISTORY_TOOL, ScriptHistoryQuery, ScriptExecutionSelection
from ..quality_loop.automation_script_review_inputs import ScriptReviewQuery
from ...domain.quality_loop.automation_script_review import SCRIPT_REVIEW_QUERY_TOOL
from ..quality_loop.run_plan_inputs import RunPlanSelection
from ...domain.quality_loop.run_plan import RUN_PLAN_PREVIEW_TOOL
from ..quality_loop.run_plan_build_inputs import RunPlanBuildSelection, RunPlanBuildQuery
from ...domain.quality_loop.run_plan_build import RUN_PLAN_BUILD_PREVIEW_TOOL, RUN_PLAN_BUILD_QUERY_TOOL
from ..quality_loop.run_plan_observation_records import ObservationRecordQuery, OBSERVATION_RECORD_QUERY_TOOL
from ..quality_loop.run_plan_environments import RunPlanEnvironmentQuery, RUN_PLAN_ENVIRONMENT_QUERY_TOOL
from ..quality_loop.run_plan_locators import RunPlanLocatorQuery, RUN_PLAN_LOCATOR_QUERY_TOOL
from ..quality_loop.environment_observation_records import EnvironmentRecordQuery
from ...domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_QUERY_TOOL
from ...domain.quality_loop.environment_health_record import HEALTH_RECORD_QUERY_TOOL
from ...domain.quality_loop.http_locator_record import LOCATOR_RECORD_QUERY_TOOL
from ...domain.quality_loop.http_fixture_recipe import RECIPE_QUERY_TOOL
from ...domain.quality_loop.http_fixture_grant import GRANT_QUERY_TOOL
from ..quality_loop.generation_job_ports import GENERATION_JOB_QUERY_TOOL, GENERATION_HISTORY_QUERY_TOOL, GenerationJobTarget, GenerationHistoryRequest
from ...domain.quality_loop.test_design_generation import GENERATION_QUERY_TOOL
from ...domain.quality_loop.test_design_scope import SCOPE_QUERY_TOOL
from .errors import PlatformApplicationError
from .tool_handlers.query_input import query_payload


class ToolTestDesignScopeObservationApplicationService:
    def __init__(self, invocations, application, access, *, generation=None, executor=None, jobs=None, mappings=None, drafts=None, automation=None, script_reviews=None, run_plans=None, run_plan_builds=None, run_plan_observations=None, run_plan_environments=None, environment_records=None, health_records=None, run_plan_locators=None, http_locator_records=None, http_fixture_recipes=None, http_fixture_grants=None):
        self.invocations, self.application, self.access = invocations, application, access
        self.generation = generation
        self.executor = executor
        self.jobs = jobs
        self.mappings = mappings
        self.drafts = drafts
        self.automation = automation
        self.script_reviews = script_reviews
        self.run_plans = run_plans
        self.run_plan_builds = run_plan_builds
        self.run_plan_observations = run_plan_observations
        self.run_plan_environments = run_plan_environments
        self.environment_records = environment_records
        self.health_records = health_records
        self.run_plan_locators = run_plan_locators
        self.http_locator_records = http_locator_records
        self.http_fixture_recipes = http_fixture_recipes
        self.http_fixture_grants = http_fixture_grants

    def describe(self, invocation_id, project_id):
        invocation = self.invocations.get_tool_invocation(invocation_id)
        if invocation.tool_id == GRANT_QUERY_TOOL:
            self.access.require_invocation_project_scope(invocation)
            if invocation.status != "completed":
                return None
            query = EnvironmentRecordQuery.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.http_fixture_grant if invocation.result else None
            if query.project_id != project_id or self.http_fixture_grants is None or receipt is None:
                raise PlatformApplicationError("fixture_grant_invalid", "Original fixture consent cannot be verified.", 409)
            self.http_fixture_grants.authorize_receipts(((query, receipt),))
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == RECIPE_QUERY_TOOL:
            self.access.require_invocation_project_scope(invocation)
            if invocation.status != "completed":
                return None
            query = EnvironmentRecordQuery.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.http_fixture_recipe if invocation.result else None
            if query.project_id != project_id or self.http_fixture_recipes is None or receipt is None:
                raise PlatformApplicationError("fixture_recipe_invalid", "Original fixture definition cannot be verified.", 409)
            self.http_fixture_recipes.authorize_receipts(((query, receipt),))
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == LOCATOR_RECORD_QUERY_TOOL:
            self.access.require_invocation_project_scope(invocation)
            if invocation.status != "completed":
                return None
            query = EnvironmentRecordQuery.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.run_plan_locator_record if invocation.result else None
            if query.project_id != project_id or self.http_locator_records is None or receipt is None:
                raise PlatformApplicationError("locator_record_invalid", "Original locator evidence cannot be verified.", 409)
            self.http_locator_records.authorize_receipts(((query, receipt),))
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id not in {SCOPE_QUERY_TOOL, GENERATION_QUERY_TOOL, GENERATION_EXECUTION_PREVIEW_TOOL, SCRIPT_PREVIEW_TOOL, SCRIPT_HISTORY_TOOL, SCRIPT_REVIEW_QUERY_TOOL, RUN_PLAN_PREVIEW_TOOL, RUN_PLAN_BUILD_PREVIEW_TOOL, RUN_PLAN_BUILD_QUERY_TOOL, OBSERVATION_RECORD_QUERY_TOOL, RUN_PLAN_ENVIRONMENT_QUERY_TOOL, RUN_PLAN_LOCATOR_QUERY_TOOL, ENVIRONMENT_RECORD_QUERY_TOOL, HEALTH_RECORD_QUERY_TOOL, GENERATION_JOB_QUERY_TOOL, GENERATION_HISTORY_QUERY_TOOL, MAPPING_QUERY_TOOL, REVIEW_DRAFT_QUERY_TOOL}:
            return None
        self.access.require_invocation_project_scope(invocation)
        if invocation.status != "completed":
            return None
        if invocation.tool_id == RUN_PLAN_LOCATOR_QUERY_TOOL:
            query = RunPlanLocatorQuery.model_validate(query_payload(invocation.input_payload))
            value = invocation.result.run_plan_locators if invocation.result else None
            if query.project_id != project_id or self.run_plan_locators is None or value is None:
                raise PlatformApplicationError("locator_receipt_invalid", "Original static locator evidence cannot be verified.", 409)
            result = self.run_plan_locators.authorize_historical_receipt(query, value)
            self.access.require_invocation_project_scope(invocation)
            return result["receipt"]
        if invocation.tool_id == HEALTH_RECORD_QUERY_TOOL:
            query = EnvironmentRecordQuery.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.run_plan_health_record if invocation.result else None
            if query.project_id != project_id or self.health_records is None or receipt is None:
                raise PlatformApplicationError("health_record_invalid", "Original health evidence cannot be verified.", 409)
            self.health_records.authorize_receipts(((query, receipt),))
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == ENVIRONMENT_RECORD_QUERY_TOOL:
            query = EnvironmentRecordQuery.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.run_plan_environment_record if invocation.result else None
            if query.project_id != project_id or self.environment_records is None or receipt is None:
                raise PlatformApplicationError("environment_record_invalid", "Original environment evidence cannot be verified.", 409)
            self.environment_records.authorize_receipts(((query, receipt),))
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == RUN_PLAN_ENVIRONMENT_QUERY_TOOL:
            query = RunPlanEnvironmentQuery.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.run_plan_environment if invocation.result else None
            if query.project_id != project_id or self.run_plan_environments is None or receipt is None:
                raise PlatformApplicationError("target_receipt_invalid", "Original target observation cannot be verified.", 409)
            value = self.run_plan_environments.authorize_historical_receipt(query, receipt)
            self.access.require_invocation_project_scope(invocation)
            return value
        if invocation.tool_id == OBSERVATION_RECORD_QUERY_TOOL:
            query = ObservationRecordQuery.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.run_plan_observations if invocation.result else None
            if (query.project_id != project_id or self.run_plan_observations is None or receipt is None
                    or self.run_plan_observations.receipt(query.project_id, query.record_id) != receipt):
                raise PlatformApplicationError("observation_receipt_changed", "Original observations changed or are unavailable.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id in {RUN_PLAN_BUILD_PREVIEW_TOOL, RUN_PLAN_BUILD_QUERY_TOOL}:
            preview = invocation.tool_id == RUN_PLAN_BUILD_PREVIEW_TOOL
            query = (RunPlanBuildSelection if preview else RunPlanBuildQuery).model_validate(query_payload(invocation.input_payload))
            receipt = (invocation.result.run_plan_build_preview if preview else invocation.result.run_plan_build) if invocation.result else None
            if query.project_id != project_id or self.run_plan_builds is None or receipt is None:
                raise PlatformApplicationError("run_plan_build_receipt_invalid", "Original build binding receipt cannot be verified.", 409)
            current = self.run_plan_builds.preview(query) if preview else self.run_plan_builds.receipt(query.project_id, query.binding_id)
            if current != receipt:
                raise PlatformApplicationError("run_plan_build_receipt_changed", "Build binding receipt changed; inspect again.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == RUN_PLAN_PREVIEW_TOOL:
            request = RunPlanSelection.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.run_plan_preview if invocation.result else None
            if (request.project_id != project_id or self.run_plans is None or receipt is None
                    or self.run_plans.preview(request) != receipt):
                raise PlatformApplicationError("run_plan_preview_changed", "RunPlan preview changed; inspect again.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == SCRIPT_HISTORY_TOOL:
            request = ScriptHistoryQuery.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.automation_script_history if invocation.result else None
            if (request.project_id != project_id or self.automation is None or receipt is None
                    or self.automation.history(request) != receipt):
                raise PlatformApplicationError("automation_history_changed", "Script history changed; inspect again.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == SCRIPT_REVIEW_QUERY_TOOL:
            request = ScriptReviewQuery.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.automation_script_review if invocation.result else None
            if (request.project_id != project_id or self.script_reviews is None or receipt is None
                    or self.script_reviews.receipt(request) != receipt):
                raise PlatformApplicationError("automation_review_receipt_changed", "Script review changed; inspect again.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == SCRIPT_PREVIEW_TOOL:
            request = ScriptExecutionSelection.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.automation_execution_preview if invocation.result else None
            if (request.project_id != project_id or self.automation is None or receipt is None
                    or self.automation.preview(request) != receipt):
                raise PlatformApplicationError("automation_execution_preview_changed", "Automation preview changed; inspect and confirm again.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == REVIEW_DRAFT_QUERY_TOOL:
            request = ReviewDraftListInput.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.test_design_review_drafts if invocation.result else None
            if (request.project_id != project_id or self.drafts is None or receipt is None or receipt.request != request):
                raise PlatformApplicationError("review_draft_receipt_mismatch", "Draft observation cannot be verified.", 409)
            self.drafts.verify_review_receipt(receipt)
            self.access.require_invocation_project_scope(invocation)
            return receipt.model_dump(mode="json")
        if invocation.tool_id == MAPPING_QUERY_TOOL:
            request = MappingQueryInput.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.test_design_mapping if invocation.result else None
            if request.project_id != project_id or self.mappings is None or receipt is None:
                raise PlatformApplicationError("mapping_receipt_mismatch", "Mapping observation cannot be verified.", 409)
            self.mappings.verify_receipt(receipt)
            if any(getattr(receipt, key) != value for key, value in request.model_dump().items()):
                raise PlatformApplicationError("mapping_receipt_mismatch", "Mapping receipt does not match this invocation.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt.model_dump(mode="json")
        if invocation.tool_id == GENERATION_HISTORY_QUERY_TOOL:
            request = GenerationHistoryRequest.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.test_design_jobs if invocation.result else None
            if (request.project_id != project_id or self.jobs is None or receipt is None
                    or self.jobs.history(request) != receipt):
                raise PlatformApplicationError("generation_history_changed", "Generation history changed; inspect again.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == GENERATION_JOB_QUERY_TOOL:
            request = GenerationJobTarget.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.test_design_job if invocation.result else None
            if (request.project_id != project_id or self.jobs is None or receipt is None
                    or self.jobs.read(request.project_id, request.invocation_id) != receipt):
                raise PlatformApplicationError("generation_job_changed", "Generation job changed; inspect again.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt
        if invocation.tool_id == GENERATION_EXECUTION_PREVIEW_TOOL:
            request = GenerationExecutionSelection.model_validate(query_payload(invocation.input_payload))
            receipt = invocation.result.test_design_execution_preview if invocation.result else None
            if (request.project_id != project_id or self.executor is None or receipt is None
                    or self.executor.preview(request) != receipt):
                raise PlatformApplicationError("generation_execution_preview_changed", "Generation preview changed; inspect and confirm again.", 409)
            self.access.require_invocation_project_scope(invocation)
            return receipt
        is_generation = invocation.tool_id == GENERATION_QUERY_TOOL
        request = (GenerationSelection if is_generation else ScopeQueryInput).model_validate(query_payload(invocation.input_payload))
        receipt = (getattr(invocation.result, "test_design_generation" if is_generation else "test_design_scope")
                   if invocation.result else None)
        if (request.project_id != project_id or receipt is None
                or any(getattr(receipt, k) != v for k, v in request.model_dump().items())):
            raise PlatformApplicationError("scope_receipt_mismatch", "Scope receipt does not match this invocation.", 409)
        application = self.generation if is_generation else self.application
        if application is None:
            raise PlatformApplicationError("generation_observer_unavailable", "Generation input observer is unavailable.", 503)
        application.verify_receipt(receipt)
        self.access.require_invocation_project_scope(invocation)
        return receipt.model_dump(mode="json")
