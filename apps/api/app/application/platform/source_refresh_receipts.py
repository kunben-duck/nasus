"""Live source authorization for targeted and whole-project ingestion receipts."""
from __future__ import annotations

from typing import Sequence

from ..system_image.source_access import SourceScopeAuthorizationPort
from ...domain.system_image.source_refresh import SourceRefreshSelection
from ...domain.system_image.source_access import SourceAccessDenied, StaleSourceAccessScope
from .errors import PlatformApplicationError
from .tool_models import ToolInvocation


class SourceRefreshReceiptAccess:
    def __init__(self, sources: SourceScopeAuthorizationPort):
        self.sources = sources

    @staticmethod
    def applies(invocation: ToolInvocation) -> bool:
        return invocation.tool_id == "system_image.sources.ingest"

    @staticmethod
    def _selection(invocation: ToolInvocation) -> tuple[str, SourceRefreshSelection | None]:
        body = invocation.input_payload
        selection = None
        try:
            if "source_ids" in body:
                if type(body["source_ids"]) is not list:
                    raise ValueError("invalid source selection")
                selection = SourceRefreshSelection(tuple(body["source_ids"]),
                    body.get("expected_manifest_id"), body.get("expected_manifest_hash"))
        except ValueError as exc:
            raise PlatformApplicationError("source_receipt_scope_invalid", "Source receipt scope could not be verified.", 409) from exc
        project_id = body.get("project_id")
        if type(project_id) is not str or not project_id:
            raise PlatformApplicationError("source_receipt_scope_invalid", "Source receipt scope could not be verified.", 409)
        return project_id, selection

    def require_access(self, invocation: ToolInvocation) -> None:
        if not self.applies(invocation):
            return
        project_id, selection = self._selection(invocation)
        try:
            if selection is None:
                self.sources.require_all_sources_access(project_id)
                return
            scope = self.sources.scope(project_id)
            if not scope.permits_sources(selection.source_ids):
                raise SourceAccessDenied("selected source no longer available")
            self.sources.require_current(scope)
        except (SourceAccessDenied, StaleSourceAccessScope, KeyError) as exc:
            raise PlatformApplicationError("source_receipt_access_denied", "Source receipt is not available.", 403) from exc

    def require_batch_access(self, invocations: Sequence[ToolInvocation]) -> None:
        groups = {}
        for invocation in invocations:
            if self.applies(invocation):
                project_id, selection = self._selection(invocation)
                groups.setdefault(project_id, []).append(selection)
        if not groups:
            return
        current = getattr(self.sources, "require_current_many", None)
        if len(groups) > 128 or not callable(current):
            raise PlatformApplicationError("source_receipt_access_unavailable", "Source receipt authorization is unavailable.", 503)
        try:
            scopes = []
            for project_id, selections in sorted(groups.items()):
                scope = (self.sources.require_all_sources_access(project_id) if None in selections
                    else self.sources.scope(project_id))
                if (scope.project_id != project_id or any(selection is not None
                        and not scope.permits_sources(selection.source_ids) for selection in selections)):
                    raise SourceAccessDenied("batch source no longer available")
                scopes.append(scope)
            current(tuple(scopes))
        except (SourceAccessDenied, StaleSourceAccessScope, KeyError) as exc:
            raise PlatformApplicationError("source_receipt_access_denied", "Source receipt is not available.", 403) from exc
        except PlatformApplicationError:
            raise
        except Exception as exc:
            raise PlatformApplicationError("source_receipt_access_unavailable", "Source receipt authorization is unavailable.", 503) from exc

    def broadcast_view(self, invocation: ToolInvocation) -> ToolInvocation:
        if not self.applies(invocation):
            return invocation
        # Shared conversations and historical events are not source authorization.
        return invocation.model_copy(update={"input_payload": {}, "result": None,
            "summary": f"Source ingestion status: {invocation.status}.",
            "idempotency_key": None, "idempotency_scope": None, "idempotency_fingerprint": None}, deep=True)
