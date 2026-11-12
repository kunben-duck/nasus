from copy import deepcopy
from dataclasses import replace
import pytest

from apps.api.app.domain.quality_loop.environment_profiles import PYTHON_ENVIRONMENT
from apps.api.app.domain.quality_loop.native_environment import NativeEnvironmentInvalid, NativeEnvironmentObservation
from apps.api.app.domain.quality_loop.native_environment_health import NativeEnvironmentHealthObservation
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.infrastructure.runner.owned_target_health import OwnedTargetHealthInspector
from apps.api.app.infrastructure.runner.owned_target_environment import CONTAINER_FORMAT
from apps.api.tests.test_owned_target_environment import ARTIFACT, spec
from apps.api.tests.test_owned_target_health import HealthCommands


class PythonCommands(HealthCommands):
    def __init__(self, spec):
        super().__init__(spec)
        app = self.containers[spec.container_id]
        app["Path"], app["Args"] = "python", ["/app/target.pyz", "runserver", "0.0.0.0:8080", "--noreload"]
        app["Mounts"][0]["Destination"] = "/app/target.pyz"
        self.responses["target"] = b'{"tags":[]}\n200'

    def __call__(self, args, **kwargs):
        if args[-2:] == ["sha256sum", "/app/target.pyz"]:
            kwargs["require_work"]()
            self.calls.append((args, kwargs))
            return 0, ARTIFACT[7:].encode() + b"  /app/target.pyz\n"
        return super().__call__(args, **kwargs)


def test_python_requires_only_owned_pg_and_realworld_probe(spec):
    assert '(eq .Path "python") (eq (len .Args) 4)' in CONTAINER_FORMAT
    spec = replace(spec, profile=PYTHON_ENVIRONMENT, dependencies=spec.dependencies[:1])
    commands = PythonCommands(spec)
    value = OwnedTargetHealthInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)
    assert value.inventory["schema"] == "nasus.owned-target-environment.v2"
    assert value.inventory["profile"] == PYTHON_ENVIRONMENT
    assert commands.health_calls == ["pg", "target"]
    assert commands.calls[-3][0][-1] == "/app/target.pyz"
    assert value.dependency_health_verified and value.target_health_verified
    assert value.inventory["execution_authorized"] is False
    assert any(args[-1] == "http://127.0.0.1:8080/api/tags" for args, _ in commands.calls)


@pytest.mark.parametrize("fault", ["legacy_schema", "unknown_profile", "missing_profile", "wrong_probe", "root", "changed_artifact", "extra_args"])
def test_python_profile_and_proofs_cannot_be_relabelled(spec, fault):
    spec = replace(spec, profile=PYTHON_ENVIRONMENT, dependencies=spec.dependencies[:1])
    commands = PythonCommands(spec)
    if fault in {"root", "changed_artifact", "extra_args"}:
        app = commands.containers[spec.container_id]
        if fault == "root": app["User"] = "0:0"
        elif fault == "extra_args": app["Args"].append("--settings=other.settings")
        else: app["Args"][0] = "/tmp/unverified.pyz"
        with pytest.raises(NativeEnvironmentInvalid):
            OwnedTargetHealthInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)
        return
    value = OwnedTargetHealthInspector(spec, command=commands).inspect(ARTIFACT, require_work=lambda: None)
    inventory, checks = deepcopy(value.inventory), deepcopy(value.checks)
    if fault == "legacy_schema": inventory["schema"] = "nasus.owned-target-environment.v1"
    if fault == "unknown_profile": inventory["profile"] = "caller-defined"
    if fault == "missing_profile": inventory.pop("profile")
    if fault == "wrong_probe": checks[-1]["probe"] = "target_actuator_health"
    with pytest.raises(NativeEnvironmentInvalid):
        NativeEnvironmentHealthObservation(inventory, acceptance_digest(inventory), checks, value.observed_at)
