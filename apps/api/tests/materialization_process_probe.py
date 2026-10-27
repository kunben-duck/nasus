"""Native materialization restart probe, restricted to disposable PG/MinIO."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
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
    from apps.api.app.bootstrap.container import get_application_container
    from apps.api.app.infrastructure.persistence.db_models import ToolInvocationRecord, UserIdentityRecord
    from apps.api.app.infrastructure.persistence.materialization_command_repository import MaterializationCommandInputRepository
    from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
    from apps.api.app.infrastructure.system_image.source_ingestion import SourceIngestionService

    request = json.loads(sys.stdin.readline())
    with session_scope() as session:
        command = session.get(ToolInvocationRecord, request["invocation_id"])
        actor = session.get(UserIdentityRecord, request["actor_id"])
        if (command is None or command.status != "running" or command.tool_id != "system_image.context.materialize"
                or command.input_payload.get("project_id") != request["project_id"]
                or actor is None or actor.status != "active"):
            raise SystemExit("Probe requires its original running command and current account")
        user = UserProfile(id=actor.user_id, name=actor.display_name, email=actor.email, role=actor.role)

    service = get_application_container().system_image.lifecycle._operations
    calls = []
    ingest = SourceIngestionService.ingest

    def counted(connector, source):
        calls.append(source.id)
        return ingest(connector, source)

    SourceIngestionService.ingest = counted

    def committed_marker(original, candidate=None):
        print(json.dumps({"boundary": request["window"], "pid": os.getpid(), "calls": calls,
            "input": asdict(original), "input_hash": original.content_hash,
            "candidate_id": candidate.image_revision_id if candidate else None}), flush=True)
        # A real SIGKILL follows; no catch/finally handler repairs this process.
        while True:
            time.sleep(1)

    if request["mode"] == "interrupt":
        if request["window"] == "after_admission":
            admit = MaterializationCommandInputRepository.admit

            def pause_after_admission(repository, *args, **kwargs):
                original = admit(repository, *args, **kwargs)
                committed_marker(original)

            MaterializationCommandInputRepository.admit = pause_after_admission
        elif request["window"] == "after_candidate":
            prepare = service.candidate_preparation.prepare

            def pause_after_candidate(*args, **kwargs):
                result = prepare(*args, **kwargs)
                scope = service.materialization_inputs.authorization.require_all_sources_access(request["project_id"])
                original = MaterializationCommandInputRepository().get(request["invocation_id"], scope)
                committed_marker(original, result.revision)

            service.candidate_preparation.prepare = pause_after_candidate
        else:
            raise SystemExit("Unknown interruption boundary")
    elif request["mode"] != "restore":
        raise SystemExit("Unknown process mode")

    try:
        with actor_scope(user):
            result = asyncio.run(service.materialize_context(request["project_id"], invocation_id=request["invocation_id"]))
            scope = service.materialization_inputs.authorization.require_all_sources_access(request["project_id"])
            original = MaterializationCommandInputRepository().get(request["invocation_id"], scope)
    except PlatformApplicationError as error:
        print(json.dumps({"pid": os.getpid(), "status": "rejected", "code": error.code, "calls": calls}), flush=True)
        return 3
    print(json.dumps({"pid": os.getpid(), "status": "restored", "calls": calls,
        "input": asdict(original), "input_hash": original.content_hash,
        "candidate_id": result.candidate_revision.image_revision_id,
        "candidate_manifest_id": result.candidate_revision.manifest_id}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
