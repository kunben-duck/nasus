"""Independent static evidence; recording never grants runtime or coverage authority."""
from copy import deepcopy
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from .acceptance_specification import acceptance_digest
from .http_locator_evidence import compile_http_locator_evidence
from .run_plan import RunPlanIntegrityError


LOCATOR_RECORD_SCHEMA = "nasus.run-plan-locator-record.v1"
LOCATOR_RECORD_TOOL = "quality.run_plan.record_locators"
LOCATOR_RECORD_QUERY_TOOL = "query.quality.run_plan_locator_record"
LOCATOR_RECORD_TOOLS = frozenset({LOCATOR_RECORD_TOOL, LOCATOR_RECORD_QUERY_TOOL})
LOCATOR_RECORD_EVENT = "quality.run_plan.locators_recorded"
LOCATOR_EVENT_FIELDS = ("project_id", "record_id", "run_plan_id", "report_hash", "status")
LOCATOR_FALSE_AUTHORITIES = ("runtime_locators_verified", "fixtures_verified", "execution_authorized", "business_coverage_verified")
LOCATOR_ZERO_COUNTS = ("automated_count", "executed_on_target_count", "passed_count")


def locator_record_identity(invocation_id):
    return str(uuid5(NAMESPACE_URL, "nasus:run-plan-locators:" + invocation_id))


def locator_record_metadata(payload):
    try:
        if (type(payload) is not dict or set(payload) != {"schema", "project_id", "record_id", "invocation_id",
                "actor_id", "recorded_at", "request", "parents", "report"}
                or payload["schema"] != LOCATOR_RECORD_SCHEMA
                or any(type(payload[key]) is not str or not payload[key].strip() or len(payload[key]) > 128
                    for key in ("project_id", "record_id", "invocation_id", "actor_id"))
                or payload["record_id"] != locator_record_identity(payload["invocation_id"])
                or datetime.fromisoformat(payload["recorded_at"]).tzinfo is None
                or type(payload["request"]) is not dict
                or set(payload["request"]) != {"project_id", "run_plan_id", "run_plan_artifact_hash"}
                or payload["request"]["project_id"] != payload["project_id"]
                or type(payload["parents"]) is not dict
                or set(payload["parents"]) != {"plan_digest", "image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash"}):
            raise RunPlanIntegrityError("locator archive scope invalid")
        report = payload["report"]
        if (report["project_id"] != payload["project_id"]
                or report["plan_digest"] != payload["parents"]["plan_digest"]
                or any(report["source_pin"][key] != payload["parents"][key] for key in
                    ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash"))
                or report["report_hash"] != acceptance_digest({key: value for key, value in report.items() if key != "report_hash"})
                or any(report[key] is not False for key in LOCATOR_FALSE_AUTHORITIES)
                or any(type(report[key]) is not int or report[key] != 0 for key in LOCATOR_ZERO_COUNTS)):
            raise RunPlanIntegrityError("locator archive cannot grant execution authority")
        return {"schema": LOCATOR_RECORD_SCHEMA,
            **{key: payload[key] for key in ("project_id", "record_id", "invocation_id", "actor_id", "recorded_at")},
            **deepcopy(payload["request"]), **deepcopy(payload["parents"]),
            "request_hash": acceptance_digest(payload["request"]), "artifact_hash": acceptance_digest(payload),
            "inventory_hash": report["inventory"]["inventory_hash"], "report_hash": report["report_hash"],
            "summary": deepcopy(report["summary"]), "status": "recorded", "historical_not_live": True,
            "source_bytes_verified": True, "durable_locator_evidence_verified": True,
            **{key: False for key in LOCATOR_FALSE_AUTHORITIES}, **{key: 0 for key in LOCATOR_ZERO_COUNTS}}
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        if isinstance(exc, RunPlanIntegrityError):
            raise
        raise RunPlanIntegrityError("locator archive cannot be verified") from exc


def validate_locator_archive(payload, request, saved):
    metadata = locator_record_metadata(payload)
    plan = saved["artifact"]["plan"]
    if (payload["request"] != request
            or saved["metadata"]["project_id"] != request["project_id"]
            or saved["metadata"]["run_plan_id"] != request["run_plan_id"]
            or saved["metadata"]["artifact_hash"] != request["run_plan_artifact_hash"]
            or payload["parents"] != {"plan_digest": plan["plan_digest"], **{key: plan["source_pin"][key]
                for key in ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")}}
            or acceptance_digest(compile_http_locator_evidence(plan, payload["report"]["inventory"])) != acceptance_digest(payload["report"])):
        raise RunPlanIntegrityError("locator archive differs from the complete original plan")
    return metadata
