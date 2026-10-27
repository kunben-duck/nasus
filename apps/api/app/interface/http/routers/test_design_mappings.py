from contextlib import contextmanager

from fastapi import APIRouter, Query, Response

from ....application.quality_loop.test_design_mapping_inputs import MappingQueryInput
from ....application.quality_loop.mapping_partition_inputs import MappingPartitionPageInput
from ....application.quality_loop.mapping_finalization_inputs import MappingFinalizationPreviewInput
from ....domain.quality_loop.mapping_partitions import MAX_PARTS, MappingPartitionOutOfRange
from ....domain.quality_loop.test_design_mapping import TestDesignMappingChanged, TestDesignMappingIntegrityError, TestDesignMappingInvalid
from ..dependencies import TestDesignMappingApp, MappingPartApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .image_revisions import revision_errors
from .acceptance_specifications import acceptance_errors
from .context_packs import context_errors
from .test_design_scopes import scope_errors


router = APIRouter()


@router.get("/v1/projects/{project_id}/quality/test-design-results/{generation_id}/mapping-finalization")
def inspect_mapping_finalization(project_id: str, generation_id: str, application: TestDesignMappingApp, response: Response,
                                 artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                                 plan_digest: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$")):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors(), mapping_errors():
        return application.finalization_preview(MappingFinalizationPreviewInput(project_id=project_id, generation_id=generation_id,
            generation_artifact_hash=artifact_hash, plan_digest=plan_digest))


@router.get("/v1/projects/{project_id}/quality/test-design-mapping-parts/{part_revision_id}")
def read_staged_mapping_part(project_id: str, part_revision_id: str, application: MappingPartApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors(), mapping_errors():
        return application.read(project_id, part_revision_id)


@router.get("/v1/projects/{project_id}/quality/test-design-results/{generation_id}/mapping-parts/{sequence}/staged")
def inspect_staged_mapping_part(project_id: str, generation_id: str, sequence: int, application: MappingPartApp,
                                response: Response, artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                                plan_digest: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$")):
    response.headers["Cache-Control"] = "private, no-store"
    if not 0 <= sequence < MAX_PARTS:
        raise error_response("invalid_mapping_partition", "Invalid mapping partition sequence.", 422)
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors(), mapping_errors():
        return application.inspect(MappingPartitionPageInput(project_id=project_id, generation_id=generation_id,
            generation_artifact_hash=artifact_hash, plan_digest=plan_digest, sequence=sequence))


@contextmanager
def mapping_errors():
    try:
        yield
    except MappingPartitionOutOfRange as exc:
        raise error_response("invalid_mapping_partition", "Mapping partition is outside the fixed plan.", 400) from exc
    except TestDesignMappingChanged as exc:
        raise error_response("test_design_mapping_changed", "Mapping changed; inspect again.", 409) from exc
    except (TestDesignMappingIntegrityError, TestDesignMappingInvalid) as exc:
        raise error_response("test_design_mapping_integrity_failed", "Mapping could not be verified.", 502) from exc


@router.get("/v1/projects/{project_id}/quality/test-design-results/{generation_id}/mapping-review")
def inspect_mapping(project_id: str, generation_id: str, application: TestDesignMappingApp, response: Response,
                    artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$")):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors(), mapping_errors():
        return application.inspect(MappingQueryInput(project_id=project_id, generation_id=generation_id, generation_artifact_hash=artifact_hash))


@router.get("/v1/projects/{project_id}/quality/test-design-mapping-reviews/{revision_id}")
def read_mapping(project_id: str, revision_id: str, application: TestDesignMappingApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors(), mapping_errors():
        return application.read(project_id, revision_id)


@router.get("/v1/projects/{project_id}/quality/test-design-results/{generation_id}/mapping-plan")
def inspect_mapping_plan(project_id: str, generation_id: str, application: TestDesignMappingApp, response: Response,
                         artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$")):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors(), mapping_errors():
        return application.partition_plan(MappingQueryInput(project_id=project_id, generation_id=generation_id,
            generation_artifact_hash=artifact_hash))


@router.get("/v1/projects/{project_id}/quality/test-design-results/{generation_id}/mapping-parts/{sequence}")
def inspect_mapping_part(project_id: str, generation_id: str, application: TestDesignMappingApp, response: Response,
                         sequence: int, artifact_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                         plan_digest: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$")):
    response.headers["Cache-Control"] = "private, no-store"
    if not 0 <= sequence < MAX_PARTS:
        raise error_response("invalid_mapping_partition", "Invalid mapping partition sequence.", 422)
    with revision_errors(), evidence_read_errors(), acceptance_errors(), context_errors(), scope_errors(), mapping_errors():
        return application.partition_page(MappingPartitionPageInput(project_id=project_id, generation_id=generation_id,
            generation_artifact_hash=artifact_hash, plan_digest=plan_digest, sequence=sequence))
