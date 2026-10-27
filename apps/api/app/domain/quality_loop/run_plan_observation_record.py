"""A complete native observation roster is evidence, not executed coverage."""
from copy import deepcopy

from .acceptance_specification import acceptance_digest
from .run_plan_observations import (
    RunPlanObservationInvalid, verify_plan, collect_run_plan_observations, collect_run_plan_attempt_observations,
)


def observation_record_metadata(archive, request, *, record_id, invocation_id, actor_id, recorded_at):
    try:
        plan = verify_plan(archive["plan"])
        summary = archive["summary"]
        unknown_items = archive.get("unverified_attempts", [])
        rebuilt = (collect_run_plan_attempt_observations(plan, archive["observations"], unknown_items,
            run_id=archive["run_id"], timeout_ms=archive["timeout_ms"]) if unknown_items else
            collect_run_plan_observations(plan, archive["observations"]))
        if summary != rebuilt:
            raise RunPlanObservationInvalid("observation registration summary differs from original case and oracle results")
        parent = {key: request[key] for key in ("project_id", "run_plan_id", "run_plan_artifact_hash", "plan_digest")}
        if (archive["original_run_plan"] != parent or archive["run_id"] != request["run_id"]
                or acceptance_digest(archive) != request["observation_artifact_hash"]
                or summary["collection_digest"] != request["collection_digest"]
                or archive["project_id"] != request["project_id"] or plan["plan_digest"] != request["plan_digest"]
                or any(archive[key] is not False for key in ("execution_authorized", "target_build_verified",
                    "business_coverage_verified", "canonical_execution_committed"))
                or any(type(summary[key]) is not int or summary[key] != 0 for key in
                    ("automated_count", "executed_on_target_count", "passed_count"))):
            raise RunPlanObservationInvalid("observation registration cannot grant or replace original authority")
        observed = {item["case_id"]: item for item in archive["observations"]}
        unknown = {item["case_id"]: item for item in archive.get("unverified_attempts", [])}
        members = []
        for ordinal, case in enumerate(summary["cases"]):
            detail = observed.get(case["case_id"]) or unknown.get(case["case_id"])
            members.append({"record_id": record_id, "project_id": request["project_id"], "ordinal": ordinal,
                "case_id": case["case_id"], "case_digest": case["case_digest"], "status": case["status"],
                "observation_digest": case["observation_digest"], "attempt_digest": case.get("attempt_digest"),
                "actions": deepcopy(detail["actions"]) if detail else [],
                "oracles": deepcopy(detail["oracles"]) if detail else []})
        if (len(members) != len(plan["prepared"]["cases"]) or
                [item["case_id"] for item in members] != [item["case_id"] for item in plan["prepared"]["cases"]]):
            raise RunPlanObservationInvalid("observation registration must preserve the full original case roster")
        return {"record_id": record_id, **parent,
            "image_revision_id": plan["source_pin"]["image_revision_id"], "manifest_id": plan["source_pin"]["manifest_id"],
            "invocation_id": invocation_id, "actor_id": actor_id, "recorded_at": recorded_at,
            "artifact_hash": request["observation_artifact_hash"], "collection_digest": request["collection_digest"],
            "request_hash": acceptance_digest(request), "run_id": request["run_id"], "status": "recorded",
            "case_count": len(members), "observed_case_count": summary["observed_case_count"],
            "outcome_unknown_case_count": len(unknown), "no_result_case_count": len(members) - len(observed) - len(unknown),
            "passed_observation_count": summary["passed_observation_count"],
            "failed_observation_count": summary["failed_observation_count"], "members": members,
            "execution_authorized": False, "target_build_verified": False, "business_coverage_verified": False,
            "canonical_execution_committed": False, "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0}
    except (KeyError, TypeError, AttributeError, UnicodeError, RecursionError):
        raise RunPlanObservationInvalid("observation registration cannot verify all original members") from None
