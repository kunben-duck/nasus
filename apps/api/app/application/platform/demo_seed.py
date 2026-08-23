from __future__ import annotations

from ..quality_loop.quality_models import (
    ApprovalDetail,
    ApprovalSummary,
    AssetLane,
    ReleaseReadiness,
    RunDetail,
    RunSummary,
    USItem,
)
from ..system_image.system_image_models import (
    BaselineRecord,
    ContextRelationship,
    KnowledgeObject,
    QualityMetricSnapshot,
    RawAssetRecord,
)
from .project_models import ProjectCard, VersionSummary
from .read_models import DocumentationEntry
from .demo_seed_ports import DemoSeedBaseline, DemoSeedSystemImage, DemoSeedWorkspacePort
from .documentation_catalog import product_documentation_entries


class DemoSeedApplicationService:
    """Seeds local/demo read models without bloating the compatibility store."""

    def __init__(self, workspace: DemoSeedWorkspacePort) -> None:
        self._workspace = workspace

    def seed(self) -> None:
        project = ProjectCard(
            id="proj_payment",
            name="Payment System",
            code="PAY",
            summary="Agent-first release quality loop for payments and checkout.",
            status="active",
            risk="medium",
            progress=68,
            active_version="2026.Q2",
            blocked_items=2,
            pending_approvals=1,
            system_image_status="ready",
        )
        version = self._payment_version()
        self._workspace.seed_baseline(
            DemoSeedBaseline(
                project=project,
                version=version,
                us_items=tuple(self._payment_us_items()),
                asset_lanes=tuple(self._payment_asset_lanes()),
                run_detail=self._payment_run_detail(),
                run_summary=self._payment_run_summary(),
                approval_detail=self._payment_approval_detail(),
                approval_summary=self._payment_approval_summary(),
                knowledge_objects=tuple(self._payment_knowledge_objects()),
                system_image=self._payment_system_image(),
                documentation_entries=tuple(self._documentation_entries()),
                release_readiness=self._payment_release_readiness(version.id),
            )
        )
        self._seed_conversations(project)

    @staticmethod
    def _payment_version() -> VersionSummary:
        return VersionSummary(
            id="ver_payment_q2",
            name="2026.Q2",
            status="active",
            branch_name="release/2026-q2",
            us_total=8,
            us_closed=5,
            pending_runs=2,
            pending_approvals=1,
        )

    @staticmethod
    def _payment_us_items() -> list[USItem]:
        return [
            USItem(
                id="us_123",
                title="Saved cards checkout flow",
                owner="Alicia",
                status="analysis",
                risk="high",
                progress=62,
                next_action="Generate scenarios",
            ),
            USItem(
                id="us_124",
                title="Refund status timeline",
                owner="Ryan",
                status="execution",
                risk="medium",
                progress=81,
                next_action="Review run failures",
            ),
        ]

    @staticmethod
    def _payment_asset_lanes() -> list[AssetLane]:
        return [
            AssetLane(
                id="lane_scenarios",
                label="Scenarios",
                status="ready_for_review",
                summary="6 scenario groups covering happy path, fallback, and risk edges.",
                updated_at="2026-03-27 18:20",
            ),
            AssetLane(
                id="lane_cases",
                label="Cases",
                status="drafting",
                summary="12 structured cases in generation progress.",
                updated_at="2026-03-27 18:28",
            ),
            AssetLane(
                id="lane_automation",
                label="Automation",
                status="not_started",
                summary="Waiting for reviewed scenarios.",
                updated_at="2026-03-27 18:28",
            ),
        ]

    @staticmethod
    def _payment_run_summary() -> RunSummary:
        return RunSummary(
            id="run_9021",
            status="failed",
            channel="web_runner",
            title="Saved cards smoke",
            summary="3 assertions failed after checkout redirect.",
            started_at="2026-03-27 17:50",
        )

    @staticmethod
    def _payment_run_detail() -> RunDetail:
        return RunDetail(
            id="run_9021",
            status="failed",
            channel="web_runner",
            title="Saved cards smoke",
            summary="3 assertions failed after checkout redirect.",
            started_at="2026-03-27 17:50",
            timeline=[
                "Queued with checkout regression pack.",
                "Started browser session against release candidate.",
                "Observed redirect mismatch on saved-card confirmation.",
                "Captured trace bundle and DOM snapshot for failure analysis.",
            ],
            evidence=["trace://run_9021", "screenshot://run_9021/step-3", "log://run_9021"],
            failure_summary=(
                "The checkout confirm selector changed after the redirect handoff, "
                "which broke the post-payment assertion path."
            ),
            healing_status="not_started",
        )

    @staticmethod
    def _payment_approval_summary() -> ApprovalSummary:
        return ApprovalSummary(
            id="approval_442",
            title="Scenario pack revision r3",
            status="waiting_approval",
            summary="Scenario baseline promotion is waiting reviewer confirmation.",
        )

    @staticmethod
    def _payment_approval_detail() -> ApprovalDetail:
        return ApprovalDetail(
            id="approval_442",
            title="Scenario pack revision r3",
            status="waiting_approval",
            summary="Scenario baseline promotion is waiting reviewer confirmation.",
            policy_reason=(
                "Version Shared promotion is allowed, but Official baseline write-back "
                "must remain blocked until release closure."
            ),
            conflict_fields=["scenario_group.payment_recovery", "risk_pattern.checkout_redirect"],
            recommended_resolution=(
                "Accept the auto-merge on shared fields and keep the new risk edge "
                "candidate version-scoped until release sign-off."
            ),
            evidence=["scenario-pack:r3", "run:run_9021", "policy:baseline_writeback_gate"],
        )

    @staticmethod
    def _payment_knowledge_objects() -> list[KnowledgeObject]:
        return [
            KnowledgeObject(
                id="OBJ-CHECKOUT",
                name="Checkout Flow",
                type="Feature",
                branch="Version Shared",
                confidence="0.91",
                relations=["Payment Gateway App", "Order Summary", "Promo Engine"],
                evidence=["PR #882", "Scenario Pack r3", "Run-9021"],
                freshness="12 mins ago",
            ),
            KnowledgeObject(
                id="OBJ-AUTH",
                name="Auth Service",
                type="System",
                branch="Official",
                confidence="0.97",
                relations=["OAuth Callback", "Session Store", "Profile API"],
                evidence=["System Image", "Legacy Regression Pack"],
                freshness="1 hr ago",
            ),
            KnowledgeObject(
                id="OBJ-ASSET",
                name="Checkout Scenario Pack",
                type="QualityAssetPack",
                branch="Candidate",
                confidence="0.88",
                relations=["US-123", "Run-9021", "Release Gate"],
                evidence=["Scenario Set", "Automation Draft"],
                freshness="5 mins ago",
            ),
        ]

    @staticmethod
    def _payment_system_image() -> DemoSeedSystemImage:
        project_id = "proj_payment"
        baseline_id = "base_proj_payment_official"
        captured_at = "2026-03-27T18:30:00+00:00"
        return DemoSeedSystemImage(
            sources=(
                RawAssetRecord(
                    id="raw_proj_payment_code",
                    project_id=project_id,
                    source_type="code",
                    source_uri="demo://payment-system/code",
                    ingestion_status="indexed",
                    content_hash="demo:payment-code",
                    content_ref="demo://payment-system/code/content",
                    evidence_refs=["demo:code-baseline"],
                    last_ingested_at=captured_at,
                ),
                RawAssetRecord(
                    id="raw_proj_payment_us",
                    project_id=project_id,
                    source_type="us_doc",
                    source_uri="demo://payment-system/us",
                    ingestion_status="indexed",
                    content_hash="demo:payment-us",
                    content_ref="demo://payment-system/us/content",
                    evidence_refs=["demo:us-baseline"],
                    last_ingested_at=captured_at,
                ),
                RawAssetRecord(
                    id="raw_proj_payment_tests",
                    project_id=project_id,
                    source_type="test_asset",
                    source_uri="demo://payment-system/tests",
                    ingestion_status="indexed",
                    content_hash="demo:payment-tests",
                    content_ref="demo://payment-system/tests/content",
                    evidence_refs=["demo:test-baseline"],
                    last_ingested_at=captured_at,
                ),
            ),
            baselines=(
                BaselineRecord(
                    id=baseline_id,
                    project_id=project_id,
                    kind="official",
                    status="ready",
                    fork_strategy="copy_on_write",
                    object_count=3,
                    relationship_count=3,
                    metric_snapshot_count=4,
                    updated_at=captured_at,
                ),
            ),
            relationships=(
                ContextRelationship(
                    id="rel_demo_us_checkout",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id="OBJ-CHECKOUT",
                    relationship_type="impacts",
                    to_object_id="OBJ-AUTH",
                    confidence=0.88,
                    source_refs=["demo:us-baseline"],
                ),
                ContextRelationship(
                    id="rel_demo_tests_checkout",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id="OBJ-ASSET",
                    relationship_type="covers",
                    to_object_id="OBJ-CHECKOUT",
                    confidence=0.90,
                    source_refs=["demo:test-baseline"],
                ),
                ContextRelationship(
                    id="rel_demo_checkout_auth",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    from_object_id="OBJ-CHECKOUT",
                    relationship_type="depends_on",
                    to_object_id="OBJ-AUTH",
                    confidence=0.92,
                    source_refs=["demo:code-baseline"],
                ),
            ),
            metric_snapshots=(
                QualityMetricSnapshot(
                    id="metric_demo_code",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    metric_group="code_quality",
                    metrics={"changed_modules": 3, "critical_paths": 2, "code_risk_score": 67},
                    evidence_refs=["demo:code-baseline"],
                    captured_at=captured_at,
                ),
                QualityMetricSnapshot(
                    id="metric_demo_us",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id="ver_payment_q2",
                    us_id="us_123",
                    metric_group="us_completion_quality",
                    metrics={"requirements_clarity": 0.82, "acceptance_criteria_coverage": 0.76},
                    evidence_refs=["demo:us-baseline"],
                    captured_at=captured_at,
                ),
                QualityMetricSnapshot(
                    id="metric_demo_tests",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id="ver_payment_q2",
                    metric_group="test_quality",
                    metrics={"scenario_coverage": 0.78, "automation_coverage": 0.52},
                    evidence_refs=["demo:test-baseline"],
                    captured_at=captured_at,
                ),
                QualityMetricSnapshot(
                    id="metric_demo_release",
                    project_id=project_id,
                    baseline_id=baseline_id,
                    version_id="ver_payment_q2",
                    metric_group="release_readiness",
                    metrics={"release_score": 71, "open_blockers": 3},
                    evidence_refs=["demo:release-evidence"],
                    captured_at=captured_at,
                ),
            ),
        )

    @staticmethod
    def _documentation_entries() -> list[DocumentationEntry]:
        return list(product_documentation_entries())

    @staticmethod
    def _payment_release_readiness(version_id: str) -> ReleaseReadiness:
        return ReleaseReadiness(
            version_id=version_id,
            status="Conditionally Ready",
            score=71,
            blockers=3,
            approvals_open=2,
            pending_merge=1,
            execution_health="1 failed run pending review",
            summary=(
                "The version is close to release, but one failed run, one pending merge, "
                "and open governance items still need resolution."
            ),
            blocker_items=[
                "Saved cards smoke run still failed after redirect.",
                "Scenario pack promotion is waiting approval.",
                "One merge resolution still needs review in governance.",
            ],
        )

    def _seed_conversations(self, project: ProjectCard) -> None:
        self._workspace.ensure_conversation("welcome", "welcome", "Welcome")
        self._workspace.ensure_conversation("build", "build", "Build")
        self._workspace.ensure_conversation("dashboard", "dashboard", "Dashboard")
        self._workspace.ensure_conversation("project", project.id, project.name)
        self._workspace.ensure_conversation(
            "workspace",
            "us_123",
            "US-123 Workspace",
        )


__all__ = ["DemoSeedApplicationService"]
