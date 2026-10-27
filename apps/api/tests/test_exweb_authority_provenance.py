"""Actual fixed exweb exports, PostgreSQL and MinIO; synthetic companion oracles."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from sqlalchemy import delete, insert, select

from apps.api.app.domain.quality_loop.acceptance_specification import AC_POLICY
from apps.api.app.domain.system_image.context_partition import RULE_AUTHORITY_POLICY
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.authority_provenance_projection_v1 import AuthorityProvenanceProjectorV1 as Projector
from apps.api.app.infrastructure.persistence.db_models import SSEEventOutboxRecord as Event
from apps.api.app.infrastructure.persistence.context_authority_models import ContextAuthorityRootRecord, ContextAuthorityDependencyRecord
from apps.api.app.infrastructure.persistence.image_revision_models import ImageObjectMemberRecord as Member
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.tests.test_authority_provenance_api import anchors
from apps.api.tests.test_exweb_context_change_impact import evidence_api, documents, export_tree
from apps.api.tests.test_exweb_source_delta import BEFORE, AFTER
from apps.api.tests.test_business_rules_api import rule, submit_rule, inspect_rule, withdraw
from apps.api.tests.test_acceptance_specifications_api import submit, inspect, ORACLE
from apps.api.tests.test_context_packs_api import preview, archive, read
from apps.api.tests.test_reference_links_api import candidate
from apps.api.tests.test_semantic_evaluations_api import completed


def test_actual_exweb_context_preserves_authority_sources_and_withdrawn_history_after_refresh(rule):
    v = rule
    target = next(obj for obj in v["rule_objects"] if obj["type"] == "SourceAcceptanceCriterion")
    query = {**v["rule_query"], "object_id": target["id"]}
    url = f"/v1/projects/{v['project_id']}/quality/acceptance-specifications"
    response = v["client"].get(url, params=query, headers=v["headers"])
    assert response.status_code == 200, response.text
    request = dict(project_id=v["project_id"], **query, basis_digest=response.json()["basis_digest"],
        expected_previous_revision_id=None, decision="approve", oracle=ORACLE,
        authority_basis="user_confirmed_requirement", reason="Explicit synthetic companion oracle, not exweb business gold",
        policy_revision=AC_POLICY)
    v.update(ac_url=url, ac_query=query, ac_request=request)
    completed(submit(v))
    completed(submit_rule(v))
    ac_head, rule_head = inspect(v)["head"], inspect_rule(v)["head"]
    previewed = preview(v, policy_revision=RULE_AUTHORITY_POLICY, max_tokens=32768)
    response, _ = archive(v, previewed)
    context, context_url = read(v, completed(response))
    pins = {item["object_id"]: item["authority"] for item in context["context"]["required_constraints"]}
    assert pins[ac_head["object_id"]]["revision_id"] == ac_head["revision_id"]
    assert pins[rule_head["object_id"]]["revision_id"] == rule_head["revision_id"]
    with session_scope() as session:
        assert session.scalars(select(Member).where(Member.project_id == v["project_id"],
            Member.image_revision_id == query["image_revision_id"], Member.binding_id == v["exweb_binding"],
            Member.kind == "code_entity")).first() is not None
        initial = anchors(session, v["project_id"])
        assert len(initial) == 2 and {row["kind"] for row in initial} == {"acceptance", "business_rule"}
        context_id = context["metadata"]["context_id"]
        root = session.get(ContextAuthorityRootRecord, (v["project_id"], context_id))
        dependencies = session.scalars(select(ContextAuthorityDependencyRecord).where(
            ContextAuthorityDependencyRecord.project_id == v["project_id"], ContextAuthorityDependencyRecord.context_id == context_id)).all()
        assert root is not None and root.authority_count == 2 and len(dependencies) == 2
        assert {item.revision_id for item in dependencies} == {ac_head["revision_id"], rule_head["revision_id"]}
        dependency_hash = root.content_hash
    old_urls = [url + "/" + ac_head["revision_id"], v["rule_url"] + "/" + rule_head["revision_id"]]
    original = [v["client"].get(path, headers=v["headers"]).json() for path in old_urls]
    completed(submit(v, {**request, "decision": "withdraw", "oracle": None, "authority_basis": None,
        "expected_previous_revision_id": ac_head["revision_id"], "reason": "Withdraw synthetic companion oracle"}))
    completed(withdraw(v))
    with session_scope() as session:
        before = anchors(session, v["project_id"])
        assert len(before) == 4 and all(row in before for row in initial)
        assert Projector().backfill(session) == 0
        ids = [row["revision_id"] for row in before]
        retained = [dict(row) for row in session.execute(select(*Event.__table__.columns).where(Event.entity_id.in_(ids))).mappings()]
        assert len(retained) == 4
        session.execute(delete(Event).where(Event.entity_id.in_(ids)))
    try:
        assert [v["client"].get(path, headers=v["headers"]).json() for path in old_urls] == original
        current = v["client"].get(context_url, headers=v["headers"])
        assert current.status_code == 200, current.text
        assert current.json()["context"] == context["context"] and current.json()["metadata"] == context["metadata"]
        assert current.json()["current_use"]["stale"] and not current.json()["current_use"]["generation_authorized"]
    finally:
        with session_scope() as session:
            session.execute(insert(Event), retained)
    count, tree_hash = export_tree(v["exweb_git"], AFTER, v["exweb_export"])
    assert (v["exweb_before_file_count"], count) == (125, 126)
    v["invoke"]("system_image.sources.ingest")
    v["invoke"]("system_image.context.materialize")
    fresh = candidate(v)
    for base, target_id in ((url, ac_head["object_id"]), (v["rule_url"], rule_head["object_id"])):
        response = v["client"].get(base, headers=v["headers"], params={"image_revision_id": fresh["image_revision_id"],
            "image_artifact_hash": fresh["artifact_hash"], "object_id": target_id})
        assert response.status_code == 200, response.text
        assert response.json()["head"] is None
    assert [v["client"].get(path, headers=v["headers"]).json() for path in old_urls] == original
    with session_scope() as session:
        assert anchors(session, v["project_id"]) == before and Projector().backfill(session) == 0
        assert session.get(ContextAuthorityRootRecord, (v["project_id"], context_id)).content_hash == dependency_hash
    report = {"verified_at": datetime.now(timezone.utc).isoformat(), "repository": "https://github.com/kunben-duck/exweb.git",
        "git_commits": [BEFORE, AFTER], "export_file_counts": [125, 126],
        "export_tree_hashes": [v["exweb_before_tree_hash"], tree_hash], "postgresql": True, "minio": True,
        "authority_registration_count": 4, "authority_kinds": ["acceptance", "business_rule"],
        "registry_digest": snapshot_digest(before), "fixed_context_authority_pins_verified": True,
        "fixed_context_authority_dependencies_registered": True, "context_authority_dependency_count": 2,
        "context_authority_registration_hash": dependency_hash,
        "withdrawal_keeps_original_context_but_invalidates_current_use": True,
        "historical_authority_survives_event_retention_and_source_refresh": True,
        "new_image_does_not_inherit_authority": True, "backfill_idempotent": True,
        "companion_oracles": "explicit_synthetic_protocol_not_exweb_business_gold",
        "external_model_called": False, "target_executed": False,
        "complete_context_authority_dag_registered": False, "automatic_project_delta_implemented": False}
    if os.getenv("EXWEB_AUTHORITY_PROVENANCE_REPORT"):
        Path(os.environ["EXWEB_AUTHORITY_PROVENANCE_REPORT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
