"""Fail early on local infrastructure clock drift, never adjust signed timestamps."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


MAX_CLOCK_SKEW_SECONDS = 30


def require_current_clock(service, remote, *, started, finished):
    if (not isinstance(remote, datetime) or remote.tzinfo is None
            or started.tzinfo is None or finished.tzinfo is None or finished < started):
        raise RuntimeError(f"{service} clock preflight returned an invalid timestamp")
    # Accommodate transport time and HTTP Date's one-second precision, not drift.
    skew = max((started - remote).total_seconds(), (remote - finished).total_seconds(), 0)
    if skew > MAX_CLOCK_SKEW_SECONDS:
        raise RuntimeError(f"{service} clock differs from the host by at least {int(skew)} seconds; "
            "synchronize the local container VM clock before running tests; no signature or consent limit was changed")


def require_s3_clock(response, *, started, finished=None):
    try:
        remote = parsedate_to_datetime(response["ResponseMetadata"]["HTTPHeaders"]["date"])
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise RuntimeError("MinIO clock preflight requires a valid HTTP Date") from None
    require_current_clock("MinIO", remote, started=started, finished=finished or datetime.now(timezone.utc))
