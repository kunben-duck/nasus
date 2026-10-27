"""Profile one existing authorized test recipe; never create facts or target requests."""
from __future__ import annotations

import argparse
import cProfile
import os
from pathlib import Path
import pstats
import re
import sys
import traceback
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def isolated_read_url(connection, database):
    url = make_url(connection)
    if (url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}
            or re.fullmatch(r"nasus_test_[0-9a-f]{32}", database) is None):
        raise ValueError("an existing isolated local PostgreSQL test database is required")
    return url.set(database=database, query={**url.query, "options": "-c default_transaction_read_only=on"})


def read_only_s3(model, **_kwargs):
    if model.name not in {"GetObject", "HeadObject", "HeadBucket", "GetBucketLocation", "ListObjectsV2"}:
        raise RuntimeError("diagnostic S3 mutations are prohibited")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--profile-output", type=Path, required=True)
    args = parser.parse_args()
    url = isolated_read_url(os.environ["NASUS_DATABASE_URL"], args.database)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SHOW transaction_read_only")) == "on"
            recipe = connection.execute(text("SELECT project_id, actor_id, artifact_ref FROM quality_http_fixture_recipes "
                "WHERE record_id = :id"), {"id": args.recipe_id}).mappings().one()
            actor = connection.execute(text("SELECT user_id, display_name, email, role, status FROM user_identities "
                "WHERE user_id = :id"), {"id": recipe["actor_id"]}).mappings().one()
            if actor["status"] != "active":
                raise PermissionError("original recipe actor is no longer active")
            location = urlsplit(recipe["artifact_ref"])
            if location.scheme != "s3" or re.fullmatch(r"nasus-test-[0-9a-f]{32}", location.netloc) is None:
                raise ValueError("an existing private isolated S3 test archive is required")
    finally:
        engine.dispose()
    os.environ.update({"NASUS_DATABASE_URL": url.render_as_string(hide_password=False),
        "NASUS_AUTO_CREATE_TABLES": "false", "NASUS_SEED_DEMO_DATA": "false", "NASUS_S3_BUCKET": location.netloc,
        "NASUS_AGENT_WORKFLOW_RUNTIME": "local", "NASUS_AGENT_GRAPH_RUNTIME": "local",
        "NASUS_LANGGRAPH_CHECKPOINT_BACKEND": "memory", "NASUS_RUNNER_MODE": "protocol_stub",
        "NASUS_CODE_GRAPH_MODE": "disabled"})
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from apps.api.app.application.platform.account_models import UserProfile
    from apps.api.app.application.platform.actor_context import actor_scope
    from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
    from apps.api.app.infrastructure.storage.object_storage import ObjectStorage
    factory = ObjectStorage._create_s3_client

    def client(config):
        value = factory(config)
        value.meta.events.register("before-call.s3", read_only_s3)
        return value

    ObjectStorage._create_s3_client = staticmethod(client)
    from apps.api.app.bootstrap import get_application_container
    container = get_application_container()
    user = UserProfile(id=actor["user_id"], name=actor["display_name"], email=actor["email"], role=actor["role"])
    profiler = cProfile.Profile()
    try:
        with actor_scope(user):
            profiler.enable()
            result = container.http_fixture_recipes.read(recipe["project_id"], args.recipe_id)
            if result["metadata"]["record_id"] != args.recipe_id or result["historical_not_live"] is not True:
                raise ValueError("the original authorized historical recipe did not match")
    finally:
        profiler.disable()
        profiler.dump_stats(str(args.profile_output))
        pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(25)
    print("response hash: " + acceptance_digest(result))
    print("authorized original fixture read completed; no mutation or target dispatch")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # SQL parameters and source excerpts must not appear in diagnostic logs.
        print("read-only diagnostic failed: " + type(error).__name__, file=sys.stderr)
        state = getattr(getattr(error, "orig", None), "sqlstate", None)
        if state is not None:
            print("PostgreSQL SQLSTATE: " + state, file=sys.stderr)
        for frame in traceback.extract_tb(error.__traceback__)[-16:]:
            print(f"{Path(frame.filename).name}:{frame.lineno}({frame.name})", file=sys.stderr)
        raise SystemExit(1)
