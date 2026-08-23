from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, File, Form, UploadFile

from ....application.platform.project_models import ProjectCreateRequest, VersionCreateRequest, VersionSummary
from ....application.system_image.source_uploads import SourceUploadFile, SourceUploadResult
from ..dependencies import GovernanceApp, ProjectWorkspaceApp, SourceUploadApp, SystemImageApp
from ..errors import error_response

router = APIRouter()


@router.post(
    "/v1/projects/{project_id}/source-files",
    response_model=SourceUploadResult,
)
async def upload_project_source_files(
    project_id: str,
    source_uploads: SourceUploadApp,
    source_type: str = Form(...),
    files: List[UploadFile] = File(...),
) -> SourceUploadResult:
    if source_type not in {"us_doc", "test_asset"}:
        raise error_response(
            "validation_error",
            "source_type must be us_doc or test_asset for file uploads",
        )
    if len(files) > source_uploads.max_files:
        raise error_response(
            "payload_too_large",
            f"source upload exceeds max file count {source_uploads.max_files}",
            413,
        )
    try:
        source_uploads.authorize_project(project_id)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc
    except PermissionError as exc:
        raise error_response("forbidden", str(exc), 403) from exc

    uploaded_files: list[SourceUploadFile] = []
    total_bytes = 0
    try:
        for upload in files:
            body = await upload.read(source_uploads.max_single_file_bytes + 1)
            if len(body) > source_uploads.max_single_file_bytes:
                raise error_response(
                    "payload_too_large",
                    (
                        "source file exceeds max single file bytes "
                        f"{source_uploads.max_single_file_bytes}: {upload.filename or 'unnamed'}"
                    ),
                    413,
                )
            total_bytes += len(body)
            if total_bytes > source_uploads.max_bytes:
                raise error_response(
                    "payload_too_large",
                    f"source upload exceeds max total bytes {source_uploads.max_bytes}",
                    413,
                )
            uploaded_files.append(
                SourceUploadFile(
                    filename=upload.filename or "unnamed-source",
                    content_type=upload.content_type or "application/octet-stream",
                    body=body,
                )
            )
    finally:
        for upload in files:
            await upload.close()

    try:
        return source_uploads.upload(project_id, source_type, uploaded_files)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc
    except PermissionError as exc:
        raise error_response("forbidden", str(exc), 403) from exc
    except ValueError as exc:
        raise error_response("validation_error", str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise error_response("source_upload_failed", str(exc), 502) from exc


@router.get("/v1/projects")
def list_projects(project_workspace: ProjectWorkspaceApp) -> Any:
    return project_workspace.list_projects()


@router.post("/v1/projects")
async def create_project(payload: ProjectCreateRequest, project_workspace: ProjectWorkspaceApp) -> Any:
    try:
        return await project_workspace.create_project(payload)
    except ValueError as exc:
        raise error_response("validation_error", str(exc)) from exc
    except RuntimeError as exc:
        raise error_response("tool_invocation_failed", str(exc), 500) from exc


@router.get("/v1/projects/{project_id}")
def get_project(project_id: str, project_workspace: ProjectWorkspaceApp) -> Any:
    try:
        return project_workspace.get_project_workspace(project_id)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc


@router.get("/v1/projects/{project_id}/versions")
def get_versions(project_id: str, project_workspace: ProjectWorkspaceApp) -> Any:
    try:
        return project_workspace.list_versions(project_id)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc


@router.post("/v1/projects/{project_id}/versions")
async def create_version(
    project_id: str,
    payload: VersionCreateRequest,
    project_workspace: ProjectWorkspaceApp,
) -> VersionSummary:
    try:
        return await project_workspace.create_version(project_id, payload)
    except ValueError as exc:
        raise error_response("validation_error", str(exc)) from exc
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc
    except RuntimeError as exc:
        raise error_response("tool_invocation_failed", str(exc), 500) from exc


@router.get("/v1/projects/{project_id}/workspaces/{us_id}")
def get_workspace(project_id: str, us_id: str, project_workspace: ProjectWorkspaceApp) -> Any:
    try:
        return project_workspace.get_workspace_data(project_id, us_id)
    except KeyError as exc:
        raise error_response("not_found", "workspace was not found", 404) from exc


@router.get("/v1/projects/{project_id}/knowledge")
def get_project_knowledge(project_id: str, system_image: SystemImageApp) -> Any:
    try:
        return system_image.list_knowledge_objects(project_id)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc


@router.get("/v1/projects/{project_id}/system-image")
def get_project_system_image(project_id: str, system_image: SystemImageApp) -> Any:
    try:
        return system_image.get_system_image(project_id)
    except KeyError as exc:
        raise error_response("not_found", f"system image for project {project_id} was not found", 404) from exc


@router.get("/v1/projects/{project_id}/knowledge/{object_id}")
def get_knowledge_detail(project_id: str, object_id: str, system_image: SystemImageApp) -> Any:
    try:
        return system_image.get_knowledge_object(project_id, object_id)
    except (KeyError, StopIteration) as exc:
        raise error_response("not_found", f"knowledge object {object_id} was not found", 404) from exc


@router.get("/v1/projects/{project_id}/runs")
def get_project_runs(project_id: str, project_workspace: ProjectWorkspaceApp) -> Any:
    return project_workspace.list_runs(project_id)


@router.get("/v1/projects/{project_id}/runs/{run_id}")
def get_run_detail(project_id: str, run_id: str, project_workspace: ProjectWorkspaceApp) -> Any:
    try:
        return project_workspace.get_run_detail(project_id, run_id)
    except KeyError as exc:
        raise error_response("not_found", f"run {run_id} was not found", 404) from exc


@router.get("/v1/projects/{project_id}/approvals")
def get_project_approvals(project_id: str, project_workspace: ProjectWorkspaceApp) -> Any:
    return project_workspace.list_approvals(project_id)


@router.get("/v1/projects/{project_id}/approvals/{approval_id}")
def get_approval_detail(project_id: str, approval_id: str, project_workspace: ProjectWorkspaceApp) -> Any:
    try:
        return project_workspace.get_approval_detail(project_id, approval_id)
    except KeyError as exc:
        raise error_response("not_found", f"approval {approval_id} was not found", 404) from exc


@router.get("/v1/projects/{project_id}/conflicts")
def get_project_conflicts(
    project_id: str,
    governance: GovernanceApp,
    task_id: Optional[str] = None,
) -> Any:
    try:
        return governance.list_conflicts(project_id, task_id=task_id)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc


@router.get("/v1/projects/{project_id}/merged-resolutions/{resolution_id}")
def get_merged_resolution(
    project_id: str,
    resolution_id: str,
    governance: GovernanceApp,
) -> Any:
    try:
        return governance.get_merged_resolution(project_id, resolution_id)
    except KeyError as exc:
        raise error_response(
            "not_found",
            f"merged resolution {resolution_id} was not found",
            404,
        ) from exc


@router.get("/v1/tasks/{task_id}/conflicts")
def get_task_conflicts(task_id: str, governance: GovernanceApp) -> Any:
    try:
        return governance.list_task_conflicts(task_id)
    except KeyError as exc:
        raise error_response("not_found", f"task {task_id} was not found", 404) from exc


@router.get("/v1/projects/{project_id}/release-readiness")
def get_release_readiness(project_id: str, project_workspace: ProjectWorkspaceApp) -> Any:
    try:
        return project_workspace.get_release_readiness(project_id)
    except KeyError as exc:
        raise error_response("not_found", f"project {project_id} was not found", 404) from exc
