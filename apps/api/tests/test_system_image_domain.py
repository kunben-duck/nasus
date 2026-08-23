from __future__ import annotations

from types import SimpleNamespace

from apps.api.app.domain.system_image.build_state import resolve_build_state
from apps.api.app.domain.system_image.chunking import (
    chunk_id,
    chunk_kind,
    content_hash,
    estimate_tokens,
    split_chunk_text,
    stable_hash,
)
from apps.api.app.domain.system_image.entity_resolution import (
    CrossSourceEntityResolver,
    EntityCandidate,
)
from apps.api.app.domain.system_image.materialization import (
    InsufficientSystemImageEvidenceError,
    assess_materialized_evidence,
    require_materialized_evidence,
)
from apps.api.app.domain.system_image.quality_context import (
    automation_feasibility,
    context_confidence,
    context_hash,
    coverage_score,
    missing_quality_context,
    release_score,
    risk_drivers,
    risk_score,
)
from apps.api.app.domain.system_image.source_binding import (
    default_source_uri,
    missing_optional_source_types,
    missing_source_types,
    source_binding_incomplete,
)
from apps.api.app.domain.system_image.us_work_items import (
    default_asset_lanes_for_us,
    derive_us_work_items_from_context,
)


def source(
    source_type: str,
    source_uri: str,
    *,
    content_hash: str = "",
    evidence_refs: list[str] | None = None,
    ingestion_status: str | None = None,
):
    return SimpleNamespace(
        id=f"raw_{source_type}",
        source_type=source_type,
        source_uri=source_uri,
        content_hash=content_hash,
        evidence_refs=evidence_refs or [],
        ingestion_status=ingestion_status or ("indexed" if content_hash or evidence_refs else "pending"),
    )


def metric(metric_group: str, **values: object):
    return SimpleNamespace(metric_group=metric_group, metrics=values)


def knowledge_object(name: str, object_type: str):
    return SimpleNamespace(name=name, type=object_type)


def materialized_object(*refs: str):
    return SimpleNamespace(evidence=list(refs))


def materialized_relationship(*refs: str):
    return SimpleNamespace(source_refs=list(refs))


def materialized_metric(metric_group: str, *refs: str):
    return SimpleNamespace(metric_group=metric_group, evidence_refs=list(refs))


def test_system_image_materialization_requires_source_backed_evidence() -> None:
    decision = assess_materialized_evidence(
        objects=[
            materialized_object("raw:code"),
            materialized_object("file:checkout.py", "code-intelligence:tree-sitter"),
        ],
        relationships=[materialized_relationship("file:checkout.py")],
        metrics=[materialized_metric("code_quality", "raw:code")],
    )

    assert decision.ready is True
    assert decision.object_count == 2
    assert decision.relationship_count == 1
    assert decision.metric_count == 1


def test_system_image_materialization_rejects_synthetic_fallback_facts() -> None:
    decision = assess_materialized_evidence(
        objects=[
            materialized_object("source:seeded-fixture"),
            materialized_object("Source import placeholders"),
        ],
        relationships=[materialized_relationship("system-image:fallback")],
        metrics=[materialized_metric("code_quality", "parser:synthetic-fixture")],
    )

    assert decision.ready is False
    assert decision.object_count == 0
    assert set(decision.missing_evidence) == {
        "at least one source-derived object in addition to the system root",
        "at least one source-derived relationship",
        "a source-derived code_quality metric",
    }
    try:
        require_materialized_evidence(
            objects=[materialized_object("source:seeded-fixture")],
            relationships=[],
            metrics=[],
        )
    except InsufficientSystemImageEvidenceError as exc:
        assert exc.decision.ready is False
    else:
        raise AssertionError("synthetic materialization evidence must fail closed")


def test_source_binding_policy_identifies_missing_and_placeholder_sources() -> None:
    project_name = "Payment System"
    sources = [
        source("code", default_source_uri(project_name, "code")),
        source("us_doc", "docs://payment-system/us", content_hash="sha256:us", evidence_refs=["doc:us"]),
    ]

    assert source_binding_incomplete(sources, project_name) is True
    assert missing_source_types(sources, project_name) == ["code"]
    assert missing_optional_source_types(sources, project_name) == ["test_asset"]


def test_source_binding_policy_accepts_code_only_baseline_and_reports_optional_gaps() -> None:
    project_name = "Payment System"
    sources = [
        source("code", "git://example/payment", content_hash="sha256:code", evidence_refs=["git:main"]),
    ]

    assert source_binding_incomplete(sources, project_name) is False
    assert missing_source_types(sources, project_name) == []
    assert missing_optional_source_types(sources, project_name) == ["us_doc", "test_asset"]


def test_chunking_policy_normalizes_text_and_prefers_newline_boundaries() -> None:
    text = "  first line\r\nsecond line\r\nthird line  "

    assert split_chunk_text(text, max_chars=120) == ["first line\nsecond line\nthird line"]
    assert split_chunk_text(text, max_chars=22) == ["first line\nsecond line", "third line"]
    assert split_chunk_text("abcdefghijklmno\nsecond\nthird", max_chars=20) == [
        "abcdefghijklmno",
        "second\nthird",
    ]
    assert split_chunk_text(" \r\n ") == []


def test_chunk_identity_hashes_and_kind_mapping_are_stable() -> None:
    digest = content_hash("checkout flow")
    first_id = chunk_id("project_pay", "raw_code", "src/pay.py", 0, digest)
    second_id = chunk_id("project_pay", "raw_code", "src/pay.py", 0, digest)

    assert digest.startswith("sha256:")
    assert first_id == second_id
    assert first_id.startswith("chunk_project_pay_")
    assert chunk_kind("code") == "code"
    assert chunk_kind("us_doc") == "requirement"
    assert chunk_kind("test_asset") == "test"
    assert chunk_kind("unknown") == "summary"


def test_token_estimate_and_stable_hash_are_deterministic() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 80) == 20
    assert stable_hash(["source", "uri"]) == stable_hash(["source", "uri"])
    assert stable_hash(["source", "uri"]) != stable_hash(["uri", "source"])
    assert stable_hash(["source", "uri"]).startswith("sha256:")


def test_quality_context_policy_detects_missing_sources_and_us_target() -> None:
    sources = [
        source("code", "git://payment", content_hash="sha256:code"),
        source("us_doc", "docs://payment/us", content_hash="sha256:us"),
        source("test_asset", "tests://payment/regression"),
    ]

    assert missing_quality_context(sources, None) == ["us_work_item"]
    assert missing_quality_context(sources, "US-123") == []


def test_quality_context_scores_confidence_risk_coverage_and_release() -> None:
    sources = [
        source("code", "git://payment", content_hash="sha256:code"),
        source("us_doc", "docs://payment/us", content_hash="sha256:us"),
        source("test_asset", "tests://payment/regression", content_hash="sha256:test"),
    ]
    relationships = [SimpleNamespace(id=f"rel_{index}") for index in range(3)]
    metrics = [
        metric("code_quality", code_risk_score=67),
        metric("test_quality", failed_runs=2, scenario_coverage=0.75, automation_coverage=0.5, test_count=4),
        metric("us_completion_quality", acceptance_criteria_coverage=0.72),
    ]

    assert context_confidence(sources, relationships, metrics) == 0.85
    assert risk_score(metrics) == 83
    assert coverage_score(metrics) == 65
    assert automation_feasibility(metrics) == 56
    assert release_score(metrics, blocked_items=1, pending_approvals=1) == 39
    assert risk_drivers(metrics, relationships) == [
        "Code risk score is elevated for changed or critical modules.",
        "Automation coverage is below the release confidence threshold.",
        "US acceptance criteria or requirement clarity needs review.",
    ]


def test_quality_context_release_metric_and_context_hash_are_deterministic() -> None:
    release_metrics = [metric("release_readiness", release_score=88)]
    first_hash = context_hash("project_pay", "base_pay", "US-123", ["raw_code"], ["chunk_1"], ["obj_1"], ["rel_1"], ["metric_1"])
    second_hash = context_hash("project_pay", "base_pay", "US-123", ["raw_code"], ["chunk_1"], ["obj_1"], ["rel_1"], ["metric_1"])

    assert release_score(release_metrics, blocked_items=99, pending_approvals=99) == 88
    assert first_hash == second_hash
    assert len(first_hash) == 64
    assert risk_drivers([], []) == ["Context relationship graph is still sparse."]


def test_build_state_policy_only_blocks_required_source_failures() -> None:
    optional_failure = resolve_build_state(
        sources=[
            source("code", "git://payment", ingestion_status="indexed"),
            source("us_doc", "docs://payment/us", ingestion_status="failed"),
        ],
        missing_source_types=[],
        has_context=True,
        has_metrics=True,
        baseline_status="ready",
        project_system_image_status="ready",
    )

    assert optional_failure.status == "ready"
    assert optional_failure.stage_index == 5
    assert optional_failure.failed_source_ids == ["raw_us_doc"]
    assert optional_failure.label == "Official System Image ready with optional source gaps"

    required_failure = resolve_build_state(
        sources=[
            source("code", "git://payment", ingestion_status="failed"),
            source("us_doc", "docs://payment/us", ingestion_status="indexed"),
        ],
        missing_source_types=[],
        has_context=False,
        has_metrics=False,
        baseline_status="draft",
        project_system_image_status="draft",
    )
    assert required_failure.status == "partially_failed"
    assert required_failure.stage_index == 1
    assert required_failure.failed_source_ids == ["raw_code"]

    missing = resolve_build_state(
        sources=[source("code", "git://payment", ingestion_status="pending")],
        missing_source_types=["code"],
        has_context=False,
        has_metrics=False,
        baseline_status=None,
        project_system_image_status="draft",
    )

    assert missing.status == "source_required"
    assert missing.stage_index == 0
    assert missing.missing_source_types == ["code"]


def test_cross_source_entity_resolution_links_requirement_code_and_tests() -> None:
    resolver = CrossSourceEntityResolver()
    candidates = [
        EntityCandidate(
            object_id="code_checkout",
            entity_kind="code",
            label="checkout payment handler",
            evidence_refs=("raw_code", "file:checkout.py"),
        ),
        EntityCandidate(
            object_id="us_checkout",
            entity_kind="us_doc",
            label="buyer checkout with saved payment card",
            evidence_refs=("raw_us", "file:US-101.md"),
        ),
        EntityCandidate(
            object_id="test_checkout",
            entity_kind="test_asset",
            label="checkout saved payment test",
            evidence_refs=("raw_tests", "file:test_checkout.py"),
        ),
    ]

    links = resolver.resolve(candidates)

    assert {
        (item.from_object_id, item.relationship_type, item.to_object_id)
        for item in links
    } == {
        ("code_checkout", "implements", "us_checkout"),
        ("test_checkout", "covers", "code_checkout"),
        ("test_checkout", "validates", "us_checkout"),
    }
    assert all(item.confidence >= resolver.minimum_confidence for item in links)
    assert resolver.resolve(
        [
            EntityCandidate("code_refund", "code", "refund processor"),
            EntityCandidate("us_profile", "us_doc", "customer profile avatar"),
        ]
    ) == []


def test_build_state_policy_resolves_ready_materialized_and_indexing_progression() -> None:
    indexed_sources = [
        source("code", "git://payment", ingestion_status="indexed"),
        source("us_doc", "docs://payment/us", ingestion_status="indexed"),
        source("test_asset", "tests://payment/regression", ingestion_status="indexed"),
    ]

    ready = resolve_build_state(
        sources=indexed_sources,
        missing_source_types=[],
        has_context=True,
        has_metrics=True,
        baseline_status="promoted",
        project_system_image_status="ready",
    )
    materialized = resolve_build_state(
        sources=indexed_sources,
        missing_source_types=[],
        has_context=True,
        has_metrics=True,
        baseline_status="draft",
        project_system_image_status="indexed",
    )
    indexed = resolve_build_state(
        sources=indexed_sources,
        missing_source_types=[],
        has_context=False,
        has_metrics=False,
        baseline_status=None,
        project_system_image_status="indexed",
    )
    ingesting = resolve_build_state(
        sources=[source("code", "git://payment", ingestion_status="ingesting")],
        missing_source_types=[],
        has_context=False,
        has_metrics=False,
        baseline_status=None,
        project_system_image_status="draft",
    )
    registered = resolve_build_state(
        sources=[source("code", "git://payment", ingestion_status="pending")],
        missing_source_types=[],
        has_context=False,
        has_metrics=False,
        baseline_status=None,
        project_system_image_status="draft",
    )

    assert ready.status == "ready"
    assert ready.stage_index == 5
    assert materialized.status == "materialized"
    assert materialized.next_recommended_tools == ["system_image.baseline.initialize"]
    assert indexed.status == "indexed"
    assert indexed.next_recommended_tools == ["system_image.context.materialize"]
    assert ingesting.status == "ingesting"
    assert registered.status == "sources_registered"


def test_us_work_item_policy_prefers_us_objects_and_derives_stable_defaults() -> None:
    decisions = derive_us_work_items_from_context(
        [
            knowledge_object("Checkout Feature", "Feature"),
            knowledge_object("US-128 Payment retry", "USWorkItem"),
            knowledge_object("US 129 Refund callback", "USWorkItem"),
        ],
        project_id="project_payment",
    )

    assert [item.id for item in decisions] == ["us_us-128_ayment", "us_us-129_ayment"]
    assert [item.title for item in decisions] == ["US-128 Payment retry", "US 129 Refund callback"]
    assert decisions[0].owner == "Nasus Agent"
    assert decisions[0].status == "analysis"
    assert decisions[0].risk == "medium"
    assert decisions[0].progress == 18
    assert decisions[0].next_action == "Generate scenarios"


def test_us_work_item_policy_falls_back_to_feature_objects_and_limits_results() -> None:
    decisions = derive_us_work_items_from_context(
        [knowledge_object(f"Capability {index}", "Feature") for index in range(10)],
        project_id="project_payment",
    )

    assert len(decisions) == 8
    assert decisions[0].id == "us_us-001_ayment"
    assert decisions[-1].id == "us_us-008_ayment"


def test_default_asset_lanes_for_derived_us_are_stable() -> None:
    lanes = default_asset_lanes_for_us("us_us-128_ayment")

    assert [lane.id for lane in lanes] == [
        "us_us-128_ayment_lane_scenarios",
        "us_us-128_ayment_lane_cases",
        "us_us-128_ayment_lane_automation",
        "us_us-128_ayment_lane_release",
    ]
    assert [lane.label for lane in lanes] == ["Scenarios", "Cases", "Automation", "Release Assessment"]
    assert all(lane.status == "not_started" for lane in lanes)
    assert lanes[0].summary == "Waiting for scenario generation from system image, US, and test evidence."
