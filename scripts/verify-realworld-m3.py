"""Explicitly separate isolated design regression from retained Portal observation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import runpy
from datetime import datetime, timezone
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "87dd078c883a046f5ff20269df2fb004d8b5f83f"
TOKENIZER_COMMIT = "08c8657f02291e11b6f6b63e0e16014f8e748518"
TOKENIZER_URL = "https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/resolve/" + TOKENIZER_COMMIT + "/tokenizer.json"


def full_acceptance_blockers():
    # Protocol specimens are not permission to claim a live execution or cleanup.
    return ["model_scope_draft_live_acceptance_required", "controlled_role_credentials_required",
        "fixture_manifest_v2_required", "durable_environment_lease_and_reset_required",
        "version_delivery_execution_progress_required", "formal_browser_runplan_required",
        "encrypted_snapshots_and_restore_required", "live_realworld_execution_and_cleanup_required"]


def report_directory():
    directory = ROOT / "output/realworld" / ("m3-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    directory.mkdir(parents=True, mode=0o700)
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("design", "full"), default="full")
    parser.add_argument("--mode", choices=("isolated", "retained"), default="isolated")
    parser.add_argument("--acceptance-id")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    if args.mode == "retained":
        if args.phase != "full" or not args.acceptance_id:
            parser.error("retained mode needs --phase full and an existing --acceptance-id; it never uses disposable stores")
        command = ["node", "scripts/realworld-retained-observe.mjs", "--acceptance-id", args.acceptance_id]
        return subprocess.call(command + (["--headed"] if args.headed else []), cwd=ROOT)
    if args.acceptance_id or args.headed:
        parser.error("--acceptance-id and --headed are retained-mode options")
    if args.phase == "full":
        directory = report_directory()
        report = {"schema": "nasus.realworld-m3-acceptance.v1", "phase": "full", "status": "blocked",
            "stage": "capability_preflight", "exit_code": 2, "full_m3_verified": False,
            "blockers": full_acceptance_blockers(), "execution_status": "not_started", "cleanup_status": "not_started",
            "message": "HTTP v4 reviewed readback is implemented, but role fixtures and batch reset are not connected. "
                "No target, model call or business write was started. --phase design checks live design only."}
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({**report, "report_path": str(directory / "report.json")}))
        return 2
    from apps.api.app.infrastructure.persistence.settings_repository import SettingsRepository
    from apps.api.app.infrastructure.persistence.settings_store import SettingsPersistence
    from apps.api.app.infrastructure.platform.model_configuration_state import SQLAlchemyModelConfigurationState
    from apps.api.app.application.platform.model_configurations import ModelConfigurationApplicationService
    from apps.api.app.infrastructure.llm import LLMGateway
    repository, gateway = SettingsRepository(), LLMGateway()
    service = ModelConfigurationApplicationService(state=SQLAlchemyModelConfigurationState(repository, gateway),
        repository=repository, secrets=SettingsPersistence(), gateway=gateway, test_grants=None)
    settings = service.get_settings()
    if settings.runtime_mode != "live":
        raise SystemExit("Select a live chat model; fallback is not acceptance evidence.")
    selected = settings.custom_model
    if (selected.model_name not in {"deepseek-v4-flash", "deepseek-flash"}
            or selected.provider_kind != "openai_compatible"
            or selected.base_url.rstrip("/") not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}):
        raise SystemExit("This acceptance profile pins official DeepSeek Flash pricing/tokenizer; provide a reviewed profile for another model.")
    directory = report_directory()
    # Download static tokenizer data only, never provider Python code or weights.
    with urlopen(TOKENIZER_URL, timeout=60) as response:
        tokenizer = response.read(32 * 1024 * 1024 + 1)
    if len(tokenizer) > 32 * 1024 * 1024:
        raise SystemExit("Tokenizer exceeds the local policy budget")
    (directory / "tokenizer.json").write_bytes(tokenizer)
    origin = ROOT / ".nasus/validation/realworld-django-ninja"
    repo = directory / "source"
    subprocess.run(["git", "clone", "--no-hardlinks", str(origin), str(repo)], check=True, capture_output=True)
    revisions = {"original": BASE}
    for name in ("defect", "fix"):
        revisions[name] = subprocess.check_output(["git", "-C", str(origin), "rev-parse", "codex/nasus-realworld-" + name]).decode().strip()
    verified = runpy.run_path(str(ROOT / "scripts/verify-realworld-loop.py"))["verify_revisions"](origin, revisions["defect"], revisions["fix"])
    if verified != revisions:
        raise SystemExit("Controlled original/defect/fix provenance does not match")
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/heads/nasus-m3-acceptance", BASE], check=True)
    env = dict(os.environ)
    env.update(M2_LIVE_SETTINGS=settings.model_dump_json(), M2_LIVE_KEY=service.get_custom_model_api_key("chat"),
        M2_ACCEPTANCE_REPORT=str(directory / "m2-report.json"), M3_ACCEPTANCE_REPORT=str(directory / "report.json"),
        M3_REVISIONS=json.dumps(revisions), M3_TOKENIZER=str(directory / "tokenizer.json"),
        M1_REALWORLD_REPOSITORY=str(repo), M2_REALWORLD_SPEC=str(ROOT / ".nasus/validation/realworld-spec"))
    env["NASUS_TEST_DATABASE_URL"] = env.get("NASUS_TEST_DATABASE_URL", env["NASUS_DATABASE_URL"])
    for key in ("ENDPOINT", "ACCESS_KEY", "SECRET_KEY"):
        env["NASUS_TEST_S3_" + key] = env.get("NASUS_TEST_S3_" + key, env["NASUS_S3_" + key])
    env["TEST_TEMPORAL_ADDRESS"] = env.get("NASUS_TEMPORAL_ADDRESS", "localhost:7233")
    print("Live M3 acceptance:", settings.model_name, "Report:", directory, flush=True)
    result = subprocess.call([sys.executable, "scripts/test-api-postgres.py", "--minio",
        "apps/api/tests/test_realworld_m3_live.py", "-x", "-q", "--tb=short",
        "--junitxml=" + str(directory / "junit.xml")], cwd=ROOT, env=env)
    report = directory / "report.json"
    evidence = json.loads(report.read_text()) if report.exists() else {"stage": "startup"}
    evidence.update(phase=args.phase, exit_code=result, full_m3_verified=False)
    if result:
        evidence["status"] = "failed"
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
