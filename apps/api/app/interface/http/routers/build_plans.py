from contextlib import contextmanager

from fastapi import APIRouter, Query, Response

from ....application.system_image.build_plans import BuildPlanList, StoredBuildPlan
from ....application.system_image.build_plan_revisions import StoredBuildPlanRevision, BuildPlanRevisionGoal
from ....application.agent.image_plan_phases import StoredImagePlanPhase
from ....application.system_image.structure_commands import StructureCommandPage
from ....application.system_image.structure_cancel_inputs import StructureCancelInput, StructureCancelStatus
from ....application.system_image.investigations import StoredInvestigation
from ....application.system_image.code_analysis_queries import CodeAnalysisIntegrityError
from ....application.platform.errors import PlatformApplicationError
from ....domain.system_image.build_plan import BuildPlanIntegrityError
from ....domain.system_image.build_plan import BuildTarget
from ....domain.system_image.publication import PublicationChanged, PublicationIntegrityError
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ....domain.agent.resume_checkpoint import AgentResumeCheckpointChanged
from ....domain.system_image.source_delta import SourceDeltaIntegrityError, SourceDeltaUnavailable
from ....domain.system_image.image_revision import ImageRevisionIntegrityError, ImageArtifactUnavailable
from ....domain.system_image.evidence import EvidenceIntegrityError, EvidenceUnavailableError
from ..dependencies import BuildPlanApp, StructureCancellationApp, InvestigationApp, BuildCompletionObservationApp, GapOwnershipApp
from ..errors import error_response


router = APIRouter()


@router.get("/v1/projects/{project_id}/system-image/build-completions/{invocation_id}/gap-owners")
def read_gap_owner_options(project_id: str, invocation_id: str, application: GapOwnershipApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.owner_options(project_id, invocation_id)


@router.get("/v1/projects/{project_id}/system-image/build-completions/{invocation_id}/gap-ownership")
def read_gap_ownership(project_id: str, invocation_id: str, application: GapOwnershipApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.read(project_id, invocation_id)


@router.get("/v1/projects/{project_id}/system-image/build-completions/{invocation_id}")
def read_build_completion(project_id: str, invocation_id: str, application: BuildCompletionObservationApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        result = application.describe(invocation_id, project_id)
        if result is None:
            raise KeyError("completed assessment not found")
        return result


@router.get("/v1/projects/{project_id}/system-image/build-targets/{baseline_id}", response_model=BuildTarget)
def read_build_target(project_id: str, baseline_id: str, application: BuildPlanApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.target(project_id, baseline_id)


@router.get("/v1/projects/{project_id}/system-image/build-investigations/{revision_id}", response_model=StoredInvestigation)
def read_investigation(project_id: str, revision_id: str, application: InvestigationApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.read(project_id, revision_id)


@contextmanager
def plan_errors():
    try:
        yield
    except KeyError as exc:
        raise error_response("not_found", "Build plan was not found.", 404) from exc
    except StaleSourceAccessScope as exc:
        raise error_response("source_access_changed", "Source access changed; reload the plan.", 409) from exc
    except SourceAccessDenied as exc:
        raise error_response("source_access_denied", "Build inputs are not available.", 403) from exc
    except PublicationChanged as exc:
        raise error_response("build_target_changed", "Build target changed; reload before preparing a plan.", 409) from exc
    except PublicationIntegrityError as exc:
        raise error_response("build_target_integrity_failed", "Build target failed integrity verification.", 502) from exc
    except BuildPlanIntegrityError as exc:
        raise error_response("build_plan_integrity_failed", "Build plan failed integrity verification.", 502) from exc
    except PlatformApplicationError:
        raise
    except AgentResumeCheckpointChanged as exc:
        raise error_response("build_goal_changed", "Build goal changed; reload its checkpoint.", 409) from exc
    except (SourceDeltaIntegrityError, ImageRevisionIntegrityError, EvidenceIntegrityError, CodeAnalysisIntegrityError) as exc:
        raise error_response("build_evidence_integrity_failed", "Build evidence failed integrity verification.", 502) from exc
    except (SourceDeltaUnavailable, ImageArtifactUnavailable, EvidenceUnavailableError) as exc:
        raise error_response("build_evidence_unavailable", "Build evidence is unavailable.", 503) from exc
    except ValueError as exc:
        raise error_response("validation_error", "Invalid build plan page.", 400) from exc


@router.get("/v1/projects/{project_id}/system-image/build-plans", response_model=BuildPlanList)
def list_build_plans(project_id: str, application: BuildPlanApp, response: Response,
                     after_id: str = Query("", max_length=64), limit: int = Query(20, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.list(project_id, after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/build-plans/{plan_id}", response_model=StoredBuildPlan)
def read_build_plan(project_id: str, plan_id: str, application: BuildPlanApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.read(project_id, plan_id)


@router.get("/v1/projects/{project_id}/system-image/build-plans/{plan_id}/revision-goals", response_model=list[BuildPlanRevisionGoal])
def revision_goals(project_id: str, plan_id: str, application: BuildPlanApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.revisions.eligible_goals(project_id, plan_id)


@router.get("/v1/projects/{project_id}/system-image/build-plans/{plan_id}/revisions", response_model=list[StoredBuildPlanRevision])
def plan_revisions(project_id: str, plan_id: str, application: BuildPlanApp, response: Response,
                   goal_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.revisions.history(project_id, plan_id, goal_id)


@router.get("/v1/projects/{project_id}/system-image/build-plans/{plan_id}/phases", response_model=list[StoredImagePlanPhase])
def plan_phases(project_id: str, plan_id: str, application: BuildPlanApp, response: Response,
                goal_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.phases.history(project_id, plan_id, goal_id)


@router.get("/v1/projects/{project_id}/system-image/build-plans/{plan_id}/structure-commands", response_model=StructureCommandPage)
def list_structure_commands(project_id: str, plan_id: str, application: BuildPlanApp, response: Response,
                            plan_digest: str = Query(..., min_length=1, max_length=128),
                            after_id: str = Query("", max_length=128), limit: int = Query(20, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.unfinished_structure_commands(project_id, plan_id, plan_digest=plan_digest,
            after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/build-plans/{plan_id}/structure-commands/{invocation_id}/status",
            response_model=StructureCancelStatus)
def read_structure_status(project_id: str, plan_id: str, invocation_id: str,
                          application: StructureCancellationApp, response: Response,
                          plan_digest: str = Query(..., min_length=1, max_length=128),
                          target_baseline_id: str = Query(..., min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with plan_errors():
        return application.inspect(StructureCancelInput(project_id=project_id, plan_id=plan_id,
            original_invocation_id=invocation_id, plan_digest=plan_digest, target_baseline_id=target_baseline_id))
