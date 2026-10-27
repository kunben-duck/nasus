"""Execution retries cannot substitute for renewed source or operation consent."""
from temporalio.exceptions import ApplicationError

from ...application.platform.errors import PlatformApplicationError
from ...domain.system_image.source_access import StaleSourceAccessScope


def execution_activity_error(error, *, prefix):
    denied = isinstance(error, (PermissionError, StaleSourceAccessScope)) or (
        isinstance(error, PlatformApplicationError) and error.status_code == 403)
    if denied:
        return ApplicationError("Original execution authority is no longer valid; explicit review is required.",
            type=prefix + "AuthorityDenied", non_retryable=True)
    return ApplicationError("Original execution infrastructure unavailable; unknown effects are never resent.",
        type=prefix + "InfrastructureFailure")
