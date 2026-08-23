from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from ...domain.quality_loop.release_decision import decide_release_decision
from ...domain.quality_loop.structured_merge import (
    MISSING_VALUE,
    StructuredMergeDecision,
    apply_manual_resolutions,
    three_way_merge,
)
from ..quality_loop.governance_models import ConflictEntry, MergedResolution
from ..quality_loop.quality_models import ApprovalDetail, ReleaseDecision
from ..system_image.system_image_models import BaselineRecord
from .governance_ports import GovernanceWorkspacePort
from .tool_models import ToolInvocation


@dataclass(frozen=True)
class GovernanceUseCaseResult:
    summary: str
    object_refs: list[str]
    evidence_refs: list[str]
    next_tools: list[str]


class GovernanceApplicationError(ValueError):
    """Raised when a governance command cannot be executed."""

    def __init__(self, summary: str) -> None:
        super().__init__(summary)
        self.summary = summary


class GovernanceApplicationService:
    """Governed approval, merge, release, and baseline use cases.

    The service owns orchestration only. Projection and persistence details are
    provided by ``GovernanceWorkspacePort`` so the application layer never
    imports the compatibility store or ORM records.
    """

    def __init__(self, workspace: GovernanceWorkspacePort) -> None:
        self._workspace = workspace

    def request_approval(self, invocation: ToolInvocation) -> GovernanceUseCaseResult:
        project_id = self._require_project(
            invocation,
            "A valid project_id is required before requesting approval.",
        )
        purpose = str(invocation.input_payload.get("purpose") or "release_governance")
        target_ref = str(invocation.input_payload.get("target_ref") or f"project:{project_id}")
        merged_resolution = self._resolution_from_ref(project_id, target_ref)
        if merged_resolution is not None and merged_resolution.status != "ready_for_approval":
            raise GovernanceApplicationError(
                f"MergedResolution {merged_resolution.id} must be ready_for_approval before approval is requested."
            )

        title = str(invocation.input_payload.get("title") or self._approval_title(purpose))
        evidence = self._string_list(invocation.input_payload.get("evidence_refs")) or [target_ref]
        approval = ApprovalDetail(
            id=f"approval_{uuid4().hex[:10]}",
            title=title,
            status="waiting_approval",
            summary=f"Approval requested for {target_ref}.",
            policy_reason=str(
                invocation.input_payload.get("policy_reason")
                or "High-risk governance actions require an explicit reviewer decision before execution."
            ),
            conflict_fields=self._string_list(invocation.input_payload.get("conflict_fields")),
            recommended_resolution=str(
                invocation.input_payload.get("recommended_resolution")
                or "Review evidence, then decide whether the requested governance action may proceed."
            ),
            evidence=evidence,
        )
        self._upsert_approval(project_id, approval)
        if merged_resolution is not None:
            merged_resolution.approval_state = "waiting_approval"
            merged_resolution.approval_ref = f"approval:{approval.id}"
            merged_resolution.updated_at = self._now()
            self._workspace.save_merged_resolution(merged_resolution)

        object_refs = [f"approval:{approval.id}", f"project:{project_id}"]
        if merged_resolution is not None:
            object_refs.insert(1, f"merged_resolution:{merged_resolution.id}")
        return GovernanceUseCaseResult(
            summary=f"Requested approval {approval.id} for {target_ref}.",
            object_refs=object_refs,
            evidence_refs=evidence,
            next_tools=["approval.decide"],
        )

    def decide_approval(self, invocation: ToolInvocation) -> GovernanceUseCaseResult:
        project_id = self._require_project(
            invocation,
            "A valid project_id is required before deciding approval.",
        )
        approval_id = str(invocation.input_payload.get("approval_id") or "")
        approval = self._workspace.get_approval(project_id, approval_id)
        if approval is None:
            raise GovernanceApplicationError(
                f"Approval {approval_id or '<missing>'} is not attached to project {project_id}."
            )

        decision = str(invocation.input_payload.get("decision") or "approved").strip().lower()
        if decision not in {"approved", "rejected"}:
            raise GovernanceApplicationError(
                "approval.decide only accepts decision=approved or decision=rejected."
            )

        rationale = str(invocation.input_payload.get("rationale") or "")
        approval.status = decision
        approval.summary = rationale or (
            "Governance reviewer approved the requested action."
            if decision == "approved"
            else "Governance reviewer rejected the requested action."
        )
        self._upsert_approval(project_id, approval)

        affected_resolutions: list[MergedResolution] = []
        approval_ref = f"approval:{approval.id}"
        for resolution in self._workspace.list_merged_resolutions(project_id):
            if resolution.approval_ref != approval_ref:
                continue
            resolution.approval_state = decision  # type: ignore[assignment]
            resolution.status = decision  # type: ignore[assignment]
            resolution.updated_at = self._now()
            self._workspace.save_merged_resolution(resolution)
            affected_resolutions.append(resolution)

        object_refs = [f"approval:{approval.id}", f"project:{project_id}"]
        object_refs.extend(f"merged_resolution:{item.id}" for item in affected_resolutions)
        return GovernanceUseCaseResult(
            summary=f"Approval {approval.id} was {decision}.",
            object_refs=object_refs,
            evidence_refs=approval.evidence,
            next_tools=(
                ["release.decision.submit"]
                if decision == "approved"
                else ["query.governance.status"]
            ),
        )

    def merge_resolution(self, invocation: ToolInvocation) -> GovernanceUseCaseResult:
        project_id = self._require_project(
            invocation,
            "A valid project_id is required before merging a resolution.",
        )
        payload = invocation.input_payload
        resolution_id = str(payload.get("resolution_id") or "")
        existing = self._workspace.get_merged_resolution(resolution_id) if resolution_id else None
        if resolution_id and (existing is None or existing.project_id != project_id):
            raise GovernanceApplicationError(
                f"MergedResolution {resolution_id} is not attached to project {project_id}."
            )

        if existing is None:
            decision = self._create_merge_decision(payload)
            now = self._now()
            target_ref = str(payload.get("target_ref") or payload.get("object_ref") or "")
            if not target_ref:
                raise GovernanceApplicationError("target_ref is required for a new structured merge.")
            resolution = MergedResolution(
                id=f"merge_{uuid4().hex[:10]}",
                project_id=project_id,
                version_id=self._optional_string(payload.get("version_id")),
                task_id=self._optional_string(payload.get("task_id") or payload.get("us_id")),
                object_ref=target_ref,
                status=self._merge_status(decision),
                base_ref=self._optional_string(payload.get("base_ref")),
                left_candidate_ref=self._optional_string(payload.get("left_candidate_ref")),
                right_candidate_ref=self._optional_string(payload.get("right_candidate_ref")),
                base_value=payload.get("base", payload.get("base_value")),
                left_candidate=payload.get("left", payload.get("left_candidate")),
                right_candidate=payload.get("right", payload.get("right_candidate")),
                merged_value=decision.merged_value,
                auto_merged_patch=decision.auto_merged_patch,
                conflict_entries=self._conflict_models(decision),
                recommended_resolution=self._merge_recommendation(decision),
                merged_from=self._merged_from(payload),
                evidence_refs=self._string_list(payload.get("evidence_refs")) or [target_ref],
                created_at=now,
                updated_at=now,
            )
            previous_status: str | None = None
        else:
            if existing.status in {"approved", "rejected"}:
                raise GovernanceApplicationError(
                    f"MergedResolution {existing.id} is already {existing.status} and cannot be edited."
                )
            previous_status = existing.status
            decision = three_way_merge(
                existing.base_value,
                existing.left_candidate,
                existing.right_candidate,
            )
            prior_manual = self._manual_resolutions_from_patches(existing.auto_merged_patch)
            if prior_manual:
                decision = apply_manual_resolutions(decision, prior_manual)
            manual_resolutions = payload.get("manual_resolutions") or {}
            if not isinstance(manual_resolutions, Mapping):
                raise GovernanceApplicationError("manual_resolutions must be an object keyed by JSON pointer path.")
            try:
                decision = apply_manual_resolutions(decision, manual_resolutions)
            except (KeyError, StopIteration, TypeError, ValueError) as exc:
                raise GovernanceApplicationError(f"Invalid manual merge resolution: {exc}") from exc
            resolution = existing
            resolution.status = self._merge_status(decision)  # type: ignore[assignment]
            resolution.merged_value = decision.merged_value
            resolution.auto_merged_patch = decision.auto_merged_patch
            resolution.conflict_entries = self._conflict_models(decision)
            resolution.recommended_resolution = self._merge_recommendation(decision)
            resolution.approval_state = "not_requested"
            resolution.approval_ref = None
            resolution.updated_at = self._now()

        self._workspace.save_merged_resolution(resolution)
        self._update_pending_merge_counters(project_id, resolution, previous_status)
        next_tools = (
            ["conflicts.get"]
            if resolution.status == "pending_merge"
            else ["approval.request", "query.governance.status"]
        )
        return GovernanceUseCaseResult(
            summary=(
                f"MergedResolution {resolution.id} retains {len(resolution.conflict_entries)} manual conflict(s)."
                if resolution.status == "pending_merge"
                else f"MergedResolution {resolution.id} is ready for approval."
            ),
            object_refs=[f"merged_resolution:{resolution.id}", f"project:{project_id}"],
            evidence_refs=resolution.evidence_refs,
            next_tools=next_tools,
        )

    def submit_release_decision(self, invocation: ToolInvocation) -> GovernanceUseCaseResult:
        project_id = self._require_project(
            invocation,
            "A valid project_id is required before submitting a release decision.",
        )
        approval = self._require_approved_approval(project_id, invocation)
        us_id, version_id = self._release_scope(project_id, invocation)
        decision = self._workspace.find_release_decision(project_id, us_id or None, version_id)
        if decision is None:
            readiness = self._workspace.get_release_readiness(version_id)
            if readiness is None:
                raise GovernanceApplicationError(
                    "Release readiness must be assessed before submitting a release decision."
                )
            decision = self._decision_from_readiness(project_id, us_id or None, readiness)

        decision.approval_ref = f"approval:{approval.id}"
        decision.created_at = self._now()
        self._workspace.save_release_decision(decision)
        return GovernanceUseCaseResult(
            summary=f"Submitted ReleaseDecision {decision.id} with status {decision.status}.",
            object_refs=[
                f"release_decision:{decision.id}",
                f"approval:{approval.id}",
                f"project:{project_id}",
            ],
            evidence_refs=decision.evidence_refs + [decision.approval_ref],
            next_tools=(
                ["baseline.promote"]
                if decision.status in {"ready", "conditional"}
                else ["query.governance.status"]
            ),
        )

    def promote_baseline(self, invocation: ToolInvocation) -> GovernanceUseCaseResult:
        project_id = self._require_project(
            invocation,
            "A valid project_id is required before promoting a baseline.",
        )
        approval = self._require_approved_approval(project_id, invocation)
        us_id, version_id = self._release_scope(project_id, invocation)
        decision = self._workspace.find_release_decision(project_id, us_id or None, version_id)
        if decision is None:
            raise GovernanceApplicationError(
                "A submitted ReleaseDecision is required before baseline promotion."
            )
        if decision.status not in {"ready", "conditional"}:
            raise GovernanceApplicationError(
                "Baseline promotion requires a ready or conditional ReleaseDecision; "
                f"current status is {decision.status}."
            )
        if decision.approval_ref != f"approval:{approval.id}":
            raise GovernanceApplicationError(
                "Baseline promotion must use the same approved approval attached to the ReleaseDecision."
            )

        baselines = self._workspace.list_baselines(project_id)
        official = next((baseline for baseline in baselines if baseline.kind == "official"), None)
        if official is None:
            official = BaselineRecord(
                id=f"baseline_{project_id}_official",
                project_id=project_id,
                kind="official",
                status="promoted",
                fork_strategy="copy_on_write",
                object_count=0,
                relationship_count=0,
                metric_snapshot_count=0,
                updated_at=self._now(),
            )
            baselines.append(official)
        else:
            official.status = "promoted"
            official.updated_at = self._now()
        self._workspace.replace_baselines(project_id, baselines)
        self._workspace.persist_system_image(project_id)

        project = self._workspace.get_project(project_id)
        project.system_image_status = "ready"
        project.progress = max(project.progress, 92)
        project.risk = "low" if decision.status == "ready" else project.risk
        self._workspace.save_project(project)
        return GovernanceUseCaseResult(
            summary=f"Promoted official baseline {official.id} from ReleaseDecision {decision.id}.",
            object_refs=[
                f"baseline:{official.id}",
                f"release_decision:{decision.id}",
                f"approval:{approval.id}",
                f"project:{project_id}",
            ],
            evidence_refs=decision.evidence_refs + [decision.approval_ref],
            next_tools=["query.system_image.status", "query.governance.status"],
        )

    def list_conflicts(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
    ) -> list[MergedResolution]:
        self._require_project_access(project_id)
        return [
            item
            for item in self._workspace.list_merged_resolutions(project_id, task_id=task_id)
            if item.status == "pending_merge"
        ]

    def get_merged_resolution(self, project_id: str, resolution_id: str) -> MergedResolution:
        self._require_project_access(project_id)
        resolution = self._workspace.get_merged_resolution(resolution_id)
        if resolution is None or resolution.project_id != project_id:
            raise KeyError(resolution_id)
        return resolution

    def list_task_conflicts(self, task_id: str) -> list[MergedResolution]:
        project_id = self._workspace.project_id_for_task(task_id)
        if project_id is None:
            raise KeyError(task_id)
        return self.list_conflicts(project_id, task_id=task_id)

    def query_keys_for(self, invocation: ToolInvocation) -> list[list[str]]:
        project_id = self.project_id_for(invocation)
        keys: list[list[str]] = []
        if invocation.conversation_id:
            keys.append(["conversation", invocation.conversation_id])
        if project_id:
            keys.extend(
                [["project", project_id], ["governance", project_id], ["system-image", project_id]]
            )
        return keys

    def project_id_for(self, invocation: ToolInvocation) -> str:
        return self._workspace.resolve_project_id(invocation) or ""

    def _require_project(self, invocation: ToolInvocation, summary: str) -> str:
        project_id = self.project_id_for(invocation)
        if not project_id or not self._workspace.has_project(project_id):
            raise GovernanceApplicationError(summary)
        self._require_project_access(project_id)
        return project_id

    def _require_project_access(self, project_id: str) -> None:
        if not self._workspace.has_project(project_id):
            raise KeyError(project_id)
        self._workspace.require_project_access(project_id)

    def _upsert_approval(self, project_id: str, approval: ApprovalDetail) -> None:
        self._workspace.save_approval(project_id, approval)

    def _decision_from_readiness(
        self,
        project_id: str,
        us_id: str | None,
        readiness: Any,
    ) -> ReleaseDecision:
        evidence_refs = [
            f"execution_evidence:{item.id}"
            for item in self._workspace.list_execution_evidence(project_id)
            if us_id is None or item.us_id == us_id
        ]
        draft = decide_release_decision(
            project_id=project_id,
            us_id=us_id,
            readiness=readiness,
            execution_evidence_refs=evidence_refs,
        )
        return ReleaseDecision(
            id=draft.id,
            project_id=draft.project_id,
            version_id=draft.version_id,
            us_id=draft.us_id,
            status=draft.status,  # type: ignore[arg-type]
            score=draft.score,
            rationale=draft.rationale,
            evidence_refs=draft.evidence_refs,
            created_at=self._now(),
        )

    def _create_merge_decision(self, payload: dict[str, Any]) -> StructuredMergeDecision:
        aliases = (
            ("base", "base_value"),
            ("left", "left_candidate"),
            ("right", "right_candidate"),
        )
        if any(not any(key in payload for key in pair) for pair in aliases):
            raise GovernanceApplicationError(
                "A new structured merge requires base, left, and right candidate values."
            )
        try:
            decision = three_way_merge(
                payload.get("base", payload.get("base_value")),
                payload.get("left", payload.get("left_candidate")),
                payload.get("right", payload.get("right_candidate")),
            )
            manual_resolutions = payload.get("manual_resolutions") or {}
            if not isinstance(manual_resolutions, Mapping):
                raise GovernanceApplicationError(
                    "manual_resolutions must be an object keyed by JSON pointer path."
                )
            return apply_manual_resolutions(decision, manual_resolutions)
        except GovernanceApplicationError:
            raise
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            raise GovernanceApplicationError(f"Invalid structured merge input: {exc}") from exc

    def _resolution_from_ref(
        self,
        project_id: str,
        target_ref: str,
    ) -> MergedResolution | None:
        if not target_ref.startswith("merged_resolution:"):
            return None
        resolution_id = target_ref.split(":", 1)[1]
        resolution = self._workspace.get_merged_resolution(resolution_id)
        if resolution is None or resolution.project_id != project_id:
            raise GovernanceApplicationError(
                f"MergedResolution {resolution_id} is not attached to project {project_id}."
            )
        return resolution

    def _require_approved_approval(
        self,
        project_id: str,
        invocation: ToolInvocation,
    ) -> ApprovalDetail:
        approval_id = str(invocation.input_payload.get("approval_id") or "")
        approval = self._workspace.get_approval(project_id, approval_id)
        if approval is None:
            raise GovernanceApplicationError(
                f"Approval {approval_id or '<missing>'} is not attached to project {project_id}."
            )
        if approval.status != "approved":
            raise GovernanceApplicationError(
                f"Approval {approval.id} must be approved before this governance action can execute."
            )
        return approval

    def _release_scope(self, project_id: str, invocation: ToolInvocation) -> tuple[str, str]:
        us_id = str(invocation.input_payload.get("us_id") or "")
        version_id = str(invocation.input_payload.get("version_id") or "")
        if not version_id:
            versions = self._workspace.list_versions(project_id)
            version_id = versions[0].id if versions else ""
        if not us_id:
            us_items = self._workspace.list_us_items(project_id)
            us_id = us_items[0].id if us_items else ""
        if not version_id:
            raise GovernanceApplicationError(
                "A version is required before submitting a governance release action."
            )
        return us_id, version_id

    def _update_pending_merge_counters(
        self,
        project_id: str,
        resolution: MergedResolution,
        previous_status: str | None,
    ) -> None:
        became_pending = previous_status is None and resolution.status == "pending_merge"
        resolved_pending = (
            previous_status == "pending_merge" and resolution.status != "pending_merge"
        )
        if not became_pending and not resolved_pending:
            return
        delta = 1 if became_pending else -1
        if resolution.version_id:
            readiness = self._workspace.get_release_readiness(resolution.version_id)
            if readiness is not None:
                readiness.pending_merge = max(0, readiness.pending_merge + delta)
                self._workspace.save_release_readiness(project_id, readiness)
        project = self._workspace.get_project(project_id)
        project.blocked_items = max(0, project.blocked_items + delta)
        self._workspace.save_project(project)

    @staticmethod
    def _manual_resolutions_from_patches(
        patches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        resolutions: dict[str, Any] = {}
        for patch in patches:
            if patch.get("source") != "manual" or not isinstance(patch.get("path"), str):
                continue
            resolutions[patch["path"]] = (
                MISSING_VALUE if patch.get("op") == "remove" else patch.get("value")
            )
        return resolutions

    @staticmethod
    def _conflict_models(decision: StructuredMergeDecision) -> list[ConflictEntry]:
        return [ConflictEntry.model_validate(asdict(item)) for item in decision.conflict_entries]

    @staticmethod
    def _merge_status(decision: StructuredMergeDecision) -> str:
        return "ready_for_approval" if decision.ready_for_approval else "pending_merge"

    @staticmethod
    def _merge_recommendation(decision: StructuredMergeDecision) -> str:
        if decision.conflict_entries:
            return (
                f"Resolve {len(decision.conflict_entries)} remaining conflict(s) by JSON pointer path, "
                "then submit the resolution for approval."
            )
        return "The structured merge is complete; request governance approval before it becomes authoritative."

    @staticmethod
    def _merged_from(payload: dict[str, Any]) -> list[str]:
        explicit = GovernanceApplicationService._string_list(payload.get("merged_from"))
        if explicit:
            return explicit
        return [
            str(value)
            for value in (
                payload.get("base_ref"),
                payload.get("left_candidate_ref"),
                payload.get("right_candidate_ref"),
            )
            if value
        ]

    @staticmethod
    def _approval_title(purpose: str) -> str:
        return {
            "release_decision": "Release decision approval",
            "baseline_promote": "Baseline promotion approval",
            "release_governance": "Release governance approval",
            "merged_resolution": "Merged resolution approval",
        }.get(purpose, "Governance approval")

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if isinstance(value, str) and value:
            return [value]
        return []

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
