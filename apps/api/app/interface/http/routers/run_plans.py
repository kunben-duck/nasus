from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Query, Response

from ....application.platform.errors import PlatformApplicationError
from ....application.quality_loop.run_plan_inputs import RunPlanSelection
from ....application.quality_loop.run_plan_locators import RunPlanLocatorQuery
from ....application.quality_loop.run_plan_build_inputs import RunPlanBuildSelection
from ....application.quality_loop.http_fixture_jobs import HttpFixtureJobTarget
from ....application.quality_loop.run_plan_case_jobs import RunPlanCaseJobTarget
from ....domain.quality_loop.run_plan_case_execution import RunPlanCaseExecutionInvalid, RunPlanCaseWorkLost
from ....application.quality_loop.http_fixture_history import HttpFixtureHistoryQuery, HttpFixtureHistoryTarget, HttpFixtureHistoryPage, HttpFixtureHistoryItem
from ....application.quality_loop.http_fixture_observations import HttpFixtureOriginalObservation
from ....domain.quality_loop.run_plan import RunPlanChanged, RunPlanIntegrityError, RunPlanInvalid
from ....domain.quality_loop.run_plan_observations import RunPlanObservationInvalid
from ....domain.quality_loop.http_fixture_history import HttpFixtureHistoryUnavailable
from ....domain.quality_loop.http_fixture_observation import HttpFixtureObservationChanged
from ....domain.system_image.source_access import StaleSourceAccessScope
from ..dependencies import RunPlanApp, RunPlanLocatorApp, RunPlanBuildApp, RunPlanObservationsApp, NativeBuildApp, EnvironmentRecordsApp, EnvironmentHealthApp
from ..dependencies import HttpLocatorRecordsApp, HttpFixtureRecipesApp
from ..dependencies import HttpFixtureGrantsApp, HttpFixtureJobsApp
from ..dependencies import RunPlanCaseJobsApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .acceptance_specifications import acceptance_errors
from .automation_inputs import automation_input_errors
from .automation_scripts import script_review_errors
from .context_packs import context_errors
from .image_revisions import revision_errors
from .test_design_mappings import mapping_errors
from .test_design_scopes import scope_errors


router = APIRouter()


@router.get("/v1/projects/{project_id}/quality/run-plan-case-executions/{invocation_id}")
def read_original_run_plan_cases(project_id: str, invocation_id: str, application: RunPlanCaseJobsApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False):
        try:
            return application.read(RunPlanCaseJobTarget(project_id=project_id, invocation_id=invocation_id))
        except RunPlanCaseWorkLost as exc:
            raise error_response("case_execution_changed", "Original case history changed; inspect the same command again.", 409) from exc
        except RunPlanCaseExecutionInvalid as exc:
            raise error_response("case_execution_invalid", "Original case execution history cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/http-fixture-operations", response_model=HttpFixtureHistoryPage)
def list_http_fixture_operations(project_id: str, application: HttpFixtureJobsApp, response: Response,
                                 after_id: str = Query(default="", max_length=128), limit: int = Query(default=3, ge=1, le=5)):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False):
        try:
            return application.history.list(HttpFixtureHistoryQuery(project_id=project_id, after_id=after_id, limit=limit))
        except HttpFixtureHistoryUnavailable as exc:
            raise error_response("fixture_history_unavailable", "Original fixture history is temporarily unavailable.", 503) from exc
        except (PlatformApplicationError, StaleSourceAccessScope):
            raise
        except ValueError as exc:
            raise error_response("fixture_history_invalid", "Original fixture history cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/http-fixture-operations/{invocation_id}", response_model=HttpFixtureHistoryItem)
def read_http_fixture_operation(project_id: str, invocation_id: str, application: HttpFixtureJobsApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False):
        try:
            return application.history.read(HttpFixtureHistoryTarget(project_id=project_id, invocation_id=invocation_id))
        except HttpFixtureHistoryUnavailable as exc:
            raise error_response("fixture_history_unavailable", "Original fixture history is temporarily unavailable.", 503) from exc
        except (PlatformApplicationError, StaleSourceAccessScope):
            raise
        except ValueError as exc:
            raise error_response("fixture_history_invalid", "Original fixture command ancestry cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/http-fixture-operations/{invocation_id}/observation", response_model=HttpFixtureOriginalObservation)
def read_original_http_fixture_observation(project_id: str, invocation_id: str, application: HttpFixtureJobsApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False):
        try:
            return application.observations.read(HttpFixtureHistoryTarget(project_id=project_id, invocation_id=invocation_id))
        except HttpFixtureHistoryUnavailable as exc:
            raise error_response("fixture_history_unavailable", "Original fixture history is temporarily unavailable.", 503) from exc
        except HttpFixtureObservationChanged as exc:
            raise error_response("fixture_observation_changed", "Original command changed; inspect the same command again.", 409) from exc
        except (PlatformApplicationError, StaleSourceAccessScope):
            raise
        except ValueError as exc:
            raise error_response("fixture_observation_invalid", "Original fixture journal cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/http-fixture-executions/{invocation_id}")
def read_http_fixture_execution(project_id: str, invocation_id: str, application: HttpFixtureJobsApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False):
        try:
            return application.read(HttpFixtureJobTarget(project_id=project_id, invocation_id=invocation_id))
        except (PlatformApplicationError, StaleSourceAccessScope):
            raise
        except ValueError as exc:
            raise error_response("fixture_execution_invalid", "Original fixture observation cannot be verified.", 502) from exc


@contextmanager
def private_read_errors():
    try:
        yield
    except PlatformApplicationError as exc:
        error = error_response(exc.code, exc.message, exc.status_code)
        error.headers = {"Cache-Control": "private, no-store"}
        raise error from exc
    except HTTPException as exc:
        # Exception responses do not inherit the endpoint's Response headers.
        exc.headers = {**(exc.headers or {}), "Cache-Control": "private, no-store"}
        raise


@contextmanager
def run_plan_errors():
    try:
        yield
    except RunPlanChanged as exc:
        raise error_response("run_plan_changed", "RunPlan inputs changed; preview and confirm again.", 409) from exc
    except RunPlanInvalid as exc:
        raise error_response("run_plan_incomplete", "RunPlan must preserve every reviewed case, source and fixture declaration.", 409) from exc
    except RunPlanIntegrityError as exc:
        raise error_response("run_plan_invalid", "RunPlan original provenance cannot be verified.", 502) from exc


@router.post("/v1/projects/{project_id}/quality/run-plan-previews")
def preview_run_plan(project_id: str, selection: RunPlanSelection, application: RunPlanApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    if project_id != selection.project_id:
        raise error_response("run_plan_scope_mismatch", "RunPlan preview project differs from its route.", 422)
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        return application.preview(selection)


@router.get("/v1/projects/{project_id}/quality/run-plans/{run_plan_id}")
def read_run_plan(project_id: str, run_plan_id: str, application: RunPlanApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        return application.read(project_id, run_plan_id)


@router.get("/v1/projects/{project_id}/quality/run-plans/{run_plan_id}/http-locators")
def inspect_run_plan_locators(project_id: str, run_plan_id: str, application: RunPlanLocatorApp, response: Response,
                              run_plan_artifact_hash: str = Query(pattern=r"^sha256:[0-9a-f]{64}$")):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        return application.inspect(RunPlanLocatorQuery(project_id=project_id, run_plan_id=run_plan_id,
            run_plan_artifact_hash=run_plan_artifact_hash))


@router.get("/v1/projects/{project_id}/quality/run-plan-observations/{record_id}")
def read_run_plan_observations(project_id: str, record_id: str, application: RunPlanObservationsApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        try:
            return application.read(project_id, record_id)
        except RunPlanObservationInvalid as exc:
            raise error_response("run_plan_observations_invalid", "Original observations cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/run-plan-locators/{record_id}")
def read_locator_record(project_id: str, record_id: str, application: HttpLocatorRecordsApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        try:
            return application.read(project_id, record_id)
        except ValueError as exc:
            raise error_response("locator_record_invalid", "Original source locator evidence cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/http-fixture-recipes/{record_id}")
def read_fixture_recipe(project_id: str, record_id: str, application: HttpFixtureRecipesApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        try:
            return application.read(project_id, record_id)
        except ValueError as exc:
            raise error_response("fixture_recipe_invalid", "Original fixture definition cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/http-fixture-grants/{record_id}")
def read_fixture_grant(project_id: str, record_id: str, application: HttpFixtureGrantsApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        try:
            return application.read(project_id, record_id)
        except ValueError as exc:
            raise error_response("fixture_grant_invalid", "Original fixture consent cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/run-plan-health/{record_id}")
def read_health_record(project_id: str, record_id: str, application: EnvironmentHealthApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        try:
            return application.read(project_id, record_id)
        except ValueError as exc:
            raise error_response("health_record_invalid", "Original instance health cannot be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/run-plan-environments/{record_id}")
def read_environment_record(project_id: str, record_id: str, application: EnvironmentRecordsApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        try:
            return application.read(project_id, record_id)
        except ValueError as exc:
            raise error_response("environment_record_invalid", "Original environment inventory cannot be verified.", 502) from exc


@router.post("/v1/projects/{project_id}/quality/run-plan-build-previews")
def preview_run_plan_build(project_id: str, selection: RunPlanBuildSelection, application: RunPlanBuildApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    if project_id != selection.project_id:
        raise error_response("run_plan_scope_mismatch", "Build binding project differs from its route.", 422)
    with revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        return application.preview(selection)


@router.get("/v1/projects/{project_id}/quality/run-plan-builds/{binding_id}")
def read_run_plan_build(project_id: str, binding_id: str, application: RunPlanBuildApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False), acceptance_errors(), context_errors(), scope_errors(), mapping_errors(), automation_input_errors(), script_review_errors(), run_plan_errors():
        return application.read(project_id, binding_id)


@router.get("/v1/projects/{project_id}/quality/native-builds/{invocation_id}")
def read_native_build(project_id: str, invocation_id: str, application: NativeBuildApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with private_read_errors(), revision_errors(), evidence_read_errors(handle_validation=False):
        try:
            return application.read(project_id, invocation_id)
        except PlatformApplicationError:
            raise
        except ValueError as exc:
            raise error_response("native_build_invalid", "Original native build cannot be verified.", 502) from exc
