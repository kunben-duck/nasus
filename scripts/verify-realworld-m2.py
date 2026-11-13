"""Run M2 on disposable PostgreSQL/MinIO with the currently selected live chat model."""
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from apps.api.app.infrastructure.persistence.settings_repository import SettingsRepository
    from apps.api.app.infrastructure.persistence.settings_store import SettingsPersistence
    from apps.api.app.infrastructure.platform.model_configuration_state import SQLAlchemyModelConfigurationState
    from apps.api.app.application.platform.model_configurations import ModelConfigurationApplicationService
    from apps.api.app.infrastructure.llm import LLMGateway
    repository, gateway = SettingsRepository(), LLMGateway()
    # Read selected configuration only. Do not initialize the development store,
    # migrate legacy settings or copy development business records into the test DB.
    service = ModelConfigurationApplicationService(state=SQLAlchemyModelConfigurationState(repository, gateway),
        repository=repository, secrets=SettingsPersistence(), gateway=gateway, test_grants=None)
    settings = service.get_settings()
    if settings.runtime_mode != "live":
        raise SystemExit("Select a live chat model before running M2 acceptance; fallback is not accepted.")
    directory = ROOT / "output" / "realworld" / ("m2-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    directory.mkdir(parents=True)
    env = dict(os.environ)
    env.update(M2_LIVE_SETTINGS=settings.model_dump_json(), M2_LIVE_KEY=service.get_custom_model_api_key("chat"),
        M2_ACCEPTANCE_REPORT=str(directory / "report.json"),
        M1_REALWORLD_REPOSITORY=str(ROOT / ".nasus/validation/realworld-django-ninja"),
        M2_REALWORLD_SPEC=str(ROOT / ".nasus/validation/realworld-spec"))
    env["NASUS_TEST_DATABASE_URL"] = env.get("NASUS_TEST_DATABASE_URL", env["NASUS_DATABASE_URL"])
    for key in ("ENDPOINT", "ACCESS_KEY", "SECRET_KEY"):
        env["NASUS_TEST_S3_" + key] = env.get("NASUS_TEST_S3_" + key, env["NASUS_S3_" + key])
    print("Live M2 acceptance:", settings.model_provider, settings.model_name, "Report:", directory, flush=True)
    return subprocess.call([sys.executable, "scripts/test-api-postgres.py", "--minio",
        "apps/api/tests/test_requirement_realworld_live.py", "-x", "-q", "--tb=short",
        "--junitxml=" + str(directory / "junit.xml")], cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
