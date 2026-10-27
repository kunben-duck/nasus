"""Independent production-domain wire specimens; no PG, Docker, model or target I/O."""
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from apps.api.tests.test_run_plan_builds import binding_inputs, refresh_pins
from apps.api.tests.test_http_fixture_journal_access import saved_inputs
from apps.api.tests.test_owned_target_environment import spec, Commands
from apps.api.app.infrastructure.runner.owned_target_environment import OwnedTargetEnvironmentInspector
from apps.api.app.application.quality_loop.http_fixtures import HttpFixtureScope
from apps.api.app.application.quality_loop.http_fixture_grants import HttpFixtureGrantRequest
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.run_plan_build import compile_run_plan_build
from apps.api.app.domain.quality_loop.environment_observation_record import ENVIRONMENT_RECORD_SCHEMA, record_identity, environment_record_metadata
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_SCHEMA, recipe_identity, validate_recipe_archive
from apps.api.app.domain.quality_loop.http_fixture_target import native_fixture_environment
from apps.api.app.domain.quality_loop.http_fixture_grant import NATIVE_GRANT_SCHEMA, GRANT_SECONDS, grant_identity, grant_metadata


def specimen():
    p, selection, builds = binding_inputs(multiple=True)
    _, _, manifest, _ = saved_inputs()
    owned = replace(spec.__wrapped__(), project_id="p")
    plan = p["artifact"]["plan"]
    declaration = plan["selection"]["fixtures"][0]
    declaration.update(data_manifest_hash=acceptance_digest(manifest), setup=manifest["setup"], cleanup=manifest["cleanup"])
    plan["selection"]["environment"].update(kind="local", base_url="http://127.0.0.1:8080", environment_id=owned.environment_id, inventory_hash=owned.digest)
    now = datetime.now(timezone.utc).isoformat()
    p["artifact"].update(invocation_id="original-plan-command", actor_id="admin", recorded_at=now)
    selected = selection.model_dump(mode="json")
    refresh_pins(p, selected, builds)
    bound = compile_run_plan_build(p, selected, builds)
    p["metadata"].update(project_id="p", run_plan_id="plan", invocation_id="original-plan-command", plan_digest=bound["plan_digest"],
        image_revision_id=bound["source_pin"]["image_revision_id"], manifest_id=bound["source_pin"]["manifest_id"])
    request = {**selected, "binding_digest": bound["binding_digest"], "source_scope_digest": acceptance_digest("explicit-source-scope")}
    artifact = {"schema": "nasus.run-plan-build-artifact.v1", "project_id": "p", "binding_id": "original-binding", "invocation_id": "binding-command",
        "actor_id": "admin", "recorded_at": now, "request": request, "binding": bound}
    binding = {"artifact": artifact, "metadata": {**{k: artifact[k] for k in ("project_id", "binding_id", "invocation_id", "actor_id", "recorded_at")},
        **{k: bound[k] for k in ("run_plan_id", "run_plan_artifact_hash", "plan_digest", "binding_digest", "target_artifact_hash")},
        "image_revision_id": bound["source_pin"]["image_revision_id"], "manifest_id": bound["source_pin"]["manifest_id"],
        "artifact_hash": acceptance_digest(artifact), "request_hash": acceptance_digest(request)}, "historical_not_live": True,
        "current_use": {"inputs_current": True, "native_build_source_attested": True, "environment_verified": False, "fixtures_verified": False, "execution_authorized": False}}
    commands = Commands(owned)
    commands.body = bound["target_artifact_hash"][7:].encode() + b"  /app/target.jar\n"
    observed = OwnedTargetEnvironmentInspector(owned, command=commands).inspect(bound["target_artifact_hash"], require_work=lambda: None)
    env = {"schema": ENVIRONMENT_RECORD_SCHEMA, "project_id": "p", "record_id": record_identity("environment-command"), "invocation_id": "environment-command",
        "actor_id": "admin", "recorded_at": now, "request": {"project_id": "p", "run_plan_id": "plan", "run_plan_artifact_hash": p["metadata"]["artifact_hash"],
            "build_binding_id": "original-binding", "build_binding_artifact_hash": binding["metadata"]["artifact_hash"]},
        "parents": {"plan_digest": bound["plan_digest"], "image_revision_id": bound["source_pin"]["image_revision_id"], "manifest_id": bound["source_pin"]["manifest_id"],
            "environment_id": owned.environment_id, "operator_policy_digest": owned.digest, "target_artifact_hash": bound["target_artifact_hash"]},
        "observation": {"inventory": observed.inventory, "inventory_hash": observed.inventory_hash, "observed_at": observed.observed_at}}
    recipe = {"schema": RECIPE_SCHEMA, "project_id": "p", "record_id": recipe_identity("recipe-command"), "invocation_id": "recipe-command", "actor_id": "admin", "recorded_at": now,
        "request": {"project_id": "p", "run_plan_id": "plan", "run_plan_artifact_hash": p["metadata"]["artifact_hash"], "manifest": manifest},
        "parents": {"plan_digest": bound["plan_digest"], **{k: plan["source_pin"][k] for k in ("image_revision_id", "image_artifact_hash", "manifest_id", "manifest_hash")}},
        "fixture_digest": acceptance_digest(declaration)}
    for b in builds:
        b.update(status="completed", execution_authorized=False, historical_not_live=True)
    return {"plan": p, "binding": binding, "builds": builds, "environment": {"metadata": environment_record_metadata(env), "archive": env, "historical_not_live": True},
        "recipe": {"metadata": validate_recipe_archive(recipe, recipe["request"], p), "archive": recipe, "historical_not_live": True}}


def grant(v):
    s, request, command = v["specimen"], HttpFixtureGrantRequest.model_validate(v["request"]), v["command"]
    plan, recipe, env = s["plan"], s["recipe"], s["environment"]
    native = native_fixture_environment(plan, recipe["archive"]["request"]["manifest"], env)
    selection = plan["artifact"]["plan"]["selection"]
    scope = HttpFixtureScope(project_id=request.project_id, attempt_id=request.attempt_id, case_id=recipe["metadata"]["case_id"],
        parent_digest=plan["metadata"]["plan_digest"], data_manifest_hash=recipe["metadata"]["data_manifest_hash"], environment_id=selection["environment"]["environment_id"],
        artifact_hash=selection["target_build"]["artifact_hash"], inventory_hash=native["inventory_hash"], timeout_ms=request.timeout_ms)
    now = datetime.now(timezone.utc)
    payload = {"schema": NATIVE_GRANT_SCHEMA, "project_id": request.project_id, "record_id": grant_identity(command), "invocation_id": command, "actor_id": "admin",
        "recorded_at": now.isoformat(), "expires_at": (now + timedelta(seconds=GRANT_SECONDS)).isoformat(), "request": request.model_dump(mode="json"),
        "scope": asdict(scope), "source_scope_digest": acceptance_digest("explicit-source-scope"), "native_environment": native}
    return {"metadata": grant_metadata(payload), "historical_not_live": True}


if __name__ == "__main__":
    print(json.dumps(grant(json.load(sys.stdin)) if len(sys.argv) > 1 and sys.argv[1] == "grant" else specimen()))
