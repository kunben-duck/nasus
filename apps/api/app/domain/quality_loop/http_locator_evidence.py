"""Static path evidence is not runtime dispatch, an oracle or permission."""
from collections import Counter
from copy import deepcopy
import json
import re

from .acceptance_specification import acceptance_digest
from .run_plan import RunPlanIntegrityError, RunPlanInvalid


LOCATOR_SCHEMA = "nasus.run-plan-http-locators.v1"
LOCATOR_POLICY = "nasus.http-locator-static-match.v1"
LOCATOR_FORMATS = {
    "nasus.frozen-http-route-inventory.v1": ("java.import-resolved-http-locators.v1", LOCATOR_SCHEMA, LOCATOR_POLICY),
    "nasus.frozen-http-route-inventory.v2": ("java.import-resolved-http-locators.v2",
        "nasus.run-plan-http-locators.v2", "nasus.http-locator-static-match.v2"),
}
HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "ANY"})
LOCATOR_STATES = ("static_match", "ambiguous", "unresolved", "not_found", "unsupported")
MAX_LOCATOR_REPORT_BYTES = 4 * 1024 * 1024


def _segments(path, *, template):
    # Do not guess framework decoding, regex/glob/matrix parameters or aliases.
    if type(path) is not str or not path.startswith("/") or any(char in path for char in "%\\;*#"):
        return None
    parts = path.split("/")
    for part in parts:
        variable = re.fullmatch(r"\{[A-Za-z][A-Za-z0-9_]*\}", part) if template else re.fullmatch(r"\{\{[A-Za-z][A-Za-z0-9_-]{0,63}\}\}", part)
        if not variable and (any(char in part for char in "{}") or part in {".", ".."}):
            return None
    return parts


def _path_match(path, route):
    actual, pattern = _segments(path, template=False), _segments(route, template=True)
    if actual is None or pattern is None:
        return None
    if len(actual) != len(pattern):
        return False
    for value, part in zip(actual, pattern):
        if re.fullmatch(r"\{[A-Za-z][A-Za-z0-9_]*\}", part):
            if not value:
                return False
        elif value != part:
            return False
    return True


def _may_overlap(path, route):
    actual, pattern = _segments(path, template=False), _segments(route, template=True)
    if actual is None or pattern is None or "?" in route:
        return None
    if len(actual) != len(pattern):
        return False
    for value, part in zip(actual, pattern):
        if (re.fullmatch(r"\{\{[A-Za-z][A-Za-z0-9_-]{0,63}\}\}", value)
                or re.fullmatch(r"\{[A-Za-z][A-Za-z0-9_]*\}", part)):
            continue
        if value != part:
            return False
    return True


def _uncertainty_scope(route):
    if "unresolved_match_scope" not in route:
        raise RunPlanIntegrityError("scoped locator uncertainty requires an explicit original scope")
    scope = route["unresolved_match_scope"]
    if scope is None:
        return None
    if type(scope) is not list or not 1 <= len(scope) <= 64:
        raise RunPlanIntegrityError("invalid bounded locator uncertainty scope")
    for item in scope:
        if (type(item) is not dict or set(item) != {"method", "route_path"}
                or type(item["method"]) is not str or item["method"] not in HTTP_METHODS
                or type(item["route_path"]) is not str or not item["route_path"].startswith("/")
                or len(item["route_path"]) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in item["route_path"])):
            raise RunPlanIntegrityError("invalid original locator method/path scope")
    pairs = [(item["method"], item["route_path"]) for item in scope]
    if pairs != sorted(set(pairs)):
        raise RunPlanIntegrityError("locator uncertainty scope must be complete and unambiguous")
    return scope


def _uncertainty_may_match(path, method, scope):
    return scope is None or any((item["method"] in {method, "ANY"} or method in {"HEAD", "OPTIONS"})
        and _may_overlap(path, item["route_path"]) is not False for item in scope)


def compile_http_locator_evidence(plan, inventory):
    try:
        rule, schema, policy = LOCATOR_FORMATS[inventory["schema"]]
        scoped = inventory["schema"] == "nasus.frozen-http-route-inventory.v2"
        if len(json.dumps(inventory, ensure_ascii=False, allow_nan=False).encode()) > MAX_LOCATOR_REPORT_BYTES:
            raise RunPlanInvalid("complete locator evidence exceeds its bound; never truncate original actions")
        if (plan["plan_digest"] != acceptance_digest({key: value for key, value in plan.items() if key != "plan_digest"})
                or inventory["rule"] != rule
                or scoped and plan["schema"] != "nasus.run-plan.v3"
                or inventory["inventory_hash"] != acceptance_digest({key: value for key, value in inventory.items() if key != "inventory_hash"})
                or type(inventory["sources"]) is not list or not 1 <= len(inventory["sources"]) <= 64):
            raise RunPlanIntegrityError("locator original plan or inventory digest differs")
        expected = sorted(plan["selection"]["target_build"]["code_sources"], key=lambda item: item["binding_id"])
        observed = [{key: source["pin"][key] for key in ("binding_id", "source_revision_id")} for source in inventory["sources"]]
        if observed != expected:
            raise RunPlanIntegrityError("locator inventory must retain the complete original code roster")
        routes, files = [], []
        for source in inventory["sources"]:
            pin = source["pin"]
            if (type(source["files"]) is not list or not 1 <= len(source["files"]) <= 1000
                    or type(source["routes"]) is not list or len(source["routes"]) > 50000):
                raise RunPlanIntegrityError("locator source inventory exceeds its complete bound")
            if any(pin[key] != plan["source_pin"][key] for key in ("project_id", "image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")):
                raise RunPlanIntegrityError("locator inventory is outside the original frozen image")
            files.extend(source["files"])
            by_path = {item["relative_path"]: item for item in source["files"]}
            if len(by_path) != len(source["files"]):
                raise RunPlanIntegrityError("locator inventory has duplicate files")
            for route in source["routes"]:
                file = by_path[route["relative_path"]]
                if (file["status"] != "parsed" or route["kind"] != "route" or route["rule"] != inventory["rule"]
                        or route["source_file_hash"] != file["source_file_hash"]
                        or type(route["start_line"]) is not int or type(route["end_line"]) is not int
                        or not 1 <= route["start_line"] <= route["end_line"]
                        or route["status"] not in {"observed", "unresolved"}):
                    raise RunPlanIntegrityError("locator route lacks parsed original source evidence")
                if scoped and route["status"] == "unresolved":
                    _uncertainty_scope(route)
                elif "unresolved_match_scope" in route:
                    raise RunPlanIntegrityError("locator scope cannot change a legacy or observed declaration")
                routes.append({"binding_id": pin["binding_id"], "source_revision_id": pin["source_revision_id"],
                    "snapshot_manifest_hash": pin["snapshot_manifest_hash"], **deepcopy(route)})
        results = []
        for script in plan["proposal"]["scripts"]:
            for index, action in enumerate(script["actions"]):
                if script["kind"] == "http" and action["action"] != "request":
                    continue
                value = {"case_id": script["case_id"], "action_index": index, "action_digest": acceptance_digest(action),
                    "source_step_indices": deepcopy(action["source_step_indices"]), "candidates": []}
                if script["kind"] != "http":
                    value.update(status="unsupported", reason="browser_locator_requires_original_dom_evidence")
                else:
                    path = action["path"].partition("?")[0]
                    value.update(request_id=action["request_id"], method=action["method"], path=action["path"])
                    unknown = (_segments(path, template=False) is None
                        or any(file["language"] == "java" and file["status"] != "parsed" for file in files))
                    for route in routes:
                        if route["status"] != "observed":
                            if not scoped or _uncertainty_may_match(path, action["method"], route["unresolved_match_scope"]):
                                unknown = True
                            continue
                        match = _path_match(path, route["route_path"])
                        if match is None:
                            unknown = True
                        elif match and route["method"] in {action["method"], "ANY"}:
                            value["candidates"].append(deepcopy(route))
                        elif match and action["method"] in {"HEAD", "OPTIONS"}:
                            unknown = True
                        elif scoped and not match and (route["method"] in {action["method"], "ANY"}
                                or action["method"] in {"HEAD", "OPTIONS"}) and _may_overlap(path, route["route_path"]) is not False:
                            unknown = True
                    count = len(value["candidates"])
                    if count > 1:
                        value.update(status="ambiguous", reason="multiple_static_declarations")
                    elif count == 1 and not unknown:
                        value.update(status="static_match", reason="method_and_path_only_not_runtime_dispatch")
                    elif unknown:
                        value.update(status="unresolved", reason="unsupported_pattern_or_request_condition")
                    else:
                        value.update(status="not_found" if any(inventory["rule"] in file["rules"] for file in files) else "unsupported",
                            reason="no_matching_observed_declaration_not_proof_of_absence")
                results.append(value)
        counts = Counter(item["status"] for item in results)
        value = {"schema": schema, "policy": policy, "project_id": plan["project_id"],
            "plan_digest": plan["plan_digest"], "script_pin": deepcopy(plan["script_pin"]),
            "source_pin": deepcopy(plan["source_pin"]), "inventory": deepcopy(inventory), "locators": results,
            "summary": {"locator_count": len(results), **{key: counts[key] for key in LOCATOR_STATES}},
            "scope": "fixed_source_static_method_and_path_only", "runtime_locators_verified": False,
            "fixtures_verified": False, "execution_authorized": False, "business_coverage_verified": False,
            "automated_count": 0, "executed_on_target_count": 0, "passed_count": 0}
        result = {**value, "report_hash": acceptance_digest(value)}
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_LOCATOR_REPORT_BYTES:
            raise RunPlanInvalid("complete locator evidence exceeds its bound; never truncate original actions")
        return result
    except (KeyError, TypeError, AttributeError) as exc:
        raise RunPlanIntegrityError("locator original scope or evidence cannot be verified") from exc
