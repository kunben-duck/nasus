from typing import Any, Protocol

from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from .account_models import UserProfile
from .errors import PlatformApplicationError
from .tool_models import ToolInvocation


class InvocationResourcePolicyPort(Protocol):
    """Resource owners decide receipt access independently of project membership."""

    def can_access(self, invocation: Any, actor: UserProfile) -> bool: ...

    def broadcast_view(self, invocation: ToolInvocation) -> ToolInvocation: ...


def resource_access_failure(invocation: ToolInvocation, error: Exception) -> bool:
    """Hide denied/unresolved scopes, never hide a failed verification service."""
    if isinstance(error, PlatformApplicationError):
        if error.status_code == 403:
            return False
        raise error
    if isinstance(error, (SourceAccessDenied, StaleSourceAccessScope, KeyError)):
        return False
    if isinstance(error, (ValueError, BuildPlanIntegrityError)):
        # Invalid attempted inputs do not establish a readable resource. A
        # completed receipt, however, must retain its original valid contract.
        if invocation.status != "completed":
            return False
        raise PlatformApplicationError("resource_receipt_invalid", "Original resource receipt could not be verified.", 502) from error
    raise PlatformApplicationError("resource_receipt_access_unavailable", "Original resource authorization is unavailable.", 503) from error
