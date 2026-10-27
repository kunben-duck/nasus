from dataclasses import asdict
import json
from typing import Protocol

from ...domain.system_image.code_observation_archive import (
    OBSERVATION_BASIS, OBSERVATION_SCHEMA, validate_observation_payload,
)
from ...domain.system_image.source_snapshots import snapshot_digest
from .source_ports import code_projection_payload


class CodeObservationReadPort(Protocol):
    def read(self, report: dict) -> dict: ...


def received_code_observations(manifest, result):
    # Capture before formal identity admission; unresolved observations remain inspectable.
    payload = {"schema": OBSERVATION_SCHEMA, "basis": OBSERVATION_BASIS,
        **{key: manifest[key] for key in ("project_id", "source_id", "external_revision")},
        "source_manifest_hash": snapshot_digest(manifest), "result": json.loads(json.dumps(code_projection_payload(result)))}
    if result.native_query_observations:
        payload.update(schema="nasus.code-observation-archive.v2",
            native_queries=[asdict(item) for item in result.native_query_observations])
    validate_observation_payload(payload)
    if not {item["relative_path"] for item in payload["result"]["entities"]} <= {
            item["path"] for item in manifest["files"]}:
        raise ValueError("code observations are outside the source snapshot")
    return payload
