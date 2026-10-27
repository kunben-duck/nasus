"""Complete read-only PostgreSQL/MinIO comparisons, not target execution proof."""
from collections import Counter
from hashlib import sha256
from types import SimpleNamespace

from sqlalchemy import event
from sqlalchemy.engine import Engine

from apps.api.app.application.platform.account_models import UserProfile
from apps.api.app.application.platform.actor_context import actor_scope
from apps.api.app.infrastructure.storage.object_storage import ObjectStorage


def measure_parent_read(v, reader, monkeypatch, *, legacy=False):
    service = v["script_service"]
    admissions = service.admissions
    inputs = admissions.inputs
    storage = admissions.artifacts.storage
    prepare, replay, get_bytes = inputs.prepare, inputs.replay, storage.get_bytes
    factory = ObjectStorage._create_s3_client
    counts, objects = Counter(), {}

    def prepared(*args):
        counts["current_inputs"] += 1
        return prepare(*args)

    def replayed(*args):
        counts["historical_inputs"] += 1
        return replay(*args)

    def archived(ref, **kwargs):
        content = get_bytes(ref, **kwargs)
        digest = sha256(content).hexdigest()
        assert ref not in objects or objects[ref] == digest
        objects[ref] = digest
        counts["objects"] += 1
        return content

    def begin(connection):
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")

    def statement(_connection, _cursor, sql, _parameters, _context, _many):
        counts["sql"] += 1
        assert sql.lstrip().split(None, 1)[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        assert "FOR UPDATE" not in sql.upper()

    def readonly(model, **_kwargs):
        assert model.name in {"GetObject", "HeadObject", "HeadBucket", "GetBucketLocation", "ListObjectsV2"}

    def client(config):
        value = factory(config)
        value.meta.events.register("before-call.s3", readonly)
        return value

    event.listen(Engine, "begin", begin)
    event.listen(Engine, "before_cursor_execute", statement)
    try:
        with monkeypatch.context() as scoped, actor_scope(UserProfile.model_validate(v["owner"])):
            scoped.setattr(inputs, "prepare", prepared)
            scoped.setattr(inputs, "replay", replayed)
            scoped.setattr(storage, "get_bytes", archived)
            scoped.setattr(ObjectStorage, "_create_s3_client", staticmethod(client))
            if legacy:
                scoped.setattr(service, "admissions", SimpleNamespace(read=admissions.read, resolve=admissions.resolve))
            response = reader()
    finally:
        event.remove(Engine, "before_cursor_execute", statement)
        event.remove(Engine, "begin", begin)
    return response, counts, objects


def assert_script_parent_read(v, command, original, monkeypatch):
    service = v["script_service"]
    revision_id = original["metadata"]["script_revision_id"]
    calls = len(v["script_calls"])
    reader = lambda: service.read(v["project_id"], revision_id)
    before, control, before_objects = measure_parent_read(v, reader, monkeypatch, legacy=True)
    after, production, after_objects = measure_parent_read(v, reader, monkeypatch)
    assert before == after == original and before_objects == after_objects and before_objects
    assert control["historical_inputs"] == control["current_inputs"] == 3
    assert production["historical_inputs"] == production["current_inputs"] == 2
    assert production["sql"] < control["sql"] and production["objects"] < control["objects"]
    assert len(v["script_calls"]) == calls == 1
    assert after["metadata"]["invocation_id"] == command["id"]
    assert after["current_use"] == {"input_current": True, "execution_authorized": False}
    assert after["result"]["proposal"]["automated_count"] == after["result"]["proposal"]["passed_count"] == 0
