"""Registered deployment shapes, not arbitrary caller-selected processes or probes."""
from dataclasses import dataclass


JAVA_ENVIRONMENT = "nasus.java21-pg-redis.v1"
PYTHON_ENVIRONMENT = "nasus.python312-django-pg.v1"


@dataclass(frozen=True)
class EnvironmentProfile:
    name: str
    dependencies: tuple[str, ...]
    executable: str
    arguments: tuple[str, ...]
    artifact_path: str
    health_path: str
    health_probe: str


def environment_profile(name):
    if name == JAVA_ENVIRONMENT:
        return EnvironmentProfile(name, ("pg", "redis"), "java", ("-jar", "/app/target.jar"),
            "/app/target.jar", "/actuator/health", "target_actuator_health")
    if name == PYTHON_ENVIRONMENT:
        return EnvironmentProfile(name, ("pg",), "python", ("/app/target.pyz", "runserver", "0.0.0.0:8080", "--noreload"),
            "/app/target.pyz", "/api/tags", "target_realworld_tags")
    raise ValueError("unsupported owned environment profile")


def inventory_profile(value):
    name = value.get("profile", JAVA_ENVIRONMENT)
    profile = environment_profile(name)
    if (name == JAVA_ENVIRONMENT and (value.get("schema") != "nasus.owned-target-environment.v1" or "profile" in value)
            or name != JAVA_ENVIRONMENT and value.get("schema") != "nasus.owned-target-environment.v2"):
        raise ValueError("owned environment schema/profile mismatch")
    return profile
