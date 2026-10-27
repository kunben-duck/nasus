"""Each public context must import in a fresh interpreter without app/main or DB."""
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("module", [
    "apps.api.app.application.quality_loop.http_fixture_history",
    "apps.api.app.application.quality_loop.http_fixture_observations",
    "apps.api.app.application.quality_loop.http_fixture_jobs",
    "apps.api.app.application.quality_loop.run_plan_case_jobs",
    "apps.api.app.infrastructure.persistence.run_plan_case_job_repository",
    "apps.api.app.infrastructure.workflow.run_plan_case_runtime",
    "apps.api.app.interface.http.routers.run_plans",
    "apps.api.app.application.platform.runtime",
    "apps.api.app.tool_invocation_handlers",
])
def test_context_import_is_order_independent_and_does_not_create_the_api(module):
    result = subprocess.run([sys.executable, "-c", f"import importlib,sys; importlib.import_module({module!r}); assert 'apps.api.app.main' not in sys.modules"],
        cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_query_helper_does_not_eagerly_import_registry_and_public_exports_remain_compatible():
    script = """
import sys
from apps.api.app.application.platform.tool_handlers.query_input import query_payload
assert query_payload({'project_id':'p','idempotency_key':'private'}) == {'project_id':'p'}
assert 'apps.api.app.application.platform.tool_handlers.registry' not in sys.modules
from apps.api.app.application.platform import tool_handlers
from apps.api.app.application.platform.tool_handlers import ToolInvocationHandlerRegistry, build_tool_handler_registry
assert ToolInvocationHandlerRegistry is tool_handlers.ToolInvocationHandlerRegistry
assert build_tool_handler_registry is tool_handlers.build_tool_handler_registry
assert set(tool_handlers.__all__) == set(tool_handlers._EXPORT_MODULES)
try:
    tool_handlers.missing_handler
except AttributeError:
    pass
else:
    raise AssertionError('unknown export was accepted')
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
