from contextlib import contextmanager

from ...application.platform.errors import PlatformApplicationError
from ...domain.system_image.evidence import (
    EvidenceIntegrityError, EvidenceLocationUnavailable, EvidencePageTooLarge, EvidenceUnavailableError,
)
from ...domain.system_image.source_access import StaleSourceAccessScope
from .errors import error_response


@contextmanager
def evidence_read_errors(*, handle_validation: bool = True):
    try:
        yield
    except KeyError as exc:
        raise error_response("not_found", "Source evidence was not found.", 404) from exc
    except EvidenceLocationUnavailable as exc:
        raise error_response("evidence_location_unavailable", "This evidence has no exact source location.", 409) from exc
    except EvidencePageTooLarge as exc:
        raise error_response("evidence_too_large", "Request fewer source lines; this page exceeds 64 KiB.", 413) from exc
    except EvidenceIntegrityError as exc:
        raise error_response("evidence_integrity_failed", "Archived evidence failed integrity verification.", 502) from exc
    except EvidenceUnavailableError as exc:
        raise error_response("evidence_unavailable", "Archived evidence is temporarily unavailable.", 503) from exc
    except PlatformApplicationError:
        raise
    except StaleSourceAccessScope:
        # The outer source/image scope handler owns authorization conflicts.
        raise
    except ValueError as exc:
        if not handle_validation:
            raise
        raise error_response("validation_error", "Requested lines are outside the evidence range.", 400) from exc
