"""Independent OS acquisition probe, restricted to disposable PG/private MinIO."""
from __future__ import annotations

import json
import os
import sys
import time


def main():
    from apps.api.app.infrastructure.persistence.database import engine

    if (engine.dialect.name != "postgresql" or not engine.url.database.startswith("nasus_test_")
            or os.getenv("NASUS_TEST_OBJECT_STORAGE_MODE") != "minio"
            or not os.getenv("NASUS_S3_BUCKET", "").startswith("nasus-test-")):
        raise SystemExit("Probe requires disposable PostgreSQL and private test MinIO")

    from apps.api.app.application.platform.account_models import UserProfile
    from apps.api.app.application.platform.actor_context import actor_scope
    from apps.api.app.application.platform.errors import PlatformApplicationError
    from apps.api.app.application.system_image.source_refresh_inputs import source_refresh_selection
    from apps.api.app.bootstrap.container import get_application_container
    from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, UserIdentityRecord
    from apps.api.app.infrastructure.persistence.source_acquisition_repository import SourceAcquisitionIntentRepository
    from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
    from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService

    request = json.loads(sys.stdin.readline())
    with session_scope() as session:
        command = session.get(ToolInvocationRecord, request["invocation_id"])
        actor = session.get(UserIdentityRecord, request["actor_id"])
        if (command is None or command.status != "running" or command.tool_id != "system_image.sources.ingest"
                or command.input_payload.get("project_id") != request["project_id"]
                or actor is None or actor.status != "active"):
            raise SystemExit("Probe requires its original running command and current account")
        selection = source_refresh_selection(command.input_payload)
        user = UserProfile(id=actor.user_id, name=actor.display_name, email=actor.email, role=actor.role)

    op = get_application_container().system_image.source_bindings._operations
    calls = []
    ingest = SourceIngestionService.ingest

    def counted(connector, source):
        calls.append(source.id)
        return ingest(connector, source)

    SourceIngestionService.ingest = counted

    if request["mode"] == "capture":
        method = "record_success" if request["window"] == "after_capture" else "commit_manifest"
        original = getattr(SourceAcquisitionIntentRepository, method)

        def wait_after_commit(repository, *args, **kwargs):
            original(repository, *args, **kwargs)
            print(json.dumps({"boundary": request["window"], "pid": os.getpid(), "calls": calls}), flush=True)
            # The parent sends SIGKILL here; no exception/finally recovery runs.
            while True:
                time.sleep(1)

        setattr(SourceAcquisitionIntentRepository, method, wait_after_commit)

    try:
        with actor_scope(user):
            op.source_ingestion_use_cases.ingest_sources(request["project_id"], selection=selection,
                invocation_id=request["invocation_id"],
                ensure_draft_state=lambda: op.ensure_state(request["project_id"], ready=False),
                source_binding_incomplete=lambda: op.source_binding_incomplete(request["project_id"]),
                missing_source_types=lambda: op.missing_source_types(request["project_id"]))
    except PlatformApplicationError as error:
        print(json.dumps({"pid": os.getpid(), "calls": calls, "status": "rejected", "code": error.code}), flush=True)
        return 3
    print(json.dumps({"pid": os.getpid(), "calls": calls, "status": "restored"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
