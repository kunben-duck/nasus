"""Closed build profiles; request data cannot introduce an executable toolchain."""
from dataclasses import dataclass
import re


JAVA_BUILD = "nasus.offline-java21-maven3911.v1"
PYTHON_BUILD = "nasus.offline-python312-zipapp.v1"


@dataclass(frozen=True)
class BuildProfile:
    adapter: str
    suffix: str
    definition: str
    runtime: str
    runtime_version: str
    build_tool: str
    build_tool_version: str


PROFILES = (
    BuildProfile(JAVA_BUILD, ".jar", "pom.xml", "Java", "21", "Maven", "3.9.11"),
    BuildProfile(PYTHON_BUILD, ".pyz", "pyproject.toml", "Python", "3.12", "zipapp", "1"),
)


def build_profile(adapter):
    for profile in PROFILES:
        if profile.adapter == adapter:
            return profile
    raise ValueError("unsupported native build adapter")


def artifact_profile(path):
    for profile in PROFILES:
        if path.startswith("target/") and path.endswith(profile.suffix):
            return profile
    raise ValueError("native artifact requires a registered target format")


def validate_toolchain(adapter, toolchain):
    build_profile(adapter)
    if not isinstance(toolchain, dict):
        raise ValueError("invalid native toolchain")
    expected = ({"java": "21", "maven": "3.9.11"} if adapter == JAVA_BUILD else
                {"python": "3.12", "zipapp": "1"})
    expected.update(network="none", dependency_cache="operator_read_only")
    if any(toolchain.get(key) != value for key, value in expected.items()):
        raise ValueError("native build output toolchain differs")
    if adapter == PYTHON_BUILD and not re.fullmatch(r"sha256:[a-f0-9]{64}", str(toolchain.get("dependency_lock_hash", ""))):
        raise ValueError("Python dependency lock is required")

