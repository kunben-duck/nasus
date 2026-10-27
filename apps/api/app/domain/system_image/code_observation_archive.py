"""Complete received projections remain observations, not registered identities."""
from collections import Counter
import json
import math

from .code_analysis import analysis_path
from .code_identity import CodeSymbolKey
from .code_provider import validate_projection_payload, PROJECTION_SCHEMA
from .image_revision import require_digest
from .source_snapshots import snapshot_digest
from .code_native_observation import validate_native_queries


OBSERVATION_SCHEMA = "nasus.code-observation-archive.v1"
OBSERVATION_BASIS = "received_projection_not_complete_native_graph"
MAX_OBSERVATION_BYTES = 32 * 1024 * 1024
ENTITY_KINDS = frozenset({"module", "class", "interface", "enum", "function", "method", "api_route", "dependency"})
RELATION_KINDS = frozenset({"belongs_to", "depends_on", "calls", "exposes"})
IDENTITY_STATUSES = frozenset({"exact", "ambiguous", "unresolved"})


def observation_summary(payload):
    result = payload["result"]
    counts = Counter(item["identity_status"] for item in result["entities"])
    return {"basis": OBSERVATION_BASIS, "entity_count": len(result["entities"]),
        "relationship_count": len(result["relationships"]),
        "identity_counts": {key: counts[key] for key in sorted(IDENTITY_STATUSES)}}


def validate_observation_payload(payload):
    native = type(payload) is dict and payload.get("schema") == "nasus.code-observation-archive.v2"
    keys = {"schema", "basis", "project_id", "source_id", "source_manifest_hash", "external_revision", "result"}
    if native:
        keys.add("native_queries")
    if (type(payload) is not dict or set(payload) != keys
            or payload["schema"] not in {OBSERVATION_SCHEMA, "nasus.code-observation-archive.v2"}
            or payload["basis"] != OBSERVATION_BASIS):
        raise ValueError("invalid code observation envelope")
    require_digest(payload["source_manifest_hash"])
    for key in ("project_id", "source_id", "external_revision"):
        if type(payload[key]) is not str or not payload[key] or len(payload[key]) > 4096:
            raise ValueError("invalid code observation source pin")
    result = payload["result"]
    if (type(result) is not dict or set(result) != {"provider", "provider_version", "entities", "relationships",
            "evidence_refs", "unsupported_paths", "file_analyses", "structural_facts", "provider_observations"}
            or type(result.get("entities")) is not list
            or type(result.get("relationships")) is not list
            or len(result["entities"]) > 50000 or len(result["relationships"]) > 100000):
        raise ValueError("invalid code observation collection")
    ids = set()
    for item in result["entities"]:
        if type(item) is not dict or set(item) != {"provider_node_id", "name", "qualified_name", "entity_kind",
                "relative_path", "language", "start_line", "end_line", "evidence_refs", "symbol_key",
                "identity_status", "location_precision", "supporting_spans"}:
            raise ValueError("invalid code entity observation fields")
        node = item.get("provider_node_id")
        if (type(node) is not str or not node or len(node) > 4096 or node in ids
                or item.get("entity_kind") not in ENTITY_KINDS
                or item.get("identity_status") not in IDENTITY_STATUSES
                or item.get("location_precision") not in {"exact", "approximate"}):
            raise ValueError("invalid code entity observation")
        analysis_path(item["relative_path"])
        if (type(item.get("start_line")) is not int or type(item.get("end_line")) is not int
                or not 1 <= item["start_line"] <= item["end_line"]):
            raise ValueError("invalid code observation location")
        for key in ("name", "qualified_name", "language"):
            if type(item[key]) is not str or not item[key] or len(item[key]) > 4096:
                raise ValueError("invalid code observation name")
        if item["symbol_key"] is not None:
            try:
                symbol = CodeSymbolKey(**item["symbol_key"])
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid code observation symbol") from exc
            if (symbol.relative_path, symbol.language, symbol.kind, symbol.name) != (
                    item["relative_path"], item["language"], item["entity_kind"], item["name"]):
                raise ValueError("code observation symbol mismatch")
        ids.add(node)
    for item in result["relationships"]:
        if (type(item) is not dict or set(item) != {"from_provider_node_id", "relationship_kind", "to_provider_node_id",
                "confidence", "evidence_refs"} or item.get("from_provider_node_id") not in ids or item.get("to_provider_node_id") not in ids
                or item.get("relationship_kind") not in RELATION_KINDS):
            raise ValueError("code observation relationship is outside its received projection")
        if type(item["confidence"]) not in {int, float} or not math.isfinite(item["confidence"]):
            raise ValueError("invalid code observation score")
    for key in ("provider", "provider_version"):
        if type(result[key]) is not str or not result[key] or len(result[key]) > 240:
            raise ValueError("invalid code observation provider")
    for key in ("evidence_refs", "unsupported_paths", "file_analyses", "structural_facts", "provider_observations"):
        if type(result[key]) is not list:
            raise ValueError("invalid code observation metadata")
    if result["provider_observations"]:
        providers = result["provider_observations"]
        complete = all(item["availability"] == "observed" and not item["gaps"]
            and item["entity_enumeration"] == item["relationship_enumeration"] == "complete"
            and not item["approximate_locations"] for item in providers)
        validate_projection_payload({"schema": PROJECTION_SCHEMA,
            "scope": "normalized_static_projection_not_business_or_runtime_acceptance",
            "status": "complete" if complete else "partial", "providers": providers})
    if native:
        observations = validate_native_queries(payload["native_queries"])
        providers = {(item["capabilities"]["provider"], item["capabilities"]["provider_version"])
            for item in result["provider_observations"] if item["availability"] == "observed"}
        if not result["provider_observations"]:
            providers = {(result["provider"], result["provider_version"])}
        if any((item.provider, item.provider_version) not in providers for item in observations):
            raise ValueError("native query observation provider differs from its projection")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    if len(body) > MAX_OBSERVATION_BYTES:
        raise ValueError("code observation archive exceeds size limit")
    return body


def validate_observation_pin(pin):
    if (type(pin) is not dict or set(pin) != {"artifact_ref", "artifact_hash", "summary"}
            or type(pin["artifact_ref"]) is not str or not pin["artifact_ref"]
            or len(pin["artifact_ref"]) > 2048):
        raise ValueError("invalid code observation archive pin")
    require_digest(pin["artifact_hash"])
    validate_observation_summary(pin["summary"])


def validate_observation_summary(summary):
    if (type(summary) is not dict or set(summary) != {"basis", "entity_count", "relationship_count", "identity_counts"}
            or summary["basis"] != OBSERVATION_BASIS):
        raise ValueError("invalid code observation summary")
    counts = summary["identity_counts"]
    if type(counts) is not dict or set(counts) != IDENTITY_STATUSES:
        raise ValueError("invalid code observation identity counts")
    for count, maximum in ((summary["entity_count"], 50000), (summary["relationship_count"], 100000),
                            *((count, 50000) for count in counts.values())):
        if type(count) is not int or not 0 <= count <= maximum:
            raise ValueError("invalid code observation count")
    if sum(counts.values()) != summary["entity_count"]:
        raise ValueError("code observation counts do not match")


def verify_observation_report(payload, report):
    validate_observation_payload(payload)
    pin = report["observation_archive"]
    validate_observation_pin(pin)
    if (snapshot_digest(payload) != pin["artifact_hash"] or observation_summary(payload) != pin["summary"]
            or any(payload[key] != report[key] for key in
                   ("project_id", "source_id", "source_manifest_hash", "external_revision"))
            or payload["result"]["provider"] != report["provider"]
            or payload["result"]["provider_version"] != report["provider_version"]):
        raise ValueError("code observation archive differs from its pinned analysis")
