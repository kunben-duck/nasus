"""Execution retries cannot substitute for renewed source or operation consent."""
import logging
import re

from sqlalchemy.exc import DBAPIError
from temporalio.exceptions import ApplicationError

from ...application.platform.errors import PlatformApplicationError
from ...domain.quality_loop.run_plan_case_execution import RunPlanCaseConsentExpired
from ...domain.system_image.source_access import StaleSourceAccessScope

logger = logging.getLogger(__name__)
ERROR_TYPE = re.compile(r"[A-Za-z_][A-Za-z_0-9]{0,79}")
SQLSTATE = re.compile(r"[A-Z0-9]{5}")


def _sqlstate(error):
    for _ in range(8):
        if error is None:
            break
        if isinstance(error, DBAPIError):
            for name in ("sqlstate", "pgcode"):
                value = getattr(error.orig, name, None)
                if type(value) is str and SQLSTATE.fullmatch(value):
                    return value
        error = error.__cause__
    return "none"


def execution_activity_error(error, *, prefix):
    denied = isinstance(error, (PermissionError, StaleSourceAccessScope, RunPlanCaseConsentExpired)) or (
        isinstance(error, PlatformApplicationError) and error.status_code == 403)
    category = prefix + ("AuthorityDenied" if denied else "InfrastructureFailure")
    error_type = type(error).__name__
    logger.warning("Original execution activity failed; category=%s exception=%s sqlstate=%s",
        category, error_type if ERROR_TYPE.fullmatch(error_type) else "Exception", _sqlstate(error))
    if denied:
        return ApplicationError("Original execution authority is no longer valid; explicit review is required.",
            type=category, non_retryable=True)
    return ApplicationError("Original execution infrastructure unavailable; unknown effects are never resent.",
        type=category)
