"""Actual PG lifecycle fencing; SDK process doubles and native exweb are distinguished."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from apps.api.app.application.system_image.code_index_generations import CodeIndexGenerationApplicationService
from apps.api.app.application.system_image.source_ports import code_projection_payload
from apps.api.app.domain.system_image.code_index import CodeIndexCancelled
from apps.api.app.domain.system_image.code_index_generation import CodeIndexBusy, CodeIndexLeaseLost
from apps.api.app.domain.system_image.code_provider_protocol import CodeProviderSDKReceipt
from apps.api.app.domain.system_image.source_snapshots import snapshot_digest
from apps.api.app.infrastructure.persistence.code_index_generation_repository import CodeIndexGenerationRepository
from apps.api.app.infrastructure.persistence.code_index_generation_models import CodeIndexProtocolRecord, CodeIndexProjectionRecord
from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord
from apps.api.app.infrastructure.persistence.source_snapshot_repository import SourceSnapshotRepository
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
from apps.api.app.infrastructure.system_image import codegraph_sdk_code_intelligence as sdk
from apps.api.app.infrastructure.system_image.code_graph_process import CodeGraphProcessRunner
from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService
from apps.api.tests.test_codegraph_sdk import config, Runner, payload
from apps.api.tests.test_code_index_generations import pg_index
from apps.api.tests.test_codegraph_exweb import exweb_sdk_input


@pytest.fixture
def pg_sdk(pg_index, monkeypatch):
    v, data = pg_index, payload()
    data["files"][0]["path"] = "payments.py"
    for node in data["nodes"]:
        node.update(path="payments.py", language="python")
    graph = sdk.CodeGraphSDKCodeIntelligenceAdapter(config(v["tmp"]), process_runner=Runner(data))
    monkeypatch.setattr(sdk, "projection_dependency_manifest", lambda **kwargs: {"fixture": "bounded dependency double"})
    v["factory"] = graph
    v["service"] = CodeIndexGenerationApplicationService(v["repository"], v["reader"], graph)
    return v


def open_generation(v):
    return v["service"].open_index(v["source"], invocation_id=v["invocation"], check_current=lambda: None)


def test_sdk_pg_rebuild_reuses_generation_pin_not_session_cursors_or_native_cache(pg_sdk):
    v = pg_sdk
    original = open_generation(v)
    pin, stale_lease = original.generation, original.lease
    with original:
        first = original.entities(limit=1)
        result = original.read_projection()
        expected = snapshot_digest(code_projection_payload(result))
        receipt = original.protocol_receipt()
        assert isinstance(receipt, CodeProviderSDKReceipt)
        with pytest.raises(CodeIndexBusy):
            v["service"].reopen(pin.project_id, pin.generation_id, check_current=lambda: None)
    status = v["repository"].status(pin)
    assert status.state == "idle" and status.protocol == receipt and status.projection_hash == expected
    with v["service"].reopen(pin.project_id, pin.generation_id, check_current=lambda: None) as rebuilt:
        assert rebuilt.generation == pin and rebuilt.lease.epoch == stale_lease.epoch + 1
        assert snapshot_digest(code_projection_payload(rebuilt.read_projection())) == expected
        assert rebuilt.protocol_receipt() == receipt
        with pytest.raises(ValueError):
            rebuilt.entities(cursor=first.next_cursor, limit=1)
        with pytest.raises(CodeIndexLeaseLost):
            v["repository"].check(stale_lease)
        with pytest.raises(CodeIndexLeaseLost, match="contract diverges"):
            v["repository"].record_protocol(rebuilt.lease, replace(receipt, runtime_hash="sha256:" + "f" * 64))
    assert len(v["factory"].runner.calls) == 2 and list(v["factory"].config.cache_dir.iterdir()) == []


def test_divergent_sdk_rebuild_cannot_replace_original_projection_pin(pg_sdk):
    v = pg_sdk
    with open_generation(v) as original:
        original.read_projection()
        pin = original.generation
    expected = v["repository"].status(pin).projection_hash
    v["factory"].runner.data["nodes"][1]["name"] = "different-provider-result"
    with pytest.raises(CodeIndexLeaseLost, match="projection diverges"):
        with v["service"].reopen(pin.project_id, pin.generation_id, check_current=lambda: None) as rebuilt:
            rebuilt.read_projection()
    status = v["repository"].status(pin)
    assert status.state == "failed" and status.projection_hash == expected


def test_pg_cancel_is_observed_inside_sdk_preparation_and_blocks_reopen(pg_sdk):
    v = pg_sdk
    index = open_generation(v)
    def cancel(args, kwargs):
        v["repository"].request_cancel(index.generation)
        kwargs["check_current"]()
    v["factory"].runner.after = cancel
    with pytest.raises(CodeIndexCancelled):
        with index:
            pytest.fail("cancelled preparation must not yield a queryable projection")
    assert v["repository"].status(index.generation).state == "cancelled"
    with pytest.raises(CodeIndexCancelled):
        v["service"].reopen(index.generation.project_id, index.generation.generation_id, check_current=lambda: None)
    assert list(v["factory"].config.cache_dir.iterdir()) == []


class NativeRunner(CodeGraphProcessRunner):
    def __init__(self):
        self.calls = []

    def run(self, args, **kwargs):
        result = super().run(args, **kwargs)
        self.calls.append({"cwd": kwargs["cwd"], "returncode": result.returncode,
            "public_entry": str(Path(args[3]).relative_to(kwargs["cwd"]))})
        return result


def test_native_exweb_sdk_pg_minio_generation_close_and_rebuild(tmp_path, exweb_sdk_input):
    source, capture, _, storage, initial, git = exweb_sdk_input
    snapshots = SourceSnapshotRepository()
    snapshots.record_capture(source, capture.snapshot, captured_at="2026-10-08T00:00:00Z")
    invocation = "sdk_native_" + uuid4().hex
    with session_scope() as session:
        session.add(ToolInvocationRecord(id=invocation, tool_id="system_image.build.structure", status="running",
            summary="isolated exweb SDK durable lifecycle validation", input_payload={"project_id": source.project_id}))
    runner = NativeRunner()
    graph = sdk.CodeGraphSDKCodeIntelligenceAdapter(initial.config, process_runner=runner)
    reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "durable-restored")
    repository = CodeIndexGenerationRepository()
    service = CodeIndexGenerationApplicationService(repository, reader, graph)
    with service.open_index(source, invocation_id=invocation, check_current=lambda: None) as index:
        pin, lease = index.generation, index.lease
        result = index.read_projection()
        expected = snapshot_digest(code_projection_payload(result))
        receipt = index.protocol_receipt()
        assert isinstance(receipt, CodeProviderSDKReceipt) and receipt.runtime_hash == graph.config.expected_runtime_hash
        assert len(result.entities) == 526 and len(result.relationships) == 580
        first = index.entities(limit=100)
        assert first.next_cursor and first.normalized_count == 526
        for method, expected_items in ((index.entities, result.entities), (index.relations, result.relationships)):
            cursor, enumerated = None, []
            while True:
                page = method(cursor=cursor, limit=100)
                assert page.normalized_count == len(expected_items)
                enumerated.extend(page.items)
                cursor = page.next_cursor
                if cursor is None:
                    break
            assert len(enumerated) == len(expected_items)
            assert sorted(snapshot_digest(asdict(item)) for item in enumerated) == sorted(
                snapshot_digest(asdict(item)) for item in expected_items)
        entity = next(item for item in result.entities if item.name == "ChatController")
        assert index.locate(entity.provider_node_id) == entity
        assert not index.impact([entity.provider_node_id]).complete
        assert repository.status(pin).protocol == receipt
    assert repository.status(pin).state == "idle" and not list(graph.config.cache_dir.iterdir())
    # A new service and reader must restore immutable MinIO inputs, not an old session.
    replay_graph = sdk.CodeGraphSDKCodeIntelligenceAdapter(initial.config, process_runner=runner)
    replay_reader = SourceIngestionService(object_storage=storage, snapshot_cache_dir=tmp_path / "replay-restored")
    replay = CodeIndexGenerationApplicationService(CodeIndexGenerationRepository(), replay_reader, replay_graph)
    with replay.reopen(pin.project_id, pin.generation_id, check_current=lambda: None) as index:
        assert index.generation == pin and index.lease.epoch == lease.epoch + 1
        assert snapshot_digest(code_projection_payload(index.read_projection())) == expected
        assert index.protocol_receipt() == receipt
        with pytest.raises(ValueError):
            index.entities(cursor=first.next_cursor, limit=100)
        with pytest.raises(CodeIndexLeaseLost):
            repository.check(lease)
    assert len(runner.calls) == 2 and all(call["returncode"] == 0 for call in runner.calls)
    assert all(call["public_entry"] == "runtime/node_modules/@colbymchenry/codegraph" for call in runner.calls)
    assert all(not Path(call["cwd"]).exists() for call in runner.calls)
    with session_scope() as session:
        protocol = session.get(CodeIndexProtocolRecord, pin.generation_id)
        projection = session.get(CodeIndexProjectionRecord, pin.generation_id)
        assert protocol.receipt == receipt.payload() and protocol.content_hash == receipt.digest
        assert projection.projection_hash == expected
    assert git("rev-parse", "HEAD") == capture.snapshot.external_revision and not git("status", "--porcelain")
    report = {"schema": "nasus.exweb-codegraph-durable-sdk-validation.v1", "source_revision": capture.snapshot.external_revision,
        "files": 126, "bytes": 180868, "generation": asdict(pin), "sdk_receipt": receipt.payload(),
        "projection_hash": expected, "entities": 526, "relationships": 580, "native_preparations": 2,
        "old_cursor_rejected": True, "stale_lease_rejected": True, "original_checkout_unchanged": True,
        "storage": "isolated_postgresql_and_private_minio", "target_executed": False, "external_model_called": False,
        "production_default_changed": False, "semantic_quality_gold": False,
        "scope": "sdk_projection_rebuild_not_native_database_resume_or_temporal_worker_restart"}
    if os.environ.get("EXWEB_CODEGRAPH_DURABLE_REPORT"):
        path = Path(os.environ["EXWEB_CODEGRAPH_DURABLE_REPORT"])
        path.parent.mkdir(parents=True, exist_ok=True)
        assert not path.exists()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
