"""Run API tests against a disposable PostgreSQL database, never developer data.

Set NASUS_TEST_DATABASE_URL to a local PostgreSQL connection whose role can
create test databases. Arguments are passed to pytest after migrations succeed.
Pass --playwright first to run the browser gate with the same isolated database.
Pass --smoke to run the smoke journey with its own PostgreSQL database and ports.
Pass --minio before these options to use a disposable private local S3 bucket;
NASUS_TEST_S3_ENDPOINT/ACCESS_KEY/SECRET_KEY must be explicitly configured.
"""
from __future__ import annotations

import os
import socket
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from isolated_test_storage import isolated_test_storage


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    args = sys.argv[1:]
    use_minio = bool(args and args[0] == "--minio")
    if use_minio:
        args = args[1:]
    connection = os.environ.get("NASUS_TEST_DATABASE_URL")
    if not connection:
        raise SystemExit("NASUS_TEST_DATABASE_URL is required")
    url = make_url(connection)
    if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("use an explicitly configured local PostgreSQL test server")
    database = "nasus_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    created = False
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{database}"'))
        created = True
        with tempfile.TemporaryDirectory(prefix="nasus-pg-test-") as directory, ExitStack() as resources:
            env = {key: value for key, value in os.environ.items() if not key.startswith("NASUS_")}
            env.update({
                "NASUS_DATABASE_URL": url.set(database=database).render_as_string(hide_password=False),
                "NASUS_TEST_DATABASE_URL": url.set(database=database).render_as_string(hide_password=False),
                "NASUS_AUTO_CREATE_TABLES": "false", "NASUS_ENV": "local",
                "NASUS_STATE_DIR": directory, "NASUS_OBJECT_STORE_DIR": str(Path(directory) / "objects"),
                "NASUS_SOURCE_CACHE_DIR": str(Path(directory) / "source-cache"),
                "NASUS_SOURCE_SNAPSHOT_CACHE_DIR": str(Path(directory) / "snapshots"),
                "NASUS_RUNNER_MODE": "protocol_stub", "NASUS_CODE_GRAPH_MODE": "disabled",
            })
            if use_minio:
                env.update(resources.enter_context(isolated_test_storage(os.environ)))
            migration = subprocess.run([
                sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", "upgrade", "head",
            ], cwd=root, env=env, check=False)
            if migration.returncode:
                return migration.returncode
            if args and args[0] == "--playwright":
                env.update({
                    "NASUS_E2E_DATABASE_URL": env["NASUS_DATABASE_URL"], "NASUS_E2E_STATE_DIR": directory,
                    "PLAYWRIGHT_API_PORT": os.environ.get("PLAYWRIGHT_API_PORT", "18080"),
                    "PLAYWRIGHT_PORTAL_PORT": os.environ.get("PLAYWRIGHT_PORTAL_PORT", "14173"),
                    "PLAYWRIGHT_OUTPUT_DIR": str(root / "output" / "playwright" / "runs" / database),
                })
                command = ["npx", "playwright", "test", *args[1:]]
            elif args == ["--smoke"]:
                api_port, portal_port = 18082, 14175
                for port in (api_port, portal_port):
                    with socket.socket() as listener:
                        listener.bind(("127.0.0.1", port))
                env.update({
                    "NASUS_SMOKE_STATE_DIR": directory,
                    "API_URL": f"http://127.0.0.1:{api_port}",
                    "PORTAL_URL": f"http://127.0.0.1:{portal_port}",
                    "SMOKE_API_COMMAND": f"exec ./.venv/bin/python -m uvicorn apps.api.app.main:app --app-dir . --host 127.0.0.1 --port {api_port}",
                    "SMOKE_PORTAL_COMMAND": f"exec node apps/portal/node_modules/vite/bin/vite.js apps/portal --host 127.0.0.1 --port {portal_port} --strictPort",
                })
                command = ["node", "tests/e2e/smoke.js"]
            else:
                command = [sys.executable, "-m", "pytest", *(args or ["apps/api/tests/test_api.py", "-q"])]
            result = subprocess.run(command, cwd=root, env=env, check=False)
            return result.returncode
    finally:
        if created:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
