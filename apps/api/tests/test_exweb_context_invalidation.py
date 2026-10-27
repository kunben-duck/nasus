"""Actual Git/PG/MinIO invalidation; no external model or target execution."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from apps.api.app.main import app
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.infrastructure.persistence.context_invalidation_models import ContextInvalidationRecord
from apps.api.app.infrastructure.persistence.db_models import LLMCallRecord
from apps.api.app.infrastructure.persistence.event_outbox_repository import EventOutboxRepository
from apps.api.tests.test_semantic_evaluations_api import completed, count, invoke
from apps.api.tests.test_context_invalidations_api import submit, history
from apps.api.tests.test_exweb_context_change_impact import (
    evidence_api, documents, publication, design_scope, generation_result, mapping,
    test_actual_exweb_new_files_propagate_to_fixed_context_derivations as verify_exweb_impact,
)
from apps.api.tests.test_exweb_source_delta import BEFORE, AFTER


def test_exweb_source_change_persists_stale_dependencies_and_blocks_generation(mapping):
    v = mapping
    verify_exweb_impact(v)
    context_id = v["impact_request"]["context_id"]
    with actor_scope(UserProfile.model_validate(v["owner"])):
        original = app.state.container.context_packs.read(v["project_id"], context_id)
    calls = count(v, LLMCallRecord)
    command = completed(submit(v))
    ident = command["result"]["object_refs"][0].split(":", 1)[1]
    response = history(v, ident)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert len(receipt["dependencies"]) == 9 and count(v, ContextInvalidationRecord) == 1
    replay = EventOutboxRepository().list_after(stream_kind="conversation",
        stream_id=v["conversation"].json()["id"], after_event_id=None)
    invalidations = [event for event in replay if event.event_type == "system_image.context.invalidated"]
    assert len(invalidations) == 1 and invalidations[0].entity_id == ident
    assert invalidations[0].snapshot_hint and invalidations[0].patch["graph_hash"] == receipt["metadata"]["graph_hash"]
    assert ["context-packs", v["project_id"]] in invalidations[0].query_keys
    with actor_scope(UserProfile.model_validate(v["owner"])):
        current = app.state.container.context_packs.read(v["project_id"], context_id)
        result = app.state.container.test_design_results.read(v["project_id"], v["generation_metadata"]["generation_id"])
    assert current["context"] == original["context"] and current["metadata"] == original["metadata"]
    assert current["current_use"]["stale"] and not result["current_use"]["scope_current"]
    refused = invoke(v, "query.quality.test_design_generation", {"project_id": v["project_id"],
        "scope_revision_id": v["execution"]["request"].scope_revision_id,
        "scope_artifact_hash": v["execution"]["request"].scope_artifact_hash}, key="invalidated-generation")
    assert refused.json()["status"] == "failed" and count(v, LLMCallRecord) == calls
    report = {"verified_at": datetime.now(timezone.utc).isoformat(), "repository": "https://github.com/kunben-duck/exweb.git",
        "git_commits": [BEFORE, AFTER], "export_file_counts": [125, 126], "postgresql": True, "minio": True,
        "dependency_count": len(receipt["dependencies"]), "graph_hash": receipt["metadata"]["graph_hash"],
        "invalidation_applied": True, "historical_context_preserved": True, "current_generation_blocked": True,
        "durable_conversation_sse_replay": True,
        "external_model_called": False, "target_executed": False, "impact_complete": False,
        "scope_and_draft_basis": "explicit_synthetic_protocol_not_exweb_business_gold"}
    if os.getenv("EXWEB_CONTEXT_INVALIDATION_REPORT"):
        Path(os.environ["EXWEB_CONTEXT_INVALIDATION_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
