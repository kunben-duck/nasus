from contextlib import contextmanager
from typing import Literal, Optional

from fastapi import APIRouter, Query, Response

from ....application.platform.errors import PlatformApplicationError
from ....application.system_image.image_revision_queries import ImageRevisionList, ImageRevisionPage
from ....application.system_image.evidence_queries import EvidencePage
from ....application.system_image.image_query_tools import ImageQueryObservation
from ....application.system_image.code_member_deltas import CodeMemberDeltaApplicationService, CodeMemberDeltaPage
from ....application.system_image.reference_links import ReferenceProposalPage
from ....application.system_image.link_decisions import LinkDecisionPage
from ....domain.system_image.image_revision import ImageArtifactUnavailable, ImageRevisionIntegrityError, ImageRevisionPageTooLarge
from ....domain.system_image.evidence import EvidenceIntegrityError, EvidencePageTooLarge
from ....domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from ....domain.system_image.source_delta import SourceDeltaIntegrityError, SourceDeltaPageTooLarge, SourceDeltaUnavailable
from ....domain.system_image.code_alias import AmbiguousCodeObjectAlias
from ..dependencies import ImageRevisionApp, ToolImageApp, ReferenceLinkApp, LinkDecisionApp, SemanticEvaluationApp, SemanticReviewApp
from ..errors import error_response
from ..evidence_errors import evidence_read_errors
from .source_documents import document_errors


router = APIRouter()


@router.get("/v1/projects/{project_id}/system-image/code-member-delta", response_model=CodeMemberDeltaPage)
def read_code_member_delta(project_id: str, application: ImageRevisionApp, response: Response,
                           before_image_revision_id: str = Query(..., min_length=1, max_length=128),
                           before_image_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                           after_image_revision_id: str = Query(..., min_length=1, max_length=128),
                           after_image_hash: str = Query(..., pattern=r"^sha256:[0-9a-f]{64}$"),
                           kind: Optional[Literal["added_member", "removed_member", "revision_changed", "projection_changed", "unchanged"]] = None,
                           offset: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors():
        return CodeMemberDeltaApplicationService(application).read(project_id, before_image_revision_id, before_image_hash,
            after_image_revision_id, after_image_hash, kind=kind, offset=offset, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/semantic-evaluations/{evaluation_id}/subjects/{subject_object_id}/reviews")
def read_semantic_reviews(project_id: str, evaluation_id: str, subject_object_id: str, application: SemanticReviewApp, response: Response,
                          offset: int = Query(0, ge=0, le=1000), limit: int = Query(20, ge=1, le=50),
                          through_decision_id: Optional[str] = Query(None, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors():
        return application.read(project_id, evaluation_id, subject_object_id, offset=offset, limit=limit, through_decision_id=through_decision_id)


@router.get("/v1/projects/{project_id}/system-image/revisions/{image_revision_id}/semantic-evaluations")
def list_semantic_evaluations(project_id: str, image_revision_id: str, application: SemanticEvaluationApp, response: Response,
                             target_object_id: str = Query(..., min_length=1, max_length=128),
                             relation: Literal["implements", "asserts"] = "implements",
                             after_id: str = Query("", max_length=128), limit: int = Query(20, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors():
        return application.list_for_target(project_id, image_revision_id, target_object_id, relation, after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/semantic-evaluations/{invocation_id}")
def read_semantic_evaluation(project_id: str, invocation_id: str, application: SemanticEvaluationApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors():
        return application.read(project_id, invocation_id)


@router.get("/v1/projects/{project_id}/system-image/revisions/{image_revision_id}/reference-proposals")
def list_reference_proposals(project_id: str, image_revision_id: str, application: ReferenceLinkApp, response: Response,
                            after_id: str = Query("", max_length=128), limit: int = Query(20, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors():
        return application.list_for_image(project_id, image_revision_id, after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/reference-proposals/{proposal_id}/assertions/{assertion_id}/decisions", response_model=LinkDecisionPage)
def read_link_decisions(project_id: str, proposal_id: str, assertion_id: str, application: LinkDecisionApp, response: Response,
                       offset: int = Query(0, ge=0, le=1000), limit: int = Query(20, ge=1, le=50),
                       through_decision_id: Optional[str] = Query(None, max_length=128)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors():
        return application.read(project_id, proposal_id, assertion_id, offset=offset, limit=limit, through_decision_id=through_decision_id)


@router.get("/v1/projects/{project_id}/system-image/reference-proposals/{proposal_id}", response_model=ReferenceProposalPage)
def read_reference_proposal(project_id: str, proposal_id: str, application: ReferenceLinkApp, response: Response,
                           section: Literal["assertions", "gaps"] = "assertions", offset: int = Query(0, ge=0, le=10000),
                           limit: int = Query(20, ge=1, le=50)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors():
        return application.read(project_id, proposal_id, section=section, offset=offset, limit=limit)


@contextmanager
def revision_errors():
    try:
        yield
    except KeyError as exc:
        raise error_response("not_found", "Image revision was not found.", 404) from exc
    except StaleSourceAccessScope as exc:
        raise error_response("source_access_changed", "Source access changed; reload the image.", 409) from exc
    except SourceAccessDenied as exc:
        raise error_response("source_access_denied", "Image inputs are not available.", 403) from exc
    except ImageRevisionIntegrityError as exc:
        raise error_response("image_integrity_failed", "Image revision failed integrity verification.", 502) from exc
    except EvidenceIntegrityError as exc:
        raise error_response("evidence_integrity_failed", "Image source evidence failed integrity verification.", 502) from exc
    except ImageArtifactUnavailable as exc:
        raise error_response("image_artifact_unavailable", "Image revision is unavailable.", 503) from exc
    except SourceDeltaIntegrityError as exc:
        raise error_response("source_delta_integrity_failed", "Source delta failed integrity verification.", 502) from exc
    except SourceDeltaUnavailable as exc:
        raise error_response("source_delta_unavailable", "Source delta archive is unavailable.", 503) from exc
    except SourceDeltaPageTooLarge as exc:
        raise error_response("source_delta_page_too_large", "Request fewer changes; page exceeds 64 KiB.", 413) from exc
    except AmbiguousCodeObjectAlias as exc:
        raise error_response("code_alias_ambiguous", "Code reference is ambiguous in this image; select an exact frozen member.", 409) from exc
    except (ImageRevisionPageTooLarge, EvidencePageTooLarge) as exc:
        raise error_response("image_page_too_large", "Request fewer items; page exceeds 64 KiB.", 413) from exc
    except PlatformApplicationError:
        raise
    except ValueError as exc:
        raise error_response("validation_error", "Invalid image revision page.", 400) from exc


@router.get("/v1/projects/{project_id}/system-image/revisions", response_model=ImageRevisionList)
def list_image_revisions(project_id: str, application: ImageRevisionApp, response: Response,
                         after_id: str = Query("", max_length=64), limit: int = Query(20, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors():
        return application.list(project_id, after_id=after_id, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/revisions/{image_revision_id}", response_model=ImageRevisionPage)
def read_image_revision(project_id: str, image_revision_id: str, application: ImageRevisionApp, response: Response,
                        section: Literal["objects", "relationships", "members", "source_members", "assertion_members", "semantic_assertion_members"] = "objects",
                        offset: int = Query(0, ge=0, le=100000), limit: int = Query(25, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors():
        return application.read(project_id, image_revision_id, section=section, offset=offset, limit=limit)


@router.get("/v1/projects/{project_id}/system-image/revisions/{image_revision_id}/objects/{object_id}/evidence/{evidence_id}",
            response_model=EvidencePage)
def read_image_evidence(project_id: str, image_revision_id: str, object_id: str, evidence_id: str,
                        application: ImageRevisionApp, response: Response,
                        start_line: Optional[int] = Query(None, ge=1), max_lines: int = Query(100, ge=1, le=200)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors():
        return application.read_evidence(project_id, image_revision_id, object_id, evidence_id,
                                         start_line=start_line, max_lines=max_lines)


@router.get("/v1/projects/{project_id}/system-image/revisions/{image_revision_id}/objects/{object_id}/identity")
def resolve_code_object(project_id: str, image_revision_id: str, object_id: str, application: ImageRevisionApp, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors():
        return application.resolve_code_object(project_id, image_revision_id, object_id)


@router.get("/v1/tool-invocations/{invocation_id}/image-query", response_model=ImageQueryObservation)
def expand_image_query(invocation_id: str, application: ToolImageApp, response: Response):
    from .context_change_impact import context_impact_errors
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), evidence_read_errors(handle_validation=False), context_impact_errors():
        return application.expand(invocation_id)


@router.get("/v1/projects/{project_id}/system-image/revisions/{image_revision_id}/objects/{object_id}/document")
def read_image_document(project_id: str, image_revision_id: str, object_id: str, application: ImageRevisionApp,
                        response: Response, offset: int = Query(0, ge=0, le=90), limit: int = Query(20, ge=1, le=90)):
    response.headers["Cache-Control"] = "private, no-store"
    with revision_errors(), document_errors():
        return application.read_document(project_id, image_revision_id, object_id, offset=offset, limit=limit)
