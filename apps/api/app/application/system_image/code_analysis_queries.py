from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Optional, Protocol

from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.code_analysis import STRUCTURE_KINDS
from ...domain.system_image.code_provider import validate_projection_payload
from ...domain.system_image.code_observation_archive import (
    ENTITY_KINDS, IDENTITY_STATUSES, RELATION_KINDS, validate_observation_pin, validate_observation_summary,
    verify_observation_report,
)
from .source_access import SourceBindingAuthorizationPort, SourceScopeAuthorizationPort
from .code_observations import CodeObservationReadPort


class CodeAnalysisIntegrityError(ValueError):
    pass


class CodeAnalysisPageTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class CodeAnalysisSummary:
    analysis_id: str
    project_id: str
    binding_id: str
    source_revision_id: str
    report_hash: str
    recorded_at: str
    provider: str
    provider_version: str
    algorithm: str
    scope: str
    raw_inventory_available: bool
    summary: dict[str, int]
    projection: Optional[dict] = None
    observation_summary: Optional[dict] = None


@dataclass(frozen=True)
class CodeAnalysisListPage:
    items: tuple[CodeAnalysisSummary, ...]
    next_after_id: Optional[str]


@dataclass(frozen=True)
class CodeAnalysisPage:
    analysis: CodeAnalysisSummary
    section: str
    items: tuple[dict, ...]
    total: int
    next_offset: Optional[int]


@dataclass(frozen=True)
class CodeSourceRevisionSummary:
    project_id: str
    source_id: str
    source_label: str
    binding_id: str
    source_revision_id: str
    external_revision: str
    acquired_at: str
    file_count: int


@dataclass(frozen=True)
class CodeSourceRevisionPage:
    items: tuple[CodeSourceRevisionSummary, ...]
    next_after_id: Optional[str]


class CodeAnalysisReadPort(Protocol):
    def list_source_revisions(self, project_id: str, *, binding_ids: frozenset[str],
                              after_id: str, limit: int) -> list[CodeSourceRevisionSummary]: ...

    def list_for_revision(self, project_id: str, source_revision_id: str, *,
                          binding_ids: frozenset[str], after_id: str, limit: int) -> list[CodeAnalysisSummary]: ...

    def read(self, project_id: str, source_revision_id: str, analysis_id: str, *,
             binding_ids: frozenset[str]) -> tuple[CodeAnalysisSummary, dict]: ...


class CodeAnalysisAuthorizationPort(SourceBindingAuthorizationPort, SourceScopeAuthorizationPort, Protocol):
    pass


def _bounded(page):
    if len(json.dumps(asdict(page), ensure_ascii=False).encode("utf-8")) > 65536:
        raise CodeAnalysisPageTooLarge("request fewer observations")
    return page


class CodeAnalysisQueryApplicationService:
    def __init__(self, repository: CodeAnalysisReadPort, authorization: CodeAnalysisAuthorizationPort,
                 observations: CodeObservationReadPort | None = None) -> None:
        self.repository = repository
        self.authorization = authorization
        self.observations = observations

    def _scope(self, project_id: str, source_revision_id: str):
        scope = self.authorization.scope(project_id)
        self.authorization.require_revision_access(project_id, source_revision_id)
        self.authorization.require_current(scope)
        return scope

    def list_source_revisions(self, project_id: str, *, after_id: str = "", limit: int = 20) -> CodeSourceRevisionPage:
        if type(limit) is not int or not 1 <= limit <= 100 or len(after_id) > 64:
            raise ValueError("invalid revision page")
        scope = self.authorization.scope(project_id)
        rows = self.repository.list_source_revisions(project_id, binding_ids=scope.binding_ids,
                                                     after_id=after_id, limit=limit + 1)
        if len(rows) > limit + 1:
            raise CodeAnalysisIntegrityError("repository exceeded revision page limit")
        for row in rows:
            if row.project_id != project_id or row.source_id not in scope.source_ids:
                raise KeyError("source revision not found")
            scope.require_binding(row.binding_id)
        items = tuple(rows[:limit])
        page = _bounded(CodeSourceRevisionPage(items, items[-1].source_revision_id if len(rows) > limit else None))
        self.authorization.require_current(scope)
        return page

    def verify_projection(self, project_id, source_revision_id, analysis_id):
        scope = self._scope(project_id, source_revision_id)
        # Reuse public integrity checks before opening the complete private archive.
        checked = self.read(project_id, source_revision_id, analysis_id, section="files", limit=1).analysis
        header, payload = self.repository.read(project_id, source_revision_id, analysis_id, binding_ids=scope.binding_ids)
        if header != checked or snapshot_digest(payload) != header.report_hash or self.observations is None:
            raise CodeAnalysisIntegrityError("Actual code build analysis changed during verification.")
        self.authorization.require_current(scope)
        try:
            body = self.observations.read(payload)
            verify_observation_report(body, payload)
            proof = {"binding_id": header.binding_id, "source_revision_id": source_revision_id,
                "analysis_id": analysis_id, "report_hash": header.report_hash,
                "observation_archive_hash": payload["observation_archive"]["artifact_hash"],
                "merged_projection_hash": snapshot_digest(body["result"])}
        except (ValueError, KeyError, TypeError) as exc:
            raise CodeAnalysisIntegrityError("Actual code build projection failed archived verification.") from exc
        self.authorization.require_current(scope)
        return proof

    @staticmethod
    def _validate_summary(item, scope, source_revision_id):
        if item.project_id != scope.project_id or item.source_revision_id != source_revision_id:
            raise KeyError("code analysis not found")
        scope.require_binding(item.binding_id)
        if item.projection is not None:
            try:
                validate_projection_payload(item.projection)
            except ValueError as exc:
                raise CodeAnalysisIntegrityError("invalid code analysis projection metadata") from exc
        if item.observation_summary is not None:
            try:
                validate_observation_summary(item.observation_summary)
            except ValueError as exc:
                raise CodeAnalysisIntegrityError("invalid code observation summary") from exc

    def list_for_revision(self, project_id: str, source_revision_id: str, *,
                          after_id: str = "", limit: int = 20) -> CodeAnalysisListPage:
        if type(limit) is not int or not 1 <= limit <= 100 or len(after_id) > 64:
            raise ValueError("invalid analysis page")
        scope = self._scope(project_id, source_revision_id)
        rows = self.repository.list_for_revision(project_id, source_revision_id, binding_ids=scope.binding_ids,
                                                after_id=after_id, limit=limit + 1)
        if len(rows) > limit + 1:
            raise CodeAnalysisIntegrityError("repository exceeded page limit")
        for row in rows:
            self._validate_summary(row, scope, source_revision_id)
        items = tuple(rows[:limit])
        page = _bounded(CodeAnalysisListPage(items, items[-1].analysis_id if len(rows) > limit else None))
        self.authorization.require_current(scope)
        return page

    def read(self, project_id: str, source_revision_id: str, analysis_id: str, *,
             section: str = "files", offset: int = 0, limit: int = 50,
             kind: str | None = None, status: str | None = None) -> CodeAnalysisPage:
        if section not in {"files", "facts", "entities", "relationships"} or type(offset) is not int or not 0 <= offset <= 100000:
            raise ValueError("invalid analysis section or offset")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid analysis page size")
        kinds = {"facts": STRUCTURE_KINDS, "entities": ENTITY_KINDS, "relationships": RELATION_KINDS}
        if kind is not None and kind not in kinds.get(section, ()):
            raise ValueError("invalid structure filter")
        statuses = {"files": {"parsed", "unsupported", "failed", "not_analyzed"}, "entities": IDENTITY_STATUSES}
        if status is not None and status not in statuses.get(section, ()):
            raise ValueError("invalid parser status filter")
        scope = self._scope(project_id, source_revision_id)
        header, payload = self.repository.read(project_id, source_revision_id, analysis_id, binding_ids=scope.binding_ids)
        self._validate_summary(header, scope, source_revision_id)
        if header.analysis_id != analysis_id:
            raise KeyError("code analysis not found")
        if (snapshot_digest(payload) != header.report_hash
                or payload.get("schema") not in {"nasus.code-analysis.v1", "nasus.code-analysis.v2", "nasus.code-analysis.v3"}):
            raise CodeAnalysisIntegrityError("code analysis failed integrity verification")
        projection = payload.get("projection")
        if ((payload["schema"] == "nasus.code-analysis.v2" and projection is None)
                or (payload["schema"] == "nasus.code-analysis.v1" and projection is not None)
                or header.projection != projection):
            raise CodeAnalysisIntegrityError("code analysis projection version or header mismatch")
        if projection is not None:
            try:
                validate_projection_payload(projection)
            except ValueError as exc:
                raise CodeAnalysisIntegrityError("invalid code analysis projection metadata") from exc
        pin = payload.get("observation_archive")
        if payload["schema"] == "nasus.code-analysis.v3":
            try:
                validate_observation_pin(pin)
            except ValueError as exc:
                raise CodeAnalysisIntegrityError("invalid code observation archive pin") from exc
            if header.observation_summary != pin["summary"]:
                raise CodeAnalysisIntegrityError("code observation header mismatch")
        elif pin is not None or header.observation_summary is not None:
            raise CodeAnalysisIntegrityError("legacy code analysis cannot claim archived observations")
        if section in {"entities", "relationships"}:
            if pin is None:
                raise KeyError("this historical report has no archived code observations")
            if self.observations is None:
                raise CodeAnalysisIntegrityError("code observation archive reader is unavailable")
            self.authorization.require_current(scope)
            try:
                body = self.observations.read(payload)
                verify_observation_report(body, payload)
                items = [{key: value for key, value in item.items() if key != "evidence_refs"}
                         for item in body["result"][section]]
            except (ValueError, KeyError, TypeError) as exc:
                raise CodeAnalysisIntegrityError("code observations failed integrity verification") from exc
        else:
            items = payload[section]
        if kind is not None:
            field = {"facts": "kind", "entities": "entity_kind", "relationships": "relationship_kind"}[section]
            items = [item for item in items if item[field] == kind]
        if status is not None:
            field = "identity_status" if section == "entities" else "status"
            items = [item for item in items if item[field] == status]
        if offset > len(items):
            raise ValueError("offset is outside this immutable report")
        end = min(offset + limit, len(items))
        page = _bounded(CodeAnalysisPage(header, section, tuple(items[offset:end]), len(items),
                                        end if end < len(items) else None))
        self.authorization.require_current(scope)
        return page
