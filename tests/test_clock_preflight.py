from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from scripts.test_clock_preflight import require_current_clock, require_s3_clock


NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


@pytest.mark.parametrize("offset", [-901, -31, 31, 901])
def test_clock_drift_stops_tests_without_adjusting_confirmation_or_signatures(offset):
    with pytest.raises(RuntimeError, match="no signature or consent limit was changed"):
        require_current_clock("PostgreSQL", NOW + timedelta(seconds=offset), started=NOW, finished=NOW)


def test_s3_http_date_accepts_transport_delay_but_rejects_missing_proof():
    response = {"ResponseMetadata": {"HTTPHeaders": {"date": format_datetime(NOW)}}}
    require_s3_clock(response, started=NOW - timedelta(seconds=2), finished=NOW + timedelta(seconds=2))
    with pytest.raises(RuntimeError, match="HTTP Date"):
        require_s3_clock({}, started=NOW, finished=NOW)


@pytest.mark.parametrize("value", [None, "2026-11-17", NOW.replace(tzinfo=None)])
def test_invalid_time_never_passes_preflight(value):
    with pytest.raises(RuntimeError, match="invalid timestamp"):
        require_current_clock("PostgreSQL", value, started=NOW, finished=NOW)
