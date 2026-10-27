from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
from dataclasses import asdict
import json
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from ...domain.agent.resume_checkpoint import AgentResumeCheckpoint
from ...domain.system_image.build_completion import assess_build_completion, completion_digest
from ...domain.system_image.build_plan import BuildPlanIntegrityError
from ...domain.system_image.source_snapshots import snapshot_digest
from ...domain.system_image.owned_build_completion import CompletionOwnershipProof, assess_owned_completion


COMPLETION_READ_TOOL = "query.system_image.build_completion.read"


class CompletionAnalysisPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_revision_id: StrictStr = Field(min_length=1, max_length=128)
    analysis_id: StrictStr = Field(min_length=1, max_length=128)
    report_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class CompletionOwnershipPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    completion_invocation_id: StrictStr = Field(min_length=1, max_length=128)
    completion_report_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    revision_id: StrictStr = Field(min_length=1, max_length=128)
    revision_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class CompletionOwnershipPort(Protocol):
    def resolve_completion(self, pin: CompletionOwnershipPin, expected_goal: dict, *, require_current: bool
                           ) -> tuple[dict, CompletionOwnershipProof]: ...


class BuildCompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: StrictStr = Field(min_length=1, max_length=128)
    investigation_revision_id: StrictStr = Field(min_length=1, max_length=128)
    investigation_revision_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    expected_goal: dict
    analyses: tuple[CompletionAnalysisPin, ...] = Field(default=(), max_length=64)
    analysis_policy: Optional[Literal["committed_build"]] = None
    ownership_pin: Optional[CompletionOwnershipPin] = None

    @model_validator(mode="after")
    def validate_pins(self):
        checkpoint = AgentResumeCheckpoint.capture(self.expected_goal)
        if (checkpoint.project_id != self.project_id or len({p.source_revision_id for p in self.analyses}) != len(self.analyses)
                or self.ownership_pin is not None and (self.analysis_policy != "committed_build" or self.analyses)):
            raise ValueError("Completion checkpoint or analysis source scope differs.")
        return self


class BuildCompletionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["build_completion"] = "build_completion"
    project_id: StrictStr
    investigation_revision_id: StrictStr
    investigation_revision_hash: StrictStr
    request_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    report_hash: StrictStr = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class BuildCompletionApplicationService:
    receipt_hash = staticmethod(completion_digest)

    def __init__(self, investigations, sources, code_analysis, *, lineage=None, ownership: Optional[CompletionOwnershipPort] = None):
        self.investigations, self.sources, self.code_analysis = investigations, sources, code_analysis
        self.lineage = lineage
        self.ownership = ownership

    def require_access(self, request):
        record = self.investigations.repository.read(request.project_id, request.investigation_revision_id)
        if (record.revision_hash != request.investigation_revision_hash
                or record.request.goal_id != request.expected_goal["id"]):
            raise BuildPlanIntegrityError("Completion input differs from the pinned investigation and goal.")
        self.investigations.require_access(record.request)
        return record

    def read(self, request, *, require_checkpoint=True):
        authorization = self.investigations.plans.authorization
        live_reads = getattr(authorization, "live_read_session", None)
        with live_reads() if live_reads else nullcontext():
            return self._read_verified(request, require_checkpoint=require_checkpoint)

    def _read_verified(self, request, *, require_checkpoint):
        self.require_access(request)
        if require_checkpoint:
            self.investigations.repository.require_checkpoint(request.expected_goal)
        scope = self.investigations.plans.authorization.scope(request.project_id)
        if request.ownership_pin is not None:
            if self.ownership is None:
                raise BuildPlanIntegrityError("Confirmed completion responsibility reader is unavailable.")
            original, proof = self.ownership.resolve_completion(request.ownership_pin, request.expected_goal,
                require_current=require_checkpoint)
            if (any(getattr(proof, key) != value for key, value in request.ownership_pin.model_dump().items())
                    or original["project_id"] != request.project_id
                    or original["investigation_revision_id"] != request.investigation_revision_id
                    or original["investigation_revision_hash"] != request.investigation_revision_hash
                    or original["goal_checkpoint"] != asdict(AgentResumeCheckpoint.capture(request.expected_goal))):
                raise BuildPlanIntegrityError("Responsibility assessment differs from the original build and checkpoint.")
            report = assess_owned_completion(original, proof)
            self.investigations.plans.authorization.require_current(scope)
            if require_checkpoint:
                self.investigations.repository.require_checkpoint(request.expected_goal)
            return report
        images = self.investigations.images
        with images.verified_read_session(reuse=True):
            record = self.investigations.read(request.project_id, request.investigation_revision_id)
            plan = self.investigations.require_access(record.request)
            _, payload = images.frozen_snapshot(request.project_id, record.request.image_revision_id)
            selection = sorted({(member["object_id"], evidence_id) for member in payload["members"]
                                if member["kind"] in {"code_entity", "source_document"}
                                for evidence_id in member["evidence_ids"]})
            if len(selection) > 50000:
                raise BuildPlanIntegrityError("Completion evidence exceeds its complete validation bound.")
            for offset in range(0, len(selection), 512):
                images.verify_evidence_selection(request.project_id, record.request.image_revision_id,
                                                 tuple(selection[offset:offset + 512]))
            scans, snapshots = [], {}
            for source in plan.proposal.intent.sources:
                if source.status != "captured":
                    continue
                snapshot = self.sources.snapshot(request.project_id, source.source_revision_id)
                if (snapshot.pin.binding_id, snapshot.pin.source_type) != (source.binding_id, source.source_type):
                    raise BuildPlanIntegrityError("Completion source differs from the captured plan.")
                snapshots[source.source_revision_id] = snapshot
                inventory = snapshot.inventory
                counts = Counter(item.status for item in inventory.entries) if inventory else Counter()
                scans.append({"binding_id": source.binding_id, "source_revision_id": source.source_revision_id,
                    "source_type": source.source_type, "manifest_hash": snapshot.pin.manifest_hash,
                    "inventory_hash": snapshot_digest(inventory.to_payload()) if inventory else None,
                    "enumeration_complete": bool(inventory and inventory.enumeration_complete),
                    "file_count": len(snapshot.files), "excluded_entries": counts["excluded"],
                    "failed_entries": counts["failed"], "unsupported_entries": counts["unsupported"],
                    "file_bodies_verified": False})
            if (sum(len(snapshot.files) for snapshot in snapshots.values()) > 5000
                    or sum(item.byte_count for snapshot in snapshots.values() for item in snapshot.files) > 100 * 1024 * 1024):
                raise BuildPlanIntegrityError("Complete source verification exceeds 5000 files or 100 MiB; no partial report is returned.")
            for scan in scans:
                verified = self.sources.verify_bodies(request.project_id, scan["source_revision_id"],
                                                       snapshots[scan["source_revision_id"]])
                scan.update(file_bodies_verified=True, verified_file_count=verified.verified_file_count,
                    verified_byte_count=verified.verified_byte_count, body_verification_hash=verified.verification_hash,
                    body_verification_method=verified.method)
            analyses, lineages = [], ()
            pins = request.analyses
            if request.analysis_policy == "committed_build":
                if self.lineage is None:
                    raise BuildPlanIntegrityError("Committed build lineage reader is unavailable.")
                lineages = self.lineage.read(request.project_id, record.request.plan_id,
                    record.request.image_revision_id, record.request.image_artifact_hash)
                actual = {}
                for lineage in lineages:
                    for item in lineage["analyses"]:
                        pin = CompletionAnalysisPin(**{key: item[key] for key in CompletionAnalysisPin.model_fields})
                        previous = actual.setdefault(pin.source_revision_id, pin)
                        if previous != pin:
                            raise BuildPlanIntegrityError("Committed build analyses are ambiguous; no latest report is selected.")
                if pins and {pin.source_revision_id: pin for pin in pins} != actual:
                    raise BuildPlanIntegrityError("Selected analysis is not this structural build's actual output.")
                pins = tuple(actual[key] for key in sorted(actual))
            for pin in pins:
                snapshot = snapshots.get(pin.source_revision_id)
                if snapshot is None or snapshot.pin.source_type != "code":
                    raise BuildPlanIntegrityError("Completion analysis is outside the fixed code sources.")
                files, offset, header = [], 0, None
                for _ in range(501):
                    page = self.code_analysis.read(request.project_id, pin.source_revision_id, pin.analysis_id,
                                                   section="files", offset=offset, limit=100)
                    if page.analysis.report_hash != pin.report_hash or (header is not None and page.analysis != header):
                        raise BuildPlanIntegrityError("Completion analysis changed its fixed digest or header.")
                    header = page.analysis
                    files.extend(page.items)
                    if page.next_offset is None:
                        break
                    if page.next_offset <= offset:
                        raise BuildPlanIntegrityError("Completion analysis pagination did not advance.")
                    offset = page.next_offset
                else:
                    raise BuildPlanIntegrityError("Completion analysis exceeds its complete pagination bound.")
                expected_files = {item.path: (item.content_hash, item.byte_count) for item in snapshot.files}
                if (len(files) != len(expected_files) or len({item["relative_path"] for item in files}) != len(files)
                        or {item["relative_path"]: (item["source_file_hash"], item["byte_count"]) for item in files} != expected_files):
                    raise BuildPlanIntegrityError("Completion analysis does not enumerate the entire fixed source inventory.")
                counts = Counter(item["status"] for item in files)
                if (not set(counts) <= {"parsed", "unsupported", "failed", "not_analyzed"}
                        or header.summary["file_count"] != len(files)
                        or any(header.summary[key] != counts[key] for key in ("parsed", "unsupported", "failed", "not_analyzed"))):
                    raise BuildPlanIntegrityError("Completion analysis counters differ from its complete file list.")
                analyses.append({**pin.model_dump(), "file_count": len(files),
                    **{key: counts[key] for key in ("parsed", "unsupported", "failed", "not_analyzed")},
                    "projection_status": header.projection["status"] if header.projection else "unknown",
                    "diagnostics_basis": "explicit_fixed_analysis_not_attested_build_lineage"})
                if request.analysis_policy == "committed_build":
                    analyses[-1].update(diagnostics_basis="committed_build_and_verified_full_projection", build_lineage_verified=True)
            report = assess_build_completion(plan.proposal, record.review, scans, analyses,
                                              request.expected_goal, len(selection), require_build_lineage=request.analysis_policy == "committed_build")
            if request.analysis_policy == "committed_build":
                report.update(schema="nasus.image-build-completion.v2", build_lineages=list(lineages))
            report.update(investigation_revision_id=record.revision_id, investigation_revision_hash=record.revision_hash,
                          goal_checkpoint=asdict(AgentResumeCheckpoint.capture(request.expected_goal)))
            if len(json.dumps(report, ensure_ascii=False, allow_nan=False).encode()) > 65536:
                raise BuildPlanIntegrityError("Completion report exceeds its complete response bound.")
        self.investigations.plans.authorization.require_current(scope)
        if require_checkpoint:
            self.investigations.repository.require_checkpoint(request.expected_goal)
        return report

    @staticmethod
    def receipt(request, report):
        return BuildCompletionReceipt(project_id=request.project_id,
            investigation_revision_id=request.investigation_revision_id,
            investigation_revision_hash=request.investigation_revision_hash,
            request_hash=snapshot_digest(request.model_dump(mode="json", exclude_none=True)), report_hash=completion_digest(report))
