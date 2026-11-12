"""Worker diagnostics do not broaden Temporal failure payloads or retry policy."""
import pytest
from sqlalchemy.exc import ProgrammingError

from apps.api.app.domain.quality_loop.http_fixture_history import HttpFixtureHistoryUnavailable
from apps.api.app.infrastructure.workflow.execution_activity_errors import execution_activity_error


@pytest.mark.parametrize("driver_state,expected", [("42804", "42804"), ("private driver data", "none")])
def test_worker_reports_only_the_sanitized_history_failure_and_sqlstate(caplog, driver_state, expected):
    driver = RuntimeError("private driver message")
    driver.sqlstate = driver_state
    error = HttpFixtureHistoryUnavailable("private original history")
    error.__cause__ = ProgrammingError("private SQL statement", {"key": "private SQL parameter"}, driver)

    failure = execution_activity_error(error, prefix="RunPlanCase")

    assert failure.type == "RunPlanCaseInfrastructureFailure" and failure.non_retryable is False
    assert "HttpFixtureHistoryUnavailable" in caplog.text and f"sqlstate={expected}" in caplog.text
    assert "private" not in caplog.text and "private" not in str(failure)
    assert len(caplog.records) == 1 and caplog.records[0].exc_info is None


def test_worker_diagnostic_keeps_authority_denial_nonretryable(caplog):
    failure = execution_activity_error(PermissionError("private revoked source"), prefix="HttpFixture")

    assert failure.type == "HttpFixtureAuthorityDenied" and failure.non_retryable is True
    assert "HttpFixtureAuthorityDenied" in caplog.text and "sqlstate=none" in caplog.text
    assert "private" not in caplog.text and "private" not in str(failure)
