from __future__ import annotations

from hashlib import sha256
import json

from ..platform.tool_models import ToolResult


def observation_receipt_fingerprint(result: ToolResult | None) -> str | None:
    if result is None or result.status != "completed":
        return None
    if result.run_plan_locator_record is not None:
        return sha256(json.dumps(result.run_plan_locator_record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if result.run_plan_health_record is not None:
        return sha256(json.dumps(result.run_plan_health_record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if result.run_plan_environment_record is not None:
        return sha256(json.dumps(result.run_plan_environment_record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if result.run_plan_environment is not None:
        return sha256(json.dumps(result.run_plan_environment, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if result.run_plan_observations is not None:
        return sha256(json.dumps(result.run_plan_observations, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if result.run_plan_build_preview is not None or result.run_plan_build is not None:
        receipt = result.run_plan_build_preview if result.run_plan_build_preview is not None else result.run_plan_build
        return sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if result.context_authority_backfill is not None:
        return sha256(result.context_authority_backfill.model_dump_json().encode("utf-8")).hexdigest()
    if result.test_design_review_drafts is not None:
        return sha256(result.test_design_review_drafts.model_dump_json().encode("utf-8")).hexdigest()
    if result.context_retrieval_result is not None:
        return sha256(json.dumps(result.context_retrieval_result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if result.context_retrieval_preview is not None:
        return sha256(json.dumps(result.context_retrieval_preview, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if result.index_preview is not None:
        return sha256(json.dumps(result.index_preview, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if result.build_plan_query is not None:
        return result.build_plan_query.plan_digest
    if result.investigation is not None:
        return result.investigation.revision_hash
    if result.business_rule_authority is not None:
        return sha256(result.business_rule_authority.model_dump_json().encode("utf-8")).hexdigest()
    if result.test_design_scope is not None:
        return sha256(result.test_design_scope.model_dump_json().encode("utf-8")).hexdigest()
    if result.acceptance_authority is not None:
        return sha256(result.acceptance_authority.model_dump_json().encode("utf-8")).hexdigest()
    if result.context_pack is not None:
        return sha256(result.context_pack.model_dump_json().encode("utf-8")).hexdigest()
    if result.image_publication is not None:
        return sha256(result.image_publication.model_dump_json().encode("utf-8")).hexdigest()
    if result.image_publication_head is not None:
        return sha256(result.image_publication_head.model_dump_json().encode("utf-8")).hexdigest()
    if result.image_query is not None:
        return result.image_query.result_hash
    if result.evidence_query is not None:
        return sha256(result.evidence_query.model_dump_json().encode("utf-8")).hexdigest()
    return None
