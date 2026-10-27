"""Compose resource policies without teaching ToolRuntime domain internals."""
from __future__ import annotations

from .errors import PlatformApplicationError
from .run_plan_receipts import RUN_PLAN_RECEIPT_TOOLS
from .run_plan_build_receipts import RUN_PLAN_BUILD_RECEIPT_TOOLS
from .native_build_receipts import NATIVE_BUILD_RECEIPT_TOOLS
from ..quality_loop.run_plan_observation_records import OBSERVATION_RECORD_TOOLS
from ..quality_loop.run_plan_environments import RUN_PLAN_ENVIRONMENT_QUERY_TOOL
from ..quality_loop.run_plan_locators import RUN_PLAN_LOCATOR_QUERY_TOOL
from ...domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_TOOLS
from ...domain.quality_loop.environment_health_record import HEALTH_RECORD_TOOLS
from ...domain.quality_loop.http_locator_record import LOCATOR_RECORD_TOOLS
from ...domain.quality_loop.http_fixture_recipe import RECIPE_TOOLS
from ...domain.quality_loop.http_fixture_grant import GRANT_TOOLS
from ...domain.quality_loop.http_fixture_command import FIXTURE_JOB_TOOLS


RESOURCE_RECEIPT_TOOLS = RUN_PLAN_RECEIPT_TOOLS | RUN_PLAN_BUILD_RECEIPT_TOOLS | NATIVE_BUILD_RECEIPT_TOOLS | OBSERVATION_RECORD_TOOLS | ENVIRONMENT_RECORD_TOOLS | HEALTH_RECORD_TOOLS | LOCATOR_RECORD_TOOLS | RECIPE_TOOLS | GRANT_TOOLS | FIXTURE_JOB_TOOLS | {"system_image.sources.ingest", RUN_PLAN_ENVIRONMENT_QUERY_TOOL, RUN_PLAN_LOCATOR_QUERY_TOOL}


def require_receipt_access(resources, invocation):
    required = invocation.tool_id in RESOURCE_RECEIPT_TOOLS
    applies = getattr(resources, "applies", None)
    if (resources is None or callable(applies) and not applies(invocation)) and required:
        raise PlatformApplicationError("source_receipt_access_unavailable", "Original resource receipt authorization is unavailable.", 503)
    if resources is not None:
        resources.require_access(invocation)


class ToolReceiptAccess:
    def __init__(self, *policies):
        self.policies = policies

    def applies(self, invocation):
        return any(policy.applies(invocation) for policy in self.policies)

    def require_access(self, invocation):
        for policy in self.policies:
            if policy.applies(invocation):
                policy.require_access(invocation)

    def require_batch_access(self, invocations):
        for policy in self.policies:
            policy.require_batch_access(invocations)

    def broadcast_view(self, invocation):
        for policy in self.policies:
            invocation = policy.broadcast_view(invocation)
        return invocation
